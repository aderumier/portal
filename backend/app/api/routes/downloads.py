"""Download queue routes."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.requests import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db, DownloadQueue
from app.services.download import DownloadService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.roles import require_download_role, require_admin_role
from app.api.routes.catalog import get_game_service
from app.config import settings
from typing import Optional
import logging
import os
import asyncio
from pathlib import Path

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
    platform: Optional[str] = None  # 'windows' or 'linux'

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

@router.get("/config")
async def get_download_config(
    current_user: dict = Depends(require_auth_user)
):
    """Get download service configuration (for download_service.py).
    
    Returns configuration values like polling interval.
    """
    return {
        "polling_interval": settings.POLLING_INTERVAL,
        "bandwidth_update_interval": settings.BANDWIDTH_UPDATE_INTERVAL
    }

@router.post("/request")
async def request_download(
    request: RequestDownloadRequest,
    http_request: Request,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Request next available download (for download_service.py).
    
    Only returns downloads associated with the authenticated token.
    Also returns current polling_interval so the service can update its configuration.
    
    If queue_type is not specified, searches all queues (fast and slow) for downloads
    associated with the token_id and returns the first available download.
    """
    queue_type = request.queue_type
    service_id = request.service_id or 'default'
    platform = request.platform  # 'windows' or 'linux'
    
    # Get token_id from request state (set by API token middleware)
    token_id = getattr(http_request.state, 'token_id', None)
    
    if token_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token ID not found. API token authentication required."
        )
    
    # If queue_type is not specified, search all queues for downloads with this token_id
    # The backend will search both fast and slow queues and return the first available download
    download_info = download_service.get_next_download(queue_type, service_id, token_id=token_id, platform=platform)
    
    if not download_info:
        return {
            "download": None,
            "polling_interval": settings.POLLING_INTERVAL
        }
    
    return {
        "download": download_info,
        "polling_interval": settings.POLLING_INTERVAL
    }

@router.post("/progress")
async def report_progress(
    request: ProgressRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
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
    
    # Use the same database session as the download_service to avoid session conflicts
    # Query using download_service's db session
    from app.database import DownloadQueue
    download = download_service.db.query(DownloadQueue).filter(DownloadQueue.id == download_id).first()
    
    if download and download.status == 'paused':
        logger.info(f"Progress report received for paused download {download_id} - returning pause signal")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download is paused"
        )
    
    # Check if download exists before updating progress
    if not download:
        # Download was removed from queue - return 410 Gone to signal the download service to stop
        logger.info(f"Progress report received for removed download {download_id} - returning 410 Gone")
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Download was removed from queue"
        )
    
    success = download_service.update_progress(download_id, bytes_transferred, bytes_per_second)
    
    if not success:
        # This shouldn't happen if download exists, but handle it gracefully
        logger.warning(f"Progress update failed for download {download_id}")
        return {"success": True}
    
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

@router.post("/remove")
async def remove_download(
    request: MarkCompletedRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Remove a download from queue without updating statistics (e.g., when file doesn't exist)."""
    download_id = request.download_id
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    success = download_service.remove_download(download_id)
    
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

@router.get("/game-details/{download_id}")
async def get_download_game_details(
    download_id: int,
    request: Request,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Get game details for a download. Only works if the game is in queue with the associated token."""
    # Get token_id from request state (set by API token middleware)
    token_id = getattr(request.state, 'token_id', None)
    
    if token_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token authentication required"
        )
    
    # Verify the download exists and is associated with this token
    from app.database import DownloadQueue
    download = db.query(DownloadQueue).filter(
        DownloadQueue.id == download_id,
        DownloadQueue.token_id == token_id
    ).first()
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or not associated with this token"
        )
    
    # Get game details
    game = download_service.game_service.get_game_by_id(download.game_id)
    
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    
    return game

@router.get("/file")
async def download_file(
    request: Request,
    system: str = Query(...),
    game_id: str = Query(...),
    relative_path: Optional[str] = Query(None),  # For directory downloads: relative path to file within directory
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db)
):
    """Download a game file. Requires authentication and the file must be in user's download queue.
    Supports HTTP Range requests for resume functionality.
    For directory downloads, use relative_path parameter to download individual files."""
    try:
        # Parse Range header if present
        range_header = request.headers.get('Range')
        start_byte = 0
        end_byte = None
        
        if range_header:
            # Parse Range header: "bytes=start-end" or "bytes=start-"
            import re
            match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start_byte = int(match.group(1))
                if match.group(2):
                    end_byte = int(match.group(2))
                logger.info(f"Range request: start={start_byte}, end={end_byte}")
        # Get token_id from request state (set by API token middleware)
        token_id = getattr(request.state, 'token_id', None) if request else None
        
        if token_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API token authentication required"
            )
        
        user_id = current_user['id']
        
        # Verify the file is in the user's download queue (or was recently completed)
        # Check for active downloads or recently completed (within last hour)
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import and_, or_
        
        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
        
        # Refresh the queue item from database to get latest status
        queue_item = db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.user_id == user_id,
                DownloadQueue.token_id == token_id,
                DownloadQueue.game_id == game_id,
                or_(
                    DownloadQueue.status.in_(['user_queue', 'pending', 'downloading', 'paused']),
                    and_(
                        DownloadQueue.status == 'completed',
                        DownloadQueue.created_at >= recent_threshold
                    )
                )
            )
        ).first()
        
        if not queue_item:
            # Also check if there's a download for this game (even if completed longer ago)
            # This allows download service to access files it's currently downloading
            queue_item = db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.token_id == token_id,
                    DownloadQueue.game_id == game_id,
                    DownloadQueue.status == 'downloading'
                )
            ).first()
        
        if not queue_item:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="File not found in your download queue or access denied"
            )
        
        # Refresh the queue item to ensure we have the latest status
        db.refresh(queue_item)
        
        # Build base path
        if not settings.GAMES_PATH:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="GAMES_PATH not configured"
            )
        
        base_path = os.path.join(settings.GAMES_PATH, system, game_id)
        
        # Check if this is a .m3u file (when relative_path is not provided)
        if relative_path is None and os.path.isfile(base_path) and base_path.lower().endswith('.m3u'):
            # .m3u file downloads - parse and return list of files to download
            from app.services.download import parse_m3u_file
            m3u_files = parse_m3u_file(base_path)
            
            # Get the directory containing the .m3u file
            m3u_dir = os.path.dirname(base_path)
            
            files_list = []
            for rel_file in m3u_files:
                # Build full path to the file
                file_full_path = os.path.normpath(os.path.join(m3u_dir, rel_file))
                
                # Verify the file exists and is within the games directory
                if os.path.exists(file_full_path) and os.path.isfile(file_full_path):
                    # Ensure the file is within the games directory (security check)
                    try:
                        if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(file_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                            file_size = os.path.getsize(file_full_path)
                            files_list.append({
                                'relative_path': rel_file.replace('\\', '/'),  # Normalize path separators
                                'size': file_size
                            })
                        else:
                            logger.warning(f"File {file_full_path} is outside games directory, skipping")
                    except ValueError:
                        logger.warning(f"File {file_full_path} path validation failed, skipping")
                else:
                    logger.warning(f"File listed in .m3u does not exist: {file_full_path}")
            
            from fastapi.responses import JSONResponse
            return JSONResponse({
                'is_m3u': True,
                'files': files_list,
                'total_files': len(files_list),
                'total_size': sum(f['size'] for f in files_list)
            })
        
        # Check if base_path is a directory first (when relative_path is not provided)
        if relative_path is None and os.path.isdir(base_path):
            # Directory downloads - return list of files to download
            # The download service will download each file individually
            files_list = []
            for root, dirs, files in os.walk(base_path):
                for filename in files:
                    file_full_path = os.path.join(root, filename)
                    # Get relative path from the directory root
                    rel_path = os.path.relpath(file_full_path, base_path)
                    file_size = os.path.getsize(file_full_path)
                    files_list.append({
                        'relative_path': rel_path.replace('\\', '/'),  # Normalize path separators
                        'size': file_size
                    })
            
            from fastapi.responses import JSONResponse
            return JSONResponse({
                'is_directory': True,
                'files': files_list,
                'total_files': len(files_list),
                'total_size': sum(f['size'] for f in files_list)
            })
        
        # If relative_path is provided, this is a file within a directory or .m3u file
        if relative_path:
            # Sanitize relative_path to prevent directory traversal
            relative_path = relative_path.lstrip('/').lstrip('\\')
            if '..' in relative_path or relative_path.startswith('/'):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid relative path"
                )
            
            # Check if base_path is a .m3u file - if so, relative_path is relative to the .m3u file's directory
            if os.path.isfile(base_path) and base_path.lower().endswith('.m3u'):
                # For .m3u files, relative_path is relative to the .m3u file's directory
                m3u_dir = os.path.dirname(base_path)
                file_path = os.path.normpath(os.path.join(m3u_dir, relative_path))
                # Ensure the file is within the games directory (security check)
                try:
                    if not os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(file_path)]) == os.path.abspath(settings.GAMES_PATH):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid relative path (outside games directory)"
                        )
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid relative path"
                    )
            else:
                # For directories, relative_path is relative to the directory
                file_path = os.path.join(base_path, relative_path)
                # Ensure the file is actually within the base_path (prevent directory traversal)
                try:
                    if not os.path.commonpath([os.path.abspath(base_path), os.path.abspath(file_path)]) == os.path.abspath(base_path):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid relative path (directory traversal detected)"
                        )
                except ValueError:
                    # Paths don't share a common base
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid relative path"
                    )
        else:
            file_path = base_path
        
        # Check if it's a file
        if os.path.isfile(file_path):
            # Single file download with server-side throttling
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="File not found"
                )
            
            # Get file size
            file_size = os.path.getsize(file_path)
            
            # Validate range request
            if range_header:
                if start_byte >= file_size:
                    raise HTTPException(
                        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                        detail=f"Range start ({start_byte}) exceeds file size ({file_size})"
                    )
                if end_byte is None:
                    end_byte = file_size - 1
                elif end_byte >= file_size:
                    end_byte = file_size - 1
                content_length = end_byte - start_byte + 1
            else:
                content_length = file_size
            
            # Get allocated bandwidth from queue item (if available)
            # Apply throttling for downloads in 'downloading' or 'pending' status
            allocated_bandwidth = 0
            logger.info(f"Queue item status: {queue_item.status}, queue_type: {queue_item.queue_type}")
            
            if queue_item.status in ['downloading', 'pending'] and queue_item.queue_type:
                # Get allocated bandwidth from the bandwidth manager
                from app.services.bandwidth import BandwidthManager
                bandwidth_manager = BandwidthManager(db)
                allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                logger.info(f"Allocated bandwidth for download: {allocated_bandwidth} bytes/s ({allocated_bandwidth / 125000:.2f} Mbits/s)")
            else:
                logger.warning(f"Not applying throttling: status={queue_item.status}, queue_type={queue_item.queue_type}")
            
            # If no bandwidth limit, use StreamingResponse without throttling (but with Range support)
            if allocated_bandwidth <= 0:
                logger.info("Using StreamingResponse (no throttling) - allocated_bandwidth is 0 or negative")
                async def generate_file():
                    """Generate file chunks without throttling."""
                    with open(file_path, 'rb') as f:
                        if start_byte > 0:
                            f.seek(start_byte)
                        remaining = content_length
                        chunk_size = 1024 * 1024  # 1MB chunks
                        while remaining > 0:
                            chunk = f.read(min(chunk_size, remaining))
                            if not chunk:
                                break
                            yield chunk
                            remaining -= len(chunk)
                
                headers = {
                    'Content-Length': str(content_length),
                    'Content-Disposition': f'attachment; filename="{os.path.basename(game_id)}"',
                    'Accept-Ranges': 'bytes'
                }
                
                if range_header:
                    headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
                    return StreamingResponse(
                        generate_file(),
                        media_type='application/octet-stream',
                        headers=headers,
                        status_code=206  # Partial Content
                    )
                else:
                    return StreamingResponse(
                        generate_file(),
                        media_type='application/octet-stream',
                        headers=headers
                    )
            
            # Create throttled streaming response with Range support
            async def generate_throttled_file():
                """Generate file chunks with bandwidth throttling and Range support."""
                import time
                chunk_size = 64 * 1024  # 64KB chunks
                bytes_per_second = allocated_bandwidth
                seconds_per_chunk = chunk_size / bytes_per_second
                logger.info(f"Starting throttled stream: chunk_size={chunk_size}, bytes_per_second={bytes_per_second}, seconds_per_chunk={seconds_per_chunk:.3f}s, start_byte={start_byte}")
                
                chunk_count = 0
                total_bytes = 0
                start_time = time.time()
                last_chunk_time = start_time
                last_user_count_check = start_time
                user_count_check_interval = 2.0  # Check every 2 seconds for user count changes
                last_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                
                with open(file_path, 'rb') as f:
                    # Seek to start position if Range request
                    if start_byte > 0:
                        f.seek(start_byte)
                    
                    remaining = content_length
                    while remaining > 0:
                        # Check if user count changed (users joined or left)
                        current_time = time.time()
                        if current_time - last_user_count_check >= user_count_check_interval:
                            current_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                            
                            # If user count changed, recompute bandwidth allocation
                            if current_active_user_count != last_active_user_count:
                                new_allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                                if new_allocated_bandwidth > 0:
                                    bytes_per_second = new_allocated_bandwidth
                                    seconds_per_chunk = chunk_size / bytes_per_second
                                    logger.info(f"User count changed ({last_active_user_count} -> {current_active_user_count}), recomputed bandwidth: {bytes_per_second} bytes/s ({bytes_per_second / 125000:.2f} Mbits/s), seconds_per_chunk={seconds_per_chunk:.3f}s")
                                    last_active_user_count = current_active_user_count
                                else:
                                    logger.warning(f"Recomputed bandwidth is 0 or negative, keeping previous allocation")
                            
                            last_user_count_check = current_time
                        
                        # Read chunk (don't exceed remaining bytes)
                        read_size = min(chunk_size, remaining)
                        chunk = f.read(read_size)
                        if not chunk:
                            break
                        
                        # Calculate when this chunk should be sent (based on current bandwidth limit)
                        current_time = time.time()
                        expected_time = last_chunk_time + seconds_per_chunk
                        
                        # If we're ahead of schedule, sleep to throttle
                        if current_time < expected_time:
                            sleep_time = expected_time - current_time
                            # Cap sleep to prevent very long sleeps (max 0.5s)
                            if sleep_time > 0.5:
                                sleep_time = 0.5
                            if sleep_time > 0:
                                await asyncio.sleep(sleep_time)
                        
                        # Yield the chunk
                        yield chunk
                        
                        # Update timing for next chunk
                        last_chunk_time = time.time()
                        chunk_count += 1
                        total_bytes += len(chunk)
                        remaining -= len(chunk)
                        
                        # Log progress every 100 chunks
                        if chunk_count % 100 == 0:
                            elapsed_total = time.time() - start_time
                            current_rate = total_bytes / elapsed_total if elapsed_total > 0 else 0
                            logger.debug(f"Streamed {total_bytes} bytes ({chunk_count} chunks), rate: {current_rate / 125000:.2f} Mbits/s (target: {bytes_per_second / 125000:.2f} Mbits/s)")
                
                logger.info(f"Completed throttled stream: {chunk_count} chunks, {total_bytes} bytes")
            
            headers = {
                'Content-Length': str(content_length),
                'Content-Disposition': f'attachment; filename="{os.path.basename(game_id)}"',
                'Accept-Ranges': 'bytes'
            }
            
            if range_header:
                headers['Content-Range'] = f'bytes {start_byte}-{end_byte}/{file_size}'
                return StreamingResponse(
                    generate_throttled_file(),
                    media_type='application/octet-stream',
                    headers=headers,
                    status_code=206  # Partial Content
                )
            else:
                return StreamingResponse(
                    generate_throttled_file(),
                    media_type='application/octet-stream',
                    headers=headers
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File or directory not found"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving download file: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while serving the file"
        )

@router.get("/queues/all")
async def get_all_queues(
    current_user: dict = Depends(require_admin_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Get all active downloads from all queues (admin only)."""
    queues = download_service.get_all_active_downloads()
    return queues

