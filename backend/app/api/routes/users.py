"""User management routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.token import ApiTokenService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
import logging

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

