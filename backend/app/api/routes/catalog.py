"""Catalog routes."""
from fastapi import APIRouter, Query, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.game import GameService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Shared GameService instance (singleton pattern)
_game_service_instance = None

def get_game_service() -> GameService:
    """Get shared game service instance (singleton)."""
    global _game_service_instance
    if _game_service_instance is None:
        _game_service_instance = GameService()
    return _game_service_instance

@router.get("/systems")
async def get_systems(
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service)
):
    """Get list of all systems."""
    systems = game_service.get_systems()
    return {"systems": systems}

@router.get("/games/{system}")
async def get_games(
    system: str,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service)
):
    """Get games for a specific system."""
    games = game_service.get_games_by_system(system, page, limit, search or '')
    has_more = game_service.has_more_games(system, page, limit)
    
    return {
        "games": games,
        "hasMore": has_more
    }

@router.get("/search")
async def search_games(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service)
):
    """Search games across all systems using partitioned index."""
    # Use indexed search - get enough results for pagination
    # Calculate how many we need: current page + 1 extra page to check if there's more
    max_results_needed = page * limit + limit
    all_results = game_service.search_indexed_games(q, limit=max_results_needed)
    
    # Apply pagination
    offset = (page - 1) * limit
    paginated_results = all_results[offset:offset + limit]
    has_more = len(all_results) > (page * limit)
    
    return {
        "results": paginated_results,
        "hasMore": has_more
    }

@router.get("/search/quick")
async def quick_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service)
):
    """Quick search using indexed games (for header search)."""
    games = game_service.search_indexed_games(q, limit)
    
    return {
        "results": games,
        "count": len(games)
    }

