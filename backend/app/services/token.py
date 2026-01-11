"""API token service."""
import secrets
import logging
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import ApiToken

logger = logging.getLogger(__name__)

class ApiTokenService:
    """Service for managing API tokens."""
    
    def __init__(self, db: Session):
        self.db = db
    
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
        
        Args:
            token: The API token to validate
            client_ip: The IP address of the client making the request (optional, for logging)
            
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

