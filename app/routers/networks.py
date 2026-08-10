"""
Dukkan Cloud - Networks Router (VPC & Firewalls)
Handles VPC creation, management, and firewall rules.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List
import logging
import ipaddress

from app.database import get_db
from app.models import Network, FirewallRule, VirtualMachine, UserRole
from app.schemas import (
    NetworkCreate, NetworkUpdate, NetworkResponse,
    FirewallRuleCreate, FirewallRuleUpdate, FirewallRuleResponse
)
from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session

DbSession = Annotated[Session, Depends(get_db)]

from app.dependencies import (
    get_current_user, is_org_admin, log_activity, CurrentUser
)
from app.services.proxmox_service import proxmox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/networks", tags=["Networks"])


@router.get("/", response_model=List[NetworkResponse])
async def list_networks(
    current_user: CurrentUser,
    db: DbSession
):
    """List all networks in the organization."""
    if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
        networks = db.query(Network).all()
    else:
        networks = db.query(Network).filter(
            Network.organization_id == current_user.organization_id
        ).all()
    
    return networks


@router.post("/", response_model=NetworkResponse, status_code=status.HTTP_201_CREATED)
async def create_network(
    network_data: NetworkCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Create a new VPC/private network."""
    # Validate CIDR
    try:
        ipaddress.ip_network(network_data.cidr, strict=False)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid CIDR notation: {e}"
        )
    
    network = Network(
        name=network_data.name,
        description=network_data.description,
        cidr=network_data.cidr,
        network_type=network_data.network_type,
        vlan_id=network_data.vlan_id,
        gateway=network_data.gateway,
        dns_servers=network_data.dns_servers,
        is_default=network_data.is_default,
        organization_id=current_user.organization_id,
    )
    
    db.add(network)
    db.commit()
    db.refresh(network)
    
    await log_activity(
        db=db,
        user=current_user,
        action="network.create",
        resource_type="network",
        resource_id=network.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Network created: {network.name}")
    return network


@router.get("/{network_id}", response_model=NetworkResponse)
async def get_network(
    network_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """Get network details."""
    network = _get_network_or_404(network_id, current_user, db)
    return network


@router.put("/{network_id}", response_model=NetworkResponse)
async def update_network(
    network_id: str,
    network_data: NetworkUpdate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Update network configuration."""
    network = _get_network_or_404(network_id, current_user, db)
    
    if network_data.name:
        network.name = network_data.name
    if network_data.description is not None:
        network.description = network_data.description
    if network_data.gateway:
        network.gateway = network_data.gateway
    if network_data.dns_servers:
        network.dns_servers = network_data.dns_servers
    if network_data.is_default is not None:
        network.is_default = network_data.is_default
    
    db.commit()
    db.refresh(network)
    
    await log_activity(
        db=db,
        user=current_user,
        action="network.update",
        resource_type="network",
        resource_id=network.id,
        ip_address=request.client.host,
    )
    
    return network


@router.delete("/{network_id}")
async def delete_network(
    network_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Delete a network."""
    network = _get_network_or_404(network_id, current_user, db)
    
    # Check if network has VMs attached
    vm_count = db.query(VirtualMachine).filter(
        VirtualMachine.network_id == network.id
    ).count()
    
    if vm_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete network with {vm_count} VM(s) attached"
        )
    
    db.delete(network)
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="network.delete",
        resource_type="network",
        resource_id=network.id,
        ip_address=request.client.host,
    )
    
    return {"message": "Network deleted successfully"}


# ============================================================================
# FIREWALL RULES
# ============================================================================

@router.get("/{network_id}/firewall", response_model=List[FirewallRuleResponse])
async def list_firewall_rules(
    network_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """List firewall rules for a network."""
    network = _get_network_or_404(network_id, current_user, db)
    
    rules = db.query(FirewallRule).filter(
        FirewallRule.network_id == network_id
    ).order_by(FirewallRule.priority.asc()).all()
    
    return rules


@router.post("/{network_id}/firewall", response_model=FirewallRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_firewall_rule(
    network_id: str,
    rule_data: FirewallRuleCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Create a new firewall rule."""
    network = _get_network_or_404(network_id, current_user, db)
    
    rule = FirewallRule(
        name=rule_data.name,
        action=rule_data.action,
        protocol=rule_data.protocol,
        port_start=rule_data.port_start,
        port_end=rule_data.port_end,
        source_cidr=rule_data.source_cidr,
        destination_cidr=rule_data.destination_cidr,
        direction=rule_data.direction,
        priority=rule_data.priority,
        is_enabled=rule_data.is_enabled,
        network_id=network_id,
        organization_id=current_user.organization_id,
    )
    
    db.add(rule)
    db.commit()
    db.refresh(rule)
    
    # Apply rule to Proxmox firewall (if VMs are attached)
    vms = db.query(VirtualMachine).filter(VirtualMachine.network_id == network_id).all()
    for vm in vms:
        try:
            await proxmox_service.apply_firewall_rules(vm, [_rule_to_proxmox_dict(rule)])
        except Exception as e:
            logger.warning(f"Failed to apply firewall rule to VM {vm.proxmox_vmid}: {e}")
    
    await log_activity(
        db=db,
        user=current_user,
        action="firewall_rule.create",
        resource_type="firewall_rule",
        resource_id=rule.id,
        ip_address=request.client.host,
    )
    
    return rule


@router.put("/firewall/{rule_id}", response_model=FirewallRuleResponse)
async def update_firewall_rule(
    rule_id: str,
    rule_data: FirewallRuleUpdate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Update a firewall rule."""
    rule = db.query(FirewallRule).filter(
        FirewallRule.id == rule_id,
        FirewallRule.organization_id == current_user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firewall rule not found"
        )
    
    if rule_data.name:
        rule.name = rule_data.name
    if rule_data.action:
        rule.action = rule_data.action
    if rule_data.protocol:
        rule.protocol = rule_data.protocol
    if rule_data.port_start is not None:
        rule.port_start = rule_data.port_start
    if rule_data.port_end is not None:
        rule.port_end = rule_data.port_end
    if rule_data.source_cidr:
        rule.source_cidr = rule_data.source_cidr
    if rule_data.destination_cidr:
        rule.destination_cidr = rule_data.destination_cidr
    if rule_data.priority is not None:
        rule.priority = rule_data.priority
    if rule_data.is_enabled is not None:
        rule.is_enabled = rule_data.is_enabled
    
    db.commit()
    db.refresh(rule)
    
    await log_activity(
        db=db,
        user=current_user,
        action="firewall_rule.update",
        resource_type="firewall_rule",
        resource_id=rule.id,
        ip_address=request.client.host,
    )
    
    return rule


@router.delete("/firewall/{rule_id}")
async def delete_firewall_rule(
    rule_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Delete a firewall rule."""
    rule = db.query(FirewallRule).filter(
        FirewallRule.id == rule_id,
        FirewallRule.organization_id == current_user.organization_id
    ).first()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firewall rule not found"
        )
    
    db.delete(rule)
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="firewall_rule.delete",
        resource_type="firewall_rule",
        resource_id=rule.id,
        ip_address=request.client.host,
    )
    
    return {"message": "Firewall rule deleted"}


def _get_network_or_404(network_id: str, user: CurrentUser, db: DbSession) -> Network:
    """Get network or raise 404/403."""
    if user.role == UserRole.SUPERADMIN or user.is_platform_admin:
        network = db.query(Network).filter(Network.id == network_id).first()
    else:
        network = db.query(Network).filter(
            Network.id == network_id,
            Network.organization_id == user.organization_id
        ).first()
    
    if not network:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Network not found"
        )
    
    return network


def _rule_to_proxmox_dict(rule: FirewallRule) -> dict:
    """Convert firewall rule to Proxmox format."""
    return {
        "type": rule.direction,
        "action": rule.action.value,
        "proto": rule.protocol.value,
        "dest_port": f"{rule.port_start}-{rule.port_end}" if rule.port_start and rule.port_end else None,
        "source": rule.source_cidr,
        "dest": rule.destination_cidr,
    }
