"""
Dukkan Cloud - Proxmox VE Service
Production-ready Proxmox API integration for LXC/QEMU provisioning.
"""

import httpx
import asyncio
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
from urllib3.exceptions import InsecureRequestWarning
import urllib3

from app.config import settings
from app.models import VirtualMachine, VMType, VMStatus, Network, Volume
from app.schemas import VMCreateLXC, VMCreateQEMU, VMCloudInit

logger = logging.getLogger(__name__)

# Suppress SSL warnings for self-signed certs (development)
if not settings.PROXMOX_VERIFY_SSL:
    urllib3.disable_warnings(InsecureRequestWarning)


class ProxmoxAPIError(Exception):
    """Custom exception for Proxmox API errors."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Proxmox API Error {status_code}: {message}")


class ProxmoxService:
    """
    Service class for interacting with Proxmox VE API.
    Handles LXC/QEMU provisioning, lifecycle management, and networking.
    """
    
    def __init__(self):
        self.base_url = settings.proxmox_base_url
        self.username = settings.PROXMOX_USER
        self.password = settings.PROXMOX_PASSWORD
        self.node = settings.PROXMOX_NODE
        self.storage = settings.PROXMOX_STORAGE
        self.verify_ssl = settings.PROXMOX_VERIFY_SSL
        self._ticket = None
        self._ticket_expiry = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get authenticated HTTP client with CSRF token."""
        await self._authenticate()
        
        client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=self.verify_ssl,
            timeout=30.0,
            headers={
                "CSRFPreventionToken": self._ticket["CSRFPreventionToken"],
            },
            cookies={
                "PVEAuthCookie": self._ticket["ticket"],
            }
        )
        return client
    
    async def _authenticate(self) -> None:
        """Authenticate with Proxmox and get access ticket."""
        if self._ticket and self._ticket_expiry:
            if datetime.utcnow() < self._ticket_expiry:
                return  # Ticket still valid
        
        url = f"{self.base_url}/access/ticket"
        data = {
            "username": self.username,
            "password": self.password,
        }
        
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=10.0) as client:
            response = await client.post(url, data=data)
            
            if response.status_code != 200:
                raise ProxmoxAPIError(
                    response.status_code,
                    f"Authentication failed: {response.text}"
                )
            
            result = response.json()
            self._ticket = result["data"]
            self._ticket_expiry = datetime.utcnow().replace(
                second=self._ticket["expires"] - 60  # Refresh 1 minute before expiry
            )
            
            logger.info("Successfully authenticated with Proxmox")
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Proxmox API."""
        client = await self._get_client()
        
        try:
            if method.upper() == "GET":
                response = await client.get(endpoint, params=params)
            elif method.upper() == "POST":
                response = await client.post(endpoint, json=data or {})
            elif method.upper() == "PUT":
                response = await client.put(endpoint, json=data or {})
            elif method.upper() == "DELETE":
                response = await client.delete(endpoint, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code not in [200, 201]:
                raise ProxmoxAPIError(
                    response.status_code,
                    f"API request failed: {response.text}"
                )
            
            return response.json()
        
        finally:
            await client.aclose()
    
    # =========================================================================
    # NODE & CLUSTER OPERATIONS
    # =========================================================================
    
    async def get_node_status(self) -> Dict[str, Any]:
        """Get node status and resource usage."""
        result = await self._request("GET", f"/nodes/{self.node}/status")
        return result.get("data", {})
    
    async def list_nodes(self) -> List[Dict[str, Any]]:
        """List all nodes in the cluster."""
        result = await self._request("GET", "/nodes")
        return result.get("data", [])
    
    # =========================================================================
    # LXC OPERATIONS
    # =========================================================================
    
    async def create_lxc(
        self,
        vmid: int,
        config: VMCreateLXC,
        network: Optional[Network] = None
    ) -> Dict[str, Any]:
        """
        Create a new LXC container from template.
        Configures hostname, resources, and networking.
        """
        logger.info(f"Creating LXC {vmid} ({config.name})...")
        
        # Build LXC configuration
        lxc_config = {
            "vmid": vmid,
            "hostname": config.hostname,
            "description": f"Created by Dukkan Cloud for {config.name}",
            "cores": config.cpu_cores,
            "memory": config.ram_gb * 1024,  # MB
            "swap": 512,  # MB
            "storage": self.storage,
            "template": settings.PROXMOX_LXC_TEMPLATE,
            "net0": self._build_lxc_network(network),
            "features": "keyctl=1,nesting=1",  # Enable Docker support
            "onboot": 0,  # Don't auto-start on host reboot
            "start": 0,  # Don't start immediately
        }
        
        # Add cloud-init user config
        if config.cloud_init:
            lxc_config.update(self._build_cloud_init_config(config.cloud_init))
        
        endpoint = f"/nodes/{self.node}/lxc"
        result = await self._request("POST", endpoint, data=lxc_config)
        
        logger.info(f"LXC {vmid} created successfully")
        return result
    
    def _build_lxc_network(self, network: Optional[Network]) -> str:
        """Build LXC network configuration string."""
        if network and network.cidr:
            # Extract gateway from CIDR or use configured gateway
            gateway = network.gateway or self._cidr_to_gateway(network.cidr)
            return f"name=eth0,bridge=vmbr0,gw={gateway},ip=dhcp,type=veth"
        return "name=eth0,bridge=vmbr0,ip=dhcp,type=veth"
    
    def _cidr_to_gateway(self, cidr: str) -> str:
        """Convert CIDR to gateway IP (first usable IP)."""
        try:
            import ipaddress
            network = ipaddress.ip_network(cidr, strict=False)
            return str(list(network.hosts())[0])
        except Exception:
            return "192.168.1.1"  # Default fallback
    
    # =========================================================================
    # QEMU OPERATIONS
    # =========================================================================
    
    async def create_qemu(
        self,
        vmid: int,
        config: VMCreateQEMU,
        network: Optional[Network] = None
    ) -> Dict[str, Any]:
        """
        Create a new QEMU VM from template with Cloud-Init.
        Configures hostname, resources, SSH keys, and networking.
        """
        logger.info(f"Creating QEMU VM {vmid} ({config.name})...")
        
        # Clone from template first
        clone_result = await self.clone_vm_template(vmid, config.template_id)
        
        # Configure VM
        qemu_config = {
            "name": config.name,
            "description": f"Created by Dukkan Cloud for {config.name}",
            "cores": config.cpu_cores,
            "memory": config.ram_gb * 1024,  # MB
            "balloon": 0,  # Disable memory ballooning
            "agent": 1,  # Enable QEMU Guest Agent
            "onboot": 0,
            "autostart": 0,
        }
        
        # Network configuration
        if network:
            qemu_config["net0"] = self._build_qemu_network(network)
        else:
            qemu_config["net0"] = "virtio,bridge=vmbr0"
        
        # Cloud-Init configuration
        if config.cloud_init:
            qemu_config.update(self._build_qemu_cloud_init(config.cloud_init, config.os_type))
        
        # Apply configuration
        endpoint = f"/nodes/{self.node}/qemu/{vmid}/config"
        await self._request("PUT", endpoint, data=qemu_config)
        
        # Resize disk if needed
        if config.disk_gb > 32:  # Assuming template has 32GB
            await self.resize_disk(vmid, "scsi0", config.disk_gb)
        
        logger.info(f"QEMU VM {vmid} configured successfully")
        return clone_result
    
    async def clone_vm_template(self, vmid: int, template_id: int) -> Dict[str, Any]:
        """Clone a VM from template."""
        endpoint = f"/nodes/{self.node}/qemu/{template_id}/clone"
        data = {
            "newid": vmid,
            "name": f"template-clone-{vmid}",
            "full": 1,  # Full clone
        }
        return await self._request("POST", endpoint, data=data)
    
    def _build_qemu_network(self, network: Network) -> str:
        """Build QEMU network configuration string."""
        return "virtio,bridge=vmbr0,firewall=1"
    
    def _build_qemu_cloud_init(self, cloud_init: VMCloudInit, os_type: str) -> Dict[str, Any]:
        """Build QEMU Cloud-Init configuration."""
        config = {
            "cipassword": cloud_init.password,
            "ciuser": cloud_init.username,
        }
        
        # SSH keys
        if cloud_init.ssh_keys:
            ssh_keys = "\n".join(cloud_init.ssh_keys)
            config["sshkeys"] = ssh_keys
        
        # Custom user-data
        if cloud_init.user_data:
            config["userdata"] = cloud_init.user_data
        
        # Network config for Cloud-Init
        config["ipconfig0"] = "ip=dhcp"
        
        return config
    
    async def resize_disk(self, vmid: int, disk: str, size_gb: int) -> None:
        """Resize a VM disk."""
        endpoint = f"/nodes/{self.node}/qemu/{vmid}/resize"
        data = {
            "disk": disk,
            "size": f"{size_gb}G",
        }
        await self._request("PUT", endpoint, data=data)
    
    # =========================================================================
    # VM LIFECYCLE OPERATIONS
    # =========================================================================
    
    async def start_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Start a VM or LXC."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/status/start"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/start"
        
        logger.info(f"Starting VM {vm.proxmox_vmid} ({vm.name})...")
        return await self._request("POST", endpoint)
    
    async def stop_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Stop a VM or LXC gracefully."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/status/stop"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/stop"
        
        logger.info(f"Stopping VM {vm.proxmox_vmid} ({vm.name})...")
        return await self._request("POST", endpoint)
    
    async def shutdown_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Shutdown a VM or LXC (graceful ACPI shutdown)."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/status/shutdown"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/shutdown"
        
        logger.info(f"Shutting down VM {vm.proxmox_vmid} ({vm.name})...")
        return await self._request("POST", endpoint)
    
    async def restart_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Restart a VM or LXC."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/status/reboot"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/reboot"
        
        logger.info(f"Restarting VM {vm.proxmox_vmid} ({vm.name})...")
        return await self._request("POST", endpoint)
    
    async def reset_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Reset a VM (hard reset, QEMU only)."""
        if vm.vm_type == VMType.QEMU:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/reset"
            logger.info(f"Resetting VM {vm.proxmox_vmid} ({vm.name})...")
            return await self._request("POST", endpoint)
        else:
            raise ValueError("Reset is only available for QEMU VMs")
    
    async def delete_vm(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Delete a VM or LXC permanently."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}"
        
        logger.info(f"Deleting VM {vm.proxmox_vmid} ({vm.name})...")
        return await self._request("DELETE", endpoint)
    
    # =========================================================================
    # VM STATUS & MONITORING
    # =========================================================================
    
    async def get_vm_status(self, vm: VirtualMachine) -> Dict[str, Any]:
        """Get current status of a VM or LXC."""
        if vm.vm_type == VMType.LXC:
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/status/current"
        else:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/status/current"
        
        result = await self._request("GET", endpoint)
        return result.get("data", {})
    
    async def get_vm_ip(self, vm: VirtualMachine, timeout: int = 120) -> Optional[str]:
        """
        Get IP address of a running VM.
        For LXC: Wait for DHCP lease
        For QEMU: Wait for QEMU Guest Agent to report IP
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                status = await self.get_vm_status(vm)
                
                if vm.vm_type == VMType.LXC:
                    # LXC: Check network interfaces
                    interfaces = status.get("network", {})
                    for iface_name, iface_data in interfaces.items():
                        if iface_name == "eth0" and "inet" in iface_data:
                            ip = iface_data["inet"]["ip-address"]
                            if ip and ip != "127.0.0.1":
                                logger.info(f"Got LXC IP: {ip}")
                                return ip
                
                else:
                    # QEMU: Use QEMU Guest Agent
                    agent_info = await self._request(
                        "GET",
                        f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/agent/network-get-interfaces"
                    )
                    
                    interfaces = agent_info.get("data", {}).get("result", [])
                    for iface in interfaces:
                        if iface.get("name") == "eth0" or iface.get("name") == "ens18":
                            for ip_info in iface.get("ip-addresses", []):
                                if ip_info.get("ip-address-type") == "ipv4":
                                    ip = ip_info.get("ip-address")
                                    if ip and ip != "127.0.0.1":
                                        logger.info(f"Got QEMU IP: {ip}")
                                        return ip
            
            except Exception as e:
                logger.debug(f"Waiting for VM IP... ({str(e)})")
            
            await asyncio.sleep(5)
        
        logger.warning(f"Timeout waiting for VM {vm.proxmox_vmid} IP address")
        return None
    
    async def wait_for_vm_running(self, vm: VirtualMachine, timeout: int = 120) -> bool:
        """Wait for VM to reach 'running' status."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = await self.get_vm_status(vm)
            vm_status = status.get("status", "")
            
            if vm_status == "running":
                logger.info(f"VM {vm.proxmox_vmid} is now running")
                return True
            
            await asyncio.sleep(3)
        
        logger.warning(f"Timeout waiting for VM {vm.proxmox_vmid} to start")
        return False
    
    # =========================================================================
    # VOLUME OPERATIONS
    # =========================================================================
    
    async def create_volume(self, volume: Volume) -> Dict[str, Any]:
        """Create a new storage volume."""
        endpoint = f"/nodes/{self.node}/storage/{volume.proxmox_storage}/content"
        data = {
            "vmid": 999,  # Use dummy VMID for standalone volumes
            "filename": f"vm-{volume.id}.raw",
            "size": f"{volume.size_gb}G",
            "format": "raw",
        }
        return await self._request("POST", endpoint, data=data)
    
    async def attach_volume_to_vm(self, vm: VirtualMachine, volume: Volume, device: str = "scsi1") -> None:
        """Attach a volume to a VM."""
        volume_id = f"{volume.proxmox_storage}:vm-{volume.id}"
        
        if vm.vm_type == VMType.QEMU:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/config"
            data = {device: volume_id}
            await self._request("PUT", endpoint, data=data)
        else:
            # LXC: Mount as bind mount
            endpoint = f"/nodes/{self.node}/lxc/{vm.proxmox_vmid}/config"
            data = {"mp1": f"{volume_id},mp=/mnt/volume1"}
            await self._request("PUT", endpoint, data=data)
    
    async def detach_volume_from_vm(self, vm: VirtualMachine, device: str = "scsi1") -> None:
        """Detach a volume from a VM."""
        if vm.vm_type == VMType.QEMU:
            endpoint = f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/config"
            data = {device: "none"}
            await self._request("PUT", endpoint, data=data)
    
    # =========================================================================
    # FIREWALL OPERATIONS
    # =========================================================================
    
    async def apply_firewall_rules(self, vm: VirtualMachine, rules: List[Dict]) -> None:
        """Apply firewall rules to a VM."""
        if vm.vm_type == VMType.QEMU:
            # Enable firewall on VM
            await self._request(
                "PUT",
                f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/config",
                data={"firewall": 1}
            )
            
            # Add rules
            for rule in rules:
                await self._request(
                    "POST",
                    f"/nodes/{self.node}/qemu/{vm.proxmox_vmid}/firewall/rules",
                    data=rule
                )


# Singleton instance
proxmox_service = ProxmoxService()
