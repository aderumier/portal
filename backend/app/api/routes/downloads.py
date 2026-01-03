"""Download queue routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.download import DownloadService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.creator import require_creator_role
from app.api.routes.catalog import get_game_service
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class AddToQueueRequest(BaseModel):
    game_id: str

class MarkCompletedRequest(BaseModel):
    game_id: str

def get_download_service(db: Session = Depends(get_db)) -> DownloadService:
    """Get download service instance."""
    game_service = get_game_service()  # Use shared singleton instance
    return DownloadService(db, game_service)

@router.get("/queue")
async def get_queue(
    current_user: dict = Depends(require_creator_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Get download queue for current user."""
    user_id = current_user['id']
    queue = download_service.get_queue(user_id)
    return queue

@router.post("/queue")
async def add_to_queue(
    request: AddToQueueRequest,
    current_user: dict = Depends(require_creator_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Add a game to the download queue."""
    user_id = current_user['id']
    game_id = request.game_id
    
    if not game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game ID is required"
        )
    
    success = download_service.add_to_queue(user_id, game_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add game to queue (game may already be in queue or not found)"
        )
    
    return {"success": True}

@router.delete("/queue/{game_id:path}")
async def remove_from_queue(
    game_id: str,
    current_user: dict = Depends(require_creator_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Remove a game from the download queue."""
    user_id = current_user['id']
    
    # URL decode the game ID (may be double-encoded)
    import urllib.parse
    game_id = urllib.parse.unquote(urllib.parse.unquote(game_id))
    
    success = download_service.remove_from_queue(user_id, game_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found in queue"
        )
    
    return {"success": True}

@router.delete("/queue")
async def clear_queue(
    current_user: dict = Depends(require_creator_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Clear the download queue for current user."""
    user_id = current_user['id']
    success = download_service.clear_queue(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear queue"
        )
    
    return {"success": True}

@router.post("/complete")
async def mark_completed(
    request: MarkCompletedRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Mark a game as completed in the queue (used by download service)."""
    user_id = current_user['id']
    game_id = request.game_id
    
    if not game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game ID is required"
        )
    
    success = download_service.remove_from_queue(user_id, game_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found in queue"
        )
    
    return {"success": True}

