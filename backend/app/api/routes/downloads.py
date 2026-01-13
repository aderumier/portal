"""Download queue routes."""
from fastapi import APIRouter, Depends, HTTPException, status, Query, WebSocket, WebSocketDisconnect, Form, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse, ORJSONResponse
from starlette.requests import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import get_db, DownloadQueue, User
from app.services.download import DownloadService
from app.services.websocket_manager import get_websocket_manager
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.roles import require_download_role, require_admin_role
from app.api.routes.catalog import get_game_service
from app.config import settings
from typing import Optional
import logging
import json
import os
import asyncio
import time
from pathlib import Path
import tarfile
import io
import struct

logger = logging.getLogger(__name__)

router = APIRouter()

class AddToQueueRequest(BaseModel):
    game_id: str
    token_name: Optional[str] = None  # Token name to associate with the download
    catalog_type: Optional[str] = 'releases'  # 'wip' or 'releases' - determines which catalog to use and whether to include snapshot path

class RequestDownloadRequest(BaseModel):
    queue_type: Optional[str] = None  # 'fast', 'slow', or None for both
    service_id: Optional[str] = 'default'
    platform: Optional[str] = None  # 'windows' or 'linux'
    client_version: Optional[str] = None  # Download client version

class ProgressRequest(BaseModel):
    download_id: int
    bytes_transferred: int
    bytes_per_second: int
    client_version: Optional[str] = None  # Download client version

class MarkCompletedRequest(BaseModel):
    download_id: int
    client_version: Optional[str] = None  # Download client version
    log_content: Optional[str] = None  # Download task log content

class ArchiveDownloadRequest(BaseModel):
    download_id: int
    files: Optional[list[str]] = None  # List of relative paths to include (optional, if not provided includes all files)

class MarkErrorRequest(BaseModel):
    download_id: int
    error_message: str
    client_version: Optional[str] = None  # Download client version
    log_content: Optional[str] = None  # Download task log content

def get_download_service(db: Session = Depends(get_db)) -> DownloadService:
    """Get download service instance."""
    game_service = get_game_service()  # Use shared singleton instance
    return DownloadService(db, game_service)

async def discover_download_files(
    download_id: int,
    token_id: str,
    user_id: int,
    requested_files: Optional[set[str]],
    db: Session
) -> tuple[list[dict], str, str]:
    """Discover all files for a download.
    
    Returns:
        Tuple of (all_files_list, system, resolved_game_id)
    """
    download_service = DownloadService(db, get_game_service())
    
    # Get queue item
    queue_item = db.query(DownloadQueue).filter(
        DownloadQueue.id == download_id,
        DownloadQueue.user_id == user_id,
        DownloadQueue.token_id == token_id
    ).first()
    
    if not queue_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    # Check if download is paused
    db.refresh(queue_item)
    if queue_item.status == 'paused':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download is paused"
        )
    
    # Get platform from Redis
    platform = 'linux'
    try:
        ws_manager = get_websocket_manager()
        redis_client = await ws_manager._get_redis_client()
        if redis_client and token_id:
            redis_key = f"ws_client:{token_id}"
            conn_data = await redis_client.get(redis_key)
            if conn_data:
                conn_info = json.loads(conn_data)
                platform = conn_info.get('platform', 'linux')
    except Exception as e:
        logger.debug(f"Could not get platform from Redis: {e}")
    
    # Get system and resolved game_id
    catalog_version = queue_item.catalog_version
    catalog_type = 'releases' if catalog_version else 'wip'
    
    # Resolve unified ROM key
    resolved_game_id = queue_item.game_id
    system = ''  # Initialize system to avoid UnboundLocalError
    try:
        game = download_service.game_service.get_game_by_id(queue_item.game_id, catalog_type=catalog_type)
        if game:
            system = game.get('system', '')
            resolved_game_id = download_service._resolve_unified_rom_key(queue_item.game_id, system, platform, catalog_type)
        else:
            logger.warning(f"Game not found for game_id: {queue_item.game_id} (catalog_type: {catalog_type})")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found"
            )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.warning(f"Failed to resolve unified ROM key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve game path"
        )
    
    # Build base path
    if not settings.GAMES_PATH:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GAMES_PATH not configured"
        )
    
    base_path = os.path.join(settings.GAMES_PATH, system, resolved_game_id)
    
    # Get all files for this download
    all_files_list = []
    if os.path.isfile(base_path):
        from app.services.download import detect_and_parse_special_file
        parsed_info = detect_and_parse_special_file(base_path, system=system)
        
        if parsed_info and parsed_info.get('files'):
            # This is a special file (.m3u, .cue, .xbox360, .psvita, .psn, .m3u ps3)
            source_dir = os.path.dirname(base_path)
            parsed_files = parsed_info['files']
            source_file = parsed_info.get('source_file', '')
            
            # Handle different special file types
            if source_file.lower().endswith('.xbox360'):
                if parsed_files:
                    directory_name = parsed_files[0]
                    dir_full_path = os.path.normpath(os.path.join(source_dir, directory_name))
                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                        try:
                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                for root, dirs, files in os.walk(dir_full_path):
                                    for filename in files:
                                        file_full_path = os.path.join(root, filename)
                                        rel_path_from_dir = os.path.relpath(file_full_path, dir_full_path)
                                        rel_path = os.path.join(directory_name, rel_path_from_dir).replace('\\', '/')
                                        if requested_files is None or rel_path in requested_files:
                                            all_files_list.append({
                                                'source_path': file_full_path,
                                                'relative_path': rel_path,
                                                'size': os.path.getsize(file_full_path)
                                            })
                                xbox360_rel_path = os.path.relpath(base_path, source_dir).replace('\\', '/')
                                if requested_files is None or xbox360_rel_path in requested_files:
                                    all_files_list.append({
                                        'source_path': base_path,
                                        'relative_path': xbox360_rel_path,
                                        'size': os.path.getsize(base_path)
                                    })
                        except ValueError:
                            pass
            elif source_file.lower().endswith('.psvita'):
                if parsed_files:
                    directory_name = parsed_files[0]
                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'psvita', 'vita3k', 'ux0', 'app', directory_name)
                    dir_full_path = os.path.normpath(save_dir_path)
                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                        try:
                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                for root, dirs, files in os.walk(dir_full_path):
                                    for filename in files:
                                        file_full_path = os.path.join(root, filename)
                                        rel_path = os.path.relpath(file_full_path, dir_full_path).replace('\\', '/')
                                        if requested_files is None or rel_path in requested_files:
                                            all_files_list.append({
                                                'source_path': file_full_path,
                                                'relative_path': rel_path,
                                                'size': os.path.getsize(file_full_path)
                                            })
                                psvita_rel_path = os.path.relpath(base_path, source_dir).replace('\\', '/')
                                if requested_files is None or psvita_rel_path in requested_files:
                                    all_files_list.append({
                                        'source_path': base_path,
                                        'relative_path': psvita_rel_path,
                                        'size': os.path.getsize(base_path)
                                    })
                        except ValueError:
                            pass
            elif source_file.lower().endswith('.psn'):
                if parsed_files:
                    directory_name = parsed_files[0]
                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                    dir_full_path = os.path.normpath(save_dir_path)
                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                        try:
                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                for root, dirs, files in os.walk(dir_full_path):
                                    for filename in files:
                                        file_full_path = os.path.join(root, filename)
                                        rel_path = os.path.relpath(file_full_path, dir_full_path).replace('\\', '/')
                                        if requested_files is None or rel_path in requested_files:
                                            all_files_list.append({
                                                'source_path': file_full_path,
                                                'relative_path': rel_path,
                                                'size': os.path.getsize(file_full_path)
                                            })
                                psn_rel_path = os.path.relpath(base_path, source_dir).replace('\\', '/')
                                if requested_files is None or psn_rel_path in requested_files:
                                    all_files_list.append({
                                        'source_path': base_path,
                                        'relative_path': psn_rel_path,
                                        'size': os.path.getsize(base_path)
                                    })
                        except ValueError:
                            pass
            elif source_file.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                if parsed_files:
                    directory_name = parsed_files[0]
                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                    dir_full_path = os.path.normpath(save_dir_path)
                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                        try:
                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                for root, dirs, files in os.walk(dir_full_path):
                                    for filename in files:
                                        file_full_path = os.path.join(root, filename)
                                        rel_path = os.path.relpath(file_full_path, dir_full_path).replace('\\', '/')
                                        if requested_files is None or rel_path in requested_files:
                                            all_files_list.append({
                                                'source_path': file_full_path,
                                                'relative_path': rel_path,
                                                'size': os.path.getsize(file_full_path)
                                            })
                                m3u_rel_path = os.path.relpath(base_path, source_dir).replace('\\', '/')
                                if requested_files is None or m3u_rel_path in requested_files:
                                    all_files_list.append({
                                        'source_path': base_path,
                                        'relative_path': m3u_rel_path,
                                        'size': os.path.getsize(base_path)
                                    })
                        except ValueError:
                            pass
            else:
                # For .m3u and .cue files: files are relative to the source file's directory
                for rel_file in parsed_files:
                    file_full_path = os.path.normpath(os.path.join(source_dir, rel_file))
                    if os.path.exists(file_full_path) and os.path.isfile(file_full_path):
                        try:
                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(file_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                rel_path = rel_file.replace('\\', '/')
                                if requested_files is None or rel_path in requested_files:
                                    all_files_list.append({
                                        'source_path': file_full_path,
                                        'relative_path': rel_path,
                                        'size': os.path.getsize(file_full_path)
                                    })
                        except ValueError:
                            pass
                if source_file:
                    rel_path = os.path.relpath(base_path, source_dir).replace('\\', '/')
                    if requested_files is None or rel_path in requested_files:
                        all_files_list.append({
                            'source_path': base_path,
                            'relative_path': rel_path,
                            'size': os.path.getsize(base_path)
                        })
    elif os.path.isdir(base_path):
        # Regular directory
        for root, dirs, filenames in os.walk(base_path):
            for filename in filenames:
                file_full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_full_path, base_path).replace('\\', '/')
                if requested_files is None or rel_path in requested_files:
                    all_files_list.append({
                        'source_path': file_full_path,
                        'relative_path': rel_path,
                        'size': os.path.getsize(file_full_path)
                    })
    
    return all_files_list, system, resolved_game_id

async def stream_archive_via_websocket(
    websocket: WebSocket,
    download_id: int,
    token_id: str,
    user_id: int,
    requested_files: Optional[list[str]],
    db: Session
):
    """Stream archive files via WebSocket using binary format with bandwidth throttling.
    
    Binary format:
    - For each file:
      - 4 bytes (uint32 BE): path_length
      - N bytes: path (UTF-8)
      - 8 bytes (uint64 BE): file_size
      - M bytes: file_data
    - End marker: 4 zero bytes
    """
    import time
    
    try:
        # Send start message
        await websocket.send_json({
            "type": "archive_start",
            "download_id": download_id
        })
        
        # Get queue item for bandwidth allocation
        queue_item = db.query(DownloadQueue).filter(
            DownloadQueue.id == download_id,
            DownloadQueue.user_id == user_id,
            DownloadQueue.token_id == token_id
        ).first()
        
        if not queue_item:
            await websocket.send_json({
                "type": "archive_error",
                "download_id": download_id,
                "error": "Download not found"
            })
            return
        
        # Get allocated bandwidth for throttling
        allocated_bandwidth = 0
        bandwidth_manager = None
        
        if queue_item.status in ['downloading'] and queue_item.queue_type:
            from app.services.bandwidth import BandwidthManager
            bandwidth_manager = BandwidthManager(db)
            allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
            
            # Apply user's custom bandwidth limit if set
            from app.database import User
            db_user = db.query(User).filter(User.user_id == queue_item.user_id).first()
            if db_user and db_user.bandwidth_limit is not None and db_user.bandwidth_limit > 0:
                allocated_bandwidth = min(allocated_bandwidth, db_user.bandwidth_limit)
                logger.info(f"Applied user bandwidth limit: {db_user.bandwidth_limit} bytes/s, effective: {allocated_bandwidth} bytes/s")
            
            logger.info(f"Allocated bandwidth for WebSocket archive download: {allocated_bandwidth} bytes/s ({allocated_bandwidth / 125000:.2f} Mbits/s)")
        
        # Convert requested_files list to set for helper function
        requested_files_set = None
        if requested_files:
            requested_files_set = set(requested_files)
        
        # Discover files using helper function
        all_files_list, system, resolved_game_id = await discover_download_files(
            download_id, token_id, user_id, requested_files_set, db
        )
        
        if not all_files_list:
            await websocket.send_json({
                "type": "archive_error",
                "download_id": download_id,
                "error": "No files found to archive"
            })
            return
        
        # Throttling setup
        if allocated_bandwidth > 0:
            chunk_size = 64 * 1024  # 64KB chunks for throttling
            bytes_per_second = allocated_bandwidth
            seconds_per_chunk = chunk_size / bytes_per_second
            logger.info(f"Starting throttled WebSocket archive stream: chunk_size={chunk_size}, bytes_per_second={bytes_per_second}, seconds_per_chunk={seconds_per_chunk:.3f}s")
            
            chunk_count = 0
            total_bytes = 0
            start_time = time.time()
            last_chunk_time = start_time
            last_user_count_check = start_time
            user_count_check_interval = 2.0
            last_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
            pause_check_interval = 2.0
            last_pause_check = start_time
            bandwidth_changed = False
        else:
            chunk_size = 1024 * 1024  # 1MB chunks
            bytes_per_second = 0
            seconds_per_chunk = 0
            logger.info("WebSocket archive stream: no throttling (allocated_bandwidth is 0)")
        
        # Stream files in binary format with throttling
        for file_info in all_files_list:
            source_path = file_info['source_path']
            relative_path = file_info['relative_path']
            file_size = file_info['size']
            
            # Check if download is paused
            if allocated_bandwidth > 0:
                current_time = time.time()
                if current_time - last_pause_check >= pause_check_interval:
                    db.refresh(queue_item)
                    if queue_item.status == 'paused':
                        logger.info(f"Download {download_id} was paused during WebSocket archive streaming - stopping")
                        await websocket.send_json({
                            "type": "archive_error",
                            "download_id": download_id,
                            "error": "Download paused"
                        })
                        return
                    last_pause_check = current_time
            
            # Encode path as UTF-8
            path_bytes = relative_path.encode('utf-8')
            path_length = len(path_bytes)
            
            # Build header: path_length (4 bytes) + path + file_size (8 bytes)
            header = struct.pack('>I', path_length)  # 4 bytes, big-endian uint32
            header += path_bytes  # path as UTF-8
            header += struct.pack('>Q', file_size)  # 8 bytes, big-endian uint64
            
            # Send header with throttling if needed
            if allocated_bandwidth > 0:
                current_time = time.time()
                expected_time = last_chunk_time + (len(header) / bytes_per_second)
                if current_time < expected_time:
                    sleep_time = expected_time - current_time
                    if sleep_time > 0.5:
                        sleep_time = 0.5
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                await websocket.send_bytes(header)
                last_chunk_time = time.time()
                total_bytes += len(header)
            else:
                await websocket.send_bytes(header)
            
            # Stream file data in chunks with throttling
            with open(source_path, 'rb') as f:
                while True:
                    # Check if download is paused
                    if allocated_bandwidth > 0:
                        current_time = time.time()
                        if current_time - last_pause_check >= pause_check_interval:
                            db.refresh(queue_item)
                            if queue_item.status == 'paused':
                                logger.info(f"Download {download_id} was paused during WebSocket archive streaming - stopping")
                                await websocket.send_json({
                                    "type": "archive_error",
                                    "download_id": download_id,
                                    "error": "Download paused"
                                })
                                return
                            last_pause_check = current_time
                        
                        # Check for bandwidth changes
                        if current_time - last_user_count_check >= user_count_check_interval:
                            bandwidth_changed = False
                            current_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                            
                            # Recompute bandwidth allocation
                            new_allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                            
                            # Re-apply user's custom bandwidth limit
                            from app.database import SessionLocal
                            fresh_db = SessionLocal()
                            try:
                                # Use fresh session to get latest user bandwidth_limit
                                fresh_user = fresh_db.query(User).filter(User.user_id == queue_item.user_id).first()
                                if fresh_user and fresh_user.bandwidth_limit is not None and fresh_user.bandwidth_limit > 0:
                                    new_allocated_bandwidth = min(new_allocated_bandwidth, fresh_user.bandwidth_limit)
                            finally:
                                fresh_db.close()
                            
                            # Update bandwidth if changed
                            if new_allocated_bandwidth > 0 and new_allocated_bandwidth != bytes_per_second:
                                bandwidth_changed = True
                                old_bytes_per_second = bytes_per_second
                                bytes_per_second = new_allocated_bandwidth
                                old_seconds_per_chunk = seconds_per_chunk
                                seconds_per_chunk = chunk_size / bytes_per_second
                                
                                if current_active_user_count != last_active_user_count:
                                    logger.info(f"WebSocket archive stream: user count changed ({last_active_user_count} -> {current_active_user_count}), recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s")
                                else:
                                    logger.info(f"WebSocket archive stream: user bandwidth limit changed, recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s")
                                last_active_user_count = current_active_user_count
                            
                            last_user_count_check = current_time
                            
                            if bandwidth_changed:
                                last_chunk_time = time.time()
                    
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    # Apply throttling if needed
                    if allocated_bandwidth > 0:
                        current_time = time.time()
                        expected_time = last_chunk_time + seconds_per_chunk
                        
                        # Sleep to throttle
                        if current_time < expected_time:
                            sleep_time = expected_time - current_time
                            if sleep_time > 0.5:
                                sleep_time = 0.5
                            if sleep_time > 0:
                                await asyncio.sleep(sleep_time)
                        
                        await websocket.send_bytes(chunk)
                        last_chunk_time = time.time()
                        chunk_count += 1
                        total_bytes += len(chunk)
                        
                        # Log progress every 100 chunks
                        if chunk_count % 100 == 0:
                            elapsed_total = time.time() - start_time
                            current_rate = total_bytes / elapsed_total if elapsed_total > 0 else 0
                            logger.debug(f"WebSocket archive stream: {total_bytes} bytes ({chunk_count} chunks), rate: {current_rate / 125000:.2f} Mbits/s (target: {bytes_per_second / 125000:.2f} Mbits/s)")
                    else:
                        await websocket.send_bytes(chunk)
        
        # Send end marker (4 zero bytes) with throttling if needed
        end_marker = struct.pack('>I', 0)
        if allocated_bandwidth > 0:
            current_time = time.time()
            expected_time = last_chunk_time + (len(end_marker) / bytes_per_second)
            if current_time < expected_time:
                sleep_time = expected_time - current_time
                if sleep_time > 0.5:
                    sleep_time = 0.5
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        
        await websocket.send_bytes(end_marker)
        
        # Send completion message
        await websocket.send_json({
            "type": "archive_complete",
            "download_id": download_id
        })
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error streaming archive via WebSocket: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "archive_error",
                "download_id": download_id,
                "error": str(e)
            })
        except:
            pass
        raise

@router.get("/queue")
async def get_queue(
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service)
):
    """Get download queue for current user."""
    user_id = current_user['id']
    queue = download_service.get_queue(user_id)
    return queue

@router.get("/history")
async def get_download_history(
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get download history for current user."""
    user_id = current_user['id']
    history = download_service.get_user_download_history(user_id, limit)
    return {"history": history}

@router.get("/history/all")
async def get_all_download_history(
    current_user: dict = Depends(require_admin_role),
    download_service: DownloadService = Depends(get_download_service),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get download history for all users (admin only)."""
    history = download_service.get_all_download_history(limit)
    return {"history": history}

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
    
    # For Releases catalog, prepend snapshot directory path to game_id and get version
    catalog_type = request.catalog_type or 'releases'
    catalog_version = None
    original_game_id = game_id  # Store original for potential error messages
    
    if catalog_type == 'releases':
        # Get game to determine system and snapshot path
        game_service = get_game_service()
        game = game_service.get_game_by_id(game_id, catalog_type='releases')
        if not game:
            logger.warning(f"Game not found in Releases catalog: {game_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Game not found in Releases catalog: {game_id}"
            )
        system_id = game.get('system', '')
        if system_id:
            # Get version string from system_versions
            catalog_version = game_service.system_versions.get(system_id)
            snapshot_dir_path = game_service.system_snapshot_paths.get(system_id)
            if snapshot_dir_path:
                # Prepend snapshot path to game_id
                # game_id is like "game.zip" or "subdir/game.zip"
                # Result should be ".zfs/snapshot/v10.5/game.zip" or ".zfs/snapshot/v10.5/subdir/game.zip"
                # snapshot_dir_path already has the leading dot (e.g., ".zfs/snapshot/v10.5/")
                snapshot_path = snapshot_dir_path
                if not snapshot_path.endswith('/'):
                    snapshot_path += '/'
                game_id = f"{snapshot_path}{game_id}"
                logger.info(f"Prepended snapshot path to game_id: {game_id}, version: {catalog_version}")
            else:
                logger.warning(f"No snapshot path found for system {system_id} in Releases catalog")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"No snapshot path found for system {system_id}"
                )
        else:
            logger.warning(f"No system ID found for game: {game_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"No system ID found for game: {game_id}"
            )
    
    success = await download_service.add_to_queue(user_id, game_id, user_has_fastdownload, token_id=token_id, catalog_version=catalog_version)
    
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
    
    Returns configuration values like bandwidth update interval.
    """
    return {
        "bandwidth_update_interval": settings.BANDWIDTH_UPDATE_INTERVAL
    }

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket endpoint for download service notifications.
    
    Clients connect with their API token as a query parameter: ws://host/api/download/ws?token=TOKEN
    Server will send notifications when games are added to user_queue for the connected token_id.
    """
    await websocket.accept()
    
    # Get token, version, and platform from query parameters
    token = websocket.query_params.get("token")
    version = websocket.query_params.get("version", "unknown")
    platform = websocket.query_params.get("platform", "unknown")
    logger.debug(f"WebSocket connection attempt - token: {'present' if token else 'missing'}, version: {version}, platform: {platform}")
    
    if not token:
        logger.warning("WebSocket connection rejected: no token provided")
        await websocket.close(code=4001, reason="No token provided")
        return
    
    # Validate token and get token_id
    from app.services.token import ApiTokenService
    
    token_service = ApiTokenService(db)
    
    # Get client IP from X-Forwarded-For header if present (for proxies), otherwise use websocket.client.host
    # This matches the logic in get_client_ip() but adapted for WebSocket connections
    client_ip = "unknown"
    
    # Check X-Forwarded-For header (used by reverse proxies like nginx)
    # Format: "client, proxy1, proxy2" - we want the first (original client)
    forwarded_for = websocket.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        # Take the first IP if multiple are present
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        # Check X-Real-IP header (alternative proxy header)
        real_ip = websocket.headers.get("x-real-ip", "").strip()
        if real_ip:
            client_ip = real_ip
        elif websocket.client:
            # Fall back to direct connection IP
            client_ip = websocket.client.host
    
    try:
        # Extract token from Bearer format if present
        token_string = token  # Keep original for Redis tracking
        if token_string.startswith("Bearer "):
            token_string = token_string[7:]
        
        # Validate token
        token_info = await token_service.validate_token(token_string, client_ip)
        if not token_info:
            logger.warning(f"WebSocket connection rejected: invalid token from {client_ip}")
            await websocket.close(code=4001, reason="Invalid token")
            return
        
        token_id = token_info['token_id']
        user_id = token_info['user_id']
        
        # Get client version and platform from query params (already extracted above)
        client_version = version
        client_platform = platform
        
        logger.info(f"WebSocket connection authenticated: token_id={token_id}, user_id={user_id}, IP={client_ip}, version={client_version}, platform={client_platform}")
        
        # Register connection with WebSocket manager (pass token_string and platform for Redis tracking)
        ws_manager = get_websocket_manager()
        accepted, reason = await ws_manager.add_connection(token_id, websocket, ip=client_ip, client_version=client_version, token_string=token_string, platform=client_platform)
        
        if not accepted:
            logger.warning(f"Connection rejected for token_id {token_id} from {client_ip}: {reason}")
            await websocket.close(code=4002, reason=reason)
            return
        
        logger.debug(f"Connection registered in WebSocket manager for token_id {token_id}")
        
        # Check for available downloads and notify client
        download_service = get_download_service(db)
        available_downloads = download_service.check_available_downloads(token_id=token_id)
        logger.debug(f"Checked available downloads for token_id {token_id}: {available_downloads}")
        
        # Send welcome message with download status
        try:
            await websocket.send_json({
                "type": "connected",
                "token_id": token_id,
                "message": "WebSocket connection established",
                "has_downloads": available_downloads.get('has_any', False),
                "has_user_queue": available_downloads.get('has_user_queue', False),
                "has_resumable": available_downloads.get('has_resumable', False)
            })
            logger.debug(f"Sent 'connected' message to token_id {token_id}")
        except Exception as e:
            logger.error(f"Error sending 'connected' message to token_id {token_id}: {e}", exc_info=True)
            raise  # Re-raise to close connection
        
        # If there are downloads available, send notification(s)
        if available_downloads.get('has_any', False):
            try:
                # Check which queue types have downloads in user_queue
                from app.database import DownloadQueue
                user_queue_items = db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'user_queue',
                    DownloadQueue.token_id == token_id
                ).all()
                
                # Send notification for each unique queue_type
                queue_types_notified = set()
                for item in user_queue_items:
                    if item.queue_type not in queue_types_notified:
                        await ws_manager.send_notification(token_id, {
                            "type": "download_available",
                            "queue_type": item.queue_type
                        })
                        queue_types_notified.add(item.queue_type)
                        logger.info(f"Sent initial download notification for token_id {token_id}, queue_type={item.queue_type}")
                
                # If there are resumable downloads, also send a notification
                if available_downloads.get('has_resumable', False):
                    # Check what queue_type the resumable downloads are
                    resumable_items = db.query(DownloadQueue).filter(
                        DownloadQueue.status == 'downloading',
                        DownloadQueue.active_download == True,
                        DownloadQueue.token_id == token_id,
                        DownloadQueue.status != 'paused'
                    ).all()
                    
                    for item in resumable_items:
                        if item.queue_type not in queue_types_notified:
                            await ws_manager.send_notification(token_id, {
                                "type": "download_available",
                                "queue_type": item.queue_type
                            })
                            queue_types_notified.add(item.queue_type)
                            logger.info(f"Sent resumable download notification for token_id {token_id}, queue_type={item.queue_type}")
            except Exception as e:
                logger.error(f"Error sending initial download notifications: {e}", exc_info=True)
                # Don't fail the connection if notification sending fails
        
        # Keep connection alive with periodic ping and handle messages
        logger.debug(f"Entering message loop for token_id {token_id}")
        try:
            while True:
                # Wait for messages (client can send pings or close messages)
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    # Handle client messages if needed (e.g., ping/pong)
                    try:
                        message = json.loads(data)
                        if message.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                        elif message.get("type") == "pong":
                            # Client responded to our ping
                            logger.debug(f"Received pong from token_id {token_id}")
                        elif message.get("type") == "request_archive":
                            # Handle archive download request via WebSocket
                            download_id = message.get("download_id")
                            requested_files = message.get("files")  # Optional list of files
                            
                            if not download_id:
                                await websocket.send_json({
                                    "type": "archive_error",
                                    "error": "download_id required"
                                })
                                continue
                            
                            logger.info(f"Received archive request via WebSocket: download_id={download_id}, files={len(requested_files) if requested_files else 'all'}")
                            try:
                                # Stream archive via WebSocket
                                await stream_archive_via_websocket(
                                    websocket, download_id, token_id, user_id, 
                                    requested_files, db
                                )
                            except Exception as e:
                                logger.error(f"Error streaming archive via WebSocket: {e}", exc_info=True)
                                try:
                                    await websocket.send_json({
                                        "type": "archive_error",
                                        "download_id": download_id,
                                        "error": str(e)
                                    })
                                except:
                                    pass
                    except json.JSONDecodeError:
                        # Non-JSON message, ignore
                        pass
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    try:
                        await websocket.send_json({"type": "ping"})
                    except RuntimeError as e:
                        # Connection is closed
                        logger.debug(f"Connection closed while sending ping to token_id {token_id}: {e}")
                        break
                    except Exception as e:
                        logger.debug(f"Error sending ping to token_id {token_id}: {e}")
                        break
                        
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: token_id={token_id}")
        except RuntimeError as e:
            # Connection closed
            logger.info(f"WebSocket connection closed for token_id {token_id}: {e}")
        except Exception as e:
            logger.error(f"WebSocket error for token_id={token_id}: {e}", exc_info=True)
        finally:
            # Remove connection on disconnect (only if it's still this connection)
            # This prevents removing a new connection if this is the old one being replaced
            try:
                await ws_manager.remove_connection(token_id, websocket)
            except Exception as e:
                logger.debug(f"Error removing connection (may already be replaced): {e}")
            
    except Exception as e:
        logger.error(f"Error in WebSocket connection: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass

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
    Also returns current bandwidth_update_interval so the service can update its configuration.
    
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
    client_version = request.client_version
    download_info = download_service.get_next_download(queue_type, service_id, token_id=token_id, platform=platform, client_version=client_version)
    
    if not download_info:
        return {
            "download": None,
            "bandwidth_update_interval": settings.BANDWIDTH_UPDATE_INTERVAL
        }
    
    return {
        "download": download_info,
        "bandwidth_update_interval": settings.BANDWIDTH_UPDATE_INTERVAL
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
    
    client_version = request.client_version
    success = download_service.update_progress(download_id, bytes_transferred, bytes_per_second, client_version=client_version)
    
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
    log_content = request.log_content
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    # Store log if provided
    if log_content:
        download_service.store_download_log(download_id, log_content)
    
    success = await download_service.complete_download(download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    return {"success": True}

@router.post("/error")
async def mark_error(
    request: MarkErrorRequest,
    current_user: dict = Depends(require_auth_user),
    download_service: DownloadService = Depends(get_download_service)
):
    """Mark a download as error (used by download service)."""
    download_id = request.download_id
    error_message = request.error_message
    log_content = request.log_content
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    # Store log if provided
    if log_content:
        download_service.store_download_log(download_id, log_content)
    
    success = await download_service.mark_download_error(download_id, error_message)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    return {"success": True}

@router.get("/log/{download_id}")
async def get_download_log(
    download_id: int,
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Get download log for a specific download."""
    from app.database import DownloadArchive
    
    # Verify download belongs to current user or user is admin
    archive_item = db.query(DownloadArchive).filter(
        DownloadArchive.download_id == download_id
    ).first()
    
    if not archive_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    # Check if user owns this download or is admin
    user_id = current_user['id']
    is_admin = current_user.get('is_admin', False)
    
    if not is_admin and archive_item.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get log content
    log_content = download_service.get_download_log(download_id)
    
    if log_content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log file not found"
        )
    
    return {"log_content": log_content}

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
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Pause a download in the queue."""
    user_id = current_user['id']
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    # Get download to check token_id before pausing
    from app.database import DownloadQueue
    download = db.query(DownloadQueue).filter(DownloadQueue.id == download_id).first()
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be paused"
        )
    
    success = download_service.pause_download(user_id, download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be paused"
        )
    
    # Send WebSocket notification
    if download.token_id:
        ws_manager = get_websocket_manager()
        await ws_manager.send_notification(download.token_id, {
            "type": "download_paused",
            "download_id": download_id,
            "queue_type": download.queue_type
        })
        logger.info(f"Sent pause notification for download {download_id} to token_id {download.token_id}")
    
    return {"success": True}

@router.post("/queue/{download_id}/resume")
async def resume_download(
    download_id: int,
    current_user: dict = Depends(require_download_role),
    download_service: DownloadService = Depends(get_download_service),
    db: Session = Depends(get_db)
):
    """Resume a paused download."""
    user_id = current_user['id']
    
    if download_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid download ID"
        )
    
    # Get download to check token_id before resuming
    from app.database import DownloadQueue
    download = db.query(DownloadQueue).filter(DownloadQueue.id == download_id).first()
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be resumed"
        )
    
    success = download_service.resume_download(user_id, download_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or cannot be resumed"
        )
    
    # Check if there's already an active download for this token_id
    # If so, don't send notification - the resumed download will be picked up when current download finishes
    from app.database import DownloadQueue
    has_active = db.query(DownloadQueue).filter(
        and_(
            DownloadQueue.token_id == download.token_id,
            DownloadQueue.active_download == True,
            DownloadQueue.status == 'downloading',
            DownloadQueue.id != download_id  # Exclude the download we just resumed
        )
    ).first()
    
    if not has_active:
        # No active downloads - send notification so client can request it immediately
        if download.token_id:
            ws_manager = get_websocket_manager()
            await ws_manager.send_notification(download.token_id, {
                "type": "download_available",
                "queue_type": download.queue_type
            })
            logger.info(f"Sent resume notification for download {download_id} to token_id {download.token_id} (no active downloads)")
    else:
        # Active download in progress - don't send notification
        # The resumed download will be picked up automatically when current download finishes
        logger.info(f"Resumed download {download_id} but not sending notification - active download {has_active.id} is in progress")
    
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
    
    # Get catalog_version from download queue item and derive catalog_type
    catalog_version = download.catalog_version
    catalog_type = 'releases' if catalog_version else 'wip'
    # Remove snapshot path prefix to get original game_id for lookup
    lookup_game_id = download.game_id
    if catalog_type == 'releases' and '.zfs/snapshot' in download.game_id:
        # Extract original game_id after snapshot path
        parts = download.game_id.split('.zfs/snapshot/', 1)
        if len(parts) > 1:
            after_snapshot = parts[1]
            if '/' in after_snapshot:
                lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
            else:
                lookup_game_id = after_snapshot
    
    # Get game details with original paths from gamelist.xml (not normalized for frontend)
    # normalize_paths=False ensures we get original paths as stored in catalog
    game = download_service.game_service.get_game_by_id(lookup_game_id, catalog_type=catalog_type, normalize_paths=False)
    
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    
    # Add download URLs for media fields while keeping original paths unchanged
    # This method handles adding download URLs based on catalog_version
    game = download_service._normalize_game_details_for_client(game, catalog_version)
    
    return game

@router.get("/file")
async def download_file(
    request: Request,
    download_id: Optional[int] = Query(None),  # Download ID from download_info (preferred)
    system: Optional[str] = Query(None),  # Optional, can be derived from download_id
    game_id: Optional[str] = Query(None),  # Optional, can be derived from download_id
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
        
        # Get download service for resolution
        download_service = DownloadService(db, get_game_service())
        
        # Get queue item - prefer download_id if provided (simpler and more reliable)
        queue_item = None
        if download_id:
            queue_item = db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id,
                DownloadQueue.user_id == user_id,
                DownloadQueue.token_id == token_id
            ).first()
            
            if queue_item:
                # Derive system and game_id from queue_item if not provided
                if not system or not game_id:
                    catalog_version = queue_item.catalog_version
                    catalog_type = 'releases' if catalog_version else 'wip'
                    lookup_game_id = queue_item.game_id
                    if catalog_type == 'releases' and '.zfs/snapshot' in queue_item.game_id:
                        parts = queue_item.game_id.split('.zfs/snapshot/', 1)
                        if len(parts) > 1:
                            after_snapshot = parts[1]
                            if '/' in after_snapshot:
                                lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                            else:
                                lookup_game_id = after_snapshot
                    
                    game = download_service.game_service.get_game_by_id(lookup_game_id, catalog_type=catalog_type)
                    if game:
                        if not system:
                            system = game.get('system', '')
                        if not game_id:
                            # Get platform from Redis for resolution
                            platform = None
                            try:
                                ws_manager = get_websocket_manager()
                                redis_client = await ws_manager._get_redis_client()
                                if redis_client and token_id:
                                    redis_key = f"ws_client:{token_id}"
                                    conn_data = await redis_client.get(redis_key)
                                    if conn_data:
                                        import json
                                        conn_info = json.loads(conn_data)
                                        platform = conn_info.get('platform', 'linux')
                            except Exception as e:
                                logger.debug(f"Could not get platform from Redis: {e}")
                            
                            if not platform:
                                platform = 'linux'
                            
                            # Resolve unified key if needed
                            resolved_game_id = download_service._resolve_unified_rom_key(
                                queue_item.game_id, system, platform, catalog_type
                            )
                            game_id = resolved_game_id
        
        # Fallback to game_id/system lookup if download_id not provided (legacy support)
        if not queue_item and game_id and system:
            from datetime import datetime, timezone, timedelta
            from sqlalchemy import and_, or_
            
            recent_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
            
            queue_item = db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.token_id == token_id,
                    DownloadQueue.game_id == game_id,
                    or_(
                        DownloadQueue.status.in_(['user_queue', 'downloading', 'paused']),
                        and_(
                            DownloadQueue.status == 'completed',
                            DownloadQueue.created_at >= recent_threshold
                        )
                    )
                )
            ).first()
        
        if not queue_item:
            logger.info(f"File download requested but queue item not found: download_id={download_id}, game_id={game_id}, system={system}")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Download was removed from queue"
            )
        
        # Get platform from Redis connection info (if available) - needed for unified key resolution
        platform = None
        try:
            ws_manager = get_websocket_manager()
            redis_client = await ws_manager._get_redis_client()
            if redis_client and token_id:
                redis_key = f"ws_client:{token_id}"
                conn_data = await redis_client.get(redis_key)
                if conn_data:
                    import json
                    conn_info = json.loads(conn_data)
                    platform = conn_info.get('platform', 'linux')  # Default to linux
                    logger.debug(f"Got platform from Redis connection info: {platform}")
        except Exception as e:
            logger.debug(f"Could not get platform from Redis: {e}")
        
        # If platform not found, default to linux
        if not platform:
            platform = 'linux'
        
        # Derive system from queue_item if not provided
        if not system:
            catalog_version = queue_item.catalog_version
            catalog_type = 'releases' if catalog_version else 'wip'
            lookup_game_id = queue_item.game_id
            if catalog_type == 'releases' and '.zfs/snapshot' in queue_item.game_id:
                parts = queue_item.game_id.split('.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    if '/' in after_snapshot:
                        lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        lookup_game_id = after_snapshot
            
            game = download_service.game_service.get_game_by_id(lookup_game_id, catalog_type=catalog_type)
            if game:
                system = game.get('system', '')
        
        if not queue_item:
            # Download was removed from queue - return 410 Gone to signal the download service to stop
            logger.info(f"File download requested for removed download: game_id={game_id}, system={system}, relative_path={relative_path}")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Download was removed from queue"
            )
        
        # Refresh the queue item to ensure we have the latest status
        db.refresh(queue_item)
        
        # Check if download is paused - reject the request immediately
        if queue_item.status == 'paused':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Download is paused"
            )
        
        # Get catalog_type from queue_item
        catalog_version = queue_item.catalog_version
        catalog_type = 'releases' if catalog_version else 'wip'
        
        # Resolve unified ROM key if needed
        # The queue_item.game_id might be unified (from add_to_queue) or already resolved (from get_next_download)
        # The request game_id might also be unified or resolved
        # Use queue_item.game_id as source of truth, but resolve if it's a unified key
        resolved_game_id = queue_item.game_id
        try:
            resolved_game_id = download_service._resolve_unified_rom_key(queue_item.game_id, system, platform, catalog_type)
            if resolved_game_id != queue_item.game_id:
                logger.info(f"Resolved unified ROM key in file endpoint: '{queue_item.game_id}' -> '{resolved_game_id}' (platform: {platform})")
        except Exception as e:
            logger.warning(f"Failed to resolve unified ROM key from queue: {e}, using queue game_id as-is")
            resolved_game_id = queue_item.game_id
        
        # Build base path using resolved game_id
        if not settings.GAMES_PATH:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="GAMES_PATH not configured"
            )
        
        # Check if this is a Releases catalog download and get snapshot path
        # The game_id path should already include snapshot prefix if from Releases catalog
        # But we need to determine catalog_type from the request or game data
        # For now, we'll check if game_id contains .zfs/snapshot pattern
        # TODO: Pass catalog_type as a parameter to this endpoint
        base_path = os.path.join(settings.GAMES_PATH, system, resolved_game_id)
        
        # If path contains .zfs/snapshot, it's from Releases catalog
        # The game_id should be in format: .zfs/snapshot/v10.5/game.zip
        # So base_path will be: GAMES_PATH/system/.zfs/snapshot/v10.5/game.zip
        
        # Check if this is a special file type that needs parsing (when relative_path is not provided)
        if relative_path is None and os.path.isfile(base_path):
            from app.services.download import detect_and_parse_special_file
            parsed_info = detect_and_parse_special_file(base_path, system=system)
            
            if parsed_info:
                # This is a special file type (.m3u, .cue, or .xbox360)
                source_dir = os.path.dirname(base_path)
                base_path_type = parsed_info['base_path_type']
                parsed_files = parsed_info['files']
                source_file = parsed_info['source_file']
                
                files_list = []
                
                if base_path_type == 'file':
                    # Check if this is a .xbox360 file (special handling for directory downloads)
                    if source_file.lower().endswith('.xbox360'):
                        # For .xbox360 files: parsed_files contains the directory name
                        # Build full path to the directory (relative to .xbox360 file's directory)
                        if parsed_files:
                            directory_name = parsed_files[0]
                            dir_full_path = os.path.normpath(os.path.join(source_dir, directory_name))
                            
                            # Verify the directory exists and is within the games directory
                            if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                # Ensure the directory is within the games directory (security check)
                                try:
                                    if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                        # Walk the directory and add all files
                                        # For .xbox360 files, relative paths should be relative to the .xbox360 file's directory
                                        # So we need to include the directory name in the path
                                        for root, dirs, files in os.walk(dir_full_path):
                                            for filename in files:
                                                file_full_path = os.path.join(root, filename)
                                                # Get relative path from the directory root
                                                rel_path_from_dir = os.path.relpath(file_full_path, dir_full_path)
                                                # Make it relative to the .xbox360 file's directory by prepending the directory name
                                                rel_path = os.path.join(directory_name, rel_path_from_dir)
                                                file_size = os.path.getsize(file_full_path)
                                                files_list.append({
                                                    'relative_path': rel_path.replace('\\', '/'),  # Normalize path separators
                                                    'size': file_size
                                                })
                                        
                                        # Include the .xbox360 file itself in the download
                                        # The .xbox360 file is a sibling of the directory, so it's relative to source_dir
                                        xbox360_rel_path = os.path.relpath(base_path, source_dir)
                                        xbox360_file_size = os.path.getsize(base_path)
                                        files_list.append({
                                            'relative_path': xbox360_rel_path.replace('\\', '/'),
                                            'size': xbox360_file_size
                                        })
                                    else:
                                        logger.warning(f"Directory {dir_full_path} is outside games directory, skipping")
                                except ValueError:
                                    logger.warning(f"Directory {dir_full_path} path validation failed, skipping")
                            else:
                                logger.warning(f"Directory listed in {source_file} does not exist: {dir_full_path}")
                    elif source_file.lower().endswith('.psvita'):
                        # For .psvita files: parsed_files contains the directory name
                        # Source directory is at {GAMES_PATH}/_saves_/psvita/vita3k/ux0/app/{directory_name}
                        if parsed_files:
                            directory_name = parsed_files[0]
                            # Build path to save directory (different from .xbox360 which uses relative paths)
                            save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'psvita', 'vita3k', 'ux0', 'app', directory_name)
                            dir_full_path = os.path.normpath(save_dir_path)
                            
                            # Verify the directory exists and is within the games directory
                            if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                # Ensure the directory is within the games directory (security check)
                                try:
                                    if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                        # Walk the directory and add all files
                                        # For .psvita files, relative paths should maintain the directory structure
                                        # Files will be placed relative to the base path, maintaining subdirectory structure
                                        for root, dirs, files in os.walk(dir_full_path):
                                            for filename in files:
                                                file_full_path = os.path.join(root, filename)
                                                # Get relative path from the save directory root
                                                rel_path_from_dir = os.path.relpath(file_full_path, dir_full_path)
                                                file_size = os.path.getsize(file_full_path)
                                                files_list.append({
                                                    'relative_path': rel_path_from_dir.replace('\\', '/'),  # Normalize path separators
                                                    'size': file_size
                                                })
                                        
                                        # Include the .psvita file itself in the download
                                        # The .psvita file should be saved to roms directory, not save directory
                                        # Get the normalized game path for roms directory (same logic as get_next_download)
                                        psvita_rel_path = os.path.relpath(base_path, source_dir)
                                        psvita_file_size = os.path.getsize(base_path)
                                        
                                        # Get normalized rom_path (without system prefix and snapshot path) for client destination
                                        # Use the same normalization method as get_next_download for consistency
                                        normalized_rom_path = download_service._remove_snapshot_path_from_game_id(resolved_game_id, catalog_version)
                                        # Remove system prefix if present (client will add it back with batocera_system)
                                        if normalized_rom_path.startswith(f"{system}/"):
                                            normalized_rom_path = normalized_rom_path[len(system) + 1:]
                                        
                                        # Get target system (batocera_system) from queue_item's download info or derive from game
                                        # This should match what's in download_info['batocera_system']
                                        target_system = system
                                        try:
                                            game = download_service.game_service.get_game_by_id(queue_item.game_id, catalog_type=catalog_type)
                                            if game:
                                                # Use the same logic as get_next_download to determine target_system
                                                game_system = game.get('system', '')
                                                if game_system:
                                                    target_system = game_system
                                        except Exception as e:
                                            logger.debug(f"Could not get game for target_system: {e}")
                                        
                                        # Include destination info: relative path for API calls, destination_rom_path for saving to roms
                                        files_list.append({
                                            'relative_path': psvita_rel_path.replace('\\', '/'),  # For API calls to download_file endpoint
                                            'size': psvita_file_size,
                                            'destination_rom_path': normalized_rom_path,  # Path relative to ROMS_PATH/system/ for saving
                                            'destination_system': target_system  # System name for destination path (batocera_system)
                                        })
                                    else:
                                        logger.warning(f"Directory {dir_full_path} is outside games directory, skipping")
                                except ValueError:
                                    logger.warning(f"Directory {dir_full_path} path validation failed, skipping")
                            else:
                                logger.warning(f"PS Vita save directory listed in {source_file} does not exist: {dir_full_path}")
                    elif source_file.lower().endswith('.psn'):
                        # For .psn files: parsed_files contains the directory name
                        # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                        if parsed_files:
                            directory_name = parsed_files[0]
                            # Build path to save directory
                            save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                            dir_full_path = os.path.normpath(save_dir_path)
                            
                            # Verify the directory exists and is within the games directory
                            if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                # Ensure the directory is within the games directory (security check)
                                try:
                                    if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                        # Walk the directory and add all files
                                        # For .psn files, relative paths should maintain the directory structure
                                        # Files will be placed relative to the base path, maintaining subdirectory structure
                                        for root, dirs, files in os.walk(dir_full_path):
                                            for filename in files:
                                                file_full_path = os.path.join(root, filename)
                                                # Get relative path from the save directory root
                                                rel_path_from_dir = os.path.relpath(file_full_path, dir_full_path)
                                                file_size = os.path.getsize(file_full_path)
                                                files_list.append({
                                                    'relative_path': rel_path_from_dir.replace('\\', '/'),  # Normalize path separators
                                                    'size': file_size
                                                })
                                        
                                        # Include the .psn file itself in the download
                                        # The .psn file should be saved to roms directory, not save directory
                                        # Get the normalized game path for roms directory (same logic as get_next_download)
                                        psn_rel_path = os.path.relpath(base_path, source_dir)
                                        psn_file_size = os.path.getsize(base_path)
                                        
                                        # Get normalized rom_path (without system prefix and snapshot path) for client destination
                                        # Use the same normalization method as get_next_download for consistency
                                        normalized_rom_path = download_service._remove_snapshot_path_from_game_id(resolved_game_id, catalog_version)
                                        # Remove system prefix if present (client will add it back with batocera_system)
                                        if normalized_rom_path.startswith(f"{system}/"):
                                            normalized_rom_path = normalized_rom_path[len(system) + 1:]
                                        
                                        # Get target system (batocera_system) from queue_item's download info or derive from game
                                        # This should match what's in download_info['batocera_system']
                                        target_system = system
                                        try:
                                            game = download_service.game_service.get_game_by_id(queue_item.game_id, catalog_type=catalog_type)
                                            if game:
                                                # Use the same logic as get_next_download to determine target_system
                                                game_system = game.get('system', '')
                                                if game_system:
                                                    target_system = game_system
                                        except Exception as e:
                                            logger.debug(f"Could not get game for target_system: {e}")
                                        
                                        # Include destination info: relative path for API calls, destination_rom_path for saving to roms
                                        files_list.append({
                                            'relative_path': psn_rel_path.replace('\\', '/'),  # For API calls to download_file endpoint
                                            'size': psn_file_size,
                                            'destination_rom_path': normalized_rom_path,  # Path relative to ROMS_PATH/system/ for saving
                                            'destination_system': target_system  # System name for destination path (batocera_system)
                                        })
                                    else:
                                        logger.warning(f"Directory {dir_full_path} is outside games directory, skipping")
                                except ValueError:
                                    logger.warning(f"Directory {dir_full_path} path validation failed, skipping")
                            else:
                                logger.warning(f"PS3 save directory listed in {source_file} does not exist: {dir_full_path}")
                    elif source_file.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                        # For PS3 .m3u files: parsed_files contains the directory name
                        # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                        if parsed_files:
                            directory_name = parsed_files[0]
                            # Build path to save directory (same as .psn)
                            save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                            dir_full_path = os.path.normpath(save_dir_path)
                            
                            # Verify the directory exists and is within the games directory
                            if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                # Ensure the directory is within the games directory (security check)
                                try:
                                    if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                        # Walk the directory and add all files
                                        # For PS3 .m3u files, relative paths should maintain the directory structure
                                        for root, dirs, files in os.walk(dir_full_path):
                                            for filename in files:
                                                file_full_path = os.path.join(root, filename)
                                                # Get relative path from the save directory root
                                                rel_path_from_dir = os.path.relpath(file_full_path, dir_full_path)
                                                file_size = os.path.getsize(file_full_path)
                                                files_list.append({
                                                    'relative_path': rel_path_from_dir.replace('\\', '/'),  # Normalize path separators
                                                    'size': file_size
                                                })
                                        
                                        # Include the .m3u file itself in the download
                                        # The .m3u file should be saved to roms directory, not save directory
                                        # Get the normalized game path for roms directory (same logic as get_next_download)
                                        m3u_rel_path = os.path.relpath(base_path, source_dir)
                                        m3u_file_size = os.path.getsize(base_path)
                                        
                                        # Get normalized rom_path (without system prefix and snapshot path) for client destination
                                        # Use the same normalization method as get_next_download for consistency
                                        normalized_rom_path = download_service._remove_snapshot_path_from_game_id(resolved_game_id, catalog_version)
                                        # Remove system prefix if present (client will add it back with batocera_system)
                                        if normalized_rom_path.startswith(f"{system}/"):
                                            normalized_rom_path = normalized_rom_path[len(system) + 1:]
                                        
                                        # Get target system (batocera_system) from queue_item's download info or derive from game
                                        # This should match what's in download_info['batocera_system']
                                        target_system = system
                                        try:
                                            game = download_service.game_service.get_game_by_id(queue_item.game_id, catalog_type=catalog_type)
                                            if game:
                                                # Use the same logic as get_next_download to determine target_system
                                                game_system = game.get('system', '')
                                                if game_system:
                                                    target_system = game_system
                                        except Exception as e:
                                            logger.debug(f"Could not get game for target_system: {e}")
                                        
                                        # Include destination info: relative path for API calls, destination_rom_path for saving to roms
                                        files_list.append({
                                            'relative_path': m3u_rel_path.replace('\\', '/'),  # For API calls to download_file endpoint
                                            'size': m3u_file_size,
                                            'destination_rom_path': normalized_rom_path,  # Path relative to ROMS_PATH/system/ for saving
                                            'destination_system': target_system  # System name for destination path (batocera_system)
                                        })
                                    else:
                                        logger.warning(f"Directory {dir_full_path} is outside games directory, skipping")
                                except ValueError:
                                    logger.warning(f"Directory {dir_full_path} path validation failed, skipping")
                            else:
                                logger.warning(f"PS3 save directory listed in {source_file} does not exist: {dir_full_path}")
                    else:
                        # For .m3u and .cue files: files are relative to the source file's directory
                        for rel_file in parsed_files:
                            # Build full path to the file
                            file_full_path = os.path.normpath(os.path.join(source_dir, rel_file))
                            
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
                                logger.warning(f"File listed in {source_file} does not exist: {file_full_path}")
                
                elif base_path_type == 'directory':
                    # Regular directory downloads (shouldn't happen with special files, but handle for completeness)
                    # This branch is for future use or fallback scenarios
                    pass
                
                return ORJSONResponse({
                    'is_directory': True,  # Generic flag for all multi-file downloads
                    'files': files_list,
                    'total_files': len(files_list),
                    'total_size': sum(f['size'] for f in files_list),
                    'base_path_type': base_path_type,  # Indicates how to interpret paths
                    'source_file': source_file  # Original file that was parsed (for logging)
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
            
            return ORJSONResponse({
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
            
            # Check if base_path is a special file type - if so, relative_path handling depends on base_path_type
            if os.path.isfile(base_path):
                from app.services.download import detect_and_parse_special_file
                parsed_info = detect_and_parse_special_file(base_path, system=system)
                
                if parsed_info:
                    if parsed_info['base_path_type'] == 'file':
                        source_file_name = parsed_info.get('source_file', '')
                        if source_file_name.lower().endswith('.xbox360'):
                            # For .xbox360 files: relative_path includes directory name and is relative to source file's directory
                            source_dir = os.path.dirname(base_path)
                            file_path = os.path.normpath(os.path.join(source_dir, relative_path))
                        elif source_file_name.lower().endswith('.psvita'):
                            # For .psvita files: parsed_files contains the directory name
                            # Source directory is at {GAMES_PATH}/_saves_/psvita/vita3k/ux0/app/{directory_name}
                            if parsed_info['files']:
                                directory_name = parsed_info['files'][0]
                                # Check if relative_path is the .psvita file itself (it will be just the filename)
                                # In that case, serve it from its original location (base_path), not from save directory
                                if relative_path == os.path.basename(base_path):
                                    # This is the .psvita file itself, serve from original location
                                    file_path = base_path
                                else:
                                    # This is a file from the save directory
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'psvita', 'vita3k', 'ux0', 'app', directory_name)
                                    file_path = os.path.normpath(os.path.join(save_dir_path, relative_path))
                            else:
                                # Fallback: treat as regular file
                                file_path = os.path.join(base_path, relative_path)
                        elif source_file_name.lower().endswith('.psn'):
                            # For .psn files: parsed_files contains the directory name
                            # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                            if parsed_info['files']:
                                directory_name = parsed_info['files'][0]
                                # Check if relative_path is the .psn file itself (it will be just the filename)
                                # In that case, serve it from its original location (base_path), not from save directory
                                if relative_path == os.path.basename(base_path):
                                    # This is the .psn file itself, serve from original location
                                    file_path = base_path
                                else:
                                    # This is a file from the save directory
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                                    file_path = os.path.normpath(os.path.join(save_dir_path, relative_path))
                            else:
                                # Fallback: treat as regular file
                                file_path = os.path.join(base_path, relative_path)
                        elif source_file_name.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                            # For PS3 .m3u files: parsed_files contains the directory name
                            # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                            if parsed_info['files']:
                                directory_name = parsed_info['files'][0]
                                # Check if relative_path is the .m3u file itself (it will be just the filename)
                                # In that case, serve it from its original location (base_path), not from save directory
                                if relative_path == os.path.basename(base_path):
                                    # This is the .m3u file itself, serve from original location
                                    file_path = base_path
                                else:
                                    # This is a file from the save directory
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                                    file_path = os.path.normpath(os.path.join(save_dir_path, relative_path))
                            else:
                                # Fallback: treat as regular file
                                file_path = os.path.join(base_path, relative_path)
                        else:
                            # For .m3u and .cue files: relative_path is relative to the source file's directory
                            source_dir = os.path.dirname(base_path)
                            file_path = os.path.normpath(os.path.join(source_dir, relative_path))
                    elif parsed_info['base_path_type'] == 'directory':
                        # For .xbox360 files: relative_path is relative to the referenced directory
                        source_dir = os.path.dirname(base_path)
                        directory_name = parsed_info['files'][0] if parsed_info['files'] else None
                        if directory_name:
                            dir_full_path = os.path.normpath(os.path.join(source_dir, directory_name))
                            file_path = os.path.normpath(os.path.join(dir_full_path, relative_path))
                        else:
                            # Fallback: treat as regular directory
                            file_path = os.path.join(base_path, relative_path)
                    else:
                        # Fallback: treat as regular file
                        file_path = os.path.join(base_path, relative_path)
                    
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
            
            if queue_item.status in ['downloading'] and queue_item.queue_type:
                # Get allocated bandwidth from the bandwidth manager
                from app.services.bandwidth import BandwidthManager
                bandwidth_manager = BandwidthManager(db)
                allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                
                # Apply user's custom bandwidth limit if set (capped at role-based limit)
                from app.database import User
                db_user = db.query(User).filter(User.user_id == queue_item.user_id).first()
                if db_user and db_user.bandwidth_limit is not None and db_user.bandwidth_limit > 0:
                    # Cap user's bandwidth_limit at the role-based limit
                    allocated_bandwidth = min(allocated_bandwidth, db_user.bandwidth_limit)
                    logger.info(f"Applied user bandwidth limit: {db_user.bandwidth_limit} bytes/s, effective: {allocated_bandwidth} bytes/s")
                
                logger.info(f"Allocated bandwidth for download: {allocated_bandwidth} bytes/s ({allocated_bandwidth / 125000:.2f} Mbits/s)")
            else:
                logger.warning(f"Not applying throttling: status={queue_item.status}, queue_type={queue_item.queue_type}")
            
            # If no bandwidth limit, use StreamingResponse without throttling (but with Range support)
            if allocated_bandwidth <= 0:
                logger.info("Using StreamingResponse (no throttling) - allocated_bandwidth is 0 or negative")
                async def generate_file():
                    """Generate file chunks without throttling."""
                    pause_check_interval = 2.0  # Check every 2 seconds for pause status
                    last_pause_check = time.time()
                    
                    with open(file_path, 'rb') as f:
                        if start_byte > 0:
                            f.seek(start_byte)
                        remaining = content_length
                        chunk_size = 1024 * 1024  # 1MB chunks
                        while remaining > 0:
                            # Check if download is paused
                            current_time = time.time()
                            if current_time - last_pause_check >= pause_check_interval:
                                # Refresh queue item from database to check status
                                db.refresh(queue_item)
                                if queue_item.status == 'paused':
                                    logger.info(f"Download {queue_item.id} was paused during streaming - stopping")
                                    return  # Stop streaming
                                last_pause_check = current_time
                            
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
                user_count_check_interval = 2.0  # Check every 2 seconds for user count changes and bandwidth limit updates
                last_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                pause_check_interval = 2.0  # Check every 2 seconds for pause status
                last_pause_check = start_time
                bandwidth_changed = False  # Track if bandwidth changed in current iteration
                
                with open(file_path, 'rb') as f:
                    # Seek to start position if Range request
                    if start_byte > 0:
                        f.seek(start_byte)
                    
                    remaining = content_length
                    while remaining > 0:
                        # Reset bandwidth_changed flag for this iteration
                        bandwidth_changed = False
                        
                        # Check if download is paused
                        current_time = time.time()
                        if current_time - last_pause_check >= pause_check_interval:
                            # Refresh queue item from database to check status
                            db.refresh(queue_item)
                            if queue_item.status == 'paused':
                                logger.info(f"Download {queue_item.id} was paused during streaming - stopping")
                                return  # Stop streaming
                            last_pause_check = current_time
                        
                        # Check if user count changed (users joined or left) or user's bandwidth_limit changed
                        if current_time - last_user_count_check >= user_count_check_interval:
                            current_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                            
                            # Recompute bandwidth allocation (may have changed due to user count)
                            new_allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                            
                            # Re-apply user's custom bandwidth limit if set (may have changed)
                            # Use a fresh database session to get the latest committed value
                            # This ensures we see changes made by other requests
                            from app.database import SessionLocal
                            fresh_db = SessionLocal()
                            try:
                                # Query with a fresh session to bypass any caching
                                fresh_user = fresh_db.query(User).filter(User.user_id == queue_item.user_id).first()
                                if fresh_user and fresh_user.bandwidth_limit is not None and fresh_user.bandwidth_limit > 0:
                                    old_allocated = new_allocated_bandwidth
                                    new_allocated_bandwidth = min(new_allocated_bandwidth, fresh_user.bandwidth_limit)
                                    if old_allocated != new_allocated_bandwidth:
                                        logger.info(f"User {queue_item.user_id} bandwidth_limit: {fresh_user.bandwidth_limit} bytes/s ({fresh_user.bandwidth_limit / 125000:.2f} Mbits/s), updated allocated bandwidth from {old_allocated} to {new_allocated_bandwidth} bytes/s")
                            finally:
                                fresh_db.close()
                            
                            # Update bandwidth if it changed (due to user count or user's limit change)
                            if new_allocated_bandwidth > 0 and new_allocated_bandwidth != bytes_per_second:
                                bandwidth_changed = True
                                old_bytes_per_second = bytes_per_second
                                bytes_per_second = new_allocated_bandwidth
                                old_seconds_per_chunk = seconds_per_chunk
                                seconds_per_chunk = chunk_size / bytes_per_second
                                
                                if current_active_user_count != last_active_user_count:
                                    logger.info(f"User count changed ({last_active_user_count} -> {current_active_user_count}), recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s ({bytes_per_second / 125000:.2f} Mbits/s), seconds_per_chunk: {old_seconds_per_chunk:.3f}s -> {seconds_per_chunk:.3f}s")
                                else:
                                    logger.info(f"User bandwidth limit changed, recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s ({bytes_per_second / 125000:.2f} Mbits/s), seconds_per_chunk: {old_seconds_per_chunk:.3f}s -> {seconds_per_chunk:.3f}s")
                                last_active_user_count = current_active_user_count
                            elif new_allocated_bandwidth <= 0:
                                logger.warning(f"Recomputed bandwidth is 0 or negative, keeping previous allocation")
                            else:
                                # Values are the same - bandwidth hasn't changed
                                logger.debug(f"Bandwidth check: new_allocated_bandwidth={new_allocated_bandwidth}, bytes_per_second={bytes_per_second} (unchanged)")
                            
                            last_user_count_check = current_time
                        
                        # Read chunk (don't exceed remaining bytes)
                        read_size = min(chunk_size, remaining)
                        chunk = f.read(read_size)
                        if not chunk:
                            break
                        
                        # Calculate when this chunk should be sent (based on current bandwidth limit)
                        current_time = time.time()
                        
                        # If bandwidth changed during the check, reset timing to apply new limit immediately
                        # This ensures the new bandwidth limit takes effect on this chunk
                        if bandwidth_changed:
                            logger.debug(f"Resetting last_chunk_time from {last_chunk_time} to {current_time} due to bandwidth change")
                            last_chunk_time = current_time
                        
                        expected_time = last_chunk_time + seconds_per_chunk
                        logger.debug(f"Chunk timing: current_time={current_time:.3f}, last_chunk_time={last_chunk_time:.3f}, seconds_per_chunk={seconds_per_chunk:.3f}, expected_time={expected_time:.3f}, bytes_per_second={bytes_per_second}")
                        
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

@router.post("/gamelist/upload")
async def upload_gamelist(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db)
):
    """Upload a tar.gz archive containing all gamelist.xml files.
    
    Stores the archive at: data/users_gamelist/<token_id>/gamelists.tar.gz
    """
    try:
        # Get token_id from request state (set by API token middleware)
        token_id = getattr(request.state, 'token_id', None)
        
        if token_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ID not found. API token authentication required."
            )
        
        # Validate file is tar.gz
        filename = file.filename or ''
        if not (filename.endswith('.tar.gz') or filename.endswith('.tgz')):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be a .tar.gz archive"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Validate it's a valid tar.gz file
        try:
            tar_buffer = io.BytesIO(file_content)
            with tarfile.open(fileobj=tar_buffer, mode='r:gz') as tar:
                # Just verify it can be opened, count files
                file_count = len(tar.getmembers())
            tar_buffer.seek(0)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tar.gz archive: {str(e)}"
            )
        
        # Check file size (max 100MB for archive)
        max_size = 100 * 1024 * 1024  # 100MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Archive size exceeds 100MB limit"
            )
        
        # Build destination path: data/users_gamelist/<token_id>/gamelists.tar.gz
        if not settings.USERS_GAMELIST_PATH:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="USERS_GAMELIST_PATH not configured"
            )
        
        # If path is relative, make it relative to project root
        # From backend/app/api/routes/downloads.py, go up 4 levels to reach project root
        if not os.path.isabs(settings.USERS_GAMELIST_PATH):
            project_root = Path(__file__).parent.parent.parent.parent
            dest_dir = project_root / settings.USERS_GAMELIST_PATH / str(token_id)
        else:
            dest_dir = Path(settings.USERS_GAMELIST_PATH) / str(token_id)
        
        # Ensure directory exists
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Write archive file
        dest_file = dest_dir / 'gamelists.tar.gz'
        with open(dest_file, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"Uploaded gamelist.tar.gz for token_id '{token_id}' ({file_count} files, {len(file_content)} bytes) to {dest_file}")
        
        return {
            "success": True,
            "message": f"Gamelist.tar.gz uploaded successfully ({file_count} files)",
            "path": str(dest_file),
            "file_count": file_count,
            "size_bytes": len(file_content)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading gamelist.tar.gz: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while uploading gamelist.tar.gz"
        )


@router.post("/file/archive")
async def download_files_as_binary(
    request: Request,
    body: ArchiveDownloadRequest,
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db)
):
    """Stream multiple files using a custom binary format.
    
    Binary format:
    - For each file:
      - 4 bytes (uint32 BE): path_length
      - N bytes: path (UTF-8 encoded)
      - 8 bytes (uint64 BE): file_size
      - M bytes: file_data (raw bytes)
    - End marker: 4 zero bytes (path_length = 0)
    
    If 'files' parameter is provided, only those files will be included.
    Otherwise, all files for the download will be included.
    """
    try:
        download_id = body.download_id
        requested_files_list = body.files
        
        # Get token_id from request state
        token_id = getattr(request.state, 'token_id', None)
        if token_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API token authentication required"
            )
        
        user_id = current_user['id']
        
        # Get list of files to include
        requested_files = None
        if requested_files_list:
            requested_files = set(requested_files_list)
        
        # Get queue item for bandwidth allocation
        queue_item = db.query(DownloadQueue).filter(
            DownloadQueue.id == download_id,
            DownloadQueue.user_id == user_id,
            DownloadQueue.token_id == token_id
        ).first()
        
        if not queue_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Download not found"
            )
        
        # Discover files using helper function
        all_files_list, system, resolved_game_id = await discover_download_files(
            download_id, token_id, user_id, requested_files, db
        )
        
        if not all_files_list:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No files found to archive"
            )
        
        # Get allocated bandwidth for throttling
        allocated_bandwidth = 0
        bandwidth_manager = None
        
        if queue_item.status in ['downloading'] and queue_item.queue_type:
            from app.services.bandwidth import BandwidthManager
            bandwidth_manager = BandwidthManager(db)
            allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
            
            # Apply user's custom bandwidth limit if set
            from app.database import User
            db_user = db.query(User).filter(User.user_id == queue_item.user_id).first()
            if db_user and db_user.bandwidth_limit is not None and db_user.bandwidth_limit > 0:
                allocated_bandwidth = min(allocated_bandwidth, db_user.bandwidth_limit)
                logger.info(f"Applied user bandwidth limit: {db_user.bandwidth_limit} bytes/s, effective: {allocated_bandwidth} bytes/s")
            
            logger.info(f"Allocated bandwidth for archive download: {allocated_bandwidth} bytes/s ({allocated_bandwidth / 125000:.2f} Mbits/s)")
        
        # Async generator to stream binary format
        async def generate_binary_stream():
            """Stream files in custom binary format with bandwidth throttling.
            
            Format per file:
            - 4 bytes (uint32 BE): path_length
            - N bytes: path (UTF-8)
            - 8 bytes (uint64 BE): file_size
            - M bytes: file_data
            End marker: 4 zero bytes
            """
            import time
            
            try:
                # Throttling setup
                if allocated_bandwidth > 0:
                    chunk_size = 64 * 1024  # 64KB chunks for throttling
                    bytes_per_second = allocated_bandwidth
                    seconds_per_chunk = chunk_size / bytes_per_second
                    logger.info(f"Starting throttled binary archive stream: chunk_size={chunk_size}, bytes_per_second={bytes_per_second}, seconds_per_chunk={seconds_per_chunk:.3f}s")
                    
                    chunk_count = 0
                    total_bytes = 0
                    start_time = time.time()
                    last_chunk_time = start_time
                    last_user_count_check = start_time
                    user_count_check_interval = 2.0
                    last_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type) if bandwidth_manager else 0
                    pause_check_interval = 2.0
                    last_pause_check = start_time
                    bandwidth_changed = False
                else:
                    # No throttling
                    chunk_size = 1024 * 1024  # 1MB chunks
                    bytes_per_second = 0
                    seconds_per_chunk = 0
                    chunk_count = 0
                    total_bytes = 0
                    start_time = time.time()
                    last_chunk_time = start_time
                    pause_check_interval = 2.0
                    last_pause_check = start_time
                    logger.info("Binary archive stream: no throttling (allocated_bandwidth is 0)")
                
                for file_info in all_files_list:
                    source_path = file_info['source_path']
                    relative_path = file_info['relative_path']
                    file_size = file_info['size']
                    
                    # Check if download is paused
                    if allocated_bandwidth > 0:
                        current_time = time.time()
                        if current_time - last_pause_check >= pause_check_interval:
                            db.refresh(queue_item)
                            if queue_item.status == 'paused':
                                logger.info(f"Download {download_id} was paused during archive streaming - stopping")
                                return
                            last_pause_check = current_time
                    
                    # Encode path as UTF-8
                    path_bytes = relative_path.encode('utf-8')
                    path_length = len(path_bytes)
                    
                    # Build header: path_length (4 bytes) + path + file_size (8 bytes)
                    header = struct.pack('>I', path_length)  # 4 bytes, big-endian uint32
                    header += path_bytes  # path as UTF-8
                    header += struct.pack('>Q', file_size)  # 8 bytes, big-endian uint64
                    
                    # Yield header (throttle if needed)
                    if allocated_bandwidth > 0:
                        # Throttle header sending
                        current_time = time.time()
                        expected_time = last_chunk_time + (len(header) / bytes_per_second)
                        if current_time < expected_time:
                            sleep_time = expected_time - current_time
                            if sleep_time > 0.5:
                                sleep_time = 0.5
                            if sleep_time > 0:
                                await asyncio.sleep(sleep_time)
                        yield header
                        last_chunk_time = time.time()
                        total_bytes += len(header)
                    else:
                        yield header
                    
                    # Stream file data in chunks with throttling
                    with open(source_path, 'rb') as f:
                        while True:
                            # Check if download is paused
                            if allocated_bandwidth > 0:
                                current_time = time.time()
                                if current_time - last_pause_check >= pause_check_interval:
                                    db.refresh(queue_item)
                                    if queue_item.status == 'paused':
                                        logger.info(f"Download {download_id} was paused during archive streaming - stopping")
                                        return
                                    last_pause_check = current_time
                                
                                # Check for bandwidth changes
                                if current_time - last_user_count_check >= user_count_check_interval:
                                    bandwidth_changed = False
                                    current_active_user_count = bandwidth_manager.get_active_user_count(queue_item.queue_type)
                                    
                                    # Recompute bandwidth allocation
                                    new_allocated_bandwidth = bandwidth_manager.allocate_bandwidth(queue_item.queue_type)
                                    
                                    # Re-apply user's custom bandwidth limit
                                    from app.database import SessionLocal, User
                                    fresh_db = SessionLocal()
                                    try:
                                        fresh_user = fresh_db.query(User).filter(User.user_id == queue_item.user_id).first()
                                        if fresh_user and fresh_user.bandwidth_limit is not None and fresh_user.bandwidth_limit > 0:
                                            new_allocated_bandwidth = min(new_allocated_bandwidth, fresh_user.bandwidth_limit)
                                    finally:
                                        fresh_db.close()
                                    
                                    # Update bandwidth if changed
                                    if new_allocated_bandwidth > 0 and new_allocated_bandwidth != bytes_per_second:
                                        bandwidth_changed = True
                                        old_bytes_per_second = bytes_per_second
                                        bytes_per_second = new_allocated_bandwidth
                                        old_seconds_per_chunk = seconds_per_chunk
                                        seconds_per_chunk = chunk_size / bytes_per_second
                                        
                                        if current_active_user_count != last_active_user_count:
                                            logger.info(f"Archive stream: user count changed ({last_active_user_count} -> {current_active_user_count}), recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s")
                                        else:
                                            logger.info(f"Archive stream: user bandwidth limit changed, recomputed bandwidth: {old_bytes_per_second} -> {bytes_per_second} bytes/s")
                                        last_active_user_count = current_active_user_count
                                    
                                    last_user_count_check = current_time
                                    
                                    if bandwidth_changed:
                                        last_chunk_time = time.time()
                            
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            
                            # Apply throttling if needed
                            if allocated_bandwidth > 0:
                                current_time = time.time()
                                expected_time = last_chunk_time + seconds_per_chunk
                                
                                # Sleep to throttle
                                if current_time < expected_time:
                                    sleep_time = expected_time - current_time
                                    if sleep_time > 0.5:
                                        sleep_time = 0.5
                                    if sleep_time > 0:
                                        await asyncio.sleep(sleep_time)
                                
                                yield chunk
                                last_chunk_time = time.time()
                                chunk_count += 1
                                total_bytes += len(chunk)
                                
                                # Log progress every 100 chunks
                                if chunk_count % 100 == 0:
                                    elapsed_total = time.time() - start_time
                                    current_rate = total_bytes / elapsed_total if elapsed_total > 0 else 0
                                    logger.debug(f"Archive stream: {total_bytes} bytes ({chunk_count} chunks), rate: {current_rate / 125000:.2f} Mbits/s (target: {bytes_per_second / 125000:.2f} Mbits/s)")
                            else:
                                yield chunk
                
                # End marker: 4 zero bytes
                end_marker = struct.pack('>I', 0)
                if allocated_bandwidth > 0:
                    # Throttle end marker
                    current_time = time.time()
                    expected_time = last_chunk_time + (len(end_marker) / bytes_per_second)
                    if current_time < expected_time:
                        sleep_time = expected_time - current_time
                        if sleep_time > 0.5:
                            sleep_time = 0.5
                        if sleep_time > 0:
                            await asyncio.sleep(sleep_time)
                
                yield end_marker
                    
            except Exception as e:
                logger.error(f"Error generating binary stream: {e}", exc_info=True)
                raise
        
        return StreamingResponse(
            generate_binary_stream(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="download_{download_id}.bin"',
                "Content-Type": "application/octet-stream"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in download_files_as_binary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating binary archive: {str(e)}"
        )


@router.get("/clients/connected")
async def get_connected_clients(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Get all connected WebSocket clients (admin only)."""
    ws_manager = get_websocket_manager()
    connections = await ws_manager.get_all_connections()
    
    # Enrich with token and user info
    from app.database import ApiToken, User
    
    enriched_connections = []
    for conn in connections:
        token_id = conn.get("token_id")
        if token_id:
            # Get token info
            token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
            if token:
                user = db.query(User).filter(User.user_id == token.user_id).first()
                enriched_connections.append({
                    "token_id": token_id,
                    "token_string": conn.get("token_string", "unknown"),
                    "token_name": token.name,
                    "username": user.username if user else token.user_id,
                    "user_id": token.user_id,
                    "ip": conn.get("ip", "unknown"),
                    "client_version": conn.get("client_version", "unknown"),
                    "platform": conn.get("platform", "unknown"),
                    "connected_at": conn.get("connected_at")
                })
    
    return {"connections": enriched_connections, "count": len(enriched_connections)}

@router.get("/devices")
async def get_connected_devices(
    current_user: dict = Depends(require_download_role),
    db: Session = Depends(get_db)
):
    """Get all non-revoked tokens with their connection status for the current user."""
    user_id = current_user['id']
    
    # Get all non-revoked tokens for the user
    from app.database import ApiToken
    tokens = db.query(ApiToken).filter(
        and_(
            ApiToken.user_id == user_id,
            ApiToken.revoked == False
        )
    ).order_by(ApiToken.created_at.desc()).all()
    
    # Get connected clients from WebSocket manager
    ws_manager = get_websocket_manager()
    connected_clients = await ws_manager.get_all_connections()
    
    # Create a set of connected token_ids for quick lookup
    connected_token_ids = set()
    for conn in connected_clients:
        token_id = conn.get("token_id")
        if token_id:
            try:
                connected_token_ids.add(int(token_id))
            except (ValueError, TypeError):
                pass  # Skip invalid token_ids
    
    # Build device list
    devices = []
    for token in tokens:
        is_connected = token.id in connected_token_ids
        # Get connection info if connected
        connection_info = None
        if is_connected:
            conn = next((c for c in connected_clients if c.get("token_id") and int(c.get("token_id")) == token.id), None)
            if conn:
                connection_info = {
                    "ip": conn.get("ip", "unknown"),
                    "client_version": conn.get("client_version", "unknown"),
                    "platform": conn.get("platform", "unknown"),
                    "connected_at": conn.get("connected_at")
                }
        
        devices.append({
            "token_id": token.id,
            "token_name": token.name,
            "is_connected": is_connected,
            "connection_info": connection_info,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None
        })
    
    return {"devices": devices}

