"""Download queue service."""
import logging
import os
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timezone
from app.database import DownloadQueue
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
            file_size = None
            if settings.GAMES_PATH:
                system = game.get('system', '')
                if system:
                    game_path = os.path.join(settings.GAMES_PATH, system, game_id)
                else:
                    game_path = os.path.join(settings.GAMES_PATH, game_id)
                if os.path.exists(game_path):
                    file_size = os.path.getsize(game_path)
                    logger.info(f"File size: {file_size} bytes")
            
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
            
            queue_items = self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
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
                        'token_name': token_name
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
    
    def get_next_download(self, queue_type: Optional[str] = None, service_id: str = 'default', token_id: Optional[int] = None) -> Optional[Dict]:
        """Get next available download from queue, including resumable interrupted downloads.
        
        Only returns downloads associated with the specified token_id.
        """
        try:
            # First, try to promote items from user queues to global queue for this token
            self._promote_user_queue_to_global(queue_type, token_id=token_id)
            
            # Then, check for downloads that are marked as downloading but might be interrupted
            # (e.g., service crashed, network issue). Allow resuming if assigned to same service
            # or if no progress in last 5 minutes (configurable timeout)
            from datetime import timedelta
            timeout_threshold = datetime.utcnow() - timedelta(minutes=5)
            
            # Check for resumable downloads (downloading status, same service or timed out)
            # Only for the authenticated token
            resumable_query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'downloading',
                DownloadQueue.active_download == True,
                or_(
                    DownloadQueue.assigned_to_service == service_id,
                    DownloadQueue.started_at < timeout_threshold
                )
            )
            
            if token_id is not None:
                resumable_query = resumable_query.filter(DownloadQueue.token_id == token_id)
            
            if queue_type:
                resumable_query = resumable_query.filter(DownloadQueue.queue_type == queue_type)
            
            resumable_download = resumable_query.order_by(DownloadQueue.started_at.asc()).first()
            
            if resumable_download:
                logger.info(f"Found resumable download: {resumable_download.id} (bytes_transferred: {resumable_download.bytes_transferred})")
                # Update service assignment in case it changed
                resumable_download.assigned_to_service = service_id
                self.db.commit()
                
                # Get game info
                game = self.game_service.get_game_by_id(resumable_download.game_id)
                if not game:
                    logger.warning(f"Game not found: {resumable_download.game_id}")
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
                        return None
                
                # Calculate available bandwidth
                allocated_bandwidth = self.bandwidth_manager.allocate_bandwidth(resumable_download.queue_type)
                
                download_info = {
                    'download_id': resumable_download.id,
                    'game_id': resumable_download.game_id,
                    'user_id': resumable_download.user_id,
                    'file_path': file_path,
                    'file_size': resumable_download.file_size,
                    'bytes_transferred': resumable_download.bytes_transferred,
                    'allocated_bandwidth': allocated_bandwidth,
                    'queue_type': resumable_download.queue_type,
                    'game_name': game.get('name', ''),
                    'system': game.get('system', '')  # Include system for download service
                }
                
                logger.info(f"Resuming download {resumable_download.id} from {resumable_download.bytes_transferred} bytes")
                return download_info
            
            # Build query for pending downloads
            # Only for the authenticated token
            query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'pending',
                DownloadQueue.active_download == False
            )
            
            # Filter by token_id if specified (required for token-based downloads)
            if token_id is not None:
                query = query.filter(DownloadQueue.token_id == token_id)
            
            # Filter by queue type if specified
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
                return None
            
            # Mark as active
            pending_download.active_download = True
            pending_download.status = 'downloading'
            pending_download.started_at = datetime.utcnow()
            pending_download.assigned_to_service = service_id
            self.db.commit()
            
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
                    return None
            
            download_info = {
                'download_id': pending_download.id,
                'game_id': pending_download.game_id,
                'user_id': pending_download.user_id,
                'file_path': file_path,
                'file_size': pending_download.file_size,
                'bytes_transferred': pending_download.bytes_transferred or 0,
                'allocated_bandwidth': allocated_bandwidth,
                'queue_type': pending_download.queue_type,
                'game_name': game.get('name', ''),
                'system': game.get('system', '')
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
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            download.bytes_transferred = bytes_transferred
            download.bandwidth_used = bytes_per_second
            
            # Update bandwidth manager
            self.bandwidth_manager.update_usage(download_id, bytes_per_second)
            
            self.db.commit()
            logger.debug(f"Updated progress for download {download_id}: {bytes_transferred} bytes, {bytes_per_second} bytes/s")
            return True
        except Exception as e:
            logger.error(f"Error updating progress: {e}")
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

