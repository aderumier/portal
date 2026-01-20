"""Redis service for tracking active downloads and progress."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client for downloads (initialized on first use)
_redis_downloads_client = None

def get_redis_downloads_client():
    """Get or create Redis client for active downloads tracking."""
    global _redis_downloads_client
    
    if _redis_downloads_client is not None:
        return _redis_downloads_client
    
    try:
        import redis.asyncio as aioredis
        redis_url = settings.REDIS_URL
        # Use database 2 for downloads to separate from sessions (0) and cache (1)
        if '/0' in redis_url:
            redis_url = redis_url.replace('/0', '/2')
        elif '/1' in redis_url:
            redis_url = redis_url.replace('/1', '/2')
        elif redis_url.endswith('/'):
            redis_url = redis_url + '2'
        else:
            redis_url = redis_url + '/2'
        
        _redis_downloads_client = aioredis.from_url(
            redis_url,
            decode_responses=True,  # Downloads use text (JSON)
            encoding='utf-8'
        )
        logger.info(f"Redis downloads client initialized (URL: {redis_url})")
        return _redis_downloads_client
    except ImportError:
        logger.warning("Redis not available for downloads tracking (redis library not installed)")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Redis downloads client: {e}")
        return None

class RedisDownloadTracker:
    """Service for tracking active downloads in Redis."""
    
    @staticmethod
    def _get_key(download_id: int) -> str:
        """Get Redis key for a download."""
        return f"download:{download_id}"
    
    @staticmethod
    async def set_active_download(
        download_id: int,
        status: str = 'downloading',
        bytes_transferred: int = 0,
        bytes_per_second: int = 0,
        file_size: Optional[int] = None,
        queue_type: Optional[str] = None,
        assigned_to_service: Optional[str] = None,
        system: Optional[str] = None,
        rom_path: Optional[str] = None
    ) -> bool:
        """Store active download info in Redis."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return False
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data = {
                'download_id': download_id,
                'status': status,
                'bytes_transferred': bytes_transferred,
                'bytes_per_second': bytes_per_second,
                'last_progress_at': datetime.now(timezone.utc).isoformat(),
                'started_at': datetime.now(timezone.utc).isoformat(),
            }
            if file_size is not None:
                data['file_size'] = file_size
            if queue_type:
                data['queue_type'] = queue_type
            if assigned_to_service:
                data['assigned_to_service'] = assigned_to_service
            if system:
                data['system'] = system
            if rom_path:
                data['rom_path'] = rom_path
            
            # Store with 24 hour expiration (downloads shouldn't take that long)
            await redis_client.setex(
                key,
                86400,  # 24 hours
                json.dumps(data)
            )
            return True
        except Exception as e:
            logger.error(f"Error setting active download in Redis: {e}")
            return False
    
    @staticmethod
    async def update_progress(
        download_id: int,
        bytes_transferred: int,
        bytes_per_second: int
    ) -> bool:
        """Update download progress in Redis."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return False
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data_str = await redis_client.get(key)
            
            if not data_str:
                # Download not in Redis (might be in SQLite only)
                return False
            
            data = json.loads(data_str)
            data['bytes_transferred'] = bytes_transferred
            data['bytes_per_second'] = bytes_per_second
            data['last_progress_at'] = datetime.now(timezone.utc).isoformat()
            
            # Update with same expiration
            ttl = await redis_client.ttl(key)
            if ttl > 0:
                await redis_client.setex(key, ttl, json.dumps(data))
            else:
                await redis_client.setex(key, 86400, json.dumps(data))
            
            return True
        except Exception as e:
            logger.error(f"Error updating progress in Redis: {e}")
            return False
    
    @staticmethod
    async def get_download_status(download_id: int) -> Optional[Dict[str, Any]]:
        """Get download status from Redis."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return None
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data_str = await redis_client.get(key)
            
            if not data_str:
                return None
            
            return json.loads(data_str)
        except Exception as e:
            logger.error(f"Error getting download status from Redis: {e}")
            return None
    
    @staticmethod
    async def update_status(download_id: int, status: str) -> bool:
        """Update download status in Redis."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return False
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data_str = await redis_client.get(key)
            
            if not data_str:
                return False
            
            data = json.loads(data_str)
            data['status'] = status
            
            ttl = await redis_client.ttl(key)
            if ttl > 0:
                await redis_client.setex(key, ttl, json.dumps(data))
            else:
                await redis_client.setex(key, 86400, json.dumps(data))
            
            return True
        except Exception as e:
            logger.error(f"Error updating status in Redis: {e}")
            return False
    
    @staticmethod
    async def set_p2p_remote_token_id(download_id: int, p2p_remote_token_id: int) -> bool:
        """Store P2P remote token ID in Redis for cancellation notification."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return False
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data_str = await redis_client.get(key)
            
            if data_str:
                # Update existing download entry
                data = json.loads(data_str)
                data['p2p_remote_token_id'] = p2p_remote_token_id
                ttl = await redis_client.ttl(key)
                if ttl > 0:
                    await redis_client.setex(key, ttl, json.dumps(data))
                else:
                    await redis_client.setex(key, 86400, json.dumps(data))
            else:
                # Create new entry if download not in Redis yet
                data = {
                    'download_id': download_id,
                    'p2p_remote_token_id': p2p_remote_token_id,
                    'status': 'downloading'
                }
                await redis_client.setex(key, 86400, json.dumps(data))
            
            return True
        except Exception as e:
            logger.error(f"Error setting P2P remote token ID in Redis: {e}")
            return False
    
    @staticmethod
    async def get_p2p_remote_token_id(download_id: int) -> Optional[int]:
        """Get P2P remote token ID from Redis."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return None
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            data_str = await redis_client.get(key)
            
            if not data_str:
                return None
            
            data = json.loads(data_str)
            return data.get('p2p_remote_token_id')
        except Exception as e:
            logger.error(f"Error getting P2P remote token ID from Redis: {e}")
            return None
    
    @staticmethod
    async def remove_download(download_id: int) -> bool:
        """Remove download from Redis (when completed/cancelled)."""
        redis_client = get_redis_downloads_client()
        if not redis_client:
            return False
        
        try:
            key = RedisDownloadTracker._get_key(download_id)
            await redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error removing download from Redis: {e}")
            return False
    
    @staticmethod
    async def close():
        """Close Redis connection."""
        global _redis_downloads_client
        if _redis_downloads_client:
            await _redis_downloads_client.close()
            _redis_downloads_client = None






