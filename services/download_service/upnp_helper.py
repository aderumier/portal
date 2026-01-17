"""UPnP helper for NAT traversal using miniupnpc library.

Uses the miniupnpc Python library on both Linux and Windows.
"""
import asyncio
import logging
from typing import Optional
import socket
import random

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
        """Add a port mapping (forwarding) on the router.
        
        Port selection strategy:
        1. Try port 8765
        2. Try ports 8766-8775 (next 10 ports)
        3. Try 20 random ports between 30000 and 50000
        """
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
            # Build port selection strategy:
            # 1. Try port 8765 first
            # 2. Try next 10 ports (8766-8775)
            # 3. Try 20 random ports between 30000 and 50000
            ports_to_try = [8765]
            
            # Add next 10 ports after 8765
            for offset in range(1, 11):
                ports_to_try.append(8765 + offset)
            
            # Add 20 random ports between 30000 and 50000
            random_ports = random.sample(range(30000, 50001), min(20, 50001 - 30000))
            ports_to_try.extend(random_ports)
            
            last_exception = None
            for try_port in ports_to_try:
                try:
                    logger.info(f"Adding UPnP port mapping: {try_port} -> {local_ip}:{internal_port} (TCP and UDP)")
                    
                    def _add_port_mapping(port):
                        # Add TCP mapping
                        tcp_result = self.upnp.addportmapping(
                            port,
                            'TCP',
                            local_ip,
                            internal_port,
                            description,
                            ''
                        )
                        # Add UDP mapping
                        udp_result = self.upnp.addportmapping(
                            port,
                            'UDP',
                            local_ip,
                            internal_port,
                            description,
                            ''
                        )
                        # Return True only if both succeeded
                        return tcp_result and udp_result
                    
                    result = await asyncio.to_thread(_add_port_mapping, try_port)
                    
                    if result:
                        self.internal_port = internal_port
                        self.external_port = try_port
                        self.port_mapped = True
                        logger.info(f"UPnP port mapping added successfully: {try_port} -> {local_ip}:{internal_port} (TCP and UDP)")
                        return True
                    else:
                        logger.debug(f"Failed to add UPnP port mapping on port {try_port} (returned False), trying next port...")
                        continue
                except Exception as e:
                    error_str = str(e)
                    # Check if it's a conflict error (miniupnpc raises Exception with "ConflictInMappingEntry" message)
                    if 'ConflictInMappingEntry' in error_str or 'Conflict' in error_str:
                        logger.debug(f"Port {try_port} is in use, trying next port...")
                        last_exception = e
                        continue
                    else:
                        # Non-conflict error, re-raise
                        raise
            
            # All ports failed
            if last_exception:
                logger.error(f"Failed to add UPnP port mapping: all attempted ports failed (tried 8765, 8766-8775, and 20 random ports 30000-50000)")
            else:
                logger.error(f"Failed to add UPnP port mapping: all attempted ports returned False")
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
            logger.info(f"Removing UPnP port mapping: {external_port} (TCP and UDP)")
            
            def _delete_port_mapping():
                # Delete TCP mapping
                tcp_result = self.upnp.deleteportmapping(external_port, 'TCP', '')
                # Delete UDP mapping
                udp_result = self.upnp.deleteportmapping(external_port, 'UDP', '')
                # Return True if at least one succeeded (in case one doesn't exist)
                return tcp_result or udp_result
            
            result = await asyncio.to_thread(_delete_port_mapping)
            
            if result:
                self.port_mapped = False
                self.internal_port = None
                self.external_port = None
                logger.info(f"UPnP port mapping removed successfully: {external_port} (TCP and UDP)")
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
