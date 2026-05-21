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
    """Require user to have either the download role or fastdownload role."""
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

    # If no download role is configured, all guild members have download access
    if not settings.DISCORD_DOWNLOAD_ROLE:
        if not current_user.get('is_guild_member', False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guild membership required"
            )
        return current_user

    # Check if user has either download role or fastdownload role
    has_download_role = current_user.get('is_download', False)
    has_fastdownload_role = current_user.get('is_fastdownload', False)
    
    # If session doesn't show either role, double-check with Discord API
    if not has_download_role and not has_fastdownload_role:
        user_id = current_user.get('id')
        logger.info(f"Session shows user {user_id} doesn't have download roles, re-checking with Discord API...")
        
        try:
            discord_service = DiscordService()
            has_download_role = await discord_service.has_role(user_id, settings.DISCORD_DOWNLOAD_ROLE)
            has_fastdownload_role = await discord_service.has_role(user_id, settings.DISCORD_FASTDOWNLOAD_ROLE)
            await discord_service.close()
            
            if has_download_role or has_fastdownload_role:
                logger.info(f"User {user_id} actually HAS download role(s), updating session")
                # Update session with correct role keys
                if 'user' in request.session:
                    request.session['user']['is_download'] = has_download_role
                    request.session['user']['is_fastdownload'] = has_fastdownload_role
                    request.session.modified = True
                # Update current_user dict for this request
                current_user['is_download'] = has_download_role
                current_user['is_fastdownload'] = has_fastdownload_role
            else:
                logger.warning(f"User {user_id} confirmed to NOT have download roles")
        except Exception as e:
            logger.error(f"Error re-checking download roles: {e}", exc_info=True)
            # If re-check fails, fall back to session value
    
    if not has_download_role and not has_fastdownload_role:
        logger.warning(f"User {current_user.get('id')} does not have download or fastdownload role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{settings.DISCORD_DOWNLOAD_ROLE} or {settings.DISCORD_FASTDOWNLOAD_ROLE} role required"
        )
    
    return current_user

async def require_admin_role(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require user to have the admin role."""
    return await require_role(request, settings.DISCORD_ADMIN_ROLE, current_user)

async def require_media_contributor(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require media contributor access.

    If MEDIA_CONTRIBUTERS is empty, any authenticated guild member is allowed.
    If non-empty, the user must have at least one of the configured Discord roles.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    auth_method = getattr(request.state, 'auth_method', None)
    if auth_method == 'api_token':
        return current_user

    if not current_user.get('is_guild_member', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guild membership required"
        )

    allowed_roles = settings.MEDIA_CONTRIBUTORS
    if not allowed_roles:
        return current_user

    if current_user.get('is_admin', False):
        return current_user

    cached_roles = current_user.get('media_contributor_roles', {})
    if any(cached_roles.get(role_name, False) for role_name in allowed_roles):
        return current_user

    user_id = current_user.get('id')
    logger.info(f"Checking media contributor access for user {user_id}: roles={allowed_roles}")

    discord_service = None
    try:
        discord_service = DiscordService()
        role_results = await discord_service.check_roles(user_id, allowed_roles)
    except Exception as e:
        logger.error(f"Error checking media contributor roles: {e}", exc_info=True)
        role_results = {}
    finally:
        if discord_service:
            await discord_service.close()

    has_access = any(role_results.get(role_name, False) for role_name in allowed_roles)

    if role_results and 'user' in request.session:
        cached = request.session['user'].setdefault('media_contributor_roles', {})
        cached.update(role_results)
        request.session['user']['is_media_contributor'] = has_access
        current_user['is_media_contributor'] = has_access
        request.session.modified = True
        current_user['media_contributor_roles'] = cached

    if not has_access:
        logger.warning(f"User {user_id} does not have any media contributor role: {allowed_roles}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Media contributor role required"
        )

    return current_user


def get_catalog_viewer_roles(catalog_type: str) -> list:
    """Return configured viewer roles for the requested catalog."""
    if catalog_type == 'wip':
        return settings.WIP_CATALOG_VIEWERS
    return settings.RELEASE_CATALOG_VIEWERS

async def require_catalog_viewer(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """Require access to the requested catalog type.

    Empty RELEASE_CATALOG_VIEWERS/WIP_CATALOG_VIEWERS preserve the previous
    behavior: any authenticated guild member may view that catalog.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    auth_method = getattr(request.state, 'auth_method', None)
    if auth_method == 'api_token':
        return current_user
    
    if not current_user.get('is_guild_member', False):
        logger.warning(f"User {current_user.get('id')} is not a guild member")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Guild membership required"
        )
    
    catalog_type = request.query_params.get('catalog_type', 'releases')
    allowed_roles = get_catalog_viewer_roles(catalog_type)
    if not allowed_roles:
        return current_user
    
    if current_user.get('is_admin', False):
        return current_user
    
    catalog_role_cache = current_user.get('catalog_viewer_roles', {})
    if any(catalog_role_cache.get(role_name, False) for role_name in allowed_roles):
        return current_user
    
    user_id = current_user.get('id')
    logger.info(
        f"Checking catalog access for user {user_id}: catalog={catalog_type}, roles={allowed_roles}"
    )
    
    discord_service = None
    try:
        discord_service = DiscordService()
        role_results = await discord_service.check_roles(user_id, allowed_roles)
    except Exception as e:
        logger.error(f"Error checking catalog viewer roles: {e}", exc_info=True)
        role_results = {}
    finally:
        if discord_service:
            await discord_service.close()
    
    has_catalog_access = any(role_results.get(role_name, False) for role_name in allowed_roles)
    
    if role_results and 'user' in request.session:
        cached_roles = request.session['user'].setdefault('catalog_viewer_roles', {})
        cached_roles.update(role_results)
        if catalog_type == 'wip':
            request.session['user']['is_wip_catalog_viewer'] = has_catalog_access
            current_user['is_wip_catalog_viewer'] = has_catalog_access
        else:
            request.session['user']['is_release_catalog_viewer'] = has_catalog_access
            current_user['is_release_catalog_viewer'] = has_catalog_access
        request.session.modified = True
        current_user['catalog_viewer_roles'] = cached_roles
    
    if not has_catalog_access:
        logger.warning(
            f"User {user_id} does not have any {catalog_type} catalog viewer role: {allowed_roles}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{catalog_type} catalog access required"
        )
    
    return current_user
