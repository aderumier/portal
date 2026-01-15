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
    """Preload all gamelist.xml files and search index on startup."""
    try:
        from app.api.routes.catalog import get_game_service
        game_service = get_game_service()
        
        # Try loading catalog from cache (this also sets _gamelists_loaded flag)
        logger.info("=== STARTUP: Attempting to load catalog from cache... ===")
        catalog_loaded_from_cache = game_service._load_catalog_from_cache()
        if not catalog_loaded_from_cache:
            logger.info("=== CACHE MISS: Preloading all gamelist.xml files into memory... ===")
            game_service.preload_all_gamelists()
            logger.info("All gamelist.xml files loaded into memory")
        else:
            logger.info("=== CACHE HIT: Catalog loaded from cache ===")
            logger.info("Assuming playcount/gametime stats are precomputed in cached catalog (stats only computed during catalog refresh)")
        
        # Try loading search index from cache (build_search_index will handle this)
        logger.info("Attempting to load search index from cache...")
        cached_wip = game_service._load_index_from_cache('wip')
        if cached_wip:
            game_service.search_index_wip = cached_wip
            game_service._index_built_wip = True
            game_service.cache['search_index_wip'] = cached_wip
            logger.info("Search index (WIP) loaded from cache")
        else:
            game_service.build_search_index('wip')
        
        cached_releases = game_service._load_index_from_cache('releases')
        if cached_releases:
            game_service.search_index_releases = cached_releases
            game_service._index_built_releases = True
            game_service.cache['search_index_releases'] = cached_releases
            logger.info("Search index (Releases) loaded from cache")
        else:
            game_service.build_search_index('releases')
        logger.info("Search index preloaded on startup (WIP and Releases)")
    except Exception as e:
        logger.warning(f"Failed to preload game data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Start background task for cleaning up stuck downloads
    asyncio.create_task(cleanup_stuck_downloads())
    
    # Start background task for promoting user_queue items to pending
    asyncio.create_task(promote_user_queue_items())
    
    # Start background task for rebuilding p2p_index hourly
    if settings.P2P_ENABLED:
        asyncio.create_task(rebuild_p2p_index_periodically())
    
    # Run initial p2p_index rebuild at startup
    if settings.P2P_ENABLED:
        try:
            from app.services.p2p_inventory import P2PInventoryService
            logger.info("Rebuilding p2p_index at startup...")
            success = await P2PInventoryService.rebuild_index()
            if success:
                logger.info("p2p_index rebuild completed at startup")
            else:
                logger.warning("p2p_index rebuild failed at startup")
        except Exception as e:
            logger.error(f"Error rebuilding p2p_index at startup: {e}", exc_info=True)
    
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

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
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
    
    Runs every 5 seconds and:
    - Checks for items in user_queue
    - Promotes items to pending if user has no active downloads
    - Sends WebSocket notifications to connected clients
    """
    from app.database import get_db, DownloadQueue
    from app.services.download import DownloadService
    from app.services.websocket_manager import get_websocket_manager
    
    while True:
        try:
            await asyncio.sleep(5)  # Run every 5 seconds
            
            # Get database session
            db = next(get_db())
            try:
                from app.api.routes.catalog import get_game_service
                game_service = get_game_service()
                download_service = DownloadService(db, game_service)
                ws_manager = get_websocket_manager()
                
                # Get all items in user_queue grouped by token_id
                user_queue_items = db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'user_queue'
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
                
                # Process each token_id
                for token_id, items in items_by_token.items():
                    try:
                        # Check if this token_id has any active downloads (downloading status)
                        # This includes downloads that are actively being downloaded
                        has_active = db.query(DownloadQueue).filter(
                            and_(
                                DownloadQueue.token_id == token_id,
                                DownloadQueue.active_download == True,
                                DownloadQueue.status == 'downloading'
                            )
                        ).first()
                        
                        if not has_active:
                            # No active downloads for this token - items stay in user_queue
                            # get_next_download now looks for user_queue items directly, so no status change needed
                            # Just send notification so client requests next download
                            queue_types_processed = set()
                            
                            for item in items:
                                if item.queue_type not in queue_types_processed:
                                    # Item stays in user_queue - get_next_download will pick it up
                                    # Send WebSocket notification if client is connected
                                    notification_sent = await ws_manager.send_notification(token_id, {
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

async def rebuild_p2p_index_periodically():
    """Background task to periodically rebuild the p2p_index.
    
    Runs every hour (3600 seconds) and atomically rebuilds the index.
    The index will rebuild naturally as clients upload inventories and downloads complete.
    """
    from app.services.p2p_inventory import P2PInventoryService
    
    # Wait a bit before first run to let server fully start
    await asyncio.sleep(60)  # Wait 1 minute after startup
    
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour (3600 seconds)
            
            logger.info("Starting periodic p2p_index rebuild...")
            success = await P2PInventoryService.rebuild_index()
            if success:
                logger.info("Periodic p2p_index rebuild completed")
            else:
                logger.warning("Periodic p2p_index rebuild failed")
                
        except asyncio.CancelledError:
            logger.info("p2p_index rebuild task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in rebuild_p2p_index_periodically background task: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retrying on error

async def cleanup_stuck_downloads():
    """Background task to detect and clean up stuck downloads.
    
    - Downloads with status 'downloading' and no progress for 2 minutes -> move back to user_queue for retry
    - Checks Redis for progress tracking (Redis is the source of truth for active downloads)
    """
    from app.database import get_db, DownloadQueue
    from app.services.redis_downloads import RedisDownloadTracker
    from datetime import timedelta
    from sqlalchemy import or_, and_
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            
            # Get database session
            db = next(get_db())
            try:
                now = datetime.now(timezone.utc)
                
                # 1. Check downloads with status 'downloading' - if no progress for 2 minutes, move back to user_queue for retry
                stuck_threshold = now - timedelta(seconds=120)
                
                # Get all active downloads from database
                active_downloads = db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'downloading',
                    DownloadQueue.active_download == True
                ).all()
                
                retried_count = 0
                for download in active_downloads:
                    # Check Redis for progress (Redis is the source of truth for active downloads)
                    redis_status = await RedisDownloadTracker.get_download_status(download.id)
                    
                    is_stuck = False
                    
                    if redis_status:
                        # Download is in Redis - check last_progress_at from Redis
                        last_progress_str = redis_status.get('last_progress_at')
                        if last_progress_str:
                            try:
                                # Parse ISO format datetime string (from datetime.now(timezone.utc).isoformat())
                                last_progress = datetime.fromisoformat(last_progress_str.replace('Z', '+00:00'))
                                if last_progress < stuck_threshold:
                                    is_stuck = True
                            except Exception as e:
                                logger.warning(f"Failed to parse last_progress_at from Redis for download {download.id}: {e}")
                                # If we can't parse, assume stuck
                                is_stuck = True
                        else:
                            # No last_progress_at in Redis - assume stuck
                            is_stuck = True
                    else:
                        # Not in Redis but should be active - this means it's stuck
                        # (download should be in Redis if it's actively downloading)
                        is_stuck = True
                    
                    if is_stuck:
                        logger.warning(f"Download {download.id} (game: {download.game_id}) has no progress for 2+ minutes, moving back to user_queue for retry")
                        
                        # Move back to user_queue so it can be retried
                        download.status = 'user_queue'
                        download.active_download = False
                        download.assigned_to_service = None
                        # Reset started_at so it can be retried fresh
                        download.started_at = None
                        # Keep last_progress_at to track when it was last attempted
                        
                        # Remove from Redis as well
                        await RedisDownloadTracker.remove_download(download.id)
                        
                        # Release bandwidth
                        if download.bandwidth_used > 0:
                            from app.services.bandwidth import BandwidthManager
                            bandwidth_manager = BandwidthManager(db)
                            bandwidth_manager.update_usage(download.queue_type, -download.bandwidth_used)
                            download.bandwidth_used = 0
                        
                        retried_count += 1
                
                # 2. Check downloads that have been retried multiple times (keep last_progress_at from multiple retries)
                # If a download has been in user_queue for a while and keeps getting stuck, we should eventually remove it
                # Check for downloads that have been retried (moved back to user_queue) multiple times
                # We'll check if last_progress_at is old (meaning it was last attempted a while ago)
                # and the download is still in user_queue (meaning it keeps getting stuck)
                
                # Actually, since we're now moving stuck downloads back to user_queue immediately,
                # we don't need the old stuck removal logic. Downloads will either:
                # 1. Get retried and succeed
                # 2. Get retried and get stuck again (will be retried again)
                # 3. Eventually be manually cancelled by user
                
                # However, to prevent infinite retry loops, we could add a check for downloads
                # that have been retried too many times. For now, we'll let them retry indefinitely
                # as the user can always manually cancel if needed.
                
                if retried_count > 0:
                    db.commit()
                    logger.info(f"Moved {retried_count} stuck downloads back to user_queue for retry")
                else:
                    db.commit()
                    
            except Exception as e:
                logger.error(f"Error in cleanup_stuck_downloads: {e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in cleanup_stuck_downloads loop: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait before retrying


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

