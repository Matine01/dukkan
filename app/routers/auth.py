"""
Dukkan Cloud - Authentication Router
Handles user registration, login, token management, and API keys.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.models import User, Organization, UserRole, APIKey
from app.schemas import (
    UserCreate, UserLogin, UserResponse, Token, 
    APIKeyCreate, APIKeySecret, APIKeyResponse
)
from app.dependencies import (
    get_current_user, verify_password, get_password_hash,
    create_access_token, hash_api_key, generate_api_key,
    log_activity, CurrentUser, DbSession
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: DbSession,
    request: Request
):
    """
    Register a new user.
    
    If organization_id is provided, joins existing org.
    Otherwise, creates a new organization with the user as admin.
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Get or create organization
    organization = None
    if user_data.organization_id:
        organization = db.query(Organization).filter(
            Organization.id == user_data.organization_id,
            Organization.is_active == True
        ).first()
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    else:
        # Create new organization
        org_name = f"{user_data.full_name}'s Organization" if user_data.full_name else "Default Organization"
        organization = Organization(name=org_name)
        db.add(organization)
        db.flush()  # Get organization ID
    
    # Create user
    hashed_password = get_password_hash(user_data.password)
    user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role=UserRole.ORG_ADMIN if not user_data.organization_id else UserRole.MEMBER,
        max_vms=user_data.max_vms,
        organization_id=organization.id,
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Log activity
    await log_activity(
        db=db,
        user=user,
        action="user.register",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )
    
    logger.info(f"New user registered: {user.email}")
    return user


@router.post("/login", response_model=Token)
async def login(
    credentials: UserLogin,
    db: DbSession,
    response: Response,
    request: Request
):
    """
    Authenticate user and return JWT token.
    
    Sets HttpOnly secure cookie for frontend authentication.
    Also returns bearer token for API clients.
    """
    # Find user by email
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.organization or not user.organization.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.id,
            "email": user.email,
            "role": user.role.value,
            "org_id": user.organization_id,
        },
        expires_delta=access_token_expires
    )
    
    # Set HttpOnly cookie for frontend
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    
    # Log activity
    await log_activity(
        db=db,
        user=user,
        action="user.login",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )
    
    logger.info(f"User logged in: {user.email}")
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/logout")
async def logout(
    response: Response,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Logout user and clear authentication cookie.
    """
    # Clear cookie
    response.delete_cookie(
        key="access_token",
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )
    
    # Log activity
    await log_activity(
        db=db,
        user=current_user,
        action="user.logout",
        resource_type="user",
        resource_id=current_user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )
    
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
    db: DbSession
):
    """
    Get current authenticated user information.
    """
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_data: UserCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Update current user profile.
    """
    # Check email uniqueness if changing email
    if user_data.email and user_data.email != current_user.email:
        existing = db.query(User).filter(User.email == user_data.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
        current_user.email = user_data.email
    
    if user_data.full_name:
        current_user.full_name = user_data.full_name
    
    if user_data.max_vms:
        current_user.max_vms = user_data.max_vms
    
    db.commit()
    db.refresh(current_user)
    
    await log_activity(
        db=db,
        user=current_user,
        action="user.update_profile",
        resource_type="user",
        resource_id=current_user.id,
        ip_address=request.client.host,
    )
    
    return current_user


@router.post("/api-keys", response_model=APIKeySecret, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: APIKeyCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Create a new API key for programmatic access.
    
    The secret_key is only shown once at creation time.
    Store it securely - it cannot be retrieved later.
    """
    # Generate API key
    prefix, full_key = generate_api_key()
    key_hash = hash_api_key(full_key)
    
    # Create API key record
    api_key = APIKey(
        name=key_data.name,
        key_hash=key_hash,
        prefix=prefix,
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        expires_at=key_data.expires_at,
    )
    
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    
    await log_activity(
        db=db,
        user=current_user,
        action="api_key.create",
        resource_type="api_key",
        resource_id=api_key.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"API key created for user {current_user.email}: {prefix}...")
    
    return APIKeySecret(
        api_key=APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            prefix=api_key.prefix,
            is_active=api_key.is_active,
            expires_at=api_key.expires_at,
            last_used_at=api_key.last_used_at,
            user_id=api_key.user_id,
            created_at=api_key.created_at,
            updated_at=api_key.updated_at,
        ),
        secret_key=full_key,
    )


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: CurrentUser,
    db: DbSession
):
    """
    List all API keys for the current user.
    """
    keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.id
    ).order_by(APIKey.created_at.desc()).all()
    
    return keys


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Revoke an API key.
    """
    api_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    ).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    api_key.is_active = False
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=api_key.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"API key revoked: {api_key.prefix}...")
    return {"message": "API key revoked successfully"}
