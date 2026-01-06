"""Authentication middleware."""
from fastapi import Request, HTTPException, status
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def get_user_from_session(request: Request) -> Optional[dict]:
    """Get user information from session."""
    return request.session.get('user')

def require_auth(request: Request) -> dict:
    """Require authentication - get user from session or raise exception."""
    user = get_user_from_session(request)
    
    if not user:
        logger.warning("No user session found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    return user



