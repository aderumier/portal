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

def get_client_ip(request: Request) -> Optional[str]:
    """Get client IP address from request, checking proxy headers first.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Client IP address as string, or None if not available
    """
    # Check X-Forwarded-For header (used by reverse proxies)
    # Format: "client, proxy1, proxy2" - we want the first (original client)
    forwarded_for = request.headers.get('X-Forwarded-For', '').strip()
    if forwarded_for:
        # Take the first IP if multiple are present
        client_ip = forwarded_for.split(',')[0].strip()
        if client_ip:
            return client_ip
    
    # Check X-Real-IP header (alternative proxy header)
    real_ip = request.headers.get('X-Real-IP', '').strip()
    if real_ip:
        return real_ip
    
    # Fall back to direct connection IP
    if request.client:
        return request.client.host
    
    return None





