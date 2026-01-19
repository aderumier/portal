"""User management routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import get_db, User, ApiToken
from app.services.token import ApiTokenService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
from app.api.middleware.roles import require_admin_role
import logging
from typing import List, Dict, Optional
import asyncio

logger = logging.getLogger(__name__)

async def _test_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Test TCP port accessibility by attempting a connection.
    
    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Connection timeout in seconds (default: 2.0)
    
    Returns:
        True if port is accessible, False otherwise
    """
    logger.debug(f"Testing TCP port {host}:{port} with timeout {timeout}s")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        # Connection successful - close immediately
        writer.close()
        await writer.wait_closed()
        logger.info(f"TCP port test succeeded for {host}:{port} - port is accessible")
        return True
    except asyncio.TimeoutError:
        logger.warning(f"TCP port test failed for {host}:{port}: Connection timeout after {timeout}s")
        return False
    except ConnectionRefusedError:
        logger.warning(f"TCP port test failed for {host}:{port}: Connection refused (port not open or firewall blocking)")
        return False
    except OSError as e:
        logger.warning(f"TCP port test failed for {host}:{port}: Network error - {type(e).__name__}: {str(e)}")
        return False
    except Exception as e:
        logger.warning(f"TCP port test failed for {host}:{port}: Unexpected error - {type(e).__name__}: {str(e)}")
        return False

router = APIRouter()

class GenerateTokenRequest(BaseModel):
    name: str = "API Token"

class UpdateBandwidthLimitRequest(BaseModel):
    bandwidth_limit: Optional[int] = None

class UpdateCustomPortRequest(BaseModel):
    custom_public_port: Optional[int] = None

def get_token_service(db: Session = Depends(get_db)) -> ApiTokenService:
    """Get API token service instance."""
    return ApiTokenService(db)

@router.get("/tokens")
async def get_tokens(
    current_user: dict = Depends(require_guild_member),
    token_service: ApiTokenService = Depends(get_token_service)
):
    """Get all API tokens for current user."""
    user_id = current_user['id']
    tokens = token_service.get_user_tokens(user_id)
    return {"tokens": tokens}

@router.post("/tokens")
async def generate_token(
    request: GenerateTokenRequest,
    current_user: dict = Depends(require_guild_member),
    token_service: ApiTokenService = Depends(get_token_service)
):
    """Generate a new API token for current user."""
    user_id = current_user['id']
    token = token_service.generate_token(user_id, request.name)
    return {"token": token}

@router.delete("/tokens/{token_id}")
async def revoke_token(
    token_id: int,
    current_user: dict = Depends(require_guild_member),
    token_service: ApiTokenService = Depends(get_token_service)
):
    """Delete an API token from the database."""
    user_id = current_user['id']
    success = await token_service.revoke_token(user_id, token_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or doesn't belong to user"
        )
    
    return {"success": True}

@router.put("/tokens/{token_id}/custom-port")
async def update_custom_port(
    token_id: int,
    request: UpdateCustomPortRequest,
    http_request: Request,
    current_user: dict = Depends(require_guild_member),
    db: Session = Depends(get_db)
):
    """Update custom public port for a token. Tests port accessibility before saving."""
    from app.api.middleware.auth import get_client_ip
    from app.services.p2p_inventory import P2PInventoryService
    
    user_id = current_user['id']
    custom_port = request.custom_public_port
    
    # Validate port range if provided
    if custom_port is not None:
        try:
            custom_port = int(custom_port)
            if custom_port < 1 or custom_port > 65535:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Port must be between 1 and 65535"
                )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid port value"
            )
    
    # Verify token belongs to current user
    token = db.query(ApiToken).filter(
        and_(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id
        )
    ).first()
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or doesn't belong to user"
        )
    
    # Test port if a custom port is being set (not clearing)
    if custom_port is not None:
        # Get external IP from P2P connection info or use client IP
        external_ip = None
        p2p_info = await P2PInventoryService.get_client_connection_info(token_id)
        if p2p_info and p2p_info.get('external_ip'):
            external_ip = p2p_info.get('external_ip')
        else:
            # Fallback to client IP from request
            client_ip = get_client_ip(http_request)
            if client_ip:
                external_ip = client_ip
        
        if not external_ip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine external IP address for port testing. Please ensure the device is connected."
            )
        
        # Test port accessibility with 2s timeout
        logger.info(f"Testing custom port {external_ip}:{custom_port} for token_id {token_id} before saving")
        port_accessible = await _test_tcp_port(external_ip, custom_port, timeout=2.0)
        
        if not port_accessible:
            logger.warning(f"Port test failed for {external_ip}:{custom_port} (token_id {token_id}) - blocking port change")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Port {custom_port} is not accessible from {external_ip}. Please ensure the port is open and forwarded correctly."
            )
        
        logger.info(f"Port test succeeded for {external_ip}:{custom_port} (token_id {token_id}) - allowing port change")
    
    # Update custom port (only if test passed or clearing)
    token.custom_public_port = custom_port
    db.commit()
    
    logger.info(f"Updated custom public port for token_id {token_id} (user {user_id}): {custom_port}")
    
    return {
        "success": True,
        "custom_public_port": custom_port
    }

@router.get("/bandwidth-limit")
async def get_bandwidth_limit(
    current_user: dict = Depends(require_guild_member),
    db: Session = Depends(get_db)
):
    """Get current user's bandwidth limit and max allowed limit based on role."""
    from app.config import settings
    
    user_id = current_user['id']
    db_user = db.query(User).filter(User.user_id == user_id).first()
    
    # Determine max limit based on user's role
    is_fastdownload = current_user.get('is_fastdownload', False)
    is_download = current_user.get('is_download', False)
    
    # Get role-based max limit
    max_limit = None
    if is_fastdownload:
        max_limit = getattr(settings, 'PER_USER_FAST_QUEUE_LIMIT', None)
    elif is_download:
        max_limit = getattr(settings, 'PER_USER_SLOW_QUEUE_LIMIT', None)
    
    current_limit = db_user.bandwidth_limit if db_user else None
    
    return {
        "bandwidth_limit": current_limit,
        "max_bandwidth_limit": max_limit,
        "has_fastdownload_role": is_fastdownload,
        "has_download_role": is_download
    }

@router.put("/bandwidth-limit")
async def update_bandwidth_limit(
    request: UpdateBandwidthLimitRequest,
    current_user: dict = Depends(require_guild_member),
    db: Session = Depends(get_db)
):
    """Update current user's bandwidth limit (capped at role-based limit)."""
    from app.config import settings
    from datetime import datetime, timezone
    
    user_id = current_user['id']
    new_limit = request.bandwidth_limit
    
    # Validate input
    if new_limit is not None:
        try:
            new_limit = int(new_limit)
            if new_limit < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bandwidth limit must be non-negative"
                )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid bandwidth limit value"
            )
    
    # Determine max limit based on user's role
    is_fastdownload = current_user.get('is_fastdownload', False)
    is_download = current_user.get('is_download', False)
    
    # Get role-based max limit
    max_limit = None
    if is_fastdownload:
        max_limit = getattr(settings, 'PER_USER_FAST_QUEUE_LIMIT', None)
    elif is_download:
        max_limit = getattr(settings, 'PER_USER_SLOW_QUEUE_LIMIT', None)
    
    # Cap the new limit at the role-based max
    if new_limit is not None and max_limit is not None:
        if new_limit > max_limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bandwidth limit cannot exceed {max_limit} bytes/s ({max_limit / 125000:.2f} Mbits/s) for your role"
            )
    
    # Get or create user
    db_user = db.query(User).filter(User.user_id == user_id).first()
    if not db_user:
        db_user = User(
            user_id=user_id,
            username=current_user.get('username'),
            total_download_mb=0.0,
            total_download_number=0,
            bandwidth_limit=new_limit,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(db_user)
    else:
        db_user.bandwidth_limit = new_limit
        db_user.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    logger.info(f"Updated bandwidth limit for user {user_id}: {new_limit} bytes/s (max allowed: {max_limit})")
    
    return {
        "bandwidth_limit": new_limit,
        "max_bandwidth_limit": max_limit,
        "has_fastdownload_role": is_fastdownload,
        "has_download_role": is_download
    }

@router.get("/stats")
async def get_users_stats(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
) -> Dict[str, List[Dict]]:
    """Get all users with their download statistics (admin only)."""
    try:
        users = db.query(User).order_by(User.total_download_mb.desc()).all()
        
        users_list = []
        for user in users:
            users_list.append({
                'user_id': user.user_id,
                'username': user.username or user.user_id,
                'total_download_mb': round(user.total_download_mb, 2),
                'total_download_number': user.total_download_number,
                'medias_upload': user.medias_upload or 0,
                'medias_validated': user.medias_validated or 0,
                'bandwidth_limit': user.bandwidth_limit,
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'last_login_ip': user.last_login_ip,
                'country': user.country,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'updated_at': user.updated_at.isoformat() if user.updated_at else None,
                'p2p_total_download_mb': round(user.p2p_total_download_mb, 2) if user.p2p_total_download_mb else 0,
                'p2p_total_upload_mb': round(user.p2p_total_upload_mb, 2) if user.p2p_total_upload_mb else 0
            })
        
        return {"users": users_list}
    except Exception as e:
        logger.error(f"Error getting users stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users statistics"
        )

@router.get("/tokens/stats")
async def get_tokens_stats(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
) -> Dict[str, List[Dict]]:
    """Get all tokens with their P2P statistics (admin only)."""
    try:
        tokens = db.query(ApiToken).order_by(ApiToken.id.asc()).all()
        
        tokens_list = []
        for token in tokens:
            # Get username from User table
            user = db.query(User).filter(User.user_id == token.user_id).first()
            username = user.username if user and user.username else token.user_id
            
            tokens_list.append({
                'token_id': token.id,
                'token_name': token.name,
                'username': username,
                'p2p_total_download_mb': round(token.p2p_total_download_mb, 2) if token.p2p_total_download_mb else 0,
                'p2p_total_upload_mb': round(token.p2p_total_upload_mb, 2) if token.p2p_total_upload_mb else 0
            })
        
        return {"tokens": tokens_list}
    except Exception as e:
        logger.error(f"Error getting tokens stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tokens statistics"
        )

