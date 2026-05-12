"""Collections routes."""
from fastapi import APIRouter, Query, Depends, Request
from fastapi.responses import ORJSONResponse, Response
from typing import Optional
from sqlalchemy.orm import Session
import logging

from app.database import get_db, System
from app.services.game import GameService
from app.services.collection import CollectionService
from app.api.middleware.roles import require_catalog_viewer
from app.api.routes.catalog import get_game_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared CollectionService instance
_collection_service_instance = None

def get_collection_service() -> CollectionService:
    """Get shared collection service instance."""
    global _collection_service_instance
    if _collection_service_instance is None:
        _collection_service_instance = CollectionService()
    return _collection_service_instance

@router.get("")
async def get_collections(
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service),
    collection_service: CollectionService = Depends(get_collection_service)
):
    """Get list of all custom collections."""
    collections = collection_service.get_collections(game_service, catalog_type)
    
    # Return response
    return ORJSONResponse(content={"collections": collections})

@router.get("/{collection_id}")
async def get_collection_games(
    collection_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=10000),
    search: Optional[str] = Query(None),
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service),
    collection_service: CollectionService = Depends(get_collection_service),
    db: Session = Depends(get_db)
):
    """Get games for a specific collection."""
    
    # Let collection service parse the cfg file and extract games via GameService
    games = collection_service.get_collection_games(
        collection_id=collection_id,
        game_service=game_service,
        page=page,
        limit=limit,
        search=search,
        catalog_type=catalog_type
    )

    # Determine hasMore
    total_count = collection_service.get_collection_game_count(collection_id, search)
    has_more = (page * limit) < total_count
    
    # Extract unique system IDs from the returned games
    system_ids = list(set([game.get('system') for game in games if game.get('system')]))
    
    # Fetch download_enabled status for these systems
    system_download_enabled = {}
    if system_ids:
        db_systems = db.query(System.id, System.download_enabled).filter(System.id.in_(system_ids)).all()
        for sys_id, download_enabled in db_systems:
            system_download_enabled[sys_id] = download_enabled

    # Attach download_enabled flag to each game
    for game in games:
        sys_id = game.get('system')
        game['download_enabled'] = system_download_enabled.get(sys_id, False)
        
    response_data = {
        "games": games,
        "hasMore": has_more,
        "subdirectory_counts": {} # Collections don't have subdirectories like systems do usually
    }
    
    return ORJSONResponse(content=response_data)
