"""
Dukkan Cloud - Admin Router
Platform administration endpoints for superadmins.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.models import (
    User, Organization, VirtualMachine, Volume, Network,
    ActivityLog, UserRole, VMStatus
)
from app.schemas import (
    PlatformStats, UserResponse, OrganizationResponse,
    AdminUserCreate, ActivityLogResponse
)
from app.dependencies import (
    is_superadmin, get_password_hash, log_activity,
    SuperAdminUser, DbSession
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats", response_model=PlatformStats)
async def get_platform_stats(
    current_user: SuperAdminUser,
    db: DbSession
):
    """
    Get platform-wide statistics.
    Only accessible by superadmins.
    """
    total_orgs = db.query(Organization).count()
    total_users = db.query(User).count()
    total_vms = db.query(VirtualMachine).count()
    total_vms_running = db.query(VirtualMachine).filter(
        VirtualMachine.status == VMStatus.RUNNING
    ).count()
    total_volumes = db.query(Volume).count()
    total_networks = db.query(Network).count()
    
    # Calculate monthly revenue (simplified)
    from datetime import datetime
    current_period = datetime.utcnow().strftime("%Y-%m")
    from app.models import UsageLog
    monthly_revenue = db.query(UsageLog).filter(
        UsageLog.billing_period == current_period
    ).with_entities(db.func.sum(UsageLog.total_cost)).scalar() or 0.0
    
    return PlatformStats(
        total_organizations=total_orgs,
        total_users=total_users,
        total_vms=total_vms,
        total_vms_running=total_vms_running,
        total_volumes=total_volumes,
        total_networks=total_networks,
        monthly_revenue=monthly_revenue,
        active_sessions=0,  # Would need Redis for accurate session count
    )


@router.get("/users", response_model=List[UserResponse])
async def list_all_users(
    current_user: SuperAdminUser,
    db: DbSession,
    role_filter: str = None
):
    """
    List all users on the platform.
    Only accessible by superadmins.
    """
    query = db.query(User)
    
    if role_filter:
        try:
            role = UserRole(role_filter)
            query = query.filter(User.role == role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {role_filter}"
            )
    
    users = query.order_by(User.created_at.desc()).all()
    return users


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: AdminUserCreate,
    current_user: SuperAdminUser,
    db: DbSession,
    request: Request
):
    """
    Create a new user (superadmin only).
    """
    # Check if user exists
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Get organization if specified
    organization = None
    if user_data.organization_id:
        organization = db.query(Organization).filter(
            Organization.id == user_data.organization_id
        ).first()
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    
    # Create user
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role,
        max_vms=user_data.max_vms,
        is_platform_admin=user_data.is_platform_admin,
        organization_id=organization.id if organization else None,
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    await log_activity(
        db=db,
        user=current_user,
        action="admin.user_create",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Admin created user: {user.email}")
    return user


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_all_organizations(
    current_user: SuperAdminUser,
    db: DbSession
):
    """
    List all organizations on the platform.
    Only accessible by superadmins.
    """
    orgs = db.query(Organization).order_by(Organization.created_at.desc()).all()
    return orgs


@router.get("/activity-logs", response_model=List[ActivityLogResponse])
async def list_activity_logs(
    current_user: SuperAdminUser,
    db: DbSession,
    limit: int = 100,
    user_id: str = None,
    action_filter: str = None
):
    """
    List platform activity logs for auditing.
    Only accessible by superadmins.
    """
    query = db.query(ActivityLog)
    
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    
    if action_filter:
        query = query.filter(ActivityLog.action.like(f"%{action_filter}%"))
    
    logs = query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()
    return logs


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: SuperAdminUser,
    db: DbSession,
    request: Request
):
    """
    Delete a user (superadmin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    # Check if user has VMs
    vm_count = db.query(VirtualMachine).filter(
        VirtualMachine.owner_id == user_id
    ).count()
    
    if vm_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User has {vm_count} VM(s). Transfer or delete them first."
        )
    
    db.delete(user)
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="admin.user_delete",
        resource_type="user",
        resource_id=user_id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Admin deleted user: {user_id}")
    return {"message": "User deleted successfully"}


@router.post("/organizations/{org_id}/deactivate")
async def deactivate_organization(
    org_id: str,
    current_user: SuperAdminUser,
    db: DbSession,
    request: Request
):
    """
    Deactivate an organization (superadmin only).
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    org.is_active = False
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="admin.org_deactivate",
        resource_type="organization",
        resource_id=org_id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Admin deactivated organization: {org_id}")
    return {"message": "Organization deactivated"}
