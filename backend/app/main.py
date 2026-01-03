"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.database import init_db
from app.api.routes import auth, catalog, downloads, users
import logging

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

# Add session middleware
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


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Batocera Games Catalog API", "version": "1.0.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

