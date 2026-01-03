"""Authentication routes."""
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services.discord import DiscordService
from app.api.middleware.api_token import get_current_user
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/login")
async def login(request: Request):
    """Redirect to Discord OAuth login."""
    discord_service = DiscordService()
    auth_url = discord_service.get_auth_url()
    await discord_service.close()
    return RedirectResponse(url=auth_url)

@router.get("/callback")
async def callback(
    request: Request,
    code: str = None,
    db: Session = Depends(get_db)
):
    """Handle Discord OAuth callback."""
    if not code:
        logger.error("No code provided in callback")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)
    
    try:
        discord_service = DiscordService()
        
        # Exchange code for access token
        token_data = await discord_service.get_access_token(code)
        
        if not token_data.get('access_token'):
            logger.error(f"Failed to get access token: {token_data}")
            await discord_service.close()
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)
        
        access_token = token_data['access_token']
        logger.info(f"Access token received, scope: {token_data.get('scope', 'not_specified')}")
        
        # Get user info
        user = await discord_service.get_user(access_token)
        
        if not user.get('id'):
            logger.error(f"Failed to get user data: {user}")
            await discord_service.close()
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)
        
        logger.info(f"User data received: {user.get('username')} (ID: {user.get('id')})")
        
        # Check guild membership
        required_guild_name = "Team Pixel Nostalgia"
        is_guild_member = await discord_service.is_guild_member_by_name(
            user['id'],
            access_token,
            required_guild_name
        )
        
        logger.info(f"Guild membership check result: {'IS member' if is_guild_member else 'NOT a member'}")
        
        # Check creator role
        is_creator = False
        if is_guild_member:
            logger.info(f"Checking if user has the Creator role (ID: {user['id']})")
            is_creator = await discord_service.has_role(user['id'], 'Creator')
            logger.info(f"Creator role check result: {'IS creator' if is_creator else 'NOT a creator'}")
        
        # Store user info in session
        request.session['user'] = {
            'id': user['id'],
            'username': user.get('username', ''),
            'avatar': user.get('avatar', ''),
            'access_token': access_token,
            'is_guild_member': is_guild_member,
            'is_creator': is_creator
        }
        
        await discord_service.close()
        
        if not is_guild_member:
            logger.info("User is not a guild member, redirecting to unauthorized")
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/unauthorized", status_code=302)
        
        logger.info("Authentication successful, redirecting to systems page")
        # Redirect to frontend
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/systems", status_code=302)
        
    except Exception as e:
        logger.error(f"Error during Discord authentication: {e}", exc_info=True)
        await discord_service.close()
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)

@router.get("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    request.session.clear()
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)

@router.get("/me")
async def get_current_user_info(
    current_user: Optional[dict] = Depends(get_current_user)
):
    """Get current user information. Returns 401 if not authenticated (expected for public pages)."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    return {
        'id': current_user.get('id'),
        'username': current_user.get('username'),
        'avatar': current_user.get('avatar'),
        'is_guild_member': current_user.get('is_guild_member', False),
        'is_creator': current_user.get('is_creator', False)
    }

