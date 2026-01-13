"""Dependency injection for FastAPI."""
from app.database import get_db
from app.config import settings

def get_settings():
    """Get application settings."""
    return settings











