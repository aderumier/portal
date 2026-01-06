"""Download queue service."""
import logging
import os
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timezone
from app.database import DownloadQueue, System
from app.services.game import GameService
from app.services.bandwidth import BandwidthManager
from app.config import settings

logger = logging.getLogger(__name__)

class DownloadService:
    """Service for managing download queue."""
    
    def __init__(self, db: Session, game_service: GameService):
        self.db = db
        self.game_service = game_service
        self.bandwidth_manager = BandwidthManager(db)
    
    def add_to_queue(self, user_id: str, game_id: str, user_has_fastdownload: bool = False, token_id: Optional[int] = None) -> bool:
        """Add a game to the user's FIFO queue."""
        try:
            logger.info(f"Adding to user queue - Game ID: {game_id}, User ID: {user_id}")
            
            # Clean up the game path by removing ./ prefix
            game_id = game_id.lstrip('./')
            logger.info(f"Cleaned game ID: {game_id}")
            
            # Determine queue type based on user role (will be used when promoted to global queue)
            queue_type = 'fast' if user_has_fastdownload else 'slow'
            logger.info(f"Queue type determined: {queue_type}")
            
            # Check if game exists
            game = self.game_service.get_game_by_id(game_id)
            if not game:
                logger.warning(f"Game not found: {game_id}")
                return False
            
            logger.info(f"Game found, adding to user queue: {game['name']}")
            
            # Check if already in queue (any status)
            existing = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id,
                    DownloadQueue.status.in_(['user_queue', 'pending', 'downloading'])
                )
            ).first()
            
            if existing:
                logger.warning(f"Game already in queue: {game_id} (status: {existing.status})")
                return False
            
            # Get file size if possible (game_id is rompath, need to prepend system)
            # Handle both files and directories
            file_size = None
            if settings.GAMES_PATH:
                system = game.get('system', '')
                if system:
                    game_path = os.path.join(settings.GAMES_PATH, system, game_id)
                else:
                    game_path = os.path.join(settings.GAMES_PATH, game_id)
                if os.path.exists(game_path):
                    if os.path.isfile(game_path):
                        file_size = os.path.getsize(game_path)
                        logger.info(f"File size: {file_size} bytes")
                    elif os.path.isdir(game_path):
                        # Calculate total size of directory recursively
                        total_size = 0
                        for dirpath, dirnames, filenames in os.walk(game_path):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                if os.path.isfile(filepath):
                                    total_size += os.path.getsize(filepath)
                        file_size = total_size
                        logger.info(f"Directory size: {file_size} bytes ({len([f for r, d, files in os.walk(game_path) for f in files])} files)")
            
            # Add to user's FIFO queue (status: 'user_queue')
            queue_item = DownloadQueue(
                user_id=user_id,
                game_id=game_id,
                status='user_queue',  # User queue status
                queue_type=queue_type,  # Store queue type for when promoted
                file_size=file_size,
                token_id=token_id  # Associate with token if provided
            )
            
            self.db.add(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully added game to user queue: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding to download queue: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False
    
    def get_queue(self, user_id: str) -> List[Dict]:
        """Get download queue for a user (includes user_queue, pending, downloading). Completed downloads are removed from the queue."""
        try:
            from app.database import ApiToken
            
            # Filter out completed downloads - they should be deleted, but filter just in case
            queue_items = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.status != 'completed'  # Exclude completed downloads (they should be deleted)
                )
            ).order_by(DownloadQueue.created_at.asc()).all()  # FIFO: oldest first
            
            # Enrich queue items with game information
            enriched_items = []
            for item in queue_items:
                game = self.game_service.get_game_by_id(item.game_id)
                if game:
                    # Calculate progress for active downloads
                    progress_percent = 0
                    if item.status == 'downloading' and item.file_size and item.file_size > 0:
                        progress_percent = min(100, int((item.bytes_transferred / item.file_size) * 100))
                    
                    # Get token name if token_id exists
                    token_name = None
                    if item.token_id:
                        token = self.db.query(ApiToken).filter(
                            ApiToken.id == item.token_id
                        ).first()
                        if token:
                            token_name = token.name
                    
                    enriched_item = {
                        'id': item.id,
                        'user_id': item.user_id,
                        'game_id': item.game_id,
                        'status': item.status,
                        'queue_type': item.queue_type,
                        'created_at': item.created_at.isoformat() if item.created_at else None,
                        'started_at': item.started_at.isoformat() if item.started_at else None,
                        'game_name': game['name'],
                        'image': game.get('image', ''),
                        'system_name': self.game_service.get_system_name(game.get('system', '')),
                        'progress_percent': progress_percent,
                        'bytes_transferred': item.bytes_transferred,
                        'file_size': item.file_size,
                        'bandwidth_used': item.bandwidth_used,
                        'token_name': token_name,
                        'download_id': item.id  # Include download_id for pause/resume actions
                    }
                    enriched_items.append(enriched_item)
            
            return enriched_items
        except Exception as e:
            logger.error(f"Error getting download queue: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def get_all_active_downloads(self) -> Dict:
        """Get all active downloads from all queues (admin only)."""
        try:
            from app.database import User
            
            # Get all downloads with status 'user_queue', 'pending', or 'downloading'
            all_downloads = self.db.query(DownloadQueue).filter(
                DownloadQueue.status.in_(['user_queue', 'pending', 'downloading'])
            ).order_by(DownloadQueue.created_at.asc()).all()
            
            # Collect unique user IDs and fetch usernames from User table
            unique_user_ids = set(item.user_id for item in all_downloads)
            username_cache = {}
            
            if unique_user_ids:
                users = self.db.query(User).filter(User.user_id.in_(list(unique_user_ids))).all()
                for user in users:
                    username_cache[user.user_id] = user.username or user.user_id
            
            # Group by queue type
            fast_queue = []
            slow_queue = []
            
            for item in all_downloads:
                game = self.game_service.get_game_by_id(item.game_id)
                if not game:
                    continue
                
                # Calculate progress percentage
                progress_percent = 0
                if item.file_size and item.file_size > 0:
                    progress_percent = int((item.bytes_transferred / item.file_size) * 100)
                
                download_item = {
                    'id': item.id,
                    'user_id': item.user_id,
                    'username': username_cache.get(item.user_id, item.user_id),
                    'game_id': item.game_id,
                    'game_name': game.get('name', ''),
                    'system': game.get('system', ''),
                    'system_name': self.game_service.get_system_name(game.get('system', '')),
                    'image': game.get('image', ''),
                    'status': item.status,
                    'queue_type': item.queue_type,
                    'active_download': item.active_download,
                    'bytes_transferred': item.bytes_transferred,
                    'file_size': item.file_size,
                    'bandwidth_used': item.bandwidth_used,
                    'progress_percent': progress_percent,
                    'started_at': item.started_at.isoformat() if item.started_at else None,
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                    'assigned_to_service': item.assigned_to_service
                }
                
                if item.queue_type == 'fast':
                    fast_queue.append(download_item)
                else:
                    slow_queue.append(download_item)
            
            # Separate user_queue items from pending/downloading
            user_queue_fast = [d for d in fast_queue if d['status'] == 'user_queue']
            user_queue_slow = [d for d in slow_queue if d['status'] == 'user_queue']
            pending_fast = [d for d in fast_queue if d['status'] == 'pending']
            pending_slow = [d for d in slow_queue if d['status'] == 'pending']
            downloading_fast = [d for d in fast_queue if d['status'] == 'downloading']
            downloading_slow = [d for d in slow_queue if d['status'] == 'downloading']
            
            return {
                'fast_queue': fast_queue,
                'slow_queue': slow_queue,
                'user_queue_fast': user_queue_fast,
                'user_queue_slow': user_queue_slow,
                'pending_fast': pending_fast,
                'pending_slow': pending_slow,
                'downloading_fast': downloading_fast,
                'downloading_slow': downloading_slow,
                'total_active': len([d for d in all_downloads if d.active_download]),
                'total_pending': len([d for d in all_downloads if d.status == 'pending']),
                'total_user_queue': len([d for d in all_downloads if d.status == 'user_queue'])
            }
        except Exception as e:
            logger.error(f"Error getting all active downloads: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'fast_queue': [],
                'slow_queue': [],
                'user_queue_fast': [],
                'user_queue_slow': [],
                'pending_fast': [],
                'pending_slow': [],
                'downloading_fast': [],
                'downloading_slow': [],
                'total_active': 0,
                'total_pending': 0,
                'total_user_queue': 0
            }
    
    def remove_from_queue(self, user_id: str, game_id: str) -> bool:
        """Remove a game from the download queue."""
        try:
            logger.info(f"Removing from queue - Game ID: {game_id}, User ID: {user_id}")
            
            # Clean up the game ID
            game_id = game_id.lstrip('./')
            logger.info(f"Cleaned game ID: {game_id}")
            
            queue_item = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id
                )
            ).first()
            
            if not queue_item:
                logger.warning(f"Game not found in queue: {game_id}")
                return False
            
            # Archive the download before deletion (user cancelled)
            self.archive_download(queue_item.id, 'cancelled')
            
            self.db.delete(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully removed game from queue: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing game from queue: {e}")
            self.db.rollback()
            return False
    
    def clear_queue(self, user_id: str) -> bool:
        """Clear all games from the download queue for a user."""
        try:
            self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
            ).delete()
            self.db.commit()
            
            logger.info(f"Successfully cleared queue for user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            self.db.rollback()
            return False
    
    def pause_download(self, user_id: str, download_id: int) -> bool:
        """Pause a download (only if it's pending or downloading)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.id == download_id,
                    DownloadQueue.user_id == user_id
                )
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for user {user_id}")
                return False
            
            # Only allow pausing if status is pending or downloading
            if download.status not in ['pending', 'downloading']:
                logger.warning(f"Cannot pause download {download_id} with status {download.status}")
                return False
            
            # Set status to paused and clear active_download flag
            download.status = 'paused'
            download.active_download = False
            download.assigned_to_service = None  # Release service assignment
            
            # Release bandwidth
            if download.bandwidth_used > 0:
                self.bandwidth_manager.update_usage(download.queue_type, -download.bandwidth_used)
                download.bandwidth_used = 0
            
            self.db.commit()
            logger.info(f"Paused download {download_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error pausing download: {e}")
            self.db.rollback()
            return False
    
    def resume_download(self, user_id: str, download_id: int) -> bool:
        """Resume a paused download (change status back to pending)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.id == download_id,
                    DownloadQueue.user_id == user_id
                )
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for user {user_id}")
                return False
            
            # Only allow resuming if status is paused
            if download.status != 'paused':
                logger.warning(f"Cannot resume download {download_id} with status {download.status}")
                return False
            
            # Change status back to pending (will be picked up by download service)
            download.status = 'pending'
            download.active_download = False
            
            self.db.commit()
            logger.info(f"Resumed download {download_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            self.db.rollback()
            return False
    
    def enrich_queue_items(self, queue_items: List[Dict]) -> List[Dict]:
        """Enrich queue items with game metadata."""
        enriched = []
        for item in queue_items:
            game = self.game_service.get_game_by_id(item.get('game_id', ''))
            if game:
                enriched_item = item.copy()
                enriched_item['game_name'] = game['name']
                enriched_item['image'] = game.get('image', '').lstrip('/')
                enriched_item['system_name'] = self.game_service.get_system_name(game.get('system', ''))
                enriched.append(enriched_item)
            else:
                enriched.append(item)
        return enriched
    
    def _promote_user_queue_to_global(self, queue_type: Optional[str] = None, token_id: Optional[int] = None) -> bool:
        """Promote items from user queues to global queue (fast or slow) when users have no active downloads.
        
        This is called when the download service connects and requests a download.
        Games are moved from user_queue status to pending status, keeping their queue_type (fast/slow).
        Only promotes games associated with the specified token_id.
        """
        try:
            # Find items in user_queue for the specific token
            # Get all user_queue items ordered by created_at (FIFO)
            user_queue_query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'user_queue'
            )
            
            # Filter by token_id if provided (required for token-based downloads)
            if token_id is not None:
                user_queue_query = user_queue_query.filter(DownloadQueue.token_id == token_id)
            
            if queue_type:
                user_queue_query = user_queue_query.filter(DownloadQueue.queue_type == queue_type)
            
            user_queue_items = user_queue_query.order_by(DownloadQueue.created_at.asc()).all()
            
            if not user_queue_items:
                logger.debug(f"No items in user queue to promote (token_id: {token_id}, queue_type: {queue_type})")
                return False
            
            logger.info(f"Found {len(user_queue_items)} items in user queue for token {token_id}, checking for promotion...")
            
            promoted = False
            for item in user_queue_items:
                # Check if this user has any active downloads for this token
                has_active = self.db.query(DownloadQueue).filter(
                    and_(
                        DownloadQueue.user_id == item.user_id,
                        DownloadQueue.token_id == item.token_id,  # Same token
                        DownloadQueue.active_download == True,
                        DownloadQueue.status == 'downloading'
                    )
                ).first()
                
                if not has_active:
                    # Promote this item to global queue (pending status)
                    # The queue_type (fast/slow) is already set when added to user_queue
                    item.status = 'pending'
                    logger.info(f"Promoted user queue item {item.id} (user: {item.user_id}, token: {item.token_id}, game: {item.game_id}) from user_queue to global {item.queue_type} queue (pending)")
                    promoted = True
                    break  # Only promote one at a time
            
            if promoted:
                self.db.commit()
                logger.info("User queue promotion completed")
            else:
                logger.debug("No items could be promoted (all users have active downloads for this token)")
            
            return promoted
        except Exception as e:
            logger.error(f"Error promoting user queue items: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False
    
    def get_next_download(self, queue_type: Optional[str] = None, service_id: str = 'default', token_id: Optional[int] = None, platform: Optional[str] = None) -> Optional[Dict]:
        """Get next available download from queue, including resumable interrupted downloads.
        
        Only returns downloads associated with the specified token_id.
        
        If queue_type is None, searches both fast and slow queues for downloads with matching token_id.
        """
        try:
            # First, try to promote items from user queues to global queue for this token
            # When queue_type is None, promote from both queues
            if queue_type is None:
                self._promote_user_queue_to_global('fast', token_id=token_id)
                self._promote_user_queue_to_global('slow', token_id=token_id)
            else:
                self._promote_user_queue_to_global(queue_type, token_id=token_id)
            
            # Then, check for downloads that are marked as downloading but might be interrupted
            # (e.g., service crashed, network issue). Allow resuming if assigned to same service
            # or if no progress in last 5 minutes (configurable timeout)
            from datetime import timedelta
            timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
            
            # Check for resumable downloads (downloading status, same service or timed out)
            # Only for the authenticated token (exclude paused)
            resumable_query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'downloading',
                DownloadQueue.active_download == True,
                or_(
                    DownloadQueue.assigned_to_service == service_id,
                    DownloadQueue.started_at < timeout_threshold
                )
            ).filter(
                DownloadQueue.status != 'paused'  # Exclude paused downloads
            )
            
            if token_id is not None:
                resumable_query = resumable_query.filter(DownloadQueue.token_id == token_id)
            
            # Filter by queue_type if specified, otherwise search all queues
            if queue_type:
                resumable_query = resumable_query.filter(DownloadQueue.queue_type == queue_type)
            
            resumable_download = resumable_query.order_by(DownloadQueue.started_at.asc()).first()
            
            if resumable_download:
                logger.info(f"Found resumable download: {resumable_download.id} (bytes_transferred: {resumable_download.bytes_transferred})")
                # Update service assignment in case it changed
                resumable_download.assigned_to_service = service_id
                # Update last_progress_at to current time (download is being resumed)
                resumable_download.last_progress_at = datetime.now(timezone.utc)
                self.db.commit()
                
                # Get game info
                game = self.game_service.get_game_by_id(resumable_download.game_id)
                if not game:
                    logger.warning(f"Game not found: {resumable_download.game_id}")
                    # Archive and remove from queue since game doesn't exist
                    self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                # Build file path (game_id is rompath, need to prepend system)
                file_path = None
                if settings.GAMES_PATH:
                    system = game.get('system', '')
                    logger.info(f"Building file path for game_id={resumable_download.game_id}, system={system}")
                    if system:
                        file_path = os.path.join(settings.GAMES_PATH, system, resumable_download.game_id)
                        logger.info(f"File path with system: {file_path}")
                    else:
                        logger.error(f"System is empty for game_id={resumable_download.game_id}, cannot build file path")
                        # Archive and remove from queue since system is missing
                        self.archive_download(resumable_download.id, 'error')
                        self.db.delete(resumable_download)
                        self.db.commit()
                        return None
                
                # Verify file or directory exists before resuming download
                if not os.path.exists(file_path):
                    logger.error(f"File or directory does not exist: {file_path} for game_id={resumable_download.game_id}")
                    # Archive and remove from queue since file doesn't exist
                    self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    logger.info(f"Removed download {resumable_download.id} from queue - file not found")
                    return None
                
                # Calculate available bandwidth
                allocated_bandwidth = self.bandwidth_manager.allocate_bandwidth(resumable_download.queue_type)
                
                # Get system info from System table - use retrobat_system for Windows, batocera_system for Linux
                db_system = self.db.query(System).filter(System.id == system).first()
                if not db_system:
                    logger.error(f"System not found in database: {system}")
                    self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                # Determine which system prefix to use based on client platform
                is_windows = platform and platform.lower() == 'windows'
                if is_windows:
                    target_system = db_system.retrobat_system
                    system_type = 'retrobat_system'
                else:
                    target_system = db_system.batocera_system
                    system_type = 'batocera_system'
                
                if not target_system:
                    logger.error(f"{system_type} not set for system: {system}")
                    self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                logger.info(f"Using {system_type}='{target_system}' for client platform (service_id={service_id}, is_windows={is_windows})")
                
                # Construct HTTP URL for the file
                import urllib.parse
                clean_game_id = resumable_download.game_id.lstrip('./')
                encoded_game_id = urllib.parse.quote(clean_game_id, safe='/')
                encoded_system = urllib.parse.quote(system, safe='')
                # Use DOWNLOAD_FILE_URL if set, otherwise fall back to API_URL
                base_url = settings.DOWNLOAD_FILE_URL if settings.DOWNLOAD_FILE_URL else settings.API_URL
                http_url = f"{base_url}/api/download/file?system={encoded_system}&game_id={encoded_game_id}"
                
                download_info = {
                    'download_id': resumable_download.id,
                    'game_id': resumable_download.game_id,
                    'user_id': resumable_download.user_id,
                    'file_path': file_path,
                    'file_url': http_url,  # HTTP URL for downloading the file
                    'file_size': resumable_download.file_size,
                    'bytes_transferred': resumable_download.bytes_transferred,
                    'allocated_bandwidth': allocated_bandwidth,
                    'queue_type': resumable_download.queue_type,
                    'game_name': game.get('name', ''),
                    'system': game.get('system', ''),  # Include system for download service
                    'batocera_system': target_system,  # Include system prefix for destination path (batocera_system for Linux, retrobat_system for Windows)
                    'game_details': game  # Include full game details for media download
                }
                
                logger.info(f"Resuming download {resumable_download.id} from {resumable_download.bytes_transferred} bytes")
                return download_info
            
            # Build query for pending downloads (exclude paused)
            # Only for the authenticated token
            query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status.in_(['pending', 'downloading']),  # Include downloading that can be resumed
                DownloadQueue.active_download == False
            ).filter(
                DownloadQueue.status != 'paused'  # Exclude paused downloads
            )
            
            # Filter by token_id if specified (required for token-based downloads)
            if token_id is not None:
                query = query.filter(DownloadQueue.token_id == token_id)
            
            # Filter by queue_type if specified, otherwise search all queues
            if queue_type:
                query = query.filter(DownloadQueue.queue_type == queue_type)
            
            # Order by created_at (oldest first)
            pending_download = query.order_by(DownloadQueue.created_at.asc()).first()
            
            if not pending_download:
                logger.debug("No pending downloads available")
                return None
            
            # Check if we can allocate bandwidth for this queue
            allocated_bandwidth = self.bandwidth_manager.allocate_bandwidth(pending_download.queue_type)
            
            if allocated_bandwidth <= 0:
                logger.debug(f"No bandwidth available for {pending_download.queue_type} queue")
                return None
            
            # Check if user already has active download (double-check)
            if not self.bandwidth_manager.can_start_download(pending_download.queue_type, pending_download.user_id):
                logger.warning(f"User {pending_download.user_id} already has active download, skipping")
                return None
            
            # Get game info
            game = self.game_service.get_game_by_id(pending_download.game_id)
            if not game:
                logger.warning(f"Game not found: {pending_download.game_id}")
                # Archive and remove from queue since game doesn't exist
                self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            # Build file path (game_id is rompath, need to prepend system)
            file_path = None
            if settings.GAMES_PATH:
                system = game.get('system', '')
                logger.info(f"Building file path for game_id={pending_download.game_id}, system={system}")
                if system:
                    file_path = os.path.join(settings.GAMES_PATH, system, pending_download.game_id)
                    logger.info(f"File path with system: {file_path}")
                else:
                    logger.error(f"System is empty for game_id={pending_download.game_id}, cannot build file path")
                    # Archive and remove from queue since system is missing
                    self.archive_download(pending_download.id, 'error')
                    self.db.delete(pending_download)
                    self.db.commit()
                    return None
            
            # Verify file or directory exists before assigning download
            if not os.path.exists(file_path):
                logger.error(f"File or directory does not exist: {file_path} for game_id={pending_download.game_id}")
                # Archive and remove from queue since file doesn't exist
                self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                logger.info(f"Removed download {pending_download.id} from queue - file not found")
                return None
            
            # Mark as active
            pending_download.active_download = True
            pending_download.status = 'downloading'
            pending_download.started_at = datetime.now(timezone.utc)
            pending_download.last_progress_at = datetime.now(timezone.utc)  # Initialize progress tracking
            pending_download.assigned_to_service = service_id
            self.db.commit()
            
            # Get system info from System table - use retrobat_system for Windows, batocera_system for Linux
            db_system = self.db.query(System).filter(System.id == system).first()
            if not db_system:
                logger.error(f"System not found in database: {system}")
                self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            # Determine which system prefix to use based on client platform
            is_windows = platform and platform.lower() == 'windows'
            if is_windows:
                target_system = db_system.retrobat_system
                system_type = 'retrobat_system'
            else:
                target_system = db_system.batocera_system
                system_type = 'batocera_system'
            
            if not target_system:
                logger.error(f"{system_type} not set for system: {system}")
                self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            logger.info(f"Using {system_type}='{target_system}' for client platform (service_id={service_id}, is_windows={is_windows})")
            
            # Construct HTTP URL for the file
            import urllib.parse
            clean_game_id = pending_download.game_id.lstrip('./')
            encoded_game_id = urllib.parse.quote(clean_game_id, safe='/')
            encoded_system = urllib.parse.quote(system, safe='')
            # Use DOWNLOAD_FILE_URL if set, otherwise fall back to API_URL
            base_url = settings.DOWNLOAD_FILE_URL if settings.DOWNLOAD_FILE_URL else settings.API_URL
            http_url = f"{base_url}/api/download/file?system={encoded_system}&game_id={encoded_game_id}"
            
            download_info = {
                'download_id': pending_download.id,
                'game_id': pending_download.game_id,
                'user_id': pending_download.user_id,
                'file_path': file_path,
                'file_url': http_url,  # HTTP URL for downloading the file
                'file_size': pending_download.file_size,
                'bytes_transferred': pending_download.bytes_transferred or 0,
                'allocated_bandwidth': allocated_bandwidth,
                'queue_type': pending_download.queue_type,
                'game_name': game.get('name', ''),
                'system': game.get('system', ''),
                'batocera_system': target_system,  # Include system prefix for destination path (batocera_system for Linux, retrobat_system for Windows)
                'game_details': game  # Include full game details for media download
            }
            
            logger.info(f"Assigned download {pending_download.id} to service {service_id} with {allocated_bandwidth} bytes/s")
            return download_info
            
        except Exception as e:
            logger.error(f"Error getting next download: {e}")
            self.db.rollback()
            return None
    
    def update_progress(self, download_id: int, bytes_transferred: int, bytes_per_second: int) -> bool:
        """Update download progress."""
        try:
            # Query the download
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Log previous values for debugging
            old_bytes = download.bytes_transferred
            old_bandwidth = download.bandwidth_used
            
            # Update progress fields - always update even if values seem the same
            # This ensures SQLAlchemy tracks the change
            download.bytes_transferred = bytes_transferred
            download.bandwidth_used = bytes_per_second
            download.last_progress_at = datetime.now(timezone.utc)
            
            # If status is "stuck", change it back to "downloading" (client reconnected)
            if download.status == 'stuck':
                logger.info(f"Download {download_id} resumed after being stuck, changing status to downloading")
                download.status = 'downloading'
                download.active_download = True
            
            # Mark object as modified explicitly (though assignment should do this)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(download, "bytes_transferred")
            flag_modified(download, "bandwidth_used")
            flag_modified(download, "last_progress_at")
            
            # Flush changes to database before commit to ensure they're persisted
            self.db.flush()
            
            # Commit all changes together
            self.db.commit()
            
            # Log the update (use INFO level so we can see it in logs)
            logger.info(f"Updated progress for download {download_id}: {old_bytes} -> {bytes_transferred} bytes, {old_bandwidth} -> {bytes_per_second} bytes/s")
            return True
        except Exception as e:
            logger.error(f"Error updating progress for download {download_id}: {e}", exc_info=True)
            self.db.rollback()
            return False
    
    def archive_download(self, download_id: int, status: str) -> bool:
        """Archive a download before deletion.
        
        Args:
            download_id: Download ID to archive
            status: Download status ('completed', 'error', 'cancelled', 'stuck', etc.)
        
        Returns:
            bool: True if archived successfully, False otherwise
        """
        try:
            from app.database import DownloadArchive, User
            
            # Get download from queue
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for archiving")
                return False
            
            # Get game information
            game = self.game_service.get_game_by_id(download.game_id)
            if not game:
                logger.warning(f"Game not found for download {download_id}, using game_id as game_name")
                game_name = download.game_id
                system = None
            else:
                game_name = game.get('name', download.game_id)
                system = game.get('system', None)
            
            # Get username from User table
            username = None
            user = self.db.query(User).filter(User.user_id == download.user_id).first()
            if user:
                username = user.username
            
            # Create archive entry
            archive_entry = DownloadArchive(
                download_id=download.id,
                timestamp=datetime.now(timezone.utc),
                user_id=download.user_id,
                username=username,
                game_name=game_name,
                system=system,
                rompath=download.game_id,
                download_status=status,
                bytes_transferred=download.bytes_transferred or 0,
                file_size=download.file_size
            )
            
            self.db.add(archive_entry)
            self.db.commit()
            
            logger.info(f"Archived download {download_id} with status '{status}'")
            return True
        except Exception as e:
            logger.error(f"Error archiving download {download_id}: {e}", exc_info=True)
            self.db.rollback()
            return False
    
    def remove_download(self, download_id: int) -> bool:
        """Remove download from queue without updating statistics (e.g., when file doesn't exist)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Archive the download before deletion
            self.archive_download(download_id, 'error')
            
            # Delete the download without updating statistics
            self.db.delete(download)
            self.db.commit()
            
            logger.info(f"Removed download {download_id} from queue (file not found or invalid)")
            return True
        except Exception as e:
            logger.error(f"Error removing download: {e}")
            self.db.rollback()
            return False
    
    def complete_download(self, download_id: int) -> bool:
        """Remove download from queue and update user download statistics."""
        try:
            from app.database import User
            
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Store user_id and game_id before deletion
            user_id = download.user_id
            game_id = download.game_id
            
            # Calculate downloaded MB (convert bytes to MB: 1 MB = 1024 * 1024 bytes)
            downloaded_bytes = download.bytes_transferred or 0
            downloaded_mb = downloaded_bytes / (1024 * 1024)
            
            # Update or create user statistics
            user = self.db.query(User).filter(
                User.user_id == user_id
            ).first()
            
            if user:
                # Update existing user
                user.total_download_mb += downloaded_mb
                user.total_download_number += 1
                user.updated_at = datetime.now(timezone.utc)
                logger.info(f"Updated user {user_id} total_download_mb: {user.total_download_mb:.2f} MB (+{downloaded_mb:.2f} MB), total_download_number: {user.total_download_number}")
            else:
                # Create new user record
                user = User(
                    user_id=user_id,
                    total_download_mb=downloaded_mb,
                    total_download_number=1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                self.db.add(user)
                logger.info(f"Created new user record for {user_id} with {downloaded_mb:.2f} MB, total_download_number: 1")
            
            # Archive the download before deletion
            self.archive_download(download_id, 'completed')
            
            # Delete the download from queue instead of marking as completed
            self.db.delete(download)
            self.db.commit()
            
            logger.info(f"Download {download_id} completed and removed from queue. User {user_id} total: {user.total_download_mb:.2f} MB, {user.total_download_number} games")
            return True
        except Exception as e:
            logger.error(f"Error completing download: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False

