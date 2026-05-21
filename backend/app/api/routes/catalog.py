"""Catalog routes."""
from fastapi import APIRouter, Query, Depends, Request, HTTPException, status
from fastapi.responses import ORJSONResponse, Response
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db, System, User
from app.services.game import GameService
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.guild import require_guild_member
from app.api.middleware.roles import get_catalog_viewer_roles, require_admin_role, require_catalog_viewer, require_media_contributor
from app.services import torrent as torrent_service
from app.config import settings
import logging
import orjson

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
    request: Request,
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    db: Session = Depends(get_db),
    game_service: GameService = Depends(get_game_service)
):
    """Get list of all enabled systems from database."""
    # Generate ETag for systems list (include catalog_type to avoid cache conflicts)
    base_etag = game_service.get_systems_etag()
    etag = f'{base_etag}-{catalog_type}'
    
    # Check if client has cached version (If-None-Match header)
    if_none_match = request.headers.get("if-none-match", "")
    if if_none_match == etag:
        # Content hasn't changed, return 304 Not Modified
        return Response(status_code=304, headers={"ETag": etag})
    
    # Get enabled systems from database
    db_systems = db.query(System).filter(System.enabled == True).order_by(System.name).all()
    
    # Ensure catalog is loaded to count games
    if not game_service._gamelists_loaded:
        game_service.preload_all_gamelists()
    
    # Select appropriate catalog and dates based on catalog_type
    if catalog_type == 'wip':
        catalog = game_service.catalog_wip
        gamelist_dates = game_service.system_gamelist_date_wip
    else:
        catalog = game_service.catalog_releases
        gamelist_dates = game_service.system_gamelist_date_releases
    
    # Build systems list with game counts
    systems = []
    for db_system in db_systems:
        # Get version if available
        version = game_service.system_versions.get(db_system.id)
        
        # If catalog_type is 'releases', only include systems that have a releases catalog (version exists)
        if catalog_type == 'releases' and not version:
            continue
        
        # Count games for this system using the appropriate catalog
        game_count = 0
        if db_system.id in catalog:
            game_count = len(catalog[db_system.id])
        
        # Use fullname from database, fallback to name
        display_name = db_system.fullname or db_system.name
        
        systems.append({
            'id': db_system.id,
            'name': display_name,
            'gameCount': game_count,
            'hardware': db_system.hardware or 'unknown',
            'manufacturer': db_system.manufacturer or 'Unknown',
            'release': db_system.release or 'Unknown',
            'version': version,
            'gamelistDate': gamelist_dates.get(db_system.id),
            'torrent_available': torrent_service.base_torrent_exists(db_system.id),
        })
    
    media_version = int(game_service._catalog_timestamp) if game_service._catalog_timestamp else 0
    response_data = {"systems": systems, "media_version": media_version}
    
    # Return response with ETag header for future 304 checks
    response = ORJSONResponse(content=response_data)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"  # Require revalidation via ETag
    return response

@router.get("/games/{system}")
async def get_games(
    request: Request,
    system: str,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=10000),
    search: Optional[str] = Query(None),
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Get games for a specific system."""
    # Only use ETag caching for non-search requests (search results are dynamic)
    use_etag = not search
    
    if use_etag:
        # Generate ETag for this request
        etag = game_service.get_catalog_etag(system, '', catalog_type)
        
        # Check if client has cached version (If-None-Match header)
        if_none_match = request.headers.get("if-none-match", "")
        if if_none_match == etag:
            # Content hasn't changed, return 304 Not Modified
            return Response(status_code=304, headers={"ETag": etag})
    
    # If limit is very large, get all games in one call
    if limit >= 10000:
        games = game_service.get_games_by_system(system, 1, 100000, search or '', catalog_type)
        has_more = False
    else:
        games = game_service.get_games_by_system(system, page, limit, search or '', catalog_type)
        has_more = game_service.has_more_games(system, page, limit, catalog_type)
    
    # Get system download_enabled status from database and add to each game
    db_system = db.query(System).filter(System.id == system).first()
    download_enabled = db_system.download_enabled if db_system else False
    
    # Add download_enabled to each game (optimized: update in-place, no new dict creation)
    [game.update({'download_enabled': download_enabled}) for game in games]
    
    # Get subdirectory counts for this system
    subdirectory_counts = game_service.get_subdirectory_counts(system, catalog_type)
    
    response_data = {
        "games": games,
        "hasMore": has_more,
        "subdirectory_counts": subdirectory_counts
    }
    
    # Return response - only add ETag for non-search requests
    if use_etag:
        # Use ORJSONResponse for efficient JSON serialization, but add ETag header
        response = ORJSONResponse(content=response_data)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "no-cache"  # Require revalidation via ETag
        return response
    else:
        # Search results - no ETag, don't cache
        response = ORJSONResponse(content=response_data)
        response.headers["Cache-Control"] = "no-store"  # Don't cache search results
        return response

@router.get("/search")
async def search_games(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100),
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Search games across all systems using partitioned index."""
    # Use indexed search - get enough results for pagination
    # Calculate how many we need: current page + 1 extra page to check if there's more
    max_results_needed = page * limit + limit
    all_results = game_service.search_indexed_games(q, limit=max_results_needed, catalog_type=catalog_type)
    
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
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Quick search using indexed games (for header search)."""
    games = game_service.search_indexed_games(q, limit, catalog_type=catalog_type)
    
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
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer),
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
    
    logger.info(f"Getting game details - system: {system}, game_id: {game_id}, decoded: {decoded_game_id}, catalog_type: {catalog_type}")
    
    # get_game_by_id expects just the rompath (relative to system directory) and system_id
    game = game_service.get_game_by_id(decoded_game_id, system, catalog_type)
    
    if not game:
        from fastapi import HTTPException, status
        logger.warning(f"Game not found - system: {system}, game_id: {decoded_game_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found"
        )
    
    # Media paths are already normalized in get_game_by_id (including snapshot prefix for Releases)
    # No additional normalization needed here
    
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

@router.get("/preference")
async def get_catalog_preference(
    request: Request,
    current_user: dict = Depends(require_guild_member)
):
    """Get user's catalog type preference from session."""
    catalog_type = request.session.get('catalog_type', 'releases')
    can_view_releases = (
        current_user.get('is_admin', False)
        or not get_catalog_viewer_roles('releases')
        or current_user.get('is_release_catalog_viewer', False)
    )
    can_view_wip = (
        current_user.get('is_admin', False)
        or not get_catalog_viewer_roles('wip')
        or current_user.get('is_wip_catalog_viewer', False)
    )
    
    if catalog_type == 'releases' and not can_view_releases:
        catalog_type = 'wip' if can_view_wip else 'releases'
    elif catalog_type == 'wip' and not can_view_wip:
        catalog_type = 'releases' if can_view_releases else 'wip'

    contributor_roles = settings.MEDIA_CONTRIBUTORS
    can_contribute = (
        current_user.get('is_admin', False)
        or not contributor_roles
        or current_user.get('is_media_contributor', False)
        or any(current_user.get('media_contributor_roles', {}).get(r, False) for r in contributor_roles)
    )

    return {
        "catalog_type": catalog_type,
        "can_view_releases": can_view_releases,
        "can_view_wip": can_view_wip,
        "can_contribute": can_contribute,
    }

@router.put("/preference")
async def set_catalog_preference(
    request: Request,
    catalog_type: str = Query(..., regex='^(wip|releases)$'),
    current_user: dict = Depends(require_catalog_viewer)
):
    """Set user's catalog type preference in session."""
    request.session['catalog_type'] = catalog_type
    return {"catalog_type": catalog_type, "message": "Preference updated"}

@router.get("/games/top/downloads")
async def get_top_downloads(
    limit: int = Query(100, ge=1, le=1000),
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    sort_by: Optional[str] = Query('download_count', regex='^(download_count|playcount|gametime)$'),
    current_user: dict = Depends(require_catalog_viewer),
    game_service: GameService = Depends(get_game_service)
):
    """Get top games sorted by criteria (default: downloads)."""
    return game_service.get_top_games(limit=limit, catalog_type=catalog_type, sort_by=sort_by)

@router.get("/torrent-systems")
async def get_torrent_systems(
    current_user: dict = Depends(require_guild_member),
):
    """Return the list of system IDs that have a torrent file available.
    Always reads from disk — no catalog cache involved."""
    from app.services.torrent import TORRENTS_DIR
    if not TORRENTS_DIR.exists():
        return {"system_ids": []}
    system_ids = [p.stem for p in TORRENTS_DIR.glob("*.torrent")]
    return {"system_ids": system_ids}


@router.get("/systems/{system_id}/torrent")
async def download_system_torrent(
    system_id: str,
    current_user: dict = Depends(require_guild_member),
    db: Session = Depends(get_db)
):
    """Download a per-user .torrent file for a system (any logged-in guild member)."""
    db_system = db.query(System).filter(System.id == system_id, System.enabled == True).first()
    if not db_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    if not torrent_service.base_torrent_exists(system_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No torrent available for this system")

    if not settings.TRACKER_ANNOUNCE_URL:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Torrent tracker not configured")

    user_id = current_user.get("id")
    db_user = db.query(User).filter(User.user_id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User record not found")

    # Generate passkey on first use
    if not db_user.torrent_passkey:
        db_user.torrent_passkey = torrent_service.generate_passkey()
        db.commit()
        db.refresh(db_user)

    torrent_bytes = torrent_service.build_user_torrent(system_id, db_user.torrent_passkey)
    if torrent_bytes is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate torrent")

    filename = f"{system_id}.torrent"
    return Response(
        content=torrent_bytes,
        media_type="application/x-bittorrent",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/contribute/systems")
async def get_contribute_systems(
    request: Request,
    current_user: dict = Depends(require_media_contributor),
    db: Session = Depends(get_db),
    game_service: GameService = Depends(get_game_service)
):
    """Get systems with count of games missing fanart, marquee, or video (WIP catalog, any logged-in user)."""
    if not game_service._gamelists_loaded:
        game_service.preload_all_gamelists()

    catalog = game_service.catalog_wip
    gamelist_dates = game_service.system_gamelist_date_wip

    db_systems = db.query(System).filter(System.enabled == True).order_by(System.name).all()

    systems = []
    for db_system in db_systems:
        if db_system.id not in catalog:
            continue
        system_catalog = catalog[db_system.id]
        missing_count = 0
        for game_data in system_catalog.values():
            fanart = game_data.get('fanart', '')
            marquee = game_data.get('marquee', '')
            video = game_data.get('video', '')
            if not fanart or not marquee or not video:
                missing_count += 1
        if missing_count == 0:
            continue
        display_name = db_system.fullname or db_system.name
        systems.append({
            'id': db_system.id,
            'name': display_name,
            'missingMediaCount': missing_count,
            'hardware': db_system.hardware or 'unknown',
            'manufacturer': db_system.manufacturer or 'Unknown',
            'release': db_system.release or 'Unknown',
            'gamelistDate': gamelist_dates.get(db_system.id),
        })

    media_version = int(game_service._catalog_timestamp) if game_service._catalog_timestamp else 0
    return ORJSONResponse(content={"systems": systems, "media_version": media_version})


@router.get("/contribute/games/{system}")
async def get_contribute_games(
    system: str,
    current_user: dict = Depends(require_media_contributor),
    game_service: GameService = Depends(get_game_service),
    db: Session = Depends(get_db)
):
    """Get games with missing fanart, marquee, or video for a system (WIP catalog, any logged-in user)."""
    if not game_service._gamelists_loaded:
        game_service.preload_all_gamelists()

    catalog = game_service.catalog_wip
    catalog_sorted_keys = game_service.catalog_sorted_keys_wip

    if system not in catalog:
        return ORJSONResponse(content={"games": []})

    system_catalog = catalog[system]
    sorted_rompaths = catalog_sorted_keys.get(system, [])

    fullname = game_service.system_fullname.get(system)
    system_name = fullname if fullname else game_service.get_system_name(system)

    def _norm(path):
        if not path:
            return ''
        p = path.lstrip('./')
        if not p.startswith(f"{system}/"):
            return f"{system}/{p}"
        return p

    games = []
    for rompath in sorted_rompaths:
        if rompath not in system_catalog:
            continue
        game_data = system_catalog[rompath]
        fanart = game_data.get('fanart', '')
        marquee = game_data.get('marquee', '')
        video = game_data.get('video', '')
        if fanart and marquee and video:
            continue

        catalog_image = game_data.get('catalog_image', '')
        if catalog_image:
            clean = catalog_image.lstrip('./')
            if not clean.startswith(f"{system}/"):
                catalog_image = f"{system}/{clean}"
            else:
                catalog_image = clean

        games.append({
            'id': rompath,
            'name': game_data.get('name', ''),
            'system': system,
            'systemName': system_name,
            'publisher': game_data.get('publisher', ''),
            'releasedate': game_data.get('releasedate', ''),
            'catalog_image': catalog_image,
            'thumbnail': _norm(game_data.get('thumbnail', '')),
            'boxart': _norm(game_data.get('boxart', '')),
            'fanart': _norm(fanart),
            'marquee': _norm(marquee),
            'video': _norm(video),
        })

    media_version = int(game_service._catalog_timestamp) if game_service._catalog_timestamp else 0
    return ORJSONResponse(content={"games": games, "media_version": media_version})


@router.get("/systems/top/downloads")
async def get_top_systems_downloads(
    limit: int = Query(100, ge=1, le=1000),
    catalog_type: Optional[str] = Query('releases', regex='^(wip|releases)$'),
    sort_by: Optional[str] = Query('download_count', regex='^(download_count|playcount|gametime)$'),
    current_user: dict = Depends(require_admin_role),
    game_service: GameService = Depends(get_game_service)
):
    """Get top systems sorted by aggregated downloads (admin only)."""
    return game_service.get_top_systems(limit=limit, catalog_type=catalog_type, sort_by=sort_by)
