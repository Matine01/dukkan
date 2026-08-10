"""
Dukkan Cloud - Pydantic Schemas
Production-ready request/response schemas with validation.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr, validator, constr
import re


# ============================================================================
# ENUMS
# ============================================================================

class UserRole(str, Enum):
    SUPERADMIN = "superadmin"
    ORG_ADMIN = "org_admin"
    MEMBER = "member"
    VIEWER = "viewer"


class VMStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    ERROR = "error"


class VMType(str, Enum):
    LXC = "lxc"
    QEMU = "qemu"


class FirewallAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REJECT = "reject"


class FirewallProtocol(str, Enum):
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ALL = "all"


class VolumeStatus(str, Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    ATTACHING = "attaching"
    DETACHING = "detaching"
    ERROR = "error"


class NetworkType(str, Enum):
    VPC = "vpc"
    PUBLIC = "public"
    PRIVATE = "private"


# ============================================================================
# MIXINS
# ============================================================================

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: Optional[datetime] = None


class IDMixin(BaseModel):
    id: str


# ============================================================================
# ORGANIZATION SCHEMAS
# ============================================================================

class OrganizationBase(BaseModel):
    name: constr(min_length=2, max_length=255)


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    is_active: Optional[bool] = None


class OrganizationResponse(OrganizationBase, IDMixin, TimestampMixin):
    is_active: bool
    member_count: int = 0
    vm_count: int = 0

    class Config:
        from_attributes = True


# ============================================================================
# USER & AUTH SCHEMAS
# ============================================================================

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[constr(max_length=255)] = None
    role: UserRole = UserRole.MEMBER
    max_vms: int = Field(default=3, ge=1, le=50)


class UserCreate(UserBase):
    password: constr(min_length=8)
    organization_id: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[constr(max_length=255)] = None
    role: Optional[UserRole] = None
    max_vms: Optional[int] = Field(default=None, ge=1, le=50)
    is_platform_admin: Optional[bool] = None


class UserResponse(UserBase, IDMixin, TimestampMixin):
    organization_id: Optional[str]
    is_platform_admin: bool
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[UserRole] = None
    organization_id: Optional[str] = None


# ============================================================================
# API KEY SCHEMAS
# ============================================================================

class APIKeyBase(BaseModel):
    name: constr(min_length=1, max_length=255)
    expires_at: Optional[datetime] = None


class APIKeyCreate(APIKeyBase):
    pass


class APIKeyResponse(IDMixin, TimestampMixin):
    name: str
    prefix: str
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    user_id: str

    class Config:
        from_attributes = True


class APIKeySecret(BaseModel):
    api_key: APIKeyResponse
    secret_key: str  # Only shown once at creation


# ============================================================================
# PROJECT SCHEMAS
# ============================================================================

class ProjectBase(BaseModel):
    name: constr(min_length=2, max_length=255)
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    organization_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(ProjectBase, IDMixin, TimestampMixin):
    owner_id: str
    organization_id: Optional[str]
    is_active: bool
    vm_count: int = 0

    class Config:
        from_attributes = True


# ============================================================================
# VIRTUAL MACHINE SCHEMAS
# ============================================================================

class VMNetworkConfig(BaseModel):
    network_id: Optional[str] = None
    ip_address: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: Optional[List[str]] = None


class VMCloudInit(BaseModel):
    username: Optional[str] = "ubuntu"
    password: Optional[constr(min_length=8)] = None
    ssh_keys: Optional[List[str]] = None
    user_data: Optional[str] = None


class VMCreateBase(BaseModel):
    name: constr(min_length=2, max_length=255)
    hostname: constr(min_length=2, max_length=255)
    vm_type: VMType = VMType.QEMU
    cpu_cores: int = Field(default=2, ge=1, le=64)
    ram_gb: int = Field(default=4, ge=1, le=512)
    disk_gb: int = Field(default=50, ge=10, le=4096)
    project_id: Optional[str] = None
    network_id: Optional[str] = None
    cloud_init: Optional[VMCloudInit] = None


class VMCreateLXC(VMCreateBase):
    vm_type: VMType = VMType.LXC
    template_id: int = Field(..., description="Proxmox LXC template ID")


class VMCreateQEMU(VMCreateBase):
    vm_type: VMType = VMType.QEMU
    template_id: int = Field(..., description="Proxmox QEMU template ID")
    os_type: str = Field(default="linux", description="linux or windows")


class VMUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    cpu_cores: Optional[int] = Field(default=None, ge=1, le=64)
    ram_gb: Optional[int] = Field(default=None, ge=1, le=512)


class VMResponse(IDMixin, TimestampMixin):
    proxmox_vmid: int
    name: str
    hostname: str
    ip_address: Optional[str] = None
    status: VMStatus
    vm_type: VMType
    node: str
    cpu_cores: int
    ram_gb: int
    disk_gb: int
    guac_protocol: Optional[str] = None
    owner_id: str
    organization_id: str
    project_id: Optional[str] = None
    network_id: Optional[str] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VMWithGuacamole(VMResponse):
    guac_url: Optional[str] = None
    guac_credentials: Optional[Dict[str, str]] = None  # Separate from URL for security


class VMAction(BaseModel):
    action: str  # start, stop, restart, reset


# ============================================================================
# NETWORK SCHEMAS
# ============================================================================

class NetworkBase(BaseModel):
    name: constr(min_length=2, max_length=255)
    description: Optional[str] = None
    cidr: str  # e.g., "10.0.0.0/24"
    network_type: NetworkType = NetworkType.VPC
    vlan_id: Optional[int] = Field(default=None, ge=1, le=4094)
    gateway: Optional[str] = None
    dns_servers: Optional[str] = None  # Comma-separated
    is_default: bool = False


class NetworkCreate(NetworkBase):
    pass


class NetworkUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    description: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: Optional[str] = None
    is_default: Optional[bool] = None


class NetworkResponse(NetworkBase, IDMixin, TimestampMixin):
    organization_id: str
    vm_count: int = 0

    class Config:
        from_attributes = True


# ============================================================================
# FIREWALL SCHEMAS
# ============================================================================

class FirewallRuleBase(BaseModel):
    name: constr(min_length=2, max_length=255)
    action: FirewallAction = FirewallAction.ALLOW
    protocol: FirewallProtocol = FirewallProtocol.TCP
    port_start: Optional[int] = Field(default=None, ge=1, le=65535)
    port_end: Optional[int] = Field(default=None, ge=1, le=65535)
    source_cidr: Optional[str] = None
    destination_cidr: Optional[str] = None
    direction: str = Field(default="ingress", pattern="^(ingress|egress)$")
    priority: int = Field(default=100, ge=1, le=1000)
    is_enabled: bool = True


class FirewallRuleCreate(FirewallRuleBase):
    vm_id: Optional[str] = None
    network_id: Optional[str] = None


class FirewallRuleUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    action: Optional[FirewallAction] = None
    protocol: Optional[FirewallProtocol] = None
    port_start: Optional[int] = Field(default=None, ge=1, le=65535)
    port_end: Optional[int] = Field(default=None, ge=1, le=65535)
    source_cidr: Optional[str] = None
    destination_cidr: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=1000)
    is_enabled: Optional[bool] = None


class FirewallRuleResponse(FirewallRuleBase, IDMixin, TimestampMixin):
    vm_id: Optional[str] = None
    network_id: Optional[str] = None
    organization_id: str

    class Config:
        from_attributes = True


# ============================================================================
# VOLUME SCHEMAS
# ============================================================================

class VolumeBase(BaseModel):
    name: constr(min_length=2, max_length=255)
    size_gb: int = Field(ge=1, le=16384)
    volume_type: str = Field(default="ssd", pattern="^(ssd|hdd|nvme)$")
    filesystem: Optional[str] = Field(default="ext4", pattern="^(ext4|xfs|ntfs)$")
    proxmox_storage: str = "local-lvm"


class VolumeCreate(VolumeBase):
    vm_id: Optional[str] = None  # Attach to VM on creation


class VolumeUpdate(BaseModel):
    name: Optional[constr(min_length=2, max_length=255)] = None
    size_gb: Optional[int] = Field(default=None, ge=1, le=16384)


class VolumeResponse(VolumeBase, IDMixin, TimestampMixin):
    status: VolumeStatus
    mount_point: Optional[str] = None
    proxmox_volume_id: Optional[str] = None
    organization_id: str
    attached_to_id: Optional[str] = None
    attached_at: Optional[datetime] = None
    detached_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VolumeAttach(BaseModel):
    vm_id: str
    device_name: Optional[str] = None


class VolumeDetach(BaseModel):
    force: bool = False


# ============================================================================
# BILLING SCHEMAS
# ============================================================================

class UsageLogResponse(IDMixin):
    vm_id: str
    vm_name: Optional[str] = None
    cpu_cores: int
    ram_gb: int
    storage_gb: int
    duration_hours: float
    cpu_cost: float
    ram_cost: float
    storage_cost: float
    total_cost: float
    billing_period: str
    start_time: datetime
    end_time: Optional[datetime] = None
    is_billed: bool

    class Config:
        from_attributes = True


class InvoiceResponse(IDMixin, TimestampMixin):
    invoice_number: str
    organization_id: str
    billing_period: str
    period_start: datetime
    period_end: datetime
    subtotal: float
    tax_rate: float
    tax_amount: float
    total_amount: float
    currency: str
    status: str
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BillingSummary(BaseModel):
    current_period: str
    total_usage: float
    total_cost: float
    vm_count: int
    volume_count: int
    breakdown: Dict[str, float] = {}


# ============================================================================
# ACTIVITY LOG SCHEMAS
# ============================================================================

class ActivityLogResponse(IDMixin):
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    organization_id: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ADMIN SCHEMAS
# ============================================================================

class PlatformStats(BaseModel):
    total_organizations: int
    total_users: int
    total_vms: int
    total_vms_running: int
    total_volumes: int
    total_networks: int
    monthly_revenue: float
    active_sessions: int


class AdminUserCreate(UserCreate):
    organization_id: Optional[str] = None
    is_platform_admin: bool = False


# ============================================================================
# WEBSOCKET MESSAGES
# ============================================================================

class WSMessage(BaseModel):
    type: str  # console, log, status
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConsoleData(BaseModel):
    vm_id: str
    output: str
    cursor_x: int = 0
    cursor_y: int = 0


class LogData(BaseModel):
    vm_id: str
    message: str
    level: str = "info"  # info, warning, error
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# RESPONSE WRAPPERS
# ============================================================================

class ResponseMeta(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 1


class PaginatedResponse(BaseModel):
    items: List[Any]
    meta: ResponseMeta


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    field_errors: Optional[List[Dict[str, str]]] = None
