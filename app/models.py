"""
Dukkan Cloud - Database Models
Production-ready SQLAlchemy ORM models with multi-tenancy and RBAC support.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, 
    Enum, Float, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, declarative_base
import uuid

Base = declarative_base()


def generate_uuid() -> str:
    """Generate a unique UUID string."""
    return str(uuid.uuid4())


class UserRole(PyEnum):
    """User role enumeration for RBAC."""
    SUPERADMIN = "superadmin"
    ORG_ADMIN = "org_admin"
    MEMBER = "member"
    VIEWER = "viewer"


class VMStatus(PyEnum):
    """Virtual Machine status enumeration."""
    STOPPED = "stopped"
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    ERROR = "error"


class VMType(PyEnum):
    """Virtual Machine type enumeration."""
    LXC = "lxc"
    QEMU = "qemu"


class FirewallAction(PyEnum):
    """Firewall rule action enumeration."""
    ALLOW = "allow"
    DENY = "deny"
    REJECT = "reject"


class FirewallProtocol(PyEnum):
    """Firewall protocol enumeration."""
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ALL = "all"


class VolumeStatus(PyEnum):
    """Volume status enumeration."""
    AVAILABLE = "available"
    IN_USE = "in_use"
    ATTACHING = "attaching"
    DETACHING = "detaching"
    ERROR = "error"


class NetworkType(PyEnum):
    """Network type enumeration."""
    VPC = "vpc"
    PUBLIC = "public"
    PRIVATE = "private"


# ============================================================================
# ORGANIZATION MODELS
# ============================================================================

class Organization(Base):
    """
    Organization model for multi-tenancy.
    Each organization can have multiple users, VMs, networks, and volumes.
    """
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    virtual_machines = relationship("VirtualMachine", back_populates="organization", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="organization", cascade="all, delete-orphan")
    networks = relationship("Network", back_populates="organization", cascade="all, delete-orphan")
    volumes = relationship("Volume", back_populates="organization", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="organization", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="organization", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_org_name', 'name'),
        Index('idx_org_active', 'is_active'),
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name})>"


# ============================================================================
# USER & AUTH MODELS
# ============================================================================

class User(Base):
    """
    User model with RBAC support.
    Users belong to an organization and have role-based permissions.
    """
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.MEMBER, nullable=False)
    is_platform_admin = Column(Boolean, default=False, nullable=False)
    max_vms = Column(Integer, default=3, nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="members")
    owned_vms = relationship("VirtualMachine", foreign_keys="VirtualMachine.owner_id", back_populates="owner")
    activity_logs = relationship("ActivityLog", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_org', 'organization_id'),
        Index('idx_user_role', 'role'),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class APIKey(Base):
    """
    API Key model for programmatic access (Terraform/Ansible).
    Keys are stored as hashes for security.
    """
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False, index=True)
    prefix = Column(String(8), nullable=False)  # First 8 chars for identification
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="api_keys")
    organization = relationship("Organization", back_populates="api_keys")

    __table_args__ = (
        Index('idx_api_key_prefix', 'prefix'),
        Index('idx_api_key_user', 'user_id'),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name}, prefix={self.prefix})>"


# ============================================================================
# PROJECT MODELS
# ============================================================================

class Project(Base):
    """
    Project model for grouping resources.
    Projects belong to a user (owner) and can contain VMs.
    """
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("User", back_populates="projects")
    virtual_machines = relationship("VirtualMachine", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_project_name', 'name'),
        Index('idx_project_owner', 'owner_id'),
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"


# ============================================================================
# VIRTUAL MACHINE MODELS
# ============================================================================

class VirtualMachine(Base):
    """
    Virtual Machine model representing Proxmox LXC/QEMU instances.
    Includes Guacamole integration for browser-based console access.
    """
    __tablename__ = "virtual_machines"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    proxmox_vmid = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    hostname = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    status = Column(Enum(VMStatus), default=VMStatus.STOPPED, nullable=False)
    vm_type = Column(Enum(VMType), default=VMType.QEMU, nullable=False)
    node = Column(String(255), default="cloud", nullable=False)
    
    # Resource specifications
    cpu_cores = Column(Integer, default=2, nullable=False)
    ram_gb = Column(Integer, default=4, nullable=False)
    disk_gb = Column(Integer, default=50, nullable=False)
    
    # Guacamole integration
    guac_username = Column(String(255), nullable=True)
    guac_password = Column(String(255), nullable=True)  # Encrypted at rest
    guac_connection_id = Column(String(255), nullable=True, index=True)
    guac_protocol = Column(String(10), nullable=True)  # ssh, rdp, vnc
    
    # Foreign keys
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    network_id = Column(String(36), ForeignKey("networks.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_vms")
    organization = relationship("Organization", back_populates="virtual_machines")
    project = relationship("Project", back_populates="virtual_machines")
    network = relationship("Network", back_populates="virtual_machines")
    volumes = relationship("VolumeAttachment", back_populates="vm", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="vm", cascade="all, delete-orphan")
    firewall_rules = relationship("FirewallRule", back_populates="vm", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_vm_org_status', 'organization_id', 'status'),
        Index('idx_vm_owner', 'owner_id'),
        Index('idx_vm_proxmox', 'proxmox_vmid'),
    )

    def __repr__(self) -> str:
        return f"<VirtualMachine(id={self.id}, name={self.name}, status={self.status})>"


# ============================================================================
# NETWORKING MODELS (VPC & Firewalls)
# ============================================================================

class Network(Base):
    """
    Network model for VPC and private networking.
    Supports CIDR notation and VLAN tagging.
    """
    __tablename__ = "networks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    cidr = Column(String(18), nullable=False)  # e.g., "10.0.0.0/24"
    network_type = Column(Enum(NetworkType), default=NetworkType.VPC, nullable=False)
    vlan_id = Column(Integer, nullable=True)  # VLAN tag (1-4094)
    gateway = Column(String(45), nullable=True)
    dns_servers = Column(String(255), nullable=True)  # Comma-separated
    is_default = Column(Boolean, default=False, nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="networks")
    virtual_machines = relationship("VirtualMachine", back_populates="network")
    firewall_rules = relationship("FirewallRule", back_populates="network", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_network_org', 'organization_id'),
        Index('idx_network_cidr', 'cidr'),
    )

    def __repr__(self) -> str:
        return f"<Network(id={self.id}, name={self.name}, cidr={self.cidr})>"


class FirewallRule(Base):
    """
    Firewall rule model for network security.
    Supports allow/deny rules with port ranges and CIDR blocks.
    """
    __tablename__ = "firewall_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    action = Column(Enum(FirewallAction), default=FirewallAction.ALLOW, nullable=False)
    protocol = Column(Enum(FirewallProtocol), default=FirewallProtocol.TCP, nullable=False)
    port_start = Column(Integer, nullable=True)  # Start of port range
    port_end = Column(Integer, nullable=True)  # End of port range
    source_cidr = Column(String(18), nullable=True)  # Source IP/CIDR
    destination_cidr = Column(String(18), nullable=True)  # Destination IP/CIDR
    direction = Column(String(10), default="ingress", nullable=False)  # ingress/egress
    priority = Column(Integer, default=100, nullable=False)  # Lower = higher priority
    is_enabled = Column(Boolean, default=True, nullable=False)
    
    # Foreign keys
    vm_id = Column(String(36), ForeignKey("virtual_machines.id"), nullable=True)
    network_id = Column(String(36), ForeignKey("networks.id"), nullable=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    vm = relationship("VirtualMachine", back_populates="firewall_rules")
    network = relationship("Network", back_populates="firewall_rules")
    organization = relationship("Organization")

    __table_args__ = (
        Index('idx_fw_vm', 'vm_id'),
        Index('idx_fw_network', 'network_id'),
        Index('idx_fw_priority', 'priority'),
    )

    def __repr__(self) -> str:
        return f"<FirewallRule(id={self.id}, name={self.name}, action={self.action})>"


# ============================================================================
# STORAGE MODELS (Block Storage & Volumes)
# ============================================================================

class Volume(Base):
    """
    Volume model for block storage.
    Volumes can be attached to VMs or remain independent.
    """
    __tablename__ = "volumes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, index=True)
    size_gb = Column(Integer, nullable=False)
    volume_type = Column(String(50), default="ssd", nullable=False)  # ssd, hdd, nvme
    status = Column(Enum(VolumeStatus), default=VolumeStatus.AVAILABLE, nullable=False)
    filesystem = Column(String(20), default="ext4", nullable=True)
    mount_point = Column(String(255), nullable=True)
    proxmox_storage = Column(String(255), nullable=False)  # Proxmox storage name
    proxmox_volume_id = Column(String(255), nullable=True)  # e.g., "local-lvm:vm-100-disk-1"
    
    # Foreign keys
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    attached_to_id = Column(String(36), ForeignKey("virtual_machines.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    attached_at = Column(DateTime, nullable=True)
    detached_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="volumes")
    attachments = relationship("VolumeAttachment", back_populates="volume", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_volume_org', 'organization_id'),
        Index('idx_volume_status', 'status'),
    )

    def __repr__(self) -> str:
        return f"<Volume(id={self.id}, name={self.name}, size_gb={self.size_gb})>"


class VolumeAttachment(Base):
    """
    Volume attachment model tracking VM-Volume relationships.
    """
    __tablename__ = "volume_attachments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    volume_id = Column(String(36), ForeignKey("volumes.id"), nullable=False)
    vm_id = Column(String(36), ForeignKey("virtual_machines.id"), nullable=False)
    device_name = Column(String(50), nullable=True)  # e.g., "/dev/sdb"
    is_boot_volume = Column(Boolean, default=False, nullable=False)
    attached_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    detached_at = Column(DateTime, nullable=True)

    # Relationships
    volume = relationship("Volume", back_populates="attachments")
    vm = relationship("VirtualMachine", back_populates="volumes")

    __table_args__ = (
        UniqueConstraint('volume_id', 'vm_id', name='uq_volume_vm'),
        Index('idx_attachment_vm', 'vm_id'),
    )

    def __repr__(self) -> str:
        return f"<VolumeAttachment(id={self.id}, volume_id={self.volume_id}, vm_id={self.vm_id})>"


# ============================================================================
# BILLING & USAGE MODELS
# ============================================================================

class UsageLog(Base):
    """
    Usage log model for billing calculations.
    Tracks hourly resource consumption per VM.
    """
    __tablename__ = "usage_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    vm_id = Column(String(36), ForeignKey("virtual_machines.id"), nullable=False)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    
    # Resource usage
    cpu_cores = Column(Integer, nullable=False)
    ram_gb = Column(Integer, nullable=False)
    storage_gb = Column(Integer, nullable=False)
    
    # Time tracking
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_hours = Column(Float, default=0.0, nullable=False)
    
    # Cost calculation
    cpu_cost = Column(Float, default=0.0, nullable=False)
    ram_cost = Column(Float, default=0.0, nullable=False)
    storage_cost = Column(Float, default=0.0, nullable=False)
    total_cost = Column(Float, default=0.0, nullable=False)
    
    # Billing period
    billing_period = Column(String(7), nullable=False, index=True)  # YYYY-MM format
    is_billed = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    vm = relationship("VirtualMachine", back_populates="usage_logs")
    organization = relationship("Organization")

    __table_args__ = (
        Index('idx_usage_vm', 'vm_id'),
        Index('idx_usage_org_period', 'organization_id', 'billing_period'),
        Index('idx_usage_billed', 'is_billed'),
    )

    def __repr__(self) -> str:
        return f"<UsageLog(id={self.id}, vm_id={self.vm_id}, period={self.billing_period})>"


class Invoice(Base):
    """
    Invoice model for monthly billing summaries.
    """
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    
    # Billing period
    billing_period = Column(String(7), nullable=False)  # YYYY-MM format
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    
    # Amounts
    subtotal = Column(Float, default=0.0, nullable=False)
    tax_rate = Column(Float, default=0.0, nullable=False)
    tax_amount = Column(Float, default=0.0, nullable=False)
    total_amount = Column(Float, default=0.0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    
    # Status
    status = Column(String(50), default="draft", nullable=False)  # draft, sent, paid, overdue
    due_date = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    
    # Metadata
    metadata = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="invoices")

    __table_args__ = (
        Index('idx_invoice_org', 'organization_id'),
        Index('idx_invoice_period', 'billing_period'),
        Index('idx_invoice_status', 'status'),
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number={self.invoice_number}, status={self.status})>"


# ============================================================================
# AUDIT LOGGING MODELS
# ============================================================================

class ActivityLog(Base):
    """
    Activity log model for audit trails.
    Tracks all user actions across the platform.
    """
    __tablename__ = "activity_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True)
    
    # Action details
    action = Column(String(100), nullable=False, index=True)  # e.g., "vm.create", "user.login"
    resource_type = Column(String(50), nullable=True)  # e.g., "virtual_machine", "user"
    resource_id = Column(String(36), nullable=True)
    details = Column(Text, nullable=True)  # JSON string with additional context
    
    # Request info
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Outcome
    status = Column(String(20), default="success", nullable=False)  # success, failure, error
    error_message = Column(Text, nullable=True)
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="activity_logs")
    organization = relationship("Organization", back_populates="activity_logs")

    __table_args__ = (
        Index('idx_activity_user', 'user_id'),
        Index('idx_activity_org', 'organization_id'),
        Index('idx_activity_timestamp', 'timestamp'),
        Index('idx_action_resource', 'resource_type', 'resource_id'),
    )

    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id}, action={self.action}, timestamp={self.timestamp})>"
