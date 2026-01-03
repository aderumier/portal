"""Bandwidth management service."""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.config import settings
from app.database import DownloadQueue

logger = logging.getLogger(__name__)


class BandwidthManager:
    """Service for managing bandwidth allocation and tracking."""
    
    def __init__(self, db: Session):
        self.db = db
        self.global_limit = settings.GLOBAL_BANDWIDTH_LIMIT
        self.per_user_slow_limit = getattr(settings, 'PER_USER_SLOW_QUEUE_LIMIT', None)
        self.per_user_fast_limit = getattr(settings, 'PER_USER_FAST_QUEUE_LIMIT', None)
    
    def get_fast_queue_bandwidth(self) -> int:
        """Get guaranteed bandwidth for fast queue (2/3 of global)."""
        return int(self.global_limit * 2 / 3)
    
    def get_current_fast_usage(self) -> int:
        """Get current bandwidth usage in fast queue."""
        active_fast = self.db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.queue_type == 'fast',
                DownloadQueue.active_download == True
            )
        ).all()
        
        total_usage = sum(item.bandwidth_used for item in active_fast)
        return total_usage
    
    def get_current_slow_usage(self) -> int:
        """Get current bandwidth usage in slow queue."""
        active_slow = self.db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.queue_type == 'slow',
                DownloadQueue.active_download == True
            )
        ).all()
        
        total_usage = sum(item.bandwidth_used for item in active_slow)
        return total_usage
    
    def get_slow_queue_bandwidth(self) -> int:
        """Get available bandwidth for slow queue (remaining after fast queue usage)."""
        current_fast_usage = self.get_current_fast_usage()
        available = self.global_limit - current_fast_usage
        return max(0, available)
    
    def get_available_bandwidth(self, queue_type: str) -> int:
        """Calculate available bandwidth for a queue type."""
        if queue_type == 'fast':
            return self.get_fast_queue_bandwidth()
        elif queue_type == 'slow':
            return self.get_slow_queue_bandwidth()
        else:
            logger.warning(f"Unknown queue type: {queue_type}")
            return 0
    
    def get_active_user_count(self, queue_type: str) -> int:
        """Get number of users with active downloads in a queue."""
        active_downloads = self.db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.queue_type == queue_type,
                DownloadQueue.active_download == True
            )
        ).all()
        
        # Count unique users
        unique_users = set(item.user_id for item in active_downloads)
        return len(unique_users)
    
    def allocate_bandwidth(self, queue_type: str) -> int:
        """Allocate bandwidth per user for a queue type."""
        # Check if per-user limit is set for this queue type
        per_user_limit = None
        if queue_type == 'slow' and self.per_user_slow_limit is not None:
            per_user_limit = self.per_user_slow_limit
        elif queue_type == 'fast' and self.per_user_fast_limit is not None:
            per_user_limit = self.per_user_fast_limit
        
        # If per-user limit is set, use it (for testing)
        if per_user_limit is not None:
            logger.debug(f"Using per-user limit for {queue_type} queue: {per_user_limit} bytes/s ({per_user_limit / 125000:.2f} Mbits/s)")
            return per_user_limit
        
        # Otherwise, share available bandwidth equally among active users
        available = self.get_available_bandwidth(queue_type)
        active_users = self.get_active_user_count(queue_type)
        
        if active_users == 0:
            # If no active users, return full available bandwidth
            return available
        
        # Share equally among active users
        per_user = available // active_users
        return per_user
    
    def can_start_download(self, queue_type: str, user_id: str) -> bool:
        """Check if a user can start a download (1 file limit)."""
        active_download = self.db.query(DownloadQueue).filter(
            and_(
                DownloadQueue.user_id == user_id,
                DownloadQueue.active_download == True
            )
        ).first()
        
        if active_download:
            logger.info(f"User {user_id} already has an active download")
            return False
        
        return True
    
    def update_usage(self, download_id: int, bytes_per_second: int) -> bool:
        """Update bandwidth usage for a download."""
        try:
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            download.bandwidth_used = bytes_per_second
            self.db.commit()
            
            logger.debug(f"Updated bandwidth usage for download {download_id}: {bytes_per_second} bytes/s")
            return True
        except Exception as e:
            logger.error(f"Error updating bandwidth usage: {e}")
            self.db.rollback()
            return False

