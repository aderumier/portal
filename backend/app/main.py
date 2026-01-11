"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.database import init_db
from app.api.routes import auth, catalog, downloads, users, media, systems_config
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
        
        # First, preload all gamelist.xml files into memory
        logger.info("Preloading all gamelist.xml files into memory...")
        game_service.preload_all_gamelists()
        logger.info("All gamelist.xml files loaded into memory")
        
        # Then, build search index (this will use the in-memory gamelists)
        logger.info("Building search index...")
        game_service.build_search_index('wip')
        if settings.ENABLE_RELEASES_CATALOG:
            game_service.build_search_index('releases')
            logger.info("Search index preloaded on startup (WIP and Releases)")
        else:
            logger.info("Search index preloaded on startup (WIP only, Releases catalog disabled)")
    except Exception as e:
        logger.warning(f"Failed to preload game data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Start background task for cleaning up stuck downloads
    asyncio.create_task(cleanup_stuck_downloads())
    
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
        from app.config import settings
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

async def cleanup_stuck_downloads():
    """Background task to detect and clean up stuck downloads.
    
    - Downloads with status 'downloading' and no progress for 2 minutes -> set to 'stuck'
    - Downloads with status 'stuck' for more than 5 minutes -> remove from queue
    """
    from app.database import get_db, DownloadQueue
    from datetime import timedelta
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            
            # Get database session
            db = next(get_db())
            try:
                now = datetime.now(timezone.utc)
                
                # 1. Check downloads with status 'downloading' - if no progress for 30 seconds, move back to user_queue for retry
                stuck_threshold = now - timedelta(seconds=30)
                
                stuck_downloads = db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'downloading',
                    DownloadQueue.active_download == True
                ).filter(
                    or_(
                        DownloadQueue.last_progress_at < stuck_threshold,
                        and_(
                            DownloadQueue.last_progress_at.is_(None),
                            DownloadQueue.started_at.isnot(None),
                            DownloadQueue.started_at < stuck_threshold
                        )
                    )
                ).all()
                
                retried_count = 0
                for download in stuck_downloads:
                    logger.warning(f"Download {download.id} (game: {download.game_id}) has no progress for 30+ seconds, moving back to user_queue for retry")
                    
                    # Move back to user_queue so it can be retried
                    download.status = 'user_queue'
                    download.active_download = False
                    download.assigned_to_service = None
                    # Reset started_at so it can be retried fresh
                    download.started_at = None
                    # Keep last_progress_at to track when it was last attempted
                    
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

