"""API token middleware."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from app.services.token import ApiTokenService
from app.api.middleware.auth import get_user_from_session, get_client_ip
import logging

logger = logging.getLogger(__name__)

async def get_current_user(
    request: Request
) -> Optional[dict]:
    """Get current user from session or API token.
    
    This function only requests a database connection when validating API tokens.
    For session-based authentication, no database connection is needed, preventing
    pool exhaustion issues when the SQLite pool is full.
    """
    # Check for API token in Authorization header
    auth_header = request.headers.get('Authorization', '')
    
    if auth_header:
        # Only get DB connection when we actually need it for token validation
        from app.database import get_db
        db = next(get_db())
        try:
            token_service = ApiTokenService(db)
            token = token_service.extract_token_from_header(auth_header)
            
            if token:
                # Get client IP address
                client_ip = get_client_ip(request)
                
                # Validate token (async method now)
                token_info = await token_service.validate_token(token, client_ip)
                if token_info:
                    # Set user info in request state
                    request.state.user = {
                        'id': token_info['user_id'],
                        'is_guild_member': True,  # API tokens assume guild membership
                        'is_download': True,  # API tokens have download access
                        'is_fastdownload': True,  # API tokens have fastdownload access
                        'is_admin': False  # API tokens don't have admin role by default
                    }
                    request.state.token_id = token_info['token_id']  # Store token_id for filtering
                    request.state.auth_method = 'api_token'
                    logger.info(
                        f"API token authentication successful for user: {token_info['user_id']}, "
                        f"token_id: {token_info['token_id']}, IP: {client_ip}"
                    )
                    return request.state.user
                else:
                    # Token validation failed (could be invalid token or revoked)
                    logger.warning(
                        f"API token authentication failed. Token may be invalid or revoked. "
                        f"Request IP: {client_ip}"
                    )
        finally:
            # Always close the DB connection
            db.close()
    
    # Fall back to session authentication (no DB connection needed)
    user = get_user_from_session(request)
    if user:
        request.state.user = user
        request.state.auth_method = 'session'
        logger.debug(f"Session authentication for user: {user.get('id')}")
        return user
    
    return None

async def require_auth_user(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require authentication - get user from session or API token."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    return current_user

