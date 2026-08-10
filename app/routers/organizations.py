"""
Dukkan Cloud - Organizations Router
Handles organization CRUD operations and member management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.models import Organization, User, UserRole, ActivityLog
from app.schemas import (
    OrganizationCreate, OrganizationUpdate, OrganizationResponse,
    UserResponse
)
from app.dependencies import (
    get_current_user, is_org_admin, is_superadmin,
    log_activity, CurrentUser, DbSession
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get("/", response_model=List[OrganizationResponse])
async def list_organizations(
    current_user: CurrentUser,
    db: DbSession
):
    """
    List organizations accessible by the current user.
    
    Superadmins see all organizations.
    Regular users see only their own organization.
    """
    if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
        orgs = db.query(Organization).all()
    else:
        orgs = db.query(Organization).filter(
            Organization.id == current_user.organization_id
        ).all()
    
    # Add counts
    result = []
    for org in orgs:
        member_count = db.query(User).filter(User.organization_id == org.id).count()
        vm_count = db.query(User).filter(User.organization_id == org.id).count()  # Simplified
        org_dict = OrganizationResponse.from_orm(org).dict()
        org_dict["member_count"] = member_count
        org_dict["vm_count"] = vm_count
        result.append(org_dict)
    
    return result


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    org_data: OrganizationCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Create a new organization.
    
    Only superadmins can create organizations directly.
    Regular users create orgs during registration.
    """
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmins can create organizations"
        )
    
    # Check name uniqueness
    existing = db.query(Organization).filter(Organization.name == org_data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name already exists"
        )
    
    org = Organization(name=org_data.name)
    db.add(org)
    db.commit()
    db.refresh(org)
    
    await log_activity(
        db=db,
        user=current_user,
        action="organization.create",
        resource_type="organization",
        resource_id=org.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Organization created: {org.name}")
    return org


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """
    Get organization details by ID.
    """
    # Permission check
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    return org


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    org_data: OrganizationUpdate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Update organization details.
    """
    # Permission check
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    if org_data.name:
        org.name = org_data.name
    if org_data.is_active is not None:
        org.is_active = org_data.is_active
    
    db.commit()
    db.refresh(org)
    
    await log_activity(
        db=db,
        user=current_user,
        action="organization.update",
        resource_type="organization",
        resource_id=org.id,
        ip_address=request.client.host,
    )
    
    return org


@router.get("/{org_id}/members", response_model=List[UserResponse])
async def list_organization_members(
    org_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """
    List all members of an organization.
    """
    # Permission check
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    members = db.query(User).filter(User.organization_id == org_id).all()
    return members


@router.post("/{org_id}/members/{user_id}/role")
async def update_member_role(
    org_id: str,
    user_id: str,
    role_data: dict,  # {"role": "org_admin"}
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Update a member's role within the organization.
    """
    # Permission check - only org admins or superadmins
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of this organization"
        )
    
    new_role = role_data.get("role")
    if new_role:
        try:
            user.role = UserRole(new_role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {new_role}"
            )
    
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="organization.member_role_update",
        resource_type="user",
        resource_id=user_id,
        details={"new_role": new_role},
        ip_address=request.client.host,
    )
    
    return {"message": f"User role updated to {new_role}"}
