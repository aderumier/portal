"""Discord guild membership middleware."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from app.api.middleware.api_token import get_current_user
import logging

logger = logging.getLogger(__name__)

async def require_guild_member(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to be a member of the Discord guild."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    # Check if authenticated via API token
    auth_method = getattr(request.state, 'auth_method', None)
    if auth_method == 'api_token':
        is_guild_member = getattr(request.state, 'is_guild_member', False)
        if not is_guild_member:
            logger.warning(f"API token user {current_user.get('id')} is not a guild member")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guild membership required"
            )
        return current_user
    
    # For web interface users, check session
    is_guild_member = current_user.get('is_guild_member', False)
    if not is_guild_member:
        logger.warning(f"User {current_user.get('id')} is not a guild member")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guild membership required"
        )
    
    return current_user

