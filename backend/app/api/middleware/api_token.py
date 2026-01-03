"""API token middleware."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.token import ApiTokenService
from app.api.middleware.auth import get_user_from_session
import logging

logger = logging.getLogger(__name__)

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[dict]:
    """Get current user from session or API token."""
    # Check for API token in Authorization header
    auth_header = request.headers.get('Authorization', '')
    
    if auth_header:
        token_service = ApiTokenService(db)
        token = token_service.extract_token_from_header(auth_header)
        
        if token:
            token_info = token_service.validate_token(token)
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
                logger.info(f"API token authentication successful for user: {token_info['user_id']}, token_id: {token_info['token_id']}")
                return request.state.user
    
    # Fall back to session authentication
    user = get_user_from_session(request)
    if user:
        request.state.user = user
        request.state.auth_method = 'session'
        logger.info(f"Session authentication for user: {user.get('id')}")
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

