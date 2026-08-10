"""
Dukkan Cloud - Volumes Router (Block Storage)
Handles volume provisioning, attachment, and detachment.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.database import get_db
from app.models import Volume, VolumeStatus, VirtualMachine, VolumeAttachment, UserRole
from app.schemas import (
    VolumeCreate, VolumeUpdate, VolumeResponse,
    VolumeAttach, VolumeDetach
)
from app.dependencies import (
    get_current_user, log_activity, CurrentUser, DbSession
)
from app.services.proxmox_service import proxmox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/volumes", tags=["Volumes"])


@router.get("/", response_model=List[VolumeResponse])
async def list_volumes(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[str] = None
):
    """List all volumes in the organization."""
    query = db.query(Volume)
    
    if current_user.role != UserRole.SUPERADMIN and not current_user.is_platform_admin:
        query = query.filter(Volume.organization_id == current_user.organization_id)
    
    if status_filter:
        try:
            vol_status = VolumeStatus(status_filter)
            query = query.filter(Volume.status == vol_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )
    
    volumes = query.order_by(Volume.created_at.desc()).all()
    return volumes


@router.post("/", response_model=VolumeResponse, status_code=status.HTTP_201_CREATED)
async def create_volume(
    volume_data: VolumeCreate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Create a new block storage volume."""
    # Create database record first
    volume = Volume(
        name=volume_data.name,
        size_gb=volume_data.size_gb,
        volume_type=volume_data.volume_type,
        filesystem=volume_data.filesystem,
        proxmox_storage=volume_data.proxmox_storage,
        status=VolumeStatus.AVAILABLE,
        organization_id=current_user.organization_id,
    )
    
    db.add(volume)
    db.commit()
    db.refresh(volume)
    
    try:
        # Create volume in Proxmox
        await proxmox_service.create_volume(volume)
        
        volume.status = VolumeStatus.AVAILABLE
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to create volume in Proxmox: {e}")
        volume.status = VolumeStatus.ERROR
        db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="volume.create",
        resource_type="volume",
        resource_id=volume.id,
        ip_address=request.client.host,
    )
    
    logger.info(f"Volume created: {volume.name} ({volume.size_gb}GB)")
    return volume


@router.get("/{volume_id}", response_model=VolumeResponse)
async def get_volume(
    volume_id: str,
    current_user: CurrentUser,
    db: DbSession
):
    """Get volume details."""
    volume = _get_volume_or_404(volume_id, current_user, db)
    return volume


@router.put("/{volume_id}", response_model=VolumeResponse)
async def update_volume(
    volume_id: str,
    volume_data: VolumeUpdate,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Update volume configuration."""
    volume = _get_volume_or_404(volume_id, current_user, db)
    
    if volume_data.name:
        volume.name = volume_data.name
    
    # Note: Resizing requires Proxmox API call and VM must be stopped
    if volume_data.size_gb and volume_data.size_gb > volume.size_gb:
        # Would need to call Proxmox resize API here
        pass
    
    db.commit()
    db.refresh(volume)
    
    await log_activity(
        db=db,
        user=current_user,
        action="volume.update",
        resource_type="volume",
        resource_id=volume.id,
        ip_address=request.client.host,
    )
    
    return volume


@router.delete("/{volume_id}")
async def delete_volume(
    volume_id: str,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Delete a volume."""
    volume = _get_volume_or_404(volume_id, current_user, db)
    
    if volume.status == VolumeStatus.IN_USE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete volume that is attached to a VM. Detach first."
        )
    
    db.delete(volume)
    db.commit()
    
    await log_activity(
        db=db,
        user=current_user,
        action="volume.delete",
        resource_type="volume",
        resource_id=volume.id,
        ip_address=request.client.host,
    )
    
    return {"message": "Volume deleted successfully"}


@router.post("/{volume_id}/attach")
async def attach_volume(
    volume_id: str,
    attach_data: VolumeAttach,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Attach a volume to a VM."""
    volume = _get_volume_or_404(volume_id, current_user, db)
    
    if volume.status == VolumeStatus.IN_USE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Volume is already attached to a VM"
        )
    
    # Get VM
    vm = db.query(VirtualMachine).filter(
        VirtualMachine.id == attach_data.vm_id,
        VirtualMachine.organization_id == current_user.organization_id
    ).first()
    
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VM not found"
        )
    
    # Attach in Proxmox
    try:
        device_name = attach_data.device_name or f"scsi{len(vm.volumes) + 1}"
        await proxmox_service.attach_volume_to_vm(vm, volume, device_name)
        
        # Update database
        volume.status = VolumeStatus.IN_USE
        volume.attached_to_id = vm.id
        volume.attached_at = db.func.now()
        
        attachment = VolumeAttachment(
            volume_id=volume.id,
            vm_id=vm.id,
            device_name=device_name,
        )
        db.add(attachment)
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to attach volume: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to attach volume: {str(e)}"
        )
    
    await log_activity(
        db=db,
        user=current_user,
        action="volume.attach",
        resource_type="volume",
        resource_id=volume.id,
        details={"vm_id": vm.id},
        ip_address=request.client.host,
    )
    
    return {"message": f"Volume attached to VM {vm.name}"}


@router.post("/{volume_id}/detach")
async def detach_volume(
    volume_id: str,
    detach_data: VolumeDetach = None,
    current_user: CurrentUser,
    db: DbSession,
    request: Request
):
    """Detach a volume from a VM."""
    volume = _get_volume_or_404(volume_id, current_user, db)
    
    if volume.status != VolumeStatus.IN_USE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Volume is not attached to any VM"
        )
    
    # Get VM
    vm = db.query(VirtualMachine).filter(VirtualMachine.id == volume.attached_to_id).first()
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VM not found"
        )
    
    # Detach in Proxmox
    try:
        force = detach_data.force if detach_data else False
        
        if not force and vm.status.value == "running":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM must be stopped to detach volume (or use force=true)"
            )
        
        await proxmox_service.detach_volume_from_vm(vm)
        
        # Update database
        volume.status = VolumeStatus.AVAILABLE
        volume.attached_to_id = None
        volume.detached_at = db.func.now()
        
        # Remove attachment record
        db.query(VolumeAttachment).filter(
            VolumeAttachment.volume_id == volume.id,
            VolumeAttachment.vm_id == vm.id
        ).delete()
        
        db.commit()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to detach volume: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detach volume: {str(e)}"
        )
    
    await log_activity(
        db=db,
        user=current_user,
        action="volume.detach",
        resource_type="volume",
        resource_id=volume.id,
        details={"vm_id": vm.id},
        ip_address=request.client.host,
    )
    
    return {"message": f"Volume detached from VM {vm.name}"}


def _get_volume_or_404(volume_id: str, user: CurrentUser, db: DbSession) -> Volume:
    """Get volume or raise 404/403."""
    if user.role == UserRole.SUPERADMIN or user.is_platform_admin:
        volume = db.query(Volume).filter(Volume.id == volume_id).first()
    else:
        volume = db.query(Volume).filter(
            Volume.id == volume_id,
            Volume.organization_id == user.organization_id
        ).first()
    
    if not volume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Volume not found"
        )
    
    return volume
