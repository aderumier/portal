"""GeoIP service using MaxMind GeoLite2 database."""
import os
import ipaddress
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Global reader instance (singleton)
_geoip_reader = None

def get_geoip_reader():
    """Get or create GeoIP reader instance (singleton)."""
    global _geoip_reader
    
    if _geoip_reader is not None:
        return _geoip_reader
    
    try:
        import geoip2.database
        from app.config import settings
        
        # Determine database path
        db_path = settings.GEOIP_DATABASE_PATH
        
        if not db_path:
            # Default to backend/data/geoip/GeoLite2-Country.mmdb
            project_root = Path(__file__).parent.parent.parent
            db_path = project_root / 'data' / 'geoip' / 'GeoLite2-Country.mmdb'
        else:
            db_path = Path(db_path)
        
        # Check if database file exists
        if not db_path.exists():
            logger.warning(f"GeoIP database not found at {db_path}. GeoIP lookups will be disabled.")
            logger.info("To enable GeoIP lookups:")
            logger.info("1. Download GeoLite2-Country.mmdb from https://dev.maxmind.com/geoip/geoip2/geolite2/")
            logger.info(f"2. Place it at: {db_path}")
            logger.info("   Or set GEOIP_DATABASE_PATH environment variable to point to the database file")
            return None
        
        # Create reader
        _geoip_reader = geoip2.database.Reader(str(db_path))
        logger.info(f"GeoIP database loaded from {db_path}")
        return _geoip_reader
        
    except ImportError:
        logger.warning("geoip2 library not installed. Install with: pip install geoip2")
        return None
    except Exception as e:
        logger.error(f"Failed to load GeoIP database: {e}", exc_info=True)
        return None

def get_country_from_ip(ip_address: Optional[str]) -> Optional[str]:
    """Get country code from IP address using MaxMind GeoLite2 database.
    
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
    
    # Get GeoIP reader
    reader = get_geoip_reader()
    if reader is None:
        return None
    
    try:
        response = reader.country(ip_address)
        country_code = response.country.iso_code
        if country_code:
            logger.debug(f"GeoIP lookup for {ip_address}: {country_code}")
            return country_code
    except Exception as e:
        logger.warning(f"Failed to get country from IP {ip_address}: {e}")
    
    return None

def close_geoip_reader():
    """Close the GeoIP reader (call on application shutdown)."""
    global _geoip_reader
    if _geoip_reader is not None:
        try:
            _geoip_reader.close()
            _geoip_reader = None
            logger.info("GeoIP database reader closed")
        except Exception as e:
            logger.error(f"Error closing GeoIP reader: {e}")

