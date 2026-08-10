"""
Dukkan Cloud - Virtual Machines Router
Handles VM/LXC provisioning, lifecycle management, and console access.
"""

import random
from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import asyncio

from app.database import get_db
from app.models import (
    VirtualMachine, VMType, VMStatus, User, UserRole,
    Organization, Project, Network, VolumeAttachment
)
from app.schemas import (
    VMCreateLXC, VMCreateQEMU, VMResponse, VMWithGuacamole,
    VMUpdate, PaginatedResponse
)
from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session

DbSession = Annotated[Session, Depends(get_db)]

from app.dependencies import (
    get_current_user, get_vm_or_404, is_superadmin, is_org_admin,
    log_activity, CurrentUser, get_websocket_user
)
from app.services.proxmox_service import proxmox_service, ProxmoxAPIError
from app.services.guacamole_service import guacamole_service, GuacamoleAPIError
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vms", tags=["Virtual Machines"])


def generate_vmid() -> int:
    """Generate a unique VM ID for Proxmox."""
    return random.randint(10000, 99999)


@router.get("/", response_model=List[VMResponse])
async def list_vms(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[str] = None,
    vm_type: Optional[str] = None
):
    """
    List virtual machines accessible by the current user.
    
    Access rules:
    - Superadmins: See all VMs
    - Org Admins: See all VMs in their organization
    - Members: See only their own VMs
    """
    query = db.query(VirtualMachine)
    
    # Apply filters based on role
    if current_user.role == UserRole.SUPERADMIN or current_user.is_platform_admin:
        pass  # See all VMs
    elif current_user.role == UserRole.ORG_ADMIN:
        query = query.filter(VirtualMachine.organization_id == current_user.organization_id)
    else:
        query = query.filter(VirtualMachine.owner_id == current_user.id)
    
    # Apply optional filters
    if status_filter:
        try:
            vm_status = VMStatus(status_filter)
            query = query.filter(VirtualMachine.status == vm_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )
    
    if vm_type:
        try:
            vm_type_enum = VMType(vm_type)
            query = query.filter(VirtualMachine.vm_type == vm_type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid VM type: {vm_type}"
            )
    
    vms = query.order_by(VirtualMachine.created_at.desc()).all()
    return vms


@router.post("/lxc", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
async def create_lxc(
    vm_data: VMCreateLXC,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Create a new LXC container.
    
    Clones from template, configures resources, starts the container,
    waits for IP, and creates Guacamole connection.
    """
    # Check VM quota
    user_vm_count = db.query(VirtualMachine).filter(
        VirtualMachine.owner_id == current_user.id
    ).count()
    
    if user_vm_count >= current_user.max_vms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"VM quota exceeded. Maximum allowed: {current_user.max_vms}"
        )
    
    # Get network if specified
    network = None
    if vm_data.network_id:
        network = db.query(Network).filter(
            Network.id == vm_data.network_id,
            Network.organization_id == current_user.organization_id
        ).first()
        if not network:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Network not found"
            )
    
    # Generate VM ID
    proxmox_vmid = generate_vmid()
    
    try:
        # Create LXC in Proxmox
        await proxmox_service.create_lxc(proxmox_vmid, vm_data, network)
        
        # Create database record
        vm = VirtualMachine(
            proxmox_vmid=proxmox_vmid,
            name=vm_data.name,
            hostname=vm_data.hostname,
            vm_type=VMType.LXC,
            cpu_cores=vm_data.cpu_cores,
            ram_gb=vm_data.ram_gb,
            disk_gb=vm_data.disk_gb,
            owner_id=current_user.id,
            organization_id=current_user.organization_id,
            project_id=vm_data.project_id,
            network_id=vm_data.network_id,
            node=settings.PROXMOX_NODE,
            status=VMStatus.STARTING,
        )
        
        db.add(vm)
        db.commit()
        db.refresh(vm)
        
        # Start the container
        await proxmox_service.start_vm(vm)
        
        # Wait for IP address
        ip_address = await proxmox_service.get_vm_ip(vm, timeout=120)
        if ip_address:
            vm.ip_address = ip_address
        
        # Create Guacamole connection (SSH for LXC)
        if vm_data.cloud_init and vm_data.cloud_init.password:
            try:
                guac_username = vm_data.cloud_init.username or "root"
                connection_id, _ = await guacamole_service.create_connection(
                    name=f"{vm.name}-console",
                    protocol="ssh",
                    hostname=ip_address or vm.hostname,
                    port=22,
                    username=guac_username,
                    password=vm_data.cloud_init.password,
                    vm_id=vm.id,
                    organization_id=vm.organization_id,
                )
                
                vm.guac_connection_id = connection_id
                vm.guac_username = guac_username
                vm.guac_protocol = "ssh"
                
            except GuacamoleAPIError as e:
                logger.warning(f"Failed to create Guacamole connection: {e}")
        
        vm.status = VMStatus.RUNNING if ip_address else VMStatus.STOPPED
        db.commit()
        
        await log_activity(
            db=db,
            user=current_user,
            action="vm.create_lxc",
            resource_type="virtual_machine",
            resource_id=vm.id,
            details={"proxmox_vmid": proxmox_vmid},
            ip_address=request.client.host,
        )
        
        logger.info(f"LXC created: {vm.name} (VMID: {proxmox_vmid})")
        return vm
        
    except ProxmoxAPIError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Proxmox error: {e.message}"
        )


@router.post("/qemu", response_model=VMResponse, status_code=status.HTTP_201_CREATED)
async def create_qemu(
    vm_data: VMCreateQEMU,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """
    Create a new QEMU VM with Cloud-Init.
    
    Clones from template, injects Cloud-Init config, starts the VM,
    waits for Guest Agent to report IP, and creates Guacamole connection.
    """
    # Check VM quota
    user_vm_count = db.query(VirtualMachine).filter(
        VirtualMachine.owner_id == current_user.id
    ).count()
    
    if user_vm_count >= current_user.max_vms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"VM quota exceeded. Maximum allowed: {current_user.max_vms}"
        )
    
    # Get network if specified
    network = None
    if vm_data.network_id:
        network = db.query(Network).filter(
            Network.id == vm_data.network_id,
            Network.organization_id == current_user.organization_id
        ).first()
        if not network:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Network not found"
            )
    
    # Generate VM ID
    proxmox_vmid = generate_vmid()
    
    try:
        # Create QEMU VM in Proxmox
        await proxmox_service.create_qemu(proxmox_vmid, vm_data, network)
        
        # Create database record
        vm = VirtualMachine(
            proxmox_vmid=proxmox_vmid,
            name=vm_data.name,
            hostname=vm_data.hostname,
            vm_type=VMType.QEMU,
            cpu_cores=vm_data.cpu_cores,
            ram_gb=vm_data.ram_gb,
            disk_gb=vm_data.disk_gb,
            owner_id=current_user.id,
            organization_id=current_user.organization_id,
            project_id=vm_data.project_id,
            network_id=vm_data.network_id,
            node=settings.PROXMOX_NODE,
            status=VMStatus.STARTING,
        )
        
        db.add(vm)
        db.commit()
        db.refresh(vm)
        
        # Start the VM
        await proxmox_service.start_vm(vm)
        
        # Wait for IP address via QEMU Guest Agent
        ip_address = await proxmox_service.get_vm_ip(vm, timeout=180)
        if ip_address:
            vm.ip_address = ip_address
        
        # Determine protocol based on OS type
        protocol = "rdp" if vm_data.os_type == "windows" else "ssh"
        port = 3389 if protocol == "rdp" else 22
        
        # Create Guacamole connection
        if vm_data.cloud_init and vm_data.cloud_init.password:
            try:
                guac_username = vm_data.cloud_init.username or ("Administrator" if vm_data.os_type == "windows" else "ubuntu")
                connection_id, _ = await guacamole_service.create_connection(
                    name=f"{vm.name}-console",
                    protocol=protocol,
                    hostname=ip_address or vm.hostname,
                    port=port,
                    username=guac_username,
                    password=vm_data.cloud_init.password,
                    vm_id=vm.id,
                    organization_id=vm.organization_id,
                )
                
                vm.guac_connection_id = connection_id
                vm.guac_username = guac_username
                vm.guac_protocol = protocol
                
            except GuacamoleAPIError as e:
                logger.warning(f"Failed to create Guacamole connection: {e}")
        
        vm.status = VMStatus.RUNNING if ip_address else VMStatus.STOPPED
        db.commit()
        
        await log_activity(
            db=db,
            user=current_user,
            action="vm.create_qemu",
            resource_type="virtual_machine",
            resource_id=vm.id,
            details={"proxmox_vmid": proxmox_vmid, "os_type": vm_data.os_type},
            ip_address=request.client.host,
        )
        
        logger.info(f"QEMU VM created: {vm.name} (VMID: {proxmox_vmid})")
        return vm
        
    except ProxmoxAPIError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Proxmox error: {e.message}"
        )


@router.get("/{vm_id}", response_model=VMWithGuacamole)
async def get_vm(
    vm: VirtualMachine = Depends(get_vm_or_404),
    current_user: User = Depends(get_current_user)
):
    """
    Get virtual machine details with secure console URL.
    
    SECURITY: Guacamole URL does NOT contain credentials.
    Credentials are returned separately in the response body.
    """
    vm_response = VMWithGuacamole.from_orm(vm)
    
    # Generate secure Guacamole URL (no credentials in URL)
    if vm.guac_connection_id:
        vm_response.guac_url = guacamole_service.generate_secure_url(vm.guac_connection_id)
        
        # Return credentials separately (NEVER in URL)
        if vm.guac_password:
            vm_response.guac_credentials = {
                "username": vm.guac_username,
                "protocol": vm.guac_protocol,
                # Note: Password is not returned here for security
                # Frontend should use existing Guacamole session
            }
    
    return vm_response


@router.post("/{vm_id}/start")
async def start_vm(
    vm: VirtualMachine = Depends(get_vm_or_404),
    db: DbSession,
    request: Request = None,
    current_user: CurrentUser = None
):
    """Start a virtual machine."""
    try:
        await proxmox_service.start_vm(vm)
        
        # Wait for running status
        running = await proxmox_service.wait_for_vm_running(vm)
        
        if running:
            vm.status = VMStatus.RUNNING
            vm.started_at = asyncio.get_event_loop().time()
        else:
            vm.status = VMStatus.ERROR
        
        db.commit()
        
        if request and current_user:
            await log_activity(
                db=db,
                user=current_user,
                action="vm.start",
                resource_type="virtual_machine",
                resource_id=vm.id,
                ip_address=request.client.host if request.client else None,
            )
        
        return {"message": f"VM {vm.name} started successfully", "status": vm.status.value}
        
    except ProxmoxAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start VM: {e.message}"
        )


@router.post("/{vm_id}/stop")
async def stop_vm(
    vm: VirtualMachine = Depends(get_vm_or_404),
    db: DbSession,
    request: Request = None,
    current_user: CurrentUser = None
):
    """Stop a virtual machine gracefully."""
    try:
        await proxmox_service.shutdown_vm(vm)
        vm.status = VMStatus.STOPPING
        vm.stopped_at = asyncio.get_event_loop().time()
        db.commit()
        
        if request and current_user:
            await log_activity(
                db=db,
                user=current_user,
                action="vm.stop",
                resource_type="virtual_machine",
                resource_id=vm.id,
                ip_address=request.client.host if request.client else None,
            )
        
        return {"message": f"VM {vm.name} is stopping", "status": vm.status.value}
        
    except ProxmoxAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop VM: {e.message}"
        )


@router.post("/{vm_id}/restart")
async def restart_vm(
    vm: VirtualMachine = Depends(get_vm_or_404),
    db: DbSession,
    request: Request = None,
    current_user: CurrentUser = None
):
    """Restart a virtual machine."""
    try:
        await proxmox_service.restart_vm(vm)
        vm.status = VMStatus.RESTARTING
        db.commit()
        
        if request and current_user:
            await log_activity(
                db=db,
                user=current_user,
                action="vm.restart",
                resource_type="virtual_machine",
                resource_id=vm.id,
                ip_address=request.client.host if request.client else None,
            )
        
        return {"message": f"VM {vm.name} is restarting", "status": vm.status.value}
        
    except ProxmoxAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart VM: {e.message}"
        )


@router.delete("/{vm_id}")
async def delete_vm(
    vm: VirtualMachine = Depends(get_vm_or_404),
    db: DbSession,
    request: Request = None,
    current_user: CurrentUser = None
):
    """Delete a virtual machine permanently."""
    try:
        # Delete Guacamole connection first
        if vm.guac_connection_id:
            try:
                await guacamole_service.delete_connection(vm.guac_connection_id)
            except GuacamoleAPIError:
                logger.warning(f"Failed to delete Guacamole connection for VM {vm.id}")
        
        # Delete from Proxmox
        await proxmox_service.delete_vm(vm)
        
        # Delete from database
        db.delete(vm)
        db.commit()
        
        if request and current_user:
            await log_activity(
                db=db,
                user=current_user,
                action="vm.delete",
                resource_type="virtual_machine",
                resource_id=vm.id,
                ip_address=request.client.host if request.client else None,
            )
        
        logger.info(f"VM deleted: {vm.name} (VMID: {vm.proxmox_vmid})")
        return {"message": f"VM {vm.name} deleted successfully"}
        
    except ProxmoxAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete VM: {e.message}"
        )


@router.websocket("/ws/console/{vm_id}")
async def websocket_console(
    websocket: WebSocket,
    vm_id: str,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time VM console streaming.
    
    Streams Proxmox VNC/Serial console output to the frontend.
    Uses xterm.js on the frontend for terminal emulation.
    """
    await websocket.accept()
    
    user = await get_websocket_user(websocket, db)
    if not user:
        return
    
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()
    if not vm:
        await websocket.close(code=4004, reason="VM not found")
        return
    
    # Check permissions
    if user.role != UserRole.SUPERADMIN and user.role != UserRole.ORG_ADMIN:
        if vm.owner_id != user.id:
            await websocket.close(code=4003, reason="Access denied")
            return
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "vm_id": vm.id,
            "vm_name": vm.name,
            "status": vm.status.value,
        })
        
        # Stream console output (simplified - in production would use Proxmox VNC proxy)
        while True:
            try:
                # Receive input from client
                data = await websocket.receive_json()
                
                if data.get("type") == "input":
                    # Forward input to VM (would use Proxmox VNC in production)
                    pass
                
                # Send periodic status updates
                status_data = await proxmox_service.get_vm_status(vm)
                await websocket.send_json({
                    "type": "status",
                    "data": status_data,
                })
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                break
                
    except Exception as e:
        logger.error(f"Console WebSocket error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except:
            pass
