"""API token service."""
import secrets
import logging
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import ApiToken
from app.services.discord import get_redis_cache_client

logger = logging.getLogger(__name__)

# Time window to check for multiple IPs (5 minutes in seconds)
IP_CHECK_WINDOW_SECONDS = 300  # 5 minutes

# Redis key prefix for token IP tracking
REDIS_TOKEN_IP_PREFIX = "token_ip:"

class ApiTokenService:
    """Service for managing API tokens."""
    
    def __init__(self, db: Session):
        self.db = db
        self._redis_client = None
    
    async def _get_redis_client(self):
        """Get Redis client for IP tracking."""
        if self._redis_client is None:
            self._redis_client = get_redis_cache_client()
        return self._redis_client
    
    async def _check_multiple_ips(self, token_id: int, current_ip: str) -> bool:
        """Check if multiple different IPs have used this token within the time window.
        
        Uses Redis Set to track IPs with automatic expiration via TTL.
        
        Returns:
            True if multiple IPs detected, False otherwise
        """
        redis_client = await self._get_redis_client()
        if not redis_client:
            # Redis not available - fall back to allowing (shouldn't happen in production)
            logger.warning("Redis not available for IP tracking, allowing token usage")
            return False
        
        redis_key = f"{REDIS_TOKEN_IP_PREFIX}{token_id}"
        
        try:
            # Add current IP to the set
            await redis_client.sadd(redis_key, current_ip)
            
            # Set TTL on the key (5 minutes) - this will auto-expire old entries
            await redis_client.expire(redis_key, IP_CHECK_WINDOW_SECONDS)
            
            # Get all IPs in the set (should include the one we just added)
            ip_addresses = await redis_client.smembers(redis_key)
            
            # Convert to set of strings (decode_responses=True means we get strings, but handle both cases)
            ip_set = {ip.decode('utf-8') if isinstance(ip, bytes) else ip for ip in ip_addresses}
            
            # If we have more than one distinct IP, it's a violation
            if len(ip_set) > 1:
                logger.warning(
                    f"Multiple IPs detected for token {token_id} within {IP_CHECK_WINDOW_SECONDS}s window: {ip_set}"
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking multiple IPs in Redis for token {token_id}: {e}")
            # On error, allow the request (fail open) but log the error
            return False
    
    async def _clear_token_ip_history(self, token_id: int):
        """Clear IP history for a token (e.g., when revoked)."""
        redis_client = await self._get_redis_client()
        if not redis_client:
            return
        
        redis_key = f"{REDIS_TOKEN_IP_PREFIX}{token_id}"
        
        try:
            await redis_client.delete(redis_key)
            logger.debug(f"Cleared IP history for token {token_id}")
        except Exception as e:
            logger.error(f"Error clearing IP history for token {token_id}: {e}")
    
    async def _revoke_token(self, token_id: int, reason: str):
        """Revoke a token and log the reason."""
        api_token = self.db.query(ApiToken).filter(
            ApiToken.id == token_id
        ).first()
        
        if api_token and not api_token.revoked:
            api_token.revoked = True
            self.db.commit()
            
            # Clear IP history from Redis
            await self._clear_token_ip_history(token_id)
            
            logger.warning(
                f"Token {token_id} (user: {api_token.user_id}) revoked automatically. "
                f"Reason: {reason}"
            )
    
    def generate_token(self, user_id: str, name: str) -> str:
        """Generate a new API token for a user."""
        # Generate a secure random token (64 characters)
        token = secrets.token_hex(32)
        
        # Insert the token into the database
        api_token = ApiToken(
            user_id=user_id,
            token=token,
            name=name,
            created_at=datetime.utcnow(),
            revoked=False
        )
        
        self.db.add(api_token)
        self.db.commit()
        
        logger.info(f"Generated API token for user: {user_id}, name: {name}")
        return token
    
    async def validate_token(self, token: str, client_ip: Optional[str] = None) -> Optional[Dict]:
        """Validate an API token and return user ID and token ID if valid.
        
        This method checks if multiple IPs are using the token within a 5-minute window.
        If so, the token is automatically revoked.
        
        Args:
            token: The API token to validate
            client_ip: The IP address of the client making the request
            
        Returns:
            Dict with user_id and token_id if valid, None otherwise
        """
        api_token = self.db.query(ApiToken).filter(
            and_(
                ApiToken.token == token,
                ApiToken.revoked == False
            )
        ).first()
        
        if not api_token:
            return None
        
        # If no IP provided, we can't check for multiple IPs, but still allow
        # (though this shouldn't happen in production)
        if not client_ip:
            logger.warning(f"Token validation without IP address for token {api_token.id}")
            api_token.last_used_at = datetime.utcnow()
            self.db.commit()
            return {
                'user_id': api_token.user_id,
                'token_id': api_token.id
            }
        
        # Check for multiple IPs in the time window
        has_multiple_ips = await self._check_multiple_ips(api_token.id, client_ip)
        if has_multiple_ips:
            # Multiple IPs detected - revoke the token
            await self._revoke_token(
                api_token.id,
                f"Multiple IPs detected within {IP_CHECK_WINDOW_SECONDS}s window. "
                f"Current IP: {client_ip}"
            )
            return None
        
        # Update last used timestamp
        api_token.last_used_at = datetime.utcnow()
        self.db.commit()
        
        return {
            'user_id': api_token.user_id,
            'token_id': api_token.id
        }
    
    def get_token_by_id(self, user_id: str, token_id: int) -> Optional[Dict]:
        """Get a token by its ID."""
        api_token = self.db.query(ApiToken).filter(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == user_id
            )
        ).first()
        
        if not api_token:
            return None
        
        return {
            'id': api_token.id,
            'user_id': api_token.user_id,
            'token': api_token.token,
            'name': api_token.name,
            'created_at': api_token.created_at.isoformat() if api_token.created_at else None,
            'last_used_at': api_token.last_used_at.isoformat() if api_token.last_used_at else None,
            'revoked': api_token.revoked
        }
    
    def get_user_tokens(self, user_id: str) -> List[Dict]:
        """Get all tokens for a user."""
        tokens = self.db.query(ApiToken).filter(
            ApiToken.user_id == user_id
        ).order_by(ApiToken.created_at.desc()).all()
        
        result = []
        for token in tokens:
            token_preview = f"{token.token[:8]}..." if len(token.token) > 8 else token.token
            result.append({
                'id': token.id,
                'name': token.name,
                'token': token.token,
                'token_preview': token_preview,
                'created_at': token.created_at.isoformat() if token.created_at else None,
                'last_used_at': token.last_used_at.isoformat() if token.last_used_at else None,
                'revoked': token.revoked
            })
        
        return result
    
    async def revoke_token(self, user_id: str, token_id: int) -> bool:
        """Revoke a token."""
        api_token = self.db.query(ApiToken).filter(
            and_(
                ApiToken.id == token_id,
                ApiToken.user_id == user_id
            )
        ).first()
        
        if not api_token:
            logger.warning(f"Token not found or doesn't belong to user: {token_id}, {user_id}")
            return False
        
        api_token.revoked = True
        self.db.commit()
        
        # Clear IP history from Redis
        await self._clear_token_ip_history(token_id)
        
        logger.info(f"Revoked API token: {token_id} for user: {user_id}")
        return True
    
    def extract_token_from_header(self, auth_header: str) -> Optional[str]:
        """Extract token from Authorization header."""
        if not auth_header:
            return None
        
        # Check for Bearer token format
        if auth_header.startswith('Bearer '):
            return auth_header[7:].strip()
        
        return None

