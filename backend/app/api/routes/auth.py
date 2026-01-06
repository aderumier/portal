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
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()

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

async def get_country_from_ip(ip_address: Optional[str]) -> Optional[str]:
    """Get country code from IP address using GeoIP service.
    
    Args:
        ip_address: IP address to lookup
        
    Returns:
        Two-letter country code (e.g., 'US', 'FR'), or None if lookup fails
    """
    if not ip_address:
        return None
    
    # Skip localhost/private IPs
    if ip_address in ('127.0.0.1', 'localhost', '::1') or ip_address.startswith(('192.168.', '10.', '172.')):
        return None
    
    try:
        # Use ip-api.com free service (no API key required, 45 requests/minute limit)
        # Alternative: ipapi.co (requires API key for production)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://ip-api.com/json/{ip_address}?fields=status,countryCode")
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    country_code = data.get('countryCode')
                    if country_code:
                        logger.debug(f"GeoIP lookup for {ip_address}: {country_code}")
                        return country_code
    except Exception as e:
        logger.warning(f"Failed to get country from IP {ip_address}: {e}")
    
    return None

@router.get("/login")
async def login(request: Request):
    """Redirect to Discord OAuth login."""
    discord_service = None
    try:
        logger.info("Login endpoint called")
        discord_service = DiscordService()
        logger.info("DiscordService created successfully")
        auth_url = discord_service.get_auth_url()
        logger.info(f"Auth URL generated: {auth_url[:50]}...")
        await discord_service.close()
        logger.info("DiscordService closed successfully")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Error in login endpoint: {e}", exc_info=True)
        if discord_service:
            try:
                await discord_service.close()
            except:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate login: {str(e)}"
        )

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
        
        # Check all configured roles
        download_role = settings.DISCORD_DOWNLOAD_ROLE
        fastdownload_role = settings.DISCORD_FASTDOWNLOAD_ROLE
        admin_role = settings.DISCORD_ADMIN_ROLE
        
        is_download = False
        is_fastdownload = False
        is_admin = False
        
        if is_guild_member:
            # Check download role
            logger.info(f"Checking if user has the {download_role} role (ID: {user['id']})")
            is_download = await discord_service.has_role(user['id'], download_role)
            logger.info(f"{download_role} role check result: {'HAS role' if is_download else 'NOT has role'}")
            
            # Check fastdownload role
            logger.info(f"Checking if user has the {fastdownload_role} role (ID: {user['id']})")
            is_fastdownload = await discord_service.has_role(user['id'], fastdownload_role)
            logger.info(f"{fastdownload_role} role check result: {'HAS role' if is_fastdownload else 'NOT has role'}")
            
            # Check admin role
            logger.info(f"Checking if user has the {admin_role} role (ID: {user['id']})")
            is_admin = await discord_service.has_role(user['id'], admin_role)
            logger.info(f"{admin_role} role check result: {'HAS role' if is_admin else 'NOT has role'}")
        
        # Store user info in session
        request.session['user'] = {
            'id': user['id'],
            'username': user.get('username', ''),
            'avatar': user.get('avatar', ''),
            'access_token': access_token,
            'is_guild_member': is_guild_member,
            'is_download': is_download,
            'is_fastdownload': is_fastdownload,
            'is_admin': is_admin
        }
        
        # Update or create user record in database with username, last_login, and IP address
        if is_guild_member:
            from app.database import User
            from datetime import datetime, timezone
            
            # Get client IP address
            client_ip = get_client_ip(request)
            
            db_user = db.query(User).filter(User.user_id == user['id']).first()
            current_time = datetime.now(timezone.utc)
            
            # Determine if we should update country (if IP is empty or changed)
            should_update_country = False
            country = None
            
            if client_ip:
                if not db_user or not db_user.last_login_ip or db_user.last_login_ip != client_ip:
                    should_update_country = True
                    country = await get_country_from_ip(client_ip)
                    if country:
                        logger.info(f"GeoIP lookup for {client_ip}: {country}")
            
            if db_user:
                # Update existing user
                db_user.username = user.get('username', '')
                db_user.last_login = current_time
                previous_ip = db_user.last_login_ip
                db_user.last_login_ip = client_ip
                
                # Update country if IP was empty or changed
                if should_update_country and country:
                    db_user.country = country
                    logger.info(f"Updated user {user['id']} country to {country} (IP changed from {previous_ip} to {client_ip})")
                elif should_update_country and not country:
                    logger.debug(f"Could not determine country for IP {client_ip}, keeping existing country: {db_user.country}")
                
                db_user.updated_at = current_time
                logger.info(f"Updated user {user['id']} username, last_login, and IP: {client_ip}")
            else:
                # Create new user record
                db_user = User(
                    user_id=user['id'],
                    username=user.get('username', ''),
                    total_download_mb=0.0,
                    total_download_number=0,
                    last_login=current_time,
                    last_login_ip=client_ip,
                    country=country,
                    created_at=current_time,
                    updated_at=current_time
                )
                db.add(db_user)
                logger.info(f"Created new user record for {user['id']} with username {user.get('username', '')}, IP: {client_ip}, country: {country}")
            
            db.commit()
        
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
    """Logout and clear session.
    
    This clears the session data, and the middleware will handle:
    - Deleting the session from storage (Redis/database/file)
    - Deleting the session cookie
    """
    # Clear session data - middleware will handle deletion and cookie removal
    request.session.clear()
    
    # Create redirect response
    # Note: The middleware will detect the empty session and delete the cookie
    redirect_response = RedirectResponse(url=f"{settings.FRONTEND_URL}/", status_code=302)
    
    # Also explicitly delete cookie here as a backup
    redirect_response.delete_cookie(
        key='session',
        path='/',
        httponly=True,
        samesite='lax'
    )
    
    return redirect_response

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
    
    # Determine which role names to return
    download_role_name = None
    fastdownload_role_name = None
    admin_role_name = None
    
    if current_user.get('is_download', False):
        download_role_name = settings.DISCORD_DOWNLOAD_ROLE
    if current_user.get('is_fastdownload', False):
        fastdownload_role_name = settings.DISCORD_FASTDOWNLOAD_ROLE
    if current_user.get('is_admin', False):
        admin_role_name = settings.DISCORD_ADMIN_ROLE
    
    return {
        'id': current_user.get('id'),
        'username': current_user.get('username'),
        'avatar': current_user.get('avatar'),
        'is_guild_member': current_user.get('is_guild_member', False),
        'is_download': current_user.get('is_download', False),
        'is_fastdownload': current_user.get('is_fastdownload', False),
        'is_admin': current_user.get('is_admin', False),
        'download_role_name': download_role_name,
        'fastdownload_role_name': fastdownload_role_name,
        'admin_role_name': admin_role_name
    }

@router.post("/refresh-roles")
async def refresh_roles_status(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """Refresh all role statuses for the current user."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    user_id = current_user.get('id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID not found"
        )
    
    try:
        discord_service = DiscordService()
        
        download_role = settings.DISCORD_DOWNLOAD_ROLE
        fastdownload_role = settings.DISCORD_FASTDOWNLOAD_ROLE
        admin_role = settings.DISCORD_ADMIN_ROLE
        
        # Check download role
        is_download = await discord_service.has_role(user_id, download_role)
        logger.info(f"Refreshed {download_role} role check for user {user_id}: {'HAS role' if is_download else 'NOT has role'}")
        
        # Check fastdownload role
        is_fastdownload = await discord_service.has_role(user_id, fastdownload_role)
        logger.info(f"Refreshed {fastdownload_role} role check for user {user_id}: {'HAS role' if is_fastdownload else 'NOT has role'}")
        
        # Check admin role
        is_admin = await discord_service.has_role(user_id, admin_role)
        logger.info(f"Refreshed {admin_role} role check for user {user_id}: {'HAS role' if is_admin else 'NOT has role'}")
        
        # Update session
        if 'user' in request.session:
            request.session['user']['is_download'] = is_download
            request.session['user']['is_fastdownload'] = is_fastdownload
            request.session['user']['is_admin'] = is_admin
            request.session.modified = True
        
        await discord_service.close()
        
        return {
            'id': user_id,
            'username': current_user.get('username'),
            'is_download': is_download,
            'is_fastdownload': is_fastdownload,
            'is_admin': is_admin,
            'refreshed': True
        }
    except Exception as e:
        logger.error(f"Error refreshing roles status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh roles status"
        )

