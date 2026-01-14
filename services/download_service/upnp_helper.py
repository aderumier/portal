"""UPnP helper for NAT traversal using miniupnpc library.

This module uses miniupnpc library which should be installed via pip.
The library requires the miniupnpc C library to be available.
"""
import asyncio
import logging
from typing import Optional
import socket

logger = logging.getLogger(__name__)

# Try to import miniupnpc
try:
    import miniupnpc
    MINIUPNPC_AVAILABLE = True
except ImportError as e:
    MINIUPNPC_AVAILABLE = False
    logger.warning(f"miniupnpc not available: {e}. UPnP functionality will be limited.")


class UPnPHelper:
    """UPnP helper for port forwarding using miniupnpc.
    
    This class provides async methods for UPnP port forwarding.
    It requires miniupnpc to be installed.
    """
    
    def __init__(self):
        self.upnp = None
        self.external_ip = None
        self.port_mapped = False
        self.internal_port = None
        self.external_port = None
    
    async def discover_router(self) -> bool:
        """Discover UPnP-enabled router.
        
        Returns:
            True if router is discovered, False otherwise
        """
        if not MINIUPNPC_AVAILABLE:
            logger.warning("miniupnpc not available, cannot discover router")
            return False
        
        try:
            logger.info("Searching for UPnP IGD devices...")
            
            # Create UPnP instance and discover (synchronous, so run in thread)
            def _discover():
                upnp = miniupnpc.UPnP()
                # Set discovery delay (in milliseconds)
                upnp.discoverdelay = 200
                # Discover devices
                num_devices = upnp.discover()
                logger.info(f"Found {num_devices} UPnP device(s)")
                
                if num_devices > 0:
                    # Select first IGD device
                    upnp.selectigd()
                    return upnp
                return None
            
            self.upnp = await asyncio.to_thread(_discover)
            
            if not self.upnp:
                logger.warning("No UPnP IGD device found")
                return False
            
            # Get external IP to verify connection
            try:
                external_ip = self.upnp.externalipaddress()
                if external_ip:
                    logger.info(f"Found UPnP gateway, external IP: {external_ip}")
                    self.external_ip = external_ip
                else:
                    logger.warning("Found UPnP gateway but could not get external IP")
            except Exception as e:
                logger.warning(f"Could not get external IP: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error discovering UPnP router: {e}", exc_info=True)
            return False
    
    async def get_external_ip(self) -> Optional[str]:
        """Get the external IP address of the router.
        
        Returns:
            External IP address as string, or None if not found
        """
        if not MINIUPNPC_AVAILABLE or not self.upnp:
            # Fallback: try to get local IP
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(5)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                self.external_ip = ip
                logger.debug(f"Fallback: using local IP: {ip}")
                return ip
            except Exception:
                return None
        
        try:
            # Use UPnP service to get external IP (synchronous, so run in thread)
            def _get_external_ip():
                return self.upnp.externalipaddress()
            
            external_ip = await asyncio.to_thread(_get_external_ip)
            
            if external_ip:
                self.external_ip = external_ip
                logger.info(f"External IP from UPnP: {self.external_ip}")
                return self.external_ip
        except Exception as e:
            logger.error(f"Error getting external IP via UPnP: {e}")
            # Fallback to local IP
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(5)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                self.external_ip = ip
                logger.debug(f"Fallback: using local IP: {ip}")
                return ip
            except Exception:
                return None
        
        return None
    
    async def add_port_mapping(
        self,
        internal_port: int,
        external_port: Optional[int] = None,
        description: str = "P2P File Sharing"
    ) -> bool:
        """Add a port mapping (forwarding) on the router.
        
        Args:
            internal_port: The internal port on the client
            external_port: The external port to open on the router (if None, use internal_port)
            description: Description for the port mapping
        
        Returns:
            True if mapping is successful, False otherwise
        """
        if not MINIUPNPC_AVAILABLE or not self.upnp:
            logger.warning("UPnP service not available, cannot add port mapping")
            return False
        
        if external_port is None:
            external_port = internal_port
        
        try:
            # Get local IP address
            local_ip = socket.gethostbyname(socket.gethostname())
            if not local_ip or local_ip.startswith("127."):
                # Try alternative method
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(5)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            
            logger.info(f"Adding UPnP port mapping: {external_port} -> {local_ip}:{internal_port}")
            
            # Add port mapping using UPnP service (synchronous, so run in thread)
            # miniupnpc.addportmapping signature: (external_port, protocol, internal_ip, internal_port, description, remote_host)
            def _add_port_mapping():
                # remote_host should be empty string for any remote host
                result = self.upnp.addportmapping(
                    external_port,
                    'TCP',
                    local_ip,
                    internal_port,
                    description,
                    ''  # remote_host (empty = any host)
                )
                return result
            
            result = await asyncio.to_thread(_add_port_mapping)
            
            if result:
                self.internal_port = internal_port
                self.external_port = external_port
                self.port_mapped = True
                logger.info(f"UPnP port mapping added successfully: {external_port} -> {local_ip}:{internal_port}")
                return True
            else:
                logger.error(f"Failed to add UPnP port mapping (returned False)")
                return False
        except Exception as e:
            logger.error(f"Error adding UPnP port mapping: {e}", exc_info=True)
            return False
    
    async def delete_port_mapping(self, external_port: int) -> bool:
        """Remove a port mapping from the router.
        
        Args:
            external_port: The external port to close on the router
        
        Returns:
            True if removal is successful, False otherwise
        """
        if not MINIUPNPC_AVAILABLE or not self.upnp:
            logger.warning("UPnP service not available, cannot delete port mapping")
            return False
        
        try:
            logger.info(f"Removing UPnP port mapping: {external_port}")
            
            # Delete port mapping using UPnP service (synchronous, so run in thread)
            # miniupnpc.deleteportmapping signature: (external_port, protocol, remote_host)
            def _delete_port_mapping():
                result = self.upnp.deleteportmapping(external_port, 'TCP', '')
                return result
            
            result = await asyncio.to_thread(_delete_port_mapping)
            
            if result:
                self.port_mapped = False
                self.internal_port = None
                self.external_port = None
                logger.info(f"UPnP port mapping removed successfully: {external_port}")
                return True
            else:
                logger.error(f"Failed to delete UPnP port mapping (returned False)")
                return False
        except Exception as e:
            logger.error(f"Error deleting UPnP port mapping: {e}", exc_info=True)
            return False
    
    def is_available(self) -> bool:
        """Check if UPnP is available.
        
        Returns:
            True if miniupnpc is available, False otherwise
        """
        return MINIUPNPC_AVAILABLE
    
    async def close(self):
        """Close any resources (miniupnpc doesn't need explicit cleanup)."""
        pass


def get_upnp_helper() -> UPnPHelper:
    """Get UPnP helper instance.
    
    Returns:
        UPnPHelper instance
    """
    return UPnPHelper()


# Note: miniupnpc is synchronous, so calls are wrapped in asyncio.to_thread().
