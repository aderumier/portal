"""User management routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db, User
from app.services.token import ApiTokenService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
from app.api.middleware.roles import require_admin_role
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

router = APIRouter()

class GenerateTokenRequest(BaseModel):
    name: str = "API Token"

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
    """Revoke an API token."""
    user_id = current_user['id']
    success = token_service.revoke_token(user_id, token_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or doesn't belong to user"
        )
    
    return {"success": True}

@router.get("/users/stats")
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
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'updated_at': user.updated_at.isoformat() if user.updated_at else None
            })
        
        return {"users": users_list}
    except Exception as e:
        logger.error(f"Error getting users stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users statistics"
        )

