"""GeoIP service using geoip2fast library."""
import ipaddress
import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Global GeoIP instance (singleton)
_geoip_instance = None

def get_geoip_instance():
    """Get or create GeoIP2Fast instance (singleton).
    
    geoip2fast includes its own data files, stored in ./data/geoip/ directory.
    The library automatically downloads and updates data files on first use if not present.
    """
    global _geoip_instance
    
    if _geoip_instance is not None:
        return _geoip_instance
    
    try:
        from geoip2fast import GeoIP2Fast
        
        # Determine project root (go up from backend/app/services to project root)
        project_root = Path(__file__).parent.parent.parent.parent
        geoip_dir = project_root / 'data' / 'geoip'
        
        # Create directory if it doesn't exist
        geoip_dir.mkdir(parents=True, exist_ok=True)
        
        # Path to geoip2fast IPv6 data file
        # The library will auto-download if the file doesn't exist
        geoip_data_file = geoip_dir / 'geoip2fast-ipv6.dat.gz'
        
        # Initialize GeoIP2Fast with custom data file path
        _geoip_instance = GeoIP2Fast(
            geoip2fast_data_file=str(geoip_data_file),
            verbose=False
        )
        logger.info(f"GeoIP2Fast initialized successfully (data file: {geoip_data_file})")
        return _geoip_instance
        
    except ImportError:
        logger.warning("geoip2fast library not installed. Install with: pip install geoip2fast")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize GeoIP2Fast: {e}", exc_info=True)
        return None

def get_country_from_ip(ip_address: Optional[str]) -> Optional[str]:
    """Get country code from IP address using geoip2fast.
    
    Args:
        ip_address: IP address to lookup (IPv4 or IPv6)
        
    Returns:
        Two-letter ISO country code (e.g., 'US', 'FR'), or None if lookup fails
    """
    if not ip_address:
        return None
    
    # Skip localhost/private IPs
    try:
        ip = ipaddress.ip_address(ip_address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return None
    except ValueError:
        # Invalid IP address
        return None
    
    # Get GeoIP instance
    geoip = get_geoip_instance()
    if geoip is None:
        return None
    
    try:
        result = geoip.lookup(ip_address)
        country_code = result.country_code
        if country_code:
            logger.debug(f"GeoIP lookup for {ip_address}: {country_code}")
            return country_code
    except Exception as e:
        logger.warning(f"Failed to get country from IP {ip_address}: {e}")
    
    return None

def close_geoip_instance():
    """Close the GeoIP instance (call on application shutdown)."""
    global _geoip_instance
    if _geoip_instance is not None:
        try:
            # geoip2fast doesn't require explicit closing, but we'll clear the reference
            _geoip_instance = None
            logger.info("GeoIP2Fast instance cleared")
        except Exception as e:
            logger.error(f"Error clearing GeoIP instance: {e}")

