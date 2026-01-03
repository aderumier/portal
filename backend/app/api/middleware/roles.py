"""Role-based middleware for Discord roles."""
from fastapi import Request, HTTPException, status, Depends
from typing import Optional
from app.api.middleware.api_token import get_current_user
from app.services.discord import DiscordService
from app.config import settings
import logging

logger = logging.getLogger(__name__)

async def require_role(
    request: Request,
    role_name: str,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to have a specific Discord role."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    # Check if authenticated via API token
    auth_method = getattr(request.state, 'auth_method', None)
    if auth_method == 'api_token':
        # API tokens bypass role checks (they're used by the download service)
        return current_user
    
    # Check if user has the required role
    # Map role names to session keys based on configured roles
    if role_name == settings.DISCORD_DOWNLOAD_ROLE:
        role_key = 'is_download'
    elif role_name == settings.DISCORD_FASTDOWNLOAD_ROLE:
        role_key = 'is_fastdownload'
    elif role_name == settings.DISCORD_ADMIN_ROLE:
        role_key = 'is_admin'
    else:
        # Fallback for any other role names
        role_key = f'is_{role_name.lower()}'
    
    has_role = current_user.get(role_key, False)
    
    # If session says user doesn't have role, double-check with Discord API
    # (in case role was added after session was created)
    if not has_role:
        user_id = current_user.get('id')
        logger.info(f"Session shows user {user_id} doesn't have {role_name} role, re-checking with Discord API...")
        
        try:
            discord_service = DiscordService()
            has_role = await discord_service.has_role(user_id, role_name)
            await discord_service.close()
            
            if has_role:
                logger.info(f"User {user_id} actually HAS {role_name} role, updating session")
                # Update session with correct role key
                if 'user' in request.session:
                    request.session['user'][role_key] = True
                    request.session.modified = True
                # Update current_user dict for this request
                current_user[role_key] = True
            else:
                logger.warning(f"User {user_id} confirmed to NOT have {role_name} role")
        except Exception as e:
            logger.error(f"Error re-checking {role_name} role: {e}", exc_info=True)
            # If re-check fails, fall back to session value
    
    if not has_role:
        logger.warning(f"User {current_user.get('id')} does not have {role_name} role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{role_name} role required"
        )
    
    return current_user

async def require_download_role(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to have the download role."""
    return await require_role(request, settings.DISCORD_DOWNLOAD_ROLE, current_user)

async def require_admin_role(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to have the admin role."""
    return await require_role(request, settings.DISCORD_ADMIN_ROLE, current_user)

