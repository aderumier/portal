"""Configuration management for the application."""
import os
import json
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
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///./data/database.sqlite')
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FRONTEND_URL: str = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    
    # Bandwidth management settings
    # GLOBAL_BANDWIDTH_LIMIT is in Mbits/s, converted to bytes/s internally
    # Default: 1000 Mbits/s = 125,000,000 bytes/s
    GLOBAL_BANDWIDTH_LIMIT_Mbits: float = float(os.getenv('GLOBAL_BANDWIDTH_LIMIT', '1000.0'))  # Mbits/s
    GLOBAL_BANDWIDTH_LIMIT: int = int(GLOBAL_BANDWIDTH_LIMIT_Mbits * 125000)  # Convert to bytes/s (1 Mbit = 125 KB)
    BANDWIDTH_UPDATE_INTERVAL: int = int(os.getenv('BANDWIDTH_UPDATE_INTERVAL', '5'))  # 5 seconds
    
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

