"""Catalog routes."""
from fastapi import APIRouter, Query, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db, System
from app.services.game import GameService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
from app.api.middleware.roles import require_admin_role
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
    db: Session = Depends(get_db),
    game_service: GameService = Depends(get_game_service)
):
    """Get list of all enabled systems from database."""
    # Get enabled systems from database
    db_systems = db.query(System).filter(System.enabled == True).order_by(System.name).all()
    
    # Ensure gamelists are loaded to count games
    if not game_service._gamelists_loaded:
        game_service.preload_all_gamelists()
    
    # Build systems list with game counts
    systems = []
    for db_system in db_systems:
        # Count games for this system
        game_count = 0
        if db_system.id in game_service.gamelists:
            root = game_service.gamelists[db_system.id]
            from app.services.game import _is_game_hidden
            for game in root.findall('.//game'):
                if not _is_game_hidden(game):
                    game_count += 1
        
        # Use fullname from database, fallback to name
        display_name = db_system.fullname or db_system.name
        
        systems.append({
            'id': db_system.id,
            'name': display_name,
            'gameCount': game_count,
            'hardware': db_system.hardware or 'unknown',
            'manufacturer': db_system.manufacturer or 'Unknown',
            'release': db_system.release or 'Unknown'
        })
    
    return {"systems": systems}

@router.get("/games/{system}")
async def get_games(
    system: str,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Get games for a specific system."""
    games = game_service.get_games_by_system(system, page, limit, search or '')
    has_more = game_service.has_more_games(system, page, limit)
    
    # Get system download_enabled status from database and add to each game
    db_system = db.query(System).filter(System.id == system).first()
    download_enabled = db_system.download_enabled if db_system else False
    
    # Add download_enabled to each game
    for game in games:
        game['download_enabled'] = download_enabled
    
    # Get subdirectory counts for this system
    subdirectory_counts = game_service.get_subdirectory_counts(system)
    
    return {
        "games": games,
        "hasMore": has_more,
        "subdirectory_counts": subdirectory_counts
    }

@router.get("/search")
async def search_games(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Search games across all systems using partitioned index."""
    # Use indexed search - get enough results for pagination
    # Calculate how many we need: current page + 1 extra page to check if there's more
    max_results_needed = page * limit + limit
    all_results = game_service.search_indexed_games(q, limit=max_results_needed)
    
    # Get download_enabled status for all systems in results
    systems_in_results = {game['system'] for game in all_results}
    systems_download_enabled = {}
    for system_id in systems_in_results:
        db_system = db.query(System).filter(System.id == system_id).first()
        systems_download_enabled[system_id] = db_system.download_enabled if db_system else False
    
    # Add download_enabled to each game
    for game in all_results:
        game['download_enabled'] = systems_download_enabled.get(game['system'], False)
    
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
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Quick search using indexed games (for header search)."""
    games = game_service.search_indexed_games(q, limit)
    
    # Get download_enabled status for all systems in results
    systems_in_results = {game['system'] for game in games}
    systems_download_enabled = {}
    for system_id in systems_in_results:
        db_system = db.query(System).filter(System.id == system_id).first()
        systems_download_enabled[system_id] = db_system.download_enabled if db_system else False
    
    # Add download_enabled to each game
    for game in games:
        game['download_enabled'] = systems_download_enabled.get(game['system'], False)
    
    return {
        "results": games,
        "count": len(games)
    }

@router.get("/game/{system}/{game_id:path}")
async def get_game_details(
    system: str,
    game_id: str,
    current_user: dict = Depends(require_guild_member),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific game."""
    import urllib.parse
    
    # URL decode the game_id (FastAPI path parameters are already decoded, but double-check)
    decoded_game_id = urllib.parse.unquote(game_id)
    
    # The game_id from gamelist.xml is the path relative to the system directory
    # It might be like "./game.zip" or "subdir/game.zip" or just "game.zip"
    # We need to pass just the rompath (without system prefix) to get_game_by_id
    # because get_game_by_id searches across all systems
    
    # Remove system prefix if present
    if decoded_game_id.startswith(f"{system}/"):
        decoded_game_id = decoded_game_id[len(system) + 1:]
    
    # Remove leading ./ if present
    decoded_game_id = decoded_game_id.lstrip('./')
    
    logger.info(f"Getting game details - system: {system}, game_id: {game_id}, decoded: {decoded_game_id}")
    
    # get_game_by_id expects just the rompath (relative to system directory)
    game = game_service.get_game_by_id(decoded_game_id)
    
    if not game:
        from fastapi import HTTPException, status
        logger.warning(f"Game not found - system: {system}, game_id: {decoded_game_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    
    # Get system download_enabled status from database
    from app.database import System
    db_system = db.query(System).filter(System.id == system).first()
    if db_system:
        game['download_enabled'] = db_system.download_enabled
    else:
        # No fallback - downloads disabled if system not found in database
        game['download_enabled'] = False
    
    return game

@router.post("/refresh")
async def refresh_catalog(
    current_user: dict = Depends(require_admin_role),
    game_service: GameService = Depends(get_game_service)
):
    """Refresh catalog cache and search index (admin only)."""
    logger.info(f"Admin {current_user.get('username')} requested catalog refresh")
    result = game_service.refresh_catalog()
    return result

