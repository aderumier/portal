"""Configuration management for the application."""
import os
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
    
    # Application settings
    GAMES_PATH: str = os.getenv('GAMES_PATH', '')
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///./data/database.sqlite')
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FRONTEND_URL: str = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    
    # CORS settings
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",  # Vite default port
    ]


settings = Settings()

