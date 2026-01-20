"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.database import init_db
from app.api.routes import auth, catalog, downloads, users, media, systems_config, bugreports
import logging
import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_, and_

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Create FastAPI app with orjson for faster JSON serialization
app = FastAPI(
    title="Batocera Games Catalog API",
    description="API for browsing and downloading games from Batocera system",
    version="1.0.0",
    default_response_class=ORJSONResponse
)

# Preload all gamelist.xml files and search index on startup
@app.on_event("startup")
async def preload_game_data():
    """Preload all gamelist.xml files and search index on startup.
    
    Only loads from .pkl cache files. Does not generate catalog/index if cache doesn't exist.
    Generation only happens when /refresh endpoint is called.
    """
    try:
        from app.api.routes.catalog import get_game_service
        game_service = get_game_service()
        
        import os
        worker_id = os.getenv('WORKER_ID', os.getpid())
        
        # Try loading catalog from cache (this also sets _gamelists_loaded flag)
        logger.info(f"[Worker {worker_id}] === STARTUP: Attempting to load catalog from .pkl cache... ===")
        catalog_loaded_from_cache = game_service._load_catalog_from_cache()
        if not catalog_loaded_from_cache:
            logger.warning(f"[Worker {worker_id}] === CACHE MISS: Catalog .pkl file not found ===")
            logger.warning(f"[Worker {worker_id}] Catalog will not be available until /refresh endpoint is called to generate it")
            logger.warning(f"[Worker {worker_id}] This prevents multiple workers from building the catalog simultaneously")
        else:
            logger.info(f"[Worker {worker_id}] === CACHE HIT: Catalog loaded from .pkl cache ===")
            logger.info(f"[Worker {worker_id}] Assuming playcount/gametime stats are precomputed in cached catalog (stats only computed during catalog refresh)")
        
        # Try loading search index from cache
        logger.info(f"[Worker {worker_id}] Attempting to load search index from .pkl cache...")
        cached_wip = game_service._load_index_from_cache('wip')
        if cached_wip:
            game_service.search_index_wip = cached_wip
            game_service._index_built_wip = True
            game_service.cache['search_index_wip'] = cached_wip
            logger.info(f"[Worker {worker_id}] Search index (WIP) loaded from .pkl cache: {len(cached_wip)} letters indexed")
        else:
            logger.warning(f"[Worker {worker_id}] Search index (WIP) .pkl file not found - will not be available until /refresh is called")
            game_service.search_index_wip = {}
            game_service._index_built_wip = False
        
        cached_releases = game_service._load_index_from_cache('releases')
        if cached_releases:
            game_service.search_index_releases = cached_releases
            game_service._index_built_releases = True
            game_service.cache['search_index_releases'] = cached_releases
            logger.info(f"[Worker {worker_id}] Search index (Releases) loaded from .pkl cache: {len(cached_releases)} letters indexed")
        else:
            logger.warning(f"[Worker {worker_id}] Search index (Releases) .pkl file not found - will not be available until /refresh is called")
            game_service.search_index_releases = {}
            game_service._index_built_releases = False
        
        logger.info("Startup complete - catalog and search index loaded from cache (if available)")
    except Exception as e:
        logger.warning(f"Failed to preload game data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Start background task for cleaning up stuck downloads
    asyncio.create_task(cleanup_stuck_downloads())
    
    # Start background task for promoting user_queue items to pending
    asyncio.create_task(promote_user_queue_items())
    
    # Start background task for cleaning up p2p_index every 24 hours
    if settings.P2P_ENABLED:
        asyncio.create_task(cleanup_p2p_index_periodically())
    
    # Start background task for refreshing Redis TTL for active WebSocket connections
    asyncio.create_task(refresh_websocket_connection_ttl_periodically())
    
    # Start background task for cleaning up dead WebSocket connections
    asyncio.create_task(cleanup_dead_websocket_connections())
    
    # Start background task for checking and reloading catalog if updated by another worker
    asyncio.create_task(check_and_reload_catalog_periodically())
    
    
    # Initialize GeoIP instance on startup
    try:
        from app.services.geoip import get_geoip_instance
        geoip = get_geoip_instance()
        if geoip:
            logger.info("GeoIP2Fast initialized successfully")
        else:
            logger.info("GeoIP2Fast not available (lookups will be disabled)")
    except Exception as e:
        logger.warning(f"Failed to initialize GeoIP2Fast: {e}")
    
    # Clear Discord roles cache on startup to ensure fresh data
    try:
        from app.services.discord import get_redis_cache_client, DiscordService
        redis_client = get_redis_cache_client()
        if redis_client:
            guild_id = settings.DISCORD_GUILD_ID
            discord_service = DiscordService()
            await discord_service._clear_guild_roles_cache(guild_id)
            await discord_service.close()
            logger.info("Cleared Discord roles cache on startup")
    except Exception as e:
        logger.debug(f"Error clearing Discord cache on startup: {e}")
    
    # Start WebSocket pub/sub listener for cross-process notifications
    try:
        from app.services.websocket_manager import get_websocket_manager
        ws_manager = get_websocket_manager()
        pubsub_started = await ws_manager.start_pubsub_listener()
        if pubsub_started:
            logger.info("WebSocket pub/sub listener started for cross-process notifications")
        else:
            logger.warning("Failed to start WebSocket pub/sub listener (cross-process notifications disabled)")
    except Exception as e:
        logger.warning(f"Error starting WebSocket pub/sub listener: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    # Stop WebSocket pub/sub listener
    try:
        from app.services.websocket_manager import get_websocket_manager
        ws_manager = get_websocket_manager()
        await ws_manager.stop_pubsub_listener()
        logger.info("WebSocket pub/sub listener stopped")
    except Exception as e:
        logger.warning(f"Error stopping WebSocket pub/sub listener: {e}")
    
    try:
        from app.services.geoip import close_geoip_instance
        close_geoip_instance()
    except Exception as e:
        logger.warning(f"Error during GeoIP cleanup: {e}")

# Add session middleware (configurable: memory, redis, file, or database)
session_storage = settings.SESSION_STORAGE.lower()
logger.info(f"=== Session storage configuration ===")
logger.info(f"SESSION_STORAGE from settings: '{session_storage}'")
logger.info(f"REDIS_URL: {settings.REDIS_URL}")
logger.info(f"REDIS_SESSION_KEY_PREFIX: {settings.REDIS_SESSION_KEY_PREFIX}")

redis_configured = False

if session_storage == 'redis':
    logger.info("Attempting to configure Redis session storage...")
    try:
        from app.middleware.redis_session_middleware import RedisSessionMiddleware
        import redis.asyncio as aioredis
        
        # Parse Redis URL from settings
        redis_url = settings.REDIS_URL
        key_prefix = settings.REDIS_SESSION_KEY_PREFIX
        
        logger.info(f"Using custom RedisSessionMiddleware implementation")
        logger.info(f"Initializing Redis session storage (URL: {redis_url})")
        
        # Create Redis connection pool
        redis_client = aioredis.from_url(
            redis_url,
            decode_responses=False,  # Sessions are binary data
            encoding='utf-8'
        )
        
        # Test connection asynchronously
        async def test_redis_connection():
            try:
                await redis_client.ping()
                logger.info("Redis connection test successful")
                return True
            except Exception as e:
                logger.warning(f"Redis connection test failed: {e}")
                return False
        
        # Try to test connection if possible
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # Loop is already running, create a task for testing
                logger.info("Event loop already running, will test Redis connection on first request")
            except RuntimeError:
                # No loop running, test synchronously
                if asyncio.run(test_redis_connection()):
                    logger.info("Redis connection verified")
        except Exception as conn_error:
            logger.warning(f"Could not test Redis connection: {conn_error}")
            logger.warning("Will attempt to connect on first request")
        
        # Use our custom Redis session middleware
        app.add_middleware(
            RedisSessionMiddleware,
            redis=redis_client,
            secret_key=settings.SECRET_KEY,
            max_age=settings.SESSION_MAX_AGE,  # 24 hours (configurable via SESSION_MAX_AGE env var)
            same_site='lax',
            key_prefix=key_prefix if key_prefix and key_prefix != "session:" else None
        )
        logger.info(f"✓✓✓ Custom Redis session middleware added successfully (URL: {redis_url}, prefix: {key_prefix}) ✓✓✓")
        redis_configured = True
        logger.info(f"redis_configured flag set to: {redis_configured}")
    except ImportError as e:
        logger.error(f"✗ redis library or RedisSessionMiddleware not available: {e}")
        logger.warning("Falling back to in-memory sessions")
        logger.warning("Install with: pip install redis")
        session_storage = 'memory'
        redis_configured = False
    except Exception as e:
        logger.error(f"✗ Failed to initialize Redis session store: {e}")
        import traceback
        logger.error(traceback.format_exc())
        logger.warning("Falling back to in-memory sessions")
        session_storage = 'memory'
        redis_configured = False

if session_storage == 'memory' and not redis_configured:
    # Default: in-memory sessions (Starlette's SessionMiddleware)
    logger.info(f"Configuring in-memory sessions (session_storage='{session_storage}', redis_configured={redis_configured})")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        max_age=settings.SESSION_MAX_AGE,  # 24 hours (configurable via SESSION_MAX_AGE env var)
        same_site="lax"
    )
    logger.info("✓ Using in-memory session storage")
elif session_storage == 'database':
    # Use database-backed sessions
    from app.middleware.persistent_session import PersistentSessionMiddleware
    app.add_middleware(
        PersistentSessionMiddleware,
        secret_key=settings.SECRET_KEY,
        max_age=settings.SESSION_MAX_AGE,  # 24 hours (configurable via SESSION_MAX_AGE env var)
        same_site="lax"
    )
    logger.info("Using database for session storage")
elif session_storage == 'file':
    # Use file-based sessions
    from app.services.session_store import FileSessionStore
    from app.middleware.file_session_middleware import FileSessionMiddleware
    file_store = FileSessionStore()
    app.add_middleware(
        FileSessionMiddleware,
        session_store=file_store,
        secret_key=settings.SECRET_KEY,
        max_age=settings.SESSION_MAX_AGE,  # 24 hours (configurable via SESSION_MAX_AGE env var)
        same_site="lax"
    )
    logger.info("Using file-based session storage")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compression is now handled by nginx (removed from backend for better performance)
# Nginx compression is faster and offloads work from Python workers

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(downloads.router, prefix="/api/download", tags=["downloads"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(systems_config.router, prefix="/api/admin", tags=["systems-config"])
app.include_router(bugreports.router, prefix="/api", tags=["bugreports"])

# Include media router
app.include_router(media.router, prefix="/api/media", tags=["media"])

# Mount static files for media (games images, videos, etc.)
# This serves files from GAMES_PATH at /media endpoint
# IMPORTANT: Mount this BEFORE routers to ensure it takes precedence
if settings.GAMES_PATH and os.path.exists(settings.GAMES_PATH):
    try:
        app.mount("/media", StaticFiles(directory=settings.GAMES_PATH), name="media")
        logger.info(f"Mounted media files from {settings.GAMES_PATH} at /media")
    except Exception as e:
        logger.error(f"Failed to mount media files: {e}")
else:
    logger.warning(f"GAMES_PATH not set or does not exist: {settings.GAMES_PATH}. Media files will not be served.")


@app.get("/robots.txt")
async def robots_txt():
    """Serve robots.txt - disallow all indexing."""
    content = """User-agent: *
Disallow: /
"""
    from fastapi.responses import Response
    return Response(content=content, media_type="text/plain")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Batocera Games Catalog API", "version": "1.0.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

async def promote_user_queue_items():
    """Background task to periodically check and promote user_queue items to pending.
    
    Runs every 5 seconds on each worker and:
    - Only handles clients connected to THIS worker's WebSocket
    - Checks for items in user_queue for those clients
    - Sends WebSocket notifications directly (no pub/sub needed)
    
    Each worker handles its own connected clients - no locking needed.
    """
    from app.database import get_db, DownloadQueue
    from app.services.download import DownloadService
    from app.services.websocket_manager import get_websocket_manager
    
    while True:
        try:
            await asyncio.sleep(5)  # Run every 5 seconds
            
            ws_manager = get_websocket_manager()
            
            # Get token_ids connected to THIS worker's WebSocket only
            local_token_ids = ws_manager.get_local_token_ids()
            
            if not local_token_ids:
                # No clients connected to this worker, nothing to do
                continue
            
            # Get database session
            db = next(get_db())
            try:
                # Only query for user_queue items belonging to our connected clients
                user_queue_items = db.query(DownloadQueue).filter(
                    and_(
                        DownloadQueue.status == 'user_queue',
                        DownloadQueue.token_id.in_(local_token_ids)
                    )
                ).order_by(DownloadQueue.created_at.asc()).all()
                
                if not user_queue_items:
                    continue
                
                # Group by token_id
                items_by_token = {}
                for item in user_queue_items:
                    if item.token_id:
                        if item.token_id not in items_by_token:
                            items_by_token[item.token_id] = []
                        items_by_token[item.token_id].append(item)
                
                # Process each token_id (all are guaranteed to be local)
                for token_id, items in items_by_token.items():
                    try:
                        # Check if this token_id has any active downloads (downloading status)
                        has_active = db.query(DownloadQueue).filter(
                            and_(
                                DownloadQueue.token_id == token_id,
                                DownloadQueue.active_download == True,
                                DownloadQueue.status == 'downloading'
                            )
                        ).first()
                        
                        if not has_active:
                            # No active downloads for this token - send notification directly
                            queue_types_processed = set()
                            
                            for item in items:
                                if item.queue_type not in queue_types_processed:
                                    # Send WebSocket notification directly (no pub/sub)
                                    notification_sent = await ws_manager.send_notification_direct(token_id, {
                                        "type": "download_available",
                                        "queue_type": item.queue_type
                                    })
                                    if notification_sent:
                                        logger.info(f"Sent download notification to token_id {token_id} for queue_type {item.queue_type} (item {item.id} in user_queue)")
                                    
                                    queue_types_processed.add(item.queue_type)
                                    
                                    # Only notify for one per queue_type per cycle
                                    break
                    except Exception as e:
                        logger.error(f"Error processing user_queue items for token_id {token_id}: {e}", exc_info=True)
                        db.rollback()
                        
            except Exception as e:
                logger.error(f"Error in promote_user_queue_items background task: {e}", exc_info=True)
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Critical error in promote_user_queue_items background task: {e}", exc_info=True)
            await asyncio.sleep(5)  # Wait before retrying

async def cleanup_p2p_index_periodically():
    """Background task to periodically clean up the p2p_index.
    
    Runs every 24 hours (86400 seconds) and removes disconnected clients from the index.
    Uses Redis distributed lock to avoid multiple workers cleaning up simultaneously.
    """
    import os
    from app.services.p2p_inventory import P2PInventoryService
    from app.services.redis_client import get_redis_ws_client
    
    lock_key = "lock:cleanup_p2p_index"
    lock_ttl = 3600  # Lock expires after 1 hour (task runs every 24h, cleanup takes time)
    
    # Wait a bit before first run to let server fully start
    await asyncio.sleep(60)  # Wait 1 minute after startup
    
    while True:
        try:
            await asyncio.sleep(86400)  # Run every 24 hours (86400 seconds)
            
            # Try to acquire Redis lock - only one worker will succeed
            redis_client = get_redis_ws_client()
            if not redis_client:
                logger.debug("Redis not available for cleanup_p2p_index lock, skipping")
                continue
            
            # SET NX (only if not exists) with expiry - atomic operation
            lock_acquired = await redis_client.set(lock_key, os.getpid(), nx=True, ex=lock_ttl)
            if not lock_acquired:
                # Another worker has the lock, skip this iteration
                logger.debug("Another worker is running p2p_index cleanup, skipping")
                continue
            
            logger.info("Starting periodic p2p_index cleanup...")
            success = await P2PInventoryService.p2p_index_garbage_collector()
            if success:
                logger.info("Periodic p2p_index cleanup completed")
            else:
                logger.warning("Periodic p2p_index cleanup failed")
                
        except asyncio.CancelledError:
            logger.info("p2p_index cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in cleanup_p2p_index_periodically background task: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retrying on error

async def refresh_websocket_connection_ttl_periodically():
    """Background task to periodically refresh Redis TTL for active WebSocket connections.
    
    Runs every 60 seconds to keep connections alive and allow multi-worker cleanup.
    Each worker refreshes the last_updated timestamp for its own connections.
    Other workers can detect stale connections (>5 min old) from crashed workers.
    """
    from app.services.websocket_manager import get_websocket_manager
    
    # Wait a bit before first run to let server fully start
    await asyncio.sleep(30)  # Wait 30 seconds after startup
    
    while True:
        try:
            ws_manager = get_websocket_manager()
            refreshed = await ws_manager.refresh_ttl_for_active_connections()
            if refreshed > 0:
                logger.debug(f"Refreshed TTL for {refreshed} WebSocket connections")
            
            await asyncio.sleep(60)  # Run every 60 seconds for multi-worker cleanup
                
        except asyncio.CancelledError:
            logger.info("WebSocket connection TTL refresh task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in refresh_websocket_connection_ttl_periodically background task: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retrying on error

async def cleanup_dead_websocket_connections():
    """Background task to periodically clean up dead WebSocket connections.
    
    Runs every minute to check and remove connections that are no longer active.
    This ensures that /connected-clients only shows actually connected clients.
    """
    from app.services.websocket_manager import get_websocket_manager
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            
            ws_manager = get_websocket_manager()
            # Call get_all_connections which will automatically clean up dead connections
            connections = await ws_manager.get_all_connections()
            
            # Log if any dead connections were found and removed
            # (The cleanup happens inside get_all_connections)
            logger.debug(f"WebSocket connection cleanup check: {len(connections)} active connections")
            
        except Exception as e:
            logger.error(f"Error in cleanup_dead_websocket_connections: {e}", exc_info=True)
            # Continue running even if there's an error
            await asyncio.sleep(60)


async def check_and_reload_catalog_periodically():
    """Background task to periodically check if catalog or search index files have been updated.
    
    Runs every minute to check if .pkl files have been modified by another worker.
    If files are newer, automatically reloads them to keep all workers in sync.
    This allows one worker to refresh the catalog and all other workers to pick up the changes.
    """
    from app.api.routes.catalog import get_game_service
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            
            import os
            worker_id = os.getenv('WORKER_ID', os.getpid())
            
            game_service = get_game_service()
            # Check if catalog or search index files have been updated and reload if needed
            reloaded = game_service._check_and_reload_catalog_if_updated()
            
            if reloaded:
                logger.info(f"[Worker {worker_id}] Catalog and/or search index reloaded from updated .pkl files")
            else:
                logger.debug(f"[Worker {worker_id}] Catalog and search index .pkl files checked - no updates detected")
            
        except Exception as e:
            logger.error(f"Error in check_and_reload_catalog_periodically: {e}", exc_info=True)
            # Continue running even if there's an error
            await asyncio.sleep(60)

async def cleanup_stuck_downloads():
    """Background task to detect and clean up stuck downloads.
    
    - Downloads in Redis with no progress for 2 minutes -> move back to user_queue for retry
    - Redis is the source of truth for active downloads (any download in Redis is actively downloading)
    
    Uses Redis distributed lock to avoid multiple workers processing the same stuck downloads simultaneously.
    """
    import os
    from app.database import SessionLocal, DownloadQueue
    from app.services.redis_downloads import RedisDownloadTracker, get_redis_downloads_client
    from app.services.redis_client import get_redis_ws_client
    from datetime import timedelta
    
    lock_key = "lock:cleanup_stuck_downloads"
    lock_ttl = 120  # Lock expires after 120 seconds (task runs every 60s)
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            
            # Try to acquire Redis lock - only one worker will succeed
            redis_ws_client = get_redis_ws_client()
            if not redis_ws_client:
                logger.debug("Redis not available for cleanup_stuck_downloads lock, skipping")
                continue
            
            # SET NX (only if not exists) with expiry - atomic operation
            lock_acquired = await redis_ws_client.set(lock_key, os.getpid(), nx=True, ex=lock_ttl)
            if not lock_acquired:
                # Another worker has the lock, skip this iteration
                continue
            
            redis_client = get_redis_downloads_client()
            if not redis_client:
                logger.debug("Redis downloads client not available for cleanup_stuck_downloads, skipping")
                continue
            
            now = datetime.now(timezone.utc)
            stuck_threshold = now - timedelta(seconds=120)  # 2 minutes
            
            # Get all active downloads from Redis (source of truth)
            stuck_download_ids = []
            
            # Scan Redis for all download keys (pattern: "download:*")
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match="download:*", count=100)
                
                for key in keys:
                    try:
                        # Extract download_id from key (format: "download:123")
                        download_id = int(key.split(":")[1])
                        
                        # Get download status from Redis
                        redis_status = await RedisDownloadTracker.get_download_status(download_id)
                        if not redis_status:
                            continue
                        
                        # Check if stuck
                        is_stuck = False
                        last_progress_str = redis_status.get('last_progress_at')
                        
                        if last_progress_str:
                            try:
                                last_progress = datetime.fromisoformat(last_progress_str.replace('Z', '+00:00'))
                                if last_progress < stuck_threshold:
                                    is_stuck = True
                            except Exception as e:
                                logger.warning(f"Failed to parse last_progress_at from Redis for download {download_id}: {e}")
                                is_stuck = True
                        else:
                            # No last_progress_at - assume stuck
                            is_stuck = True
                        
                        if is_stuck:
                            stuck_download_ids.append(download_id)
                            
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error processing download key {key}: {e}")
                        continue
                
                if cursor == 0:
                    break
            
            # Only query SQLite for stuck downloads (much smaller set)
            if stuck_download_ids:
                db = SessionLocal()
                try:
                    retried_count = 0
                    
                    # Query only the stuck downloads from database
                    stuck_downloads = db.query(DownloadQueue).filter(
                        DownloadQueue.id.in_(stuck_download_ids)
                    ).all()
                    
                    for download in stuck_downloads:
                        logger.warning(f"Download {download.id} (game: {download.game_id}) has no progress for 2+ minutes, moving back to user_queue for retry")
                        
                        # Move back to user_queue so it can be retried
                        download.status = 'user_queue'
                        download.active_download = False
                        download.assigned_to_service = None
                        download.started_at = None
                        
                        # Remove from Redis as well
                        await RedisDownloadTracker.remove_download(download.id)
                        
                        # Release bandwidth
                        if download.bandwidth_used > 0:
                            from app.services.bandwidth import BandwidthManager
                            bandwidth_manager = BandwidthManager(db)
                            bandwidth_manager.update_usage(download.queue_type, -download.bandwidth_used)
                            download.bandwidth_used = 0
                        
                        retried_count += 1
                    
                    if retried_count > 0:
                        db.commit()
                        logger.info(f"Moved {retried_count} stuck downloads back to user_queue for retry")
                    else:
                        db.commit()
                        
                except Exception as e:
                    logger.error(f"Error in cleanup_stuck_downloads database operations: {e}", exc_info=True)
                    db.rollback()
                finally:
                    db.close()
            else:
                logger.debug("No stuck downloads found")
                
        except Exception as e:
            logger.error(f"Error in cleanup_stuck_downloads loop: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait before retrying


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

