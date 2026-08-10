"""
Dukkan Cloud - Dependencies
Authentication, authorization (RBAC), and resource access dependencies.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Callable, Annotated
from functools import wraps
import jwt
import hashlib
import secrets
from fastapi import Depends, HTTPException, status, Request, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import logging

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, APIKey, Organization, VirtualMachine
from app.schemas import TokenData, UserRole as UserRoleSchema

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
http_bearer = HTTPBearer(auto_error=False)


# ============================================================================
# PASSWORD HASHING UTILITIES
# ============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    import bcrypt
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    import bcrypt
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


# ============================================================================
# JWT TOKEN UTILITIES
# ============================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        role: str = payload.get("role")
        org_id: str = payload.get("org_id")
        
        if user_id is None:
            return None
        
        return TokenData(
            user_id=user_id,
            email=email,
            role=UserRoleSchema(role) if role else None,
            organization_id=org_id
        )
    except jwt.PyJWTError:
        return None


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.
    Returns (prefix, full_key) - prefix for display, full_key for use.
    """
    prefix = "dk_" + secrets.token_urlsafe(6)  # e.g., "dk_abc123xyz"
    secret = secrets.token_urlsafe(32)
    full_key = f"{prefix}_{secret}"
    return prefix, full_key


# ============================================================================
# AUTHENTICATION DEPENDENCIES
# ============================================================================

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer)
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    Authentication priority:
    1. HttpOnly cookie (for browser frontend)
    2. Bearer token in Authorization header (for API clients)
    3. X-API-Key header (for programmatic access like Terraform/Ansible)
    
    Raises HTTPException with 401 if authentication fails.
    """
    # Check for API Key first (programmatic access)
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        return await _authenticate_api_key(db, api_key_header)
    
    # Check for Bearer token
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    
    # If no bearer token, check cookies (for HttpOnly JWT)
    if not token:
        token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Decode and validate token
    token_data = decode_access_token(token)
    if token_data is None or token_data.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last used for API keys if applicable
    # (handled in _authenticate_api_key)
    
    return user


async def _authenticate_api_key(db: Session, api_key: str) -> User:
    """
    Authenticate using an API key.
    Updates last_used_at timestamp on successful authentication.
    """
    key_hash = hash_api_key(api_key)
    
    api_key_obj = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()
    
    if not api_key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check expiration
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last used timestamp
    api_key_obj.last_used_at = datetime.utcnow()
    db.commit()
    
    # Get the user associated with this API key
    user = db.query(User).filter(User.id == api_key_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


# ============================================================================
# RBAC DEPENDENCIES (Role-Based Access Control)
# ============================================================================

def require_role(*allowed_roles: UserRole) -> Callable:
    """
    Factory function to create role-based dependency.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role(UserRole.SUPERADMIN))):
            ...
    
        @router.get("/org-admin-only")
        async def org_admin_endpoint(user: User = Depends(require_role(UserRole.ORG_ADMIN, UserRole.SUPERADMIN))):
            ...
    """
    
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        # Superadmins can access everything
        if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
            return current_user
        
        # Check if user has one of the allowed roles
        if current_user.role not in allowed_roles:
            allowed_role_names = [r.value for r in allowed_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_role_names)}",
            )
        
        return current_user
    
    return role_checker


# Pre-built role checkers for common use cases
is_superadmin = require_role(UserRole.SUPERADMIN)
is_org_admin = require_role(UserRole.ORG_ADMIN)
is_member_or_higher = require_role(UserRole.MEMBER, UserRole.ORG_ADMIN, UserRole.SUPERADMIN)


# ============================================================================
# ORGANIZATION ACCESS DEPENDENCIES
# ============================================================================

async def get_organization_from_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Organization:
    """
    Get the organization associated with the current user.
    Raises 400 if user has no organization.
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with any organization",
        )
    
    org = db.query(Organization).filter(
        Organization.id == current_user.organization_id,
        Organization.is_active == True
    ).first()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found or inactive",
        )
    
    return org


# ============================================================================
# VM ACCESS DEPENDENCIES
# ============================================================================

async def get_vm_or_404(
    vm_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> VirtualMachine:
    """
    Get a VM by ID with proper access control.
    
    Access rules:
    - Superadmins: Can access all VMs
    - Org Admins: Can access all VMs in their organization
    - Members: Can only access VMs they own
    - Viewers: Read-only access based on org membership
    
    Raises HTTPException with 404 if VM not found or 403 if access denied.
    """
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()
    
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Virtual machine with ID {vm_id} not found",
        )
    
    # Superadmins can access all VMs
    if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
        return vm
    
    # Org admins can access all VMs in their organization
    if current_user.role == UserRole.ORG_ADMIN:
        if vm.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: VM belongs to a different organization",
            )
        return vm
    
    # Members and viewers can only access their own VMs
    if vm.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You can only access your own virtual machines",
        )
    
    return vm


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentOrg = Annotated[Organization, Depends(get_organization_from_user)]
SuperAdminUser = Annotated[User, Depends(is_superadmin)]
OrgAdminUser = Annotated[User, Depends(is_org_admin)]
DbSession = Annotated[Session, Depends(get_db)]


# ============================================================================
# WEBSOCKET AUTHENTICATION
# ============================================================================

async def get_websocket_user(
    websocket: WebSocket,
    db: Session
) -> Optional[User]:
    """
    Authenticate a WebSocket connection.
    Accepts token via query parameter or subprotocol.
    """
    token = websocket.query_params.get("token")
    
    if not token:
        # Try to get token from subprotocol
        protocols = websocket.subprotocols
        if protocols:
            for protocol in protocols:
                if protocol.startswith("bearer-"):
                    token = protocol.replace("bearer-", "")
                    break
    
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return None
    
    token_data = decode_access_token(token)
    if token_data is None or token_data.user_id is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return None
    
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        await websocket.close(code=4003, reason="User not found")
        return None
    
    return user


# ============================================================================
# AUDIT LOGGING HELPER
# ============================================================================

async def log_activity(
    db: Session,
    user: User,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None
):
    """
    Log an activity for audit purposes.
    """
    from app.models import ActivityLog
    
    if not settings.AUDIT_LOG_ENABLED:
        return
    
    log_entry = ActivityLog(
        user_id=user.id,
        organization_id=user.organization_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=str(details) if details else None,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        error_message=error_message,
    )
    
    db.add(log_entry)
    db.commit()
