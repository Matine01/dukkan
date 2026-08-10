"""
Dukkan Cloud - Billing Router
Handles usage tracking, invoices, and billing summaries.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from dateutil.relativedelta import relativedelta

from app.database import get_db
from app.models import (
    UsageLog, Invoice, VirtualMachine, Volume, Organization, UserRole
)
from app.schemas import UsageLogResponse, InvoiceResponse, BillingSummary
from app.dependencies import (
    get_current_user, is_org_admin, is_superadmin, log_activity, CurrentUser, DbSession
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/summary", response_model=BillingSummary)
async def get_billing_summary(
    current_user: CurrentUser,
    db: DbSession,
    period: Optional[str] = None  # YYYY-MM format
):
    """
    Get billing summary for the current or specified period.
    """
    if not period:
        period = datetime.utcnow().strftime("%Y-%m")
    
    # Parse period
    try:
        period_date = datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid period format. Use YYYY-MM"
        )
    
    # Get organization
    if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
        org_id = current_user.organization_id
    else:
        org_id = current_user.organization_id
    
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization"
        )
    
    # Get usage logs for period
    usage_logs = db.query(UsageLog).filter(
        UsageLog.organization_id == org_id,
        UsageLog.billing_period == period,
    ).all()
    
    # Calculate totals
    total_cost = sum(log.total_cost for log in usage_logs)
    vm_count = len(set(log.vm_id for log in usage_logs))
    
    # Get volume count
    volume_count = db.query(Volume).filter(
        Volume.organization_id == org_id
    ).count()
    
    # Breakdown by category
    breakdown = {
        "compute": sum(log.cpu_cost + log.ram_cost for log in usage_logs),
        "storage": sum(log.storage_cost for log in usage_logs),
    }
    
    return BillingSummary(
        current_period=period,
        total_usage=sum(log.duration_hours for log in usage_logs),
        total_cost=total_cost,
        vm_count=vm_count,
        volume_count=volume_count,
        breakdown=breakdown,
    )


@router.get("/usage", response_model=List[UsageLogResponse])
async def list_usage_logs(
    current_user: CurrentUser,
    db: DbSession,
    period: Optional[str] = None,
    vm_id: Optional[str] = None
):
    """
    List detailed usage logs for billing analysis.
    """
    if not period:
        period = datetime.utcnow().strftime("%Y-%m")
    
    query = db.query(UsageLog).filter(
        UsageLog.billing_period == period
    )
    
    # Filter by organization (unless superadmin)
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        query = query.filter(UsageLog.organization_id == current_user.organization_id)
    
    # Filter by VM if specified
    if vm_id:
        query = query.filter(UsageLog.vm_id == vm_id)
    
    logs = query.order_by(UsageLog.start_time.desc()).all()
    
    # Add VM names
    result = []
    for log in logs:
        log_dict = UsageLogResponse.from_orm(log).dict()
        vm = db.query(VirtualMachine).filter(VirtualMachine.id == log.vm_id).first()
        log_dict["vm_name"] = vm.name if vm else None
        result.append(log_dict)
    
    return result


@router.get("/invoices", response_model=List[InvoiceResponse])
async def list_invoices(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[str] = None
):
    """
    List all invoices for the organization.
    """
    query = db.query(Invoice)
    
    # Filter by organization
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        query = query.filter(Invoice.organization_id == current_user.organization_id)
    
    # Filter by status
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    
    invoices = query.order_by(Invoice.billing_period.desc()).all()
    return invoices


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Get invoice details.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if invoice.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    return invoice


@router.post("/invoices/generate")
async def generate_invoice(
    period: str,  # YYYY-MM format
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Generate an invoice for a specific billing period.
    Usually run automatically on the first day of each month.
    """
    # Only org admins or superadmins can generate invoices
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if current_user.role != UserRole.ORG_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
    
    org_id = current_user.organization_id
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization"
        )
    
    # Check if invoice already exists
    existing = db.query(Invoice).filter(
        Invoice.organization_id == org_id,
        Invoice.billing_period == period
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice for period {period} already exists"
        )
    
    # Get usage logs for period
    usage_logs = db.query(UsageLog).filter(
        UsageLog.organization_id == org_id,
        UsageLog.billing_period == period,
        UsageLog.is_billed == False
    ).all()
    
    if not usage_logs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No unbilled usage found for period {period}"
        )
    
    # Calculate totals
    subtotal = sum(log.total_cost for log in usage_logs)
    tax_rate = settings.TAX_RATE
    tax_amount = subtotal * tax_rate
    total_amount = subtotal + tax_amount
    
    # Parse period for dates
    period_date = datetime.strptime(period, "%Y-%m")
    period_start = period_date.replace(day=1)
    period_end = (period_date + relativedelta(months=1)).replace(day=1) - timedelta(seconds=1)
    
    # Generate invoice number
    invoice_number = f"INV-{org_id[:8].upper()}-{period.replace('-', '')}"
    
    # Create invoice
    invoice = Invoice(
        invoice_number=invoice_number,
        organization_id=org_id,
        billing_period=period,
        period_start=period_start,
        period_end=period_end,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=settings.BILLING_CURRENCY,
        status="draft",
        due_date=period_start + timedelta(days=30),
    )
    
    db.add(invoice)
    
    # Mark usage logs as billed
    for log in usage_logs:
        log.is_billed = True
    
    db.commit()
    db.refresh(invoice)
    
    await log_activity(
        db=db,
        user=current_user,
        action="invoice.generate",
        resource_type="invoice",
        resource_id=invoice.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Invoice generated: {invoice.invoice_number}")
    return {"message": "Invoice generated successfully", "invoice_id": invoice.id}


@router.post("/invoices/{invoice_id}/mark-paid")
async def mark_invoice_paid(
    invoice_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Mark an invoice as paid.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if invoice.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    invoice.status = "paid"
    invoice.paid_at = datetime.utcnow()
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="invoice.mark_paid",
        resource_type="invoice",
        resource_id=invoice.id,
        ip_address=request.client.host,
    )
    
    return {"message": "Invoice marked as paid"}
