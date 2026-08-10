"""
Dukkan Cloud - Apache Guacamole Service
Production-ready Guacamole API integration for browser-based console access.

CRITICAL SECURITY RULE:
Guacamole URLs must NEVER contain passwords in the query string.
The API returns clean URLs (/#/client/{id}) and credentials separately
to prevent browser history leaks.
"""

import httpx
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import logging
import base64
import urllib.parse

from app.config import settings
from app.models import VirtualMachine, VMType

logger = logging.getLogger(__name__)


class GuacamoleAPIError(Exception):
    """Custom exception for Guacamole API errors."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Guacamole API Error {status_code}: {message}")


class GuacamoleService:
    """
    Service class for interacting with Apache Guacamole REST API.
    Handles connection creation, authentication, and secure URL generation.
    """
    
    def __init__(self):
        self.base_url = settings.guacamole_base_url
        self.username = settings.GUACAMOLE_USER
        self.password = settings.GUACAMOLE_PASSWORD
        self.datasource = settings.GUACAMOLE_DATASOURCE
        self._auth_token = None
        self._token_expiry = None
    
    async def _authenticate(self) -> str:
        """Authenticate with Guacamole and get auth token."""
        if self._auth_token and self._token_expiry:
            if datetime.utcnow() < self._token_expiry:
                return self._auth_token
        
        # Guacamole uses form-encoded authentication
        url = f"{self.base_url}/session/login"
        data = {
            "username": self.username,
            "password": self.password,
        }
        
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.post(url, data=data)
            
            if response.status_code != 200:
                raise GuacamoleAPIError(
                    response.status_code,
                    f"Authentication failed: {response.text}"
                )
            
            result = response.json()
            self._auth_token = result.get("authToken")
            self._token_expiry = datetime.utcnow().replace(
                minute=datetime.utcnow().minute + 59  # Token valid for ~1 hour
            )
            
            logger.info("Successfully authenticated with Guacamole")
            return self._auth_token
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Guacamole API."""
        auth_token = await self._authenticate()
        
        # Add auth token to params
        if params is None:
            params = {}
        params["token"] = auth_token
        
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            if method.upper() == "GET":
                response = await client.get(f"{self.base_url}{endpoint}", params=params)
            elif method.upper() == "POST":
                response = await client.post(f"{self.base_url}{endpoint}", json=data or {}, params=params)
            elif method.upper() == "PUT":
                response = await client.put(f"{self.base_url}{endpoint}", json=data or {}, params=params)
            elif method.upper() == "DELETE":
                response = await client.delete(f"{self.base_url}{endpoint}", params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code not in [200, 201, 204]:
                raise GuacamoleAPIError(
                    response.status_code,
                    f"API request failed: {response.text}"
                )
            
            # Handle 204 No Content
            if response.status_code == 204:
                return {}
            
            return response.json()
    
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    async def create_connection(
        self,
        name: str,
        protocol: str,
        hostname: str,
        port: int,
        username: str,
        password: str,
        vm_id: str,
        organization_id: str
    ) -> Tuple[str, str]:
        """
        Create a new Guacamole connection for a VM.
        
        Returns:
            Tuple of (connection_id, guac_username)
        
        SECURITY: Passwords are stored encrypted in Guacamole's database.
        The returned URL does NOT contain credentials.
        """
        logger.info(f"Creating Guacamole connection for VM {vm_id}...")
        
        # Build connection parameters based on protocol
        if protocol == "rdp":
            parameters = self._build_rdp_params(hostname, port, username, password)
        elif protocol == "ssh":
            parameters = self._build_ssh_params(hostname, port, username, password)
        elif protocol == "vnc":
            parameters = self._build_vnc_params(hostname, port, password)
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")
        
        # Connection configuration
        connection_config = {
            "name": name,
            "protocol": protocol,
            "parameters": parameters,
            "parentIdentifier": "ROOT",
        }
        
        # Create connection
        endpoint = f"/api/session/data/{self.datasource}/connections"
        result = await self._request("POST", endpoint, data=connection_config)
        
        connection_id = result.get("identifier")
        logger.info(f"Guacamole connection created: {connection_id}")
        
        return connection_id, username
    
    def _build_rdp_params(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str
    ) -> Dict[str, str]:
        """Build RDP connection parameters."""
        return {
            "hostname": hostname,
            "port": str(port),
            "username": username,
            "password": password,
            "security": "nla",  # Network Level Authentication
            "ignore-cert": "true",
            "create-console": "true",
            "console-audio": "true",
            "enable-audio": "true",
            "audio-server-name": "pulse",
            "disable-bitmap-caching": "false",
            "enable-wallpaper": "true",
            "enable-theming": "true",
            "enable-font-smoothing": "true",
            "enable-full-window-drag": "true",
            "enable-desktop-composition": "true",
            "enable-menu-animations": "true",
            "resize-method": "display-update",
            "color-depth": "32",
            "cursor": "pointer",
        }
    
    def _build_ssh_params(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str
    ) -> Dict[str, str]:
        """Build SSH connection parameters."""
        return {
            "hostname": hostname,
            "port": str(port),
            "username": username,
            "password": password,
            "protocol": "ssh",
            "font-size": "12",
            "color-scheme": "white-black",
            "backspace": "^?",
            "terminal-type": "linux",
            "scrollback": "1000",
        }
    
    def _build_vnc_params(
        self,
        hostname: str,
        port: int,
        password: str
    ) -> Dict[str, str]:
        """Build VNC connection parameters."""
        return {
            "hostname": hostname,
            "port": str(port),
            "password": password,
            "read-only": "false",
            "swap-red-blue": "false",
            "cursor": "pointer",
            "color-depth": "32",
            "clipboard-encoding": "UTF-8",
            "dest-host": hostname,
            "dest-port": str(port),
        }
    
    async def update_connection(
        self,
        connection_id: str,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> None:
        """Update an existing connection."""
        # First, get current connection details
        endpoint = f"/api/session/data/{self.datasource}/connections/{connection_id}"
        current = await self._request("GET", endpoint)
        
        # Update fields
        if hostname:
            current["parameters"]["hostname"] = hostname
        if port:
            current["parameters"]["port"] = str(port)
        if username:
            current["parameters"]["username"] = username
        if password:
            current["parameters"]["password"] = password
        
        # Put updated connection
        await self._request("PUT", endpoint, data=current)
        logger.info(f"Guacamole connection {connection_id} updated")
    
    async def delete_connection(self, connection_id: str) -> None:
        """Delete a Guacamole connection."""
        endpoint = f"/api/session/data/{self.datasource}/connections/{connection_id}"
        await self._request("DELETE", endpoint)
        logger.info(f"Guacamole connection {connection_id} deleted")
    
    # =========================================================================
    # SECURE URL GENERATION
    # =========================================================================
    
    def generate_secure_url(self, connection_id: str) -> str:
        """
        Generate a secure Guacamole client URL.
        
        CRITICAL SECURITY:
        - URL does NOT contain credentials
        - URL format: /#/client/{connection_id}
        - Credentials are passed separately via API response
        - Frontend must handle authentication separately
        
        This prevents passwords from appearing in:
        - Browser history
        - Server logs
        - Referrer headers
        - Screen sharing recordings
        """
        # Clean URL without any credentials
        base_guac_url = settings.GUACAMOLE_URL.rstrip('/')
        return f"{base_guac_url}/#/client/{connection_id}"
    
    def get_credentials_payload(
        self,
        username: str,
        password: str,
        protocol: str
    ) -> Dict[str, str]:
        """
        Get credentials as a separate payload.
        
        This should be returned in the API response body,
        NEVER in the URL. Frontend will use this to populate
        the connection form or store securely.
        """
        return {
            "username": username,
            "password": password,
            "protocol": protocol,
        }
    
    # =========================================================================
    # CONNECTION GROUPS (for organization)
    # =========================================================================
    
    async def create_connection_group(
        self,
        name: str,
        organization_id: str,
        parent_identifier: str = "ROOT"
    ) -> str:
        """Create a connection group for organizing connections."""
        group_config = {
            "name": name,
            "type": "ORGANIZATIONAL",
            "parentIdentifier": parent_identifier,
        }
        
        endpoint = f"/api/session/data/{self.datasource}/connectionGroups"
        result = await self._request("POST", endpoint, data=group_config)
        
        return result.get("identifier")
    
    async def move_connection_to_group(
        self,
        connection_id: str,
        group_id: str
    ) -> None:
        """Move a connection to a connection group."""
        endpoint = f"/api/session/data/{self.datasource}/connections/{connection_id}"
        
        # Get current connection
        connection = await self._request("GET", endpoint)
        connection["parentIdentifier"] = group_id
        
        # Update with new parent
        await self._request("PUT", endpoint, data=connection)
    
    # =========================================================================
    # USER MANAGEMENT (optional - for multi-tenant setups)
    # =========================================================================
    
    async def create_user(self, username: str, password: str) -> str:
        """Create a new Guacamole user."""
        user_config = {
            "username": username,
            "password": password,
            "attributes": {
                "disabled": "",
                "expired": "",
                "access-window-start": "",
                "access-window-end": "",
                "valid-from": "",
                "valid-until": "",
                "timezone": "",
            },
            "profileAttributes": {
                "fullName": "",
                "emailAddress": "",
                "organization": "",
                "organizationalRole": "",
            },
        }
        
        endpoint = f"/api/session/data/{self.datasource}/users"
        result = await self._request("POST", endpoint, data=user_config)
        
        return result.get("username")
    
    async def grant_connection_permission(
        self,
        username: str,
        connection_id: str,
        permission: str = "READ"
    ) -> None:
        """Grant a user permission to access a connection."""
        endpoint = f"/api/session/data/{self.datasource}/users/{username}/permissions/connectionPermissions/{connection_id}"
        data = {"permission": permission}
        await self._request("POST", endpoint, data=data)


# Singleton instance
guacamole_service = GuacamoleService()
