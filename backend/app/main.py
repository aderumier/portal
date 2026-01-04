"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.database import init_db
from app.api.routes import auth, catalog, downloads, users, media
import logging
import os
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_, and_

logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Create FastAPI app
app = FastAPI(
    title="Batocera Games Catalog API",
    description="API for browsing and downloading games from Batocera system",
    version="1.0.0"
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
        game_service.build_search_index()
        logger.info("Search index preloaded on startup")
    except Exception as e:
        logger.warning(f"Failed to preload game data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Start background task for cleaning up stuck downloads
    asyncio.create_task(cleanup_stuck_downloads())

# Add session middleware (in-memory sessions)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=3600 * 24 * 7,  # 7 days
    same_site="lax"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(catalog.router, prefix="/api", tags=["catalog"])
app.include_router(downloads.router, prefix="/api/download", tags=["downloads"])
app.include_router(users.router, prefix="/api", tags=["users"])

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

