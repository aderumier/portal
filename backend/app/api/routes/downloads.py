"""Download queue routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.download import DownloadService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.roles import require_download_role, require_admin_role
from app.api.routes.catalog import get_game_service
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class AddToQueueRequest(BaseModel):
    game_id: str
    token_name: Optional[str] = None  # Token name to associate with the download

class MarkCompletedRequest(BaseModel):
    download_id: int

class RequestDownloadRequest(BaseModel):
    queue_type: Optional[str] = None  # 'fast', 'slow', or None for both
    service_id: Optional[str] = 'default'

class ProgressRequest(BaseModel):
    download_id: int
    bytes_transferred: int
    bytes_per_second: int

def get_download_service(db: Session = Depends(get_db)) -> DownloadService:
    """Get download service instance."""
    game_service = get_game_service()  # Use shared singleton instance
    return DownloadService(db, game_service)

@router.get("/queue")
async def get_queue(
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Get download queue for current user."""
    user_id = current_user['id']
    queue = download_service.get_queue(user_id)
    return queue

@router.post("/queue")
async def add_to_queue(
    request: AddToQueueRequest,
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Add a game to the download queue."""
    user_id = current_user['id']
    game_id = request.game_id
    
    if not game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Game ID is required"
        )
    
    # Get token_id - always required
    from app.services.token import ApiTokenService
    token_service = ApiTokenService(db)
    user_tokens = token_service.get_user_tokens(user_id)
    active_tokens = [t for t in user_tokens if not t.get('revoked', False)]
    
    if len(active_tokens) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active API tokens found. Please create a token first."
        )
    elif len(active_tokens) == 1:
        # User has only one token, use it by default
        token_id = active_tokens[0]['id']
    else:
        # User has multiple tokens
        if not request.token_name:
            # Require token selection
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple tokens found. Please specify token_name",
                headers={"X-Requires-Token-Selection": "true", "X-Available-Tokens": str([t['name'] for t in active_tokens])}
            )
        
        # Find token by name
        matching_token = next((t for t in active_tokens if t['name'] == request.token_name), None)
        if not matching_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Token '{request.token_name}' not found or revoked"
            )
        token_id = matching_token['id']
    
    # Check if user has fastdownload role
    user_has_fastdownload = current_user.get('is_fastdownload', False)
    
    success = download_service.add_to_queue(user_id, game_id, user_has_fastdownload, token_id=token_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add game to queue (game may already be in queue, not found, or user already has active download)"
        )
    
    return {"success": True}

@router.delete("/queue/{game_id:path}")
async def remove_from_queue(
    game_id: str,
    current_user: dict = Depends(require_download_role),
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
    current_user: dict = Depends(require_download_role),
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

@router.post("/request")
async def request_download(
    request: RequestDownloadRequest,
    http_request: Request,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Request next available download (for download_service.py).
    
    Only returns downloads associated with the authenticated token.
    """
    queue_type = request.queue_type
    service_id = request.service_id or 'default'
    
    # Get token_id from request state (set by API token middleware)
    token_id = getattr(http_request.state, 'token_id', None)
    
    if token_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token ID not found. API token authentication required."
        )
    
    download_info = download_service.get_next_download(queue_type, service_id, token_id=token_id)
    
    if not download_info:
        return {"download": None}
    
    return {"download": download_info}

@router.post("/progress")
async def report_progress(
    request: ProgressRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Report download progress (for download_service.py)."""
    download_id = request.download_id
    bytes_transferred = request.bytes_transferred
    bytes_per_second = request.bytes_per_second
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    success = download_service.update_progress(download_id, bytes_transferred, bytes_per_second)
    
    if not success:
        # Download might already be completed/deleted - this is OK for final progress reports
        # Log as warning but don't raise error to avoid breaking the download service
        logger.warning(f"Progress update failed for download {download_id} - download may already be completed")
        return {"success": True, "warning": "Download not found (may already be completed)"}
    
    return {"success": True}

@router.post("/complete")
async def mark_completed(
    request: MarkCompletedRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Mark a download as completed (used by download service)."""
    download_id = request.download_id
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    success = download_service.complete_download(download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    return {"success": True}

@router.post("/queue/{download_id}/pause")
async def pause_download(
    download_id: int,
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Pause a download in the queue."""
    user_id = current_user['id']
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    success = download_service.pause_download(user_id, download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be paused"
        )
    
    return {"success": True}

@router.post("/queue/{download_id}/resume")
async def resume_download(
    download_id: int,
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Resume a paused download."""
    user_id = current_user['id']
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    success = download_service.resume_download(user_id, download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be resumed"
        )
    
    return {"success": True}

@router.get("/queues/all")
async def get_all_queues(
    current_user: dict = Depends(require_admin_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Get all active downloads from all queues (admin only)."""
    queues = download_service.get_all_active_downloads()
    return queues

