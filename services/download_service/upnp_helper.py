"""UPnP helper for NAT traversal using miniupnpc library (Linux) or upnpc.exe (Windows).

On Linux, uses the miniupnpc Python library.
On Windows, uses the upnpc.exe command-line tool to avoid library issues.
"""
import asyncio
import logging
import platform
import subprocess
from typing import Optional
import socket
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

# Detect platform
IS_WINDOWS = platform.system() == 'Windows'

# Try to import miniupnpc (only used on Linux)
MINIUPNPC_AVAILABLE = False
if not IS_WINDOWS:
    try:
        import miniupnpc
        MINIUPNPC_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"miniupnpc not available: {e}. UPnP functionality will be limited.")

# Windows: Try to find upnpc.exe
UPNPC_EXE_PATH = None
if IS_WINDOWS:
    # When frozen (exe), look in executable directory
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        upnpc_exe = exe_dir / 'upnpc.exe'
        if upnpc_exe.exists():
            UPNPC_EXE_PATH = str(upnpc_exe)
    else:
        # When running as script, try current directory and PATH
        script_dir = Path(__file__).parent
        upnpc_exe = script_dir / 'upnpc.exe'
        if upnpc_exe.exists():
            UPNPC_EXE_PATH = str(upnpc_exe)
        else:
            # Try PATH
            try:
                result = subprocess.run(['where', 'upnpc.exe'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    UPNPC_EXE_PATH = result.stdout.strip().split('\n')[0]
            except Exception:
                pass
    
    if UPNPC_EXE_PATH:
        logger.debug(f"Found upnpc.exe at: {UPNPC_EXE_PATH}")
    else:
        logger.debug("upnpc.exe not found (UPnP will use Python library if available)")


class UPnPHelper:
    """UPnP helper for port forwarding.
    
    On Linux: uses miniupnpc Python library
    On Windows: uses upnpc.exe command-line tool if available, otherwise falls back to Python library
    """
    
    def __init__(self):
        self.upnp = None  # Used on Linux or Windows fallback
        self.external_ip = None
        self.port_mapped = False
        self.internal_port = None
        self.external_port = None
        self.use_upnpc_exe = IS_WINDOWS and UPNPC_EXE_PATH is not None
    
    def _find_upnpc_exe(self) -> Optional[str]:
        """Find upnpc.exe path (Windows only)."""
        return UPNPC_EXE_PATH
    
    async def _run_upnpc_command(self, args: list, timeout: float = 10.0) -> tuple[int, str, str]:
        """Run upnpc.exe command and return (returncode, stdout, stderr)."""
        exe_path = self._find_upnpc_exe()
        if not exe_path:
            return (1, "", "upnpc.exe not found")
        
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [exe_path] + args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return (result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return (1, "", "Command timed out")
        except Exception as e:
            return (1, "", str(e))
    
    async def discover_router(self) -> bool:
        """Discover UPnP-enabled router."""
        if self.use_upnpc_exe:
            # Windows: Use upnpc.exe -s to get status (this also discovers the router)
            logger.info("Searching for UPnP IGD devices using upnpc.exe...")
            returncode, stdout, stderr = await self._run_upnpc_command(['-s'], timeout=15.0)
            
            if returncode == 0:
                # Parse external IP from output
                # Format: "ExternalIPAddress = x.x.x.x" or "status = Connected"
                for line in stdout.split('\n'):
                    if 'ExternalIPAddress' in line or 'ExternalIP' in line:
                        parts = line.split('=')
                        if len(parts) >= 2:
                            ip = parts[1].strip()
                            if ip and ip != '0.0.0.0':
                                self.external_ip = ip
                                logger.info(f"Found UPnP gateway, external IP: {self.external_ip}")
                                return True
                    elif 'status' in line.lower() and 'connected' in line.lower():
                        # Router found but no external IP yet
                        logger.info("UPnP gateway found (connected)")
                        return True
                # If we got status but no IP, router might still be found
                logger.info("UPnP gateway found (no external IP in status)")
                return True
            else:
                logger.warning(f"UPnP discovery failed: {stderr}")
                return False
        else:
            # Linux or Windows fallback: Use Python library
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
        
        if self.use_upnpc_exe:
            # Windows: Use upnpc.exe -s
            returncode, stdout, stderr = await self._run_upnpc_command(['-s'], timeout=10.0)
            if returncode == 0:
                for line in stdout.split('\n'):
                    if 'ExternalIPAddress' in line or 'ExternalIP' in line:
                        parts = line.split('=')
                        if len(parts) >= 2:
                            ip = parts[1].strip()
                            if ip and ip != '0.0.0.0':
                                self.external_ip = ip
                                return ip
        
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
        
        if self.use_upnpc_exe:
            # Windows: Use upnpc.exe -a
            # Format: upnpc.exe -a <local_ip> <external_port> <internal_port> TCP [lease_duration]
            logger.info(f"Adding UPnP port mapping: {external_port} -> {local_ip}:{internal_port}")
            returncode, stdout, stderr = await self._run_upnpc_command(
                ['-a', local_ip, str(external_port), str(internal_port), 'TCP'],
                timeout=10.0
            )
            
            if returncode == 0:
                self.internal_port = internal_port
                self.external_port = external_port
                self.port_mapped = True
                logger.info(f"UPnP port mapping added successfully: {external_port} -> {local_ip}:{internal_port}")
                return True
            else:
                logger.error(f"Failed to add UPnP port mapping: {stderr}")
                return False
        else:
            # Linux or Windows fallback: Use Python library
            if not MINIUPNPC_AVAILABLE or not self.upnp:
                logger.warning("UPnP service not available, cannot add port mapping")
                return False
            
            try:
                logger.info(f"Adding UPnP port mapping: {external_port} -> {local_ip}:{internal_port}")
                
                def _add_port_mapping():
                    result = self.upnp.addportmapping(
                        external_port,
                        'TCP',
                        local_ip,
                        internal_port,
                        description,
                        ''
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
                    logger.error("Failed to add UPnP port mapping (returned False)")
                    return False
            except Exception as e:
                logger.error(f"Error adding UPnP port mapping: {e}", exc_info=True)
                return False
    
    async def delete_port_mapping(self, external_port: int) -> bool:
        """Remove a port mapping from the router."""
        if self.use_upnpc_exe:
            # Windows: Use upnpc.exe -d
            # Format: upnpc.exe -d <external_port> TCP
            logger.info(f"Removing UPnP port mapping: {external_port}")
            returncode, stdout, stderr = await self._run_upnpc_command(
                ['-d', str(external_port), 'TCP'],
                timeout=10.0
            )
            
            if returncode == 0:
                self.port_mapped = False
                self.internal_port = None
                self.external_port = None
                logger.info(f"UPnP port mapping removed successfully: {external_port}")
                return True
            else:
                logger.error(f"Failed to delete UPnP port mapping: {stderr}")
                return False
        else:
            # Linux or Windows fallback: Use Python library
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
        if IS_WINDOWS:
            return UPNPC_EXE_PATH is not None or MINIUPNPC_AVAILABLE
        else:
            return MINIUPNPC_AVAILABLE
    
    async def close(self):
        """Close any resources."""
        pass


def get_upnp_helper() -> UPnPHelper:
    """Get UPnP helper instance."""
    return UPnPHelper()
