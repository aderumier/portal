"""Creator role middleware."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from app.api.middleware.api_token import get_current_user
import logging

logger = logging.getLogger(__name__)

async def require_creator_role(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to have the Creator role."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    # Check if authenticated via API token
    auth_method = getattr(request.state, 'auth_method', None)
    if auth_method == 'api_token':
        # API tokens bypass creator role check (they're used by the download service)
        return current_user
    
    # For web interface users, check creator role
    is_creator = current_user.get('is_creator', False)
    if not is_creator:
        logger.warning(f"User {current_user.get('id')} does not have creator role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creator role required"
        )
    
    return current_user

