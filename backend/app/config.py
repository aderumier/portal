"""Configuration management for the application."""
import os
import json
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


class Settings:
    """Application settings loaded from environment variables."""
    
    # Discord OAuth2 settings
    DISCORD_CLIENT_ID: str = os.getenv('DISCORD_CLIENT_ID', '')
    DISCORD_CLIENT_SECRET: str = os.getenv('DISCORD_CLIENT_SECRET', '')
    DISCORD_REDIRECT_URI: str = os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:8000/api/auth/callback')
    DISCORD_BOT_TOKEN: str = os.getenv('DISCORD_BOT_TOKEN', '')
    DISCORD_GUILD_ID: str = os.getenv('DISCORD_GUILD_ID', '1006854943157788722')
    
    # Discord role mappings
    DISCORD_DOWNLOAD_ROLE: str = os.getenv('DISCORD_DOWNLOAD_ROLE', 'Creator')
    DISCORD_ADMIN_ROLE: str = os.getenv('DISCORD_ADMIN_ROLE', 'Creator')
    DISCORD_FASTDOWNLOAD_ROLE: str = os.getenv('DISCORD_FASTDOWNLOAD_ROLE', 'fastdownload')
    
    # Application settings
    GAMES_PATH: str = os.getenv('GAMES_PATH', '')
    USERS_MEDIA_PATH: str = os.getenv('USERS_MEDIA_PATH', '')
    USERS_GAMELIST_PATH: str = os.getenv('USERS_GAMELIST_PATH', 'data/users_gamelist')  # Path for storing user gamelist.xml files
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///./data/database.sqlite')
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FRONTEND_URL: str = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    API_URL: str = os.getenv('API_URL', 'http://localhost:8000')  # Backend API URL for download service
    DOWNLOAD_FILE_URL: str = os.getenv('DOWNLOAD_FILE_URL', '')  # Public URL for download file endpoint (defaults to API_URL if not set)
    
    # Session storage settings
    SESSION_STORAGE: str = os.getenv('SESSION_STORAGE', 'memory')  # Options: 'memory', 'redis', 'file', 'database'
    REDIS_URL: str = os.getenv('REDIS_URL', 'redis://localhost:6379/0')  # Redis connection URL for session storage
    REDIS_SESSION_KEY_PREFIX: str = os.getenv('REDIS_SESSION_KEY_PREFIX', 'session:')  # Prefix for session keys in Redis
    SESSION_MAX_AGE: int = int(os.getenv('SESSION_MAX_AGE', str(3600 * 24)))  # Session timeout in seconds (default: 24 hours)
    
    # Bandwidth management settings
    # GLOBAL_BANDWIDTH_LIMIT is in Mbits/s, converted to bytes/s internally
    # Default: 1000 Mbits/s = 125,000,000 bytes/s
    GLOBAL_BANDWIDTH_LIMIT_Mbits: float = float(os.getenv('GLOBAL_BANDWIDTH_LIMIT', '1000.0'))  # Mbits/s
    GLOBAL_BANDWIDTH_LIMIT: int = int(GLOBAL_BANDWIDTH_LIMIT_Mbits * 125000)  # Convert to bytes/s (1 Mbit = 125 KB)
    BANDWIDTH_UPDATE_INTERVAL: int = int(os.getenv('BANDWIDTH_UPDATE_INTERVAL', '5'))  # 5 seconds
    
    # Download service settings
    POLLING_INTERVAL: int = int(os.getenv('POLLING_INTERVAL', '10'))  # Seconds between queue checks
    
    # Backend worker settings
    BACKEND_WORKERS: int = int(os.getenv('BACKEND_WORKERS', '4'))  # Number of uvicorn workers
    REDIS_WS_DB: int = int(os.getenv('REDIS_WS_DB', '4'))  # Redis database number for websocket tracking
    
    # P2P settings
    P2P_ENABLED: bool = os.getenv('P2P_ENABLED', 'true').lower() == 'true'  # Enable P2P transfers (default: true)
    P2P_PORT: int = int(os.getenv('P2P_PORT', '8765'))  # Local port for P2P service (default: 8765)
    UPnP_ENABLED: bool = os.getenv('UPnP_ENABLED', 'true').lower() == 'true'  # Enable UPnP (default: true)
    P2P_MAX_PEER_ATTEMPTS: int = int(os.getenv('P2P_MAX_PEER_ATTEMPTS', '5'))  # Max peers to try (default: 5)
    P2P_TIMEOUT: int = int(os.getenv('P2P_TIMEOUT', '30'))  # Timeout for P2P requests in seconds (default: 30)
    
    # Catalog settings
    # Note: Releases catalog is always enabled
    
    # Per-user bandwidth limits for testing (optional, in Mbits/s)
    # If not set, no per-user limit is applied (users share available bandwidth equally)
    # If set, each user is limited to this bandwidth regardless of available bandwidth
    PER_USER_SLOW_QUEUE_LIMIT_Mbits: Optional[float] = None
    PER_USER_FAST_QUEUE_LIMIT_Mbits: Optional[float] = None
    
    # Load per-user limits from environment if set
    _per_user_slow = os.getenv('PER_USER_SLOW_QUEUE_LIMIT_Mbits', '')
    if _per_user_slow:
        PER_USER_SLOW_QUEUE_LIMIT_Mbits = float(_per_user_slow)
        PER_USER_SLOW_QUEUE_LIMIT: int = int(PER_USER_SLOW_QUEUE_LIMIT_Mbits * 125000)  # Convert to bytes/s
    else:
        PER_USER_SLOW_QUEUE_LIMIT: Optional[int] = None
    
    _per_user_fast = os.getenv('PER_USER_FAST_QUEUE_LIMIT_Mbits', '')
    if _per_user_fast:
        PER_USER_FAST_QUEUE_LIMIT_Mbits = float(_per_user_fast)
        PER_USER_FAST_QUEUE_LIMIT: int = int(PER_USER_FAST_QUEUE_LIMIT_Mbits * 125000)  # Convert to bytes/s
    else:
        PER_USER_FAST_QUEUE_LIMIT: Optional[int] = None
    
    # CORS settings
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",  # Vite default port
    ]
    
    # Media mapping cache
    _media_mapping: dict = None
    
    @classmethod
    def get_media_mapping(cls) -> dict:
        """Load and cache media field name to directory mapping."""
        if cls._media_mapping is not None:
            return cls._media_mapping
        
        mapping_file = Path(__file__).parent.parent / 'media_mapping.json'
        
        if not mapping_file.exists():
            # Return default mapping if file doesn't exist
            cls._media_mapping = {
                "thumbnail": "thumbnails",
                "boxart": "boxart",
                "boxback": "boxback",
                "marquee": "marquees",
                "fanart": "fanarts",
                "cartridge": "cartridges",
                "titleshot": "titles",
                "image": "images",
                "screenshot": "screenshots",
                "wheel": "wheels",
                "mix": "mix",
                "video": "videos"
            }
            return cls._media_mapping
        
        try:
            with open(mapping_file, 'r') as f:
                cls._media_mapping = json.load(f)
            return cls._media_mapping
        except Exception as e:
            # Return default mapping on error
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to load media mapping: {e}")
            cls._media_mapping = {
                "thumbnail": "thumbnails",
                "boxart": "boxart",
                "boxback": "boxback",
                "marquee": "marquees",
                "fanart": "fanarts",
                "cartridge": "cartridges",
                "titleshot": "titles",
                "image": "images",
                "screenshot": "screenshots",
                "wheel": "wheels",
                "mix": "mix",
                "video": "videos"
            }
            return cls._media_mapping


settings = Settings()

