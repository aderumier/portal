"""Creator role middleware."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from app.api.middleware.api_token import get_current_user
from app.services.discord import DiscordService
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
    
    # If session says user is not creator, double-check with Discord API
    # (in case role was added after session was created)
    if not is_creator:
        user_id = current_user.get('id')
        logger.info(f"Session shows user {user_id} is not creator, re-checking with Discord API...")
        
        try:
            discord_service = DiscordService()
            is_creator = await discord_service.has_role(user_id, 'Creator')
            await discord_service.close()
            
            if is_creator:
                logger.info(f"User {user_id} actually HAS creator role, updating session")
                # Update session
                if 'user' in request.session:
                    request.session['user']['is_creator'] = True
                    request.session.modified = True
                # Update current_user dict for this request
                current_user['is_creator'] = True
            else:
                logger.warning(f"User {user_id} confirmed to NOT have creator role")
        except Exception as e:
            logger.error(f"Error re-checking creator role: {e}", exc_info=True)
            # If re-check fails, fall back to session value
    
    if not is_creator:
        logger.warning(f"User {current_user.get('id')} does not have creator role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creator role required"
        )
    
    return current_user

