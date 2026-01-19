"""UPnP helper for NAT traversal using miniupnpc library.

Uses the miniupnpc Python library on both Linux and Windows.
"""
import asyncio
import logging
from typing import Optional
import socket
import random
import html

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
        self.router_ip = None  # Router's local IP (gateway)
        self.local_ip = None  # Our local IP on the interface that can reach the router
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
            
            # Get router's local IP (gateway IP) from UPnP device
            try:
                # Try multiple methods to get the router's local IP
                import re
                
                # Method 1: Check if miniupnpc exposes lanaddr directly
                if hasattr(self.upnp, 'lanaddr') and self.upnp.lanaddr:
                    self.router_ip = self.upnp.lanaddr
                    logger.info(f"Found UPnP router local IP via lanaddr: {self.router_ip}")
                # Method 2: Try to get from IGD description URL
                elif hasattr(self.upnp, 'igddescpath') and self.upnp.igddescpath:
                    desc_url = self.upnp.igddescpath
                    match = re.search(r'http://([0-9.]+)', desc_url)
                    if match:
                        self.router_ip = match.group(1)
                        logger.info(f"Extracted router IP from UPnP description URL: {self.router_ip}")
                # Method 3: Try to get from rootdesc URL
                elif hasattr(self.upnp, 'rootdesc') and self.upnp.rootdesc:
                    rootdesc = self.upnp.rootdesc
                    match = re.search(r'http://([0-9.]+)', rootdesc)
                    if match:
                        self.router_ip = match.group(1)
                        logger.info(f"Extracted router IP from UPnP rootdesc: {self.router_ip}")
                # Method 4: Try to get from discovered devices (if accessible)
                elif hasattr(self.upnp, 'discover') and hasattr(self.upnp, 'selectigd'):
                    # The router IP might be in the device list, but miniupnpc doesn't expose it easily
                    # We'll rely on the connection method instead
                    logger.debug("Router IP not directly available from UPnP device, will use connection method")
            except Exception as e:
                logger.debug(f"Could not get router IP from UPnP device: {e}")
            
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
    
    async def _get_local_ip_for_router(self) -> Optional[str]:
        """Get the local IP address of the interface that can reach the UPnP router.
        
        Returns:
            Local IP address string, or None if cannot be determined
        """
        # If we already determined it, return cached value
        if self.local_ip:
            return self.local_ip
        
        # If we have the router's local IP, find the interface that can reach it
        if self.router_ip:
            try:
                # Try to connect to the router IP to determine which interface to use
                # This ensures we use the interface on the same network as the router
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                try:
                    # Try to connect to router (UDP doesn't actually connect, but sets route)
                    s.connect((self.router_ip, 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                    
                    # Verify it's not a loopback address
                    if local_ip and local_ip != "127.0.0.1" and not local_ip.startswith("127."):
                        self.local_ip = local_ip
                        logger.info(f"Determined local IP for router {self.router_ip}: {local_ip}")
                        return local_ip
                    else:
                        logger.warning(f"Got loopback address {local_ip} when connecting to router {self.router_ip}, trying alternative method")
                except Exception as e:
                    logger.debug(f"Could not connect to router {self.router_ip} to determine local IP: {e}")
                    s.close()
            except Exception as e:
                logger.debug(f"Error determining local IP for router: {e}")
        
        # Fallback: Try to get local IP by connecting to router IP or using network interfaces
        # Method 1: Try connecting to router IP if we have it
        if self.router_ip:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                s.connect((self.router_ip, 1900))  # UPnP discovery port
                local_ip = s.getsockname()[0]
                s.close()
                if local_ip and local_ip != "127.0.0.1":
                    self.local_ip = local_ip
                    logger.info(f"Determined local IP via router connection: {local_ip}")
                    return local_ip
            except Exception as e:
                logger.debug(f"Could not determine local IP via router connection: {e}")
        
        # Method 2: Try to enumerate network interfaces and find one on same subnet as router
        if self.router_ip:
            try:
                import ipaddress
                router_net = ipaddress.ip_network(f"{self.router_ip}/24", strict=False)
                
                # Try to get all network interfaces
                try:
                    import netifaces
                    for interface in netifaces.interfaces():
                        addrs = netifaces.ifaddresses(interface)
                        if netifaces.AF_INET in addrs:
                            for addr_info in addrs[netifaces.AF_INET]:
                                local_ip = addr_info.get('addr')
                                if local_ip and local_ip != "127.0.0.1":
                                    try:
                                        if ipaddress.ip_address(local_ip) in router_net:
                                            self.local_ip = local_ip
                                            logger.info(f"Found local IP {local_ip} on interface {interface} (same subnet as router {self.router_ip})")
                                            return local_ip
                                    except ValueError:
                                        continue
                except ImportError:
                    logger.debug("netifaces not available, skipping interface enumeration")
                except Exception as e:
                    logger.debug(f"Error enumerating interfaces: {e}")
            except Exception as e:
                logger.debug(f"Error finding local IP via subnet matching: {e}")
        
        # Method 3: Try to get default gateway and use interface that can reach it
        try:
            # Try common default gateway IPs
            gateway_ips = ["192.168.1.1", "192.168.0.1", "10.0.0.1", "172.16.0.1"]
            
            # Also try to get default gateway from system if possible
            try:
                import subprocess
                import platform
                if platform.system() == "Windows":
                    # Windows: route print to get default gateway
                    result = subprocess.run(["route", "print", "0.0.0.0"], 
                                          capture_output=True, text=True, timeout=2)
                    for line in result.stdout.split('\n'):
                        if "0.0.0.0" in line and "On-link" not in line:
                            parts = line.split()
                            if len(parts) > 2:
                                gateway = parts[2]
                                if gateway and gateway != "0.0.0.0":
                                    gateway_ips.insert(0, gateway)
                                    break
                else:
                    # Linux: ip route or route command
                    try:
                        result = subprocess.run(["ip", "route", "show", "default"], 
                                              capture_output=True, text=True, timeout=2)
                        for line in result.stdout.split('\n'):
                            if "default via" in line:
                                parts = line.split()
                                if "via" in parts:
                                    idx = parts.index("via")
                                    if idx + 1 < len(parts):
                                        gateway = parts[idx + 1]
                                        if gateway:
                                            gateway_ips.insert(0, gateway)
                                            break
                    except:
                        try:
                            result = subprocess.run(["route", "-n"], 
                                                  capture_output=True, text=True, timeout=2)
                            for line in result.stdout.split('\n'):
                                if "0.0.0.0" in line or "default" in line.lower():
                                    parts = line.split()
                                    if len(parts) > 1:
                                        gateway = parts[1]
                                        if gateway and gateway != "0.0.0.0":
                                            gateway_ips.insert(0, gateway)
                                            break
                        except:
                            pass
            except Exception as e:
                logger.debug(f"Could not get default gateway from system: {e}")
            
            # Try connecting to gateway IPs to find the right interface
            for gateway_ip in gateway_ips:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(1)
                    s.connect((gateway_ip, 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                    if local_ip and local_ip != "127.0.0.1":
                        self.local_ip = local_ip
                        logger.info(f"Determined local IP via gateway {gateway_ip}: {local_ip}")
                        return local_ip
                except:
                    continue
        except Exception as e:
            logger.debug(f"Error trying gateway method: {e}")
        
        # Method 4: Final fallback - connect to external IP (original method)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(5)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            if local_ip and local_ip != "127.0.0.1":
                self.local_ip = local_ip
                logger.warning(f"Using final fallback method to determine local IP (may be incorrect if multiple interfaces): {local_ip}")
                return local_ip
        except Exception as e:
            logger.warning(f"Final fallback method to get local IP failed: {e}")
        
        return None
    
    async def add_port_mapping(
        self,
        internal_port: int,
        external_port: Optional[int] = None,
        description: str = "P2P File Sharing"
    ) -> bool:
        """Add a port mapping (forwarding) on the router.
        
        Args:
            internal_port: Internal port to forward
            external_port: External port (optional, will try multiple if not specified)
            description: Description for the port mapping (will be escaped for XML safety)
        
        Port selection strategy:
        1. Try port 8765
        2. Try ports 8766-8775 (next 10 ports)
        3. Try 20 random ports between 30000 and 50000
        """
        # Escape XML special characters in description for safety
        # This ensures <, >, & are properly escaped for XML/UPnP
        description = html.escape(description, quote=False)
        
        # Get local IP address - use the interface that can reach the router
        local_ip = await self._get_local_ip_for_router()
        if not local_ip:
            logger.error("Failed to determine local IP address for port mapping")
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
