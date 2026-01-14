"""UPnP helper for NAT traversal using miniupnpc library.

Uses the miniupnpc Python library on both Linux and Windows.
"""
import asyncio
import logging
from typing import Optional
import socket

logger = logging.getLogger(__name__)

# Try to import miniupnpc
MINIUPNPC_AVAILABLE = False
try:
    import miniupnpc
    MINIUPNPC_AVAILABLE = True
except ImportError as e:
    logger.warning(f"miniupnpc not available: {e}. UPnP functionality will be limited.")


class UPnPHelper:
    """UPnP helper for port forwarding using miniupnpc Python library."""
    
    def __init__(self):
        self.upnp = None
        self.external_ip = None
        self.port_mapped = False
        self.internal_port = None
        self.external_port = None
    
    async def discover_router(self) -> bool:
        """Discover UPnP-enabled router."""
        if not MINIUPNPC_AVAILABLE:
            logger.warning("miniupnpc not available, cannot discover router")
            return False
        
        try:
            logger.info("Searching for UPnP IGD devices...")
            
            def _discover():
                try:
                    upnp = miniupnpc.UPnP()
                    upnp.discoverdelay = 200
                    num_devices = upnp.discover()
                    
                    if num_devices < 0:
                        logger.warning(f"UPnP discovery returned error code: {num_devices}")
                        return None
                    
                    logger.info(f"Found {num_devices} UPnP device(s)")
                    
                    if num_devices > 0:
                        try:
                            upnp.selectigd()
                            return upnp
                        except Exception as e:
                            logger.warning(f"Failed to select IGD device: {type(e).__name__}: {e}", exc_info=True)
                            return None
                    return None
                except Exception as e:
                    logger.warning(f"UPnP discovery raised exception: {type(e).__name__}: {e}", exc_info=True)
                    return None
            
            self.upnp = await asyncio.to_thread(_discover)
            
            if not self.upnp:
                logger.warning("No UPnP IGD device found")
                return False
            
            # Get external IP
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
        """Get the external IP address of the router."""
        if self.external_ip:
            return self.external_ip
        
        if self.upnp:
            try:
                external_ip = self.upnp.externalipaddress()
                if external_ip:
                    self.external_ip = external_ip
                    return external_ip
            except Exception as e:
                logger.warning(f"Could not get external IP from UPnP: {e}")
        
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
    
    async def add_port_mapping(
        self,
        internal_port: int,
        external_port: Optional[int] = None,
        description: str = "P2P File Sharing"
    ) -> bool:
        """Add a port mapping (forwarding) on the router."""
        if external_port is None:
            external_port = internal_port
        
        # Get local IP address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(5)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception as e:
            logger.error(f"Failed to get local IP: {e}")
            return False
        
        if not MINIUPNPC_AVAILABLE or not self.upnp:
            logger.warning("UPnP service not available, cannot add port mapping")
            return False
        
        try:
            # Try the requested port first
            ports_to_try = [external_port]
            # If there's a conflict, try alternative ports (increment by 1)
            # Try up to 10 alternative ports
            for offset in range(1, 11):
                ports_to_try.append(external_port + offset)
            
            last_exception = None
            for try_port in ports_to_try:
                try:
                    logger.info(f"Adding UPnP port mapping: {try_port} -> {local_ip}:{internal_port}")
                    
                    def _add_port_mapping(port):
                        result = self.upnp.addportmapping(
                            port,
                            'TCP',
                            local_ip,
                            internal_port,
                            description,
                            ''
                        )
                        return result
                    
                    result = await asyncio.to_thread(_add_port_mapping, try_port)
                    
                    if result:
                        self.internal_port = internal_port
                        self.external_port = try_port
                        self.port_mapped = True
                        if try_port != external_port:
                            logger.info(f"UPnP port mapping added successfully on alternative port {try_port} (original {external_port} was in use): {try_port} -> {local_ip}:{internal_port}")
                        else:
                            logger.info(f"UPnP port mapping added successfully: {try_port} -> {local_ip}:{internal_port}")
                        return True
                    else:
                        logger.debug(f"Failed to add UPnP port mapping on port {try_port} (returned False), trying next port...")
                        continue
                except Exception as e:
                    error_str = str(e)
                    # Check if it's a conflict error (miniupnpc raises Exception with "ConflictInMappingEntry" message)
                    if 'ConflictInMappingEntry' in error_str or 'Conflict' in error_str:
                        if try_port == external_port:
                            logger.warning(f"Port {external_port} is already in use, trying alternative ports...")
                        logger.debug(f"Port {try_port} is in use, trying next port...")
                        last_exception = e
                        continue
                    else:
                        # Non-conflict error, re-raise
                        raise
            
            # All ports failed
            if last_exception:
                logger.error(f"Failed to add UPnP port mapping: all ports from {external_port} to {ports_to_try[-1]} are in use or unavailable")
            else:
                logger.error(f"Failed to add UPnP port mapping: all ports from {external_port} to {ports_to_try[-1]} returned False")
            return False
        except Exception as e:
            logger.error(f"Error adding UPnP port mapping: {e}", exc_info=True)
            return False
    
    async def delete_port_mapping(self, external_port: int) -> bool:
        """Remove a port mapping from the router."""
        if not MINIUPNPC_AVAILABLE or not self.upnp:
            logger.warning("UPnP service not available, cannot delete port mapping")
            return False
        
        try:
            logger.info(f"Removing UPnP port mapping: {external_port}")
            
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
                logger.error("Failed to delete UPnP port mapping (returned False)")
                return False
        except Exception as e:
            logger.error(f"Error deleting UPnP port mapping: {e}", exc_info=True)
            return False
    
    def is_available(self) -> bool:
        """Check if UPnP is available."""
        return MINIUPNPC_AVAILABLE
    
    async def close(self):
        """Close any resources."""
        pass


def get_upnp_helper() -> UPnPHelper:
    """Get UPnP helper instance."""
    return UPnPHelper()
