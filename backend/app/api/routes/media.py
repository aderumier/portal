"""Media upload and validation routes."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.middleware.roles import require_admin_role, require_media_contributor
from app.services.media import MediaService
from app.database import get_db, User
from app.config import settings
from sqlalchemy import text
import os
import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()

def get_media_service() -> MediaService:
    """Get media service instance."""
    return MediaService()

async def _fetch_external_romfile_map(client, system):
    """Fetch a ``{stem: romfile}`` map for a system from the external gamelist
    service. Used to resolve romfiles for systems not present in the local WIP
    catalog (the contribute game list is sourced from the same service)."""
    try:
        resp = await client.get(
            f"{settings.GAMELIST_SERVICE_URL}/api/external/games",
            params={"system": system},
            headers={"X-API-Token": settings.GAMELIST_API_TOKEN},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Error fetching external games for system '{system}': {e}", exc_info=True)
        return {}

    romfile_map = {}
    for game in data.get('games', []):
        romfile = game.get('romfile', '')
        if not romfile:
            continue
        stem = os.path.splitext(os.path.basename(romfile))[0]
        romfile_map[stem] = romfile if romfile.startswith('./') else f'./{romfile}'
    return romfile_map


async def _notify_gamelist_add_media(items):
    """Notify the external gamelist service that media files were added.

    items: list of dicts with keys ``system``, ``fieldname``, ``filename``.
    Items are grouped by system and sent as a single batched request per
    system using the ``/api/external/add-media`` batch format:
        {"system": "snes", "media": [{"romfile", "mediatype", "mediafilename"}, ...]}

    The romfile for each item is resolved from the local WIP catalog when
    available, falling back to the external gamelist service for systems not
    tracked locally.
    """
    if not settings.GAMELIST_SERVICE_URL or not items:
        return

    from app.api.routes.catalog import get_game_service
    game_service = get_game_service()

    async with httpx.AsyncClient(timeout=30.0) as client:
        external_maps = {}  # system -> {stem: romfile}, fetched lazily

        # Resolve each item's romfile and group by system
        by_system = {}
        for item in items:
            system = item['system']
            fieldname = item['fieldname']
            filename = item['filename']
            stem = os.path.splitext(filename)[0]

            system_catalog = game_service.catalog_wip.get(system, {})
            rompath = next(
                (k for k in system_catalog if os.path.splitext(os.path.basename(k))[0] == stem),
                None
            )
            if rompath:
                romfile = rompath if rompath.startswith('./') else f'./{rompath}'
            else:
                if system not in external_maps:
                    external_maps[system] = await _fetch_external_romfile_map(client, system)
                romfile = external_maps[system].get(stem)

            if not romfile:
                logger.warning(f"Could not find romfile for stem '{stem}' in system '{system}' (local catalog or external)")
                continue

            by_system.setdefault(system, []).append({
                "romfile": romfile,
                "mediatype": fieldname,
                "mediafilename": filename,
            })

        if not by_system:
            return

        for system, media_list in by_system.items():
            try:
                resp = await client.post(
                    f"{settings.GAMELIST_SERVICE_URL}/api/external/add-media",
                    json={"system": system, "media": media_list},
                    headers={"X-API-Token": settings.GAMELIST_API_TOKEN},
                )
                resp.raise_for_status()
                logger.info(f"Notified gamelist service for system '{system}' with {len(media_list)} media item(s)")
            except Exception as e:
                logger.error(f"Error notifying gamelist service for system '{system}': {e}", exc_info=True)

@router.post("/upload")
async def upload_media(
    system: str = Form(...),
    game_id: str = Form(...),
    media_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_media_contributor),
    media_service: MediaService = Depends(get_media_service),
    db: Session = Depends(get_db)
):
    """Upload media file for a game."""
    try:
        # Validate file type
        restricted_extensions = {
            'marquee': ['png'],
            'fanart':  ['jpg', 'jpeg'],
            'video':   ['mp4'],
        }
        default_image_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
        default_video_extensions = ['mp4', 'mkv', 'avi', 'webm']
        file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''

        is_video_upload = media_type == 'video'
        allowed_extensions = restricted_extensions.get(
            media_type,
            default_video_extensions if is_video_upload else default_image_extensions
        )

        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Validate media type
        valid_media_types = ['thumbnail', 'boxart', 'boxback', 'marquee', 'fanart', 
                           'cartridge', 'titleshot', 'image', 'screenshot', 'wheel', 'mix', 'video']
        if media_type not in valid_media_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid media type. Allowed: {', '.join(valid_media_types)}"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Check file size (10 MB for images, 200 MB for video)
        max_size = 200 * 1024 * 1024 if is_video_upload else 10 * 1024 * 1024
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds {'200MB' if is_video_upload else '10MB'} limit"
            )
        
        # Get user_id from current_user
        user_id = current_user.get('id')
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User ID not found"
            )
        
        # Upload file
        success = media_service.upload_media(
            system=system,
            game_id=game_id,
            media_type=media_type,
            file_content=file_content,
            file_extension=file_extension,
            user_id=user_id
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload media file"
            )
        
        # Increment medias_upload counter for user
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if user:
                user.medias_upload = (user.medias_upload or 0) + 1
                db.commit()
                logger.info(f"Incremented medias_upload for user {user_id}")
            else:
                # Create user record if it doesn't exist
                new_user = User(
                    user_id=user_id,
                    username=current_user.get('username'),
                    medias_upload=1,
                    medias_validated=0
                )
                db.add(new_user)
                db.commit()
                logger.info(f"Created user record for {user_id} with medias_upload=1")
        except Exception as e:
            logger.error(f"Error updating medias_upload counter: {e}", exc_info=True)
            db.rollback()
        
        return {
            "success": True,
            "message": "Media uploaded successfully and is pending validation"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading media: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while uploading media"
        )

@router.get("/pending-count")
async def get_pending_media_count(
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service),
):
    """Return the count of all pending media uploads (admin only, lightweight)."""
    return {"count": media_service.get_pending_media_count()}

@router.get("/pending")
async def get_pending_media(
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service),
    db: Session = Depends(get_db)
):
    """Get list of pending media uploads with username and game name information."""
    from app.api.routes.catalog import get_game_service
    try:
        pending = media_service.get_pending_media()

        # Build per-system stem→{name, rompath} lookup from the WIP catalog
        game_service = get_game_service()
        stem_name_cache: dict[str, dict] = {}
        for item in pending:
            system = item.get('system', '')
            if system not in stem_name_cache:
                system_catalog = game_service.catalog_wip.get(system, {})
                stem_name_cache[system] = {
                    os.path.splitext(os.path.basename(k))[0]: {'name': v.get('name', ''), 'rompath': k}
                    for k, v in system_catalog.items()
                }
            stem = os.path.splitext(item.get('filename', ''))[0]
            info = stem_name_cache[system].get(stem, {})
            item['game_name'] = info.get('name', stem)
            item['game_id'] = info.get('rompath', '')

        # Enrich with username information
        for item in pending:
            user_id = item.get('user_id')
            if user_id:
                user = db.query(User).filter(User.user_id == user_id).first()
                if user:
                    item['username'] = user.username
                else:
                    item['username'] = None
            else:
                item['username'] = None

        return {"pending_media": pending}
    except Exception as e:
        logger.error(f"Error getting pending media: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching pending media"
        )

@router.post("/validate")
async def validate_media(
    system: str = Form(...),
    fieldname: str = Form(...),
    filename: str = Form(...),
    user_id: str = Form(None),  # Optional, will be extracted from path if not provided
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service),
    db: Session = Depends(get_db)
):
    """Validate and move media from pending to final location."""
    try:
        success, validated_user_id = media_service.validate_media(system, fieldname, filename, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to validate media file"
            )
        
        # Increment medias_validated counter for the user who uploaded the media
        if validated_user_id:
            try:
                user = db.query(User).filter(User.user_id == validated_user_id).first()
                if user:
                    user.medias_validated = (user.medias_validated or 0) + 1
                    db.commit()
                    logger.info(f"Incremented medias_validated for user {validated_user_id}")
                else:
                    # Create user record if it doesn't exist
                    new_user = User(
                        user_id=validated_user_id,
                        medias_upload=0,
                        medias_validated=1
                    )
                    db.add(new_user)
                    db.commit()
                    logger.info(f"Created user record for {validated_user_id} with medias_validated=1")
            except Exception as e:
                logger.error(f"Error updating medias_validated counter: {e}", exc_info=True)
                db.rollback()

        # Notify external gamelist service
        await _notify_gamelist_add_media([
            {"system": system, "fieldname": fieldname, "filename": filename}
        ])

        return {
            "success": True,
            "message": "Media validated and moved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating media: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while validating media"
        )


class ValidateBatchItem(BaseModel):
    system: str
    fieldname: str
    filename: str
    user_id: Optional[str] = None


class ValidateBatchRequest(BaseModel):
    items: List[ValidateBatchItem]


@router.post("/validate-batch")
async def validate_media_batch(
    request: ValidateBatchRequest,
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service),
    db: Session = Depends(get_db)
):
    """Validate and move multiple pending media files in one request.

    Files are moved one by one (collecting per-file failures), user
    ``medias_validated`` counters are aggregated into a single commit per
    user, and the external gamelist service is notified with a single
    batched request per system.
    """
    validated = []
    failed = []
    user_counts = {}
    notify_items = []

    for item in request.items:
        try:
            success, validated_user_id = media_service.validate_media(
                item.system, item.fieldname, item.filename, item.user_id
            )
            if not success:
                failed.append({"filename": item.filename, "error": "Failed to validate media file"})
                continue

            validated.append(item.filename)
            if validated_user_id:
                user_counts[validated_user_id] = user_counts.get(validated_user_id, 0) + 1
            notify_items.append({
                "system": item.system,
                "fieldname": item.fieldname,
                "filename": item.filename,
            })
        except Exception as e:
            logger.error(f"Error validating media {item.filename}: {e}", exc_info=True)
            failed.append({"filename": item.filename, "error": str(e)})

    # Aggregate medias_validated counters (one commit per user)
    for validated_user_id, count in user_counts.items():
        try:
            user = db.query(User).filter(User.user_id == validated_user_id).first()
            if user:
                user.medias_validated = (user.medias_validated or 0) + count
            else:
                user = User(user_id=validated_user_id, medias_upload=0, medias_validated=count)
                db.add(user)
            db.commit()
            logger.info(f"Incremented medias_validated by {count} for user {validated_user_id}")
        except Exception as e:
            logger.error(f"Error updating medias_validated counter for {validated_user_id}: {e}", exc_info=True)
            db.rollback()

    # Notify external gamelist service (one batched request per system)
    await _notify_gamelist_add_media(notify_items)

    return {
        "success": len(failed) == 0,
        "validated": validated,
        "failed": failed,
    }


@router.delete("/pending")
async def delete_pending_media(
    system: str = Query(...),
    fieldname: str = Query(...),
    filename: str = Query(...),
    user_id: str = Query(None),  # Optional, will be searched if not provided
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Delete pending media file."""
    try:
        success = media_service.delete_pending_media(system, fieldname, filename, user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending media file not found"
            )
        
        return {
            "success": True,
            "message": "Pending media deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting pending media: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting pending media"
        )

@router.get("/my-pending")
async def get_my_pending_media(
    system: str = Query(None),
    current_user: dict = Depends(require_media_contributor),
    media_service: MediaService = Depends(get_media_service)
):
    """Get pending media for the current authenticated user, enriched with game info."""
    from app.api.routes.catalog import get_game_service
    user_id = current_user.get('id')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID not found")
    pending = media_service.get_pending_media_for_user(user_id, system)

    # Enrich with game_name and game_id from WIP catalog
    game_service = get_game_service()
    stem_name_cache: dict[str, dict] = {}
    for item in pending:
        sys = item.get('system', '')
        if sys not in stem_name_cache:
            system_catalog = game_service.catalog_wip.get(sys, {})
            stem_name_cache[sys] = {
                os.path.splitext(os.path.basename(k))[0]: {'name': v.get('name', ''), 'rompath': k}
                for k, v in system_catalog.items()
            }
        stem = os.path.splitext(item.get('filename', ''))[0]
        info = stem_name_cache[sys].get(stem, {})
        item['game_name'] = info.get('name', stem)
        item['game_id'] = info.get('rompath', '')

    return {"pending_media": pending}

@router.delete("/my-pending")
async def delete_my_pending_media(
    system: str = Query(...),
    fieldname: str = Query(...),
    filename: str = Query(...),
    current_user: dict = Depends(require_media_contributor),
    media_service: MediaService = Depends(get_media_service)
):
    """Delete a pending media file belonging to the current user."""
    user_id = current_user.get('id')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID not found")
    success = media_service.delete_pending_media(system, fieldname, filename, user_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending media file not found")
    return {"success": True, "message": "Pending media deleted successfully"}

def _overwrite_pending_file(media_service, user_id, system, fieldname, filename, content):
    """Overwrite an existing pending media file in place with new bytes.

    Used by the crop endpoints. Guards against path traversal and requires the
    target file to already exist (we only replace existing uploads, never create
    new ones here).
    """
    from pathlib import Path

    if not media_service.users_media_path:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="USERS_MEDIA_PATH not configured")

    base = Path(media_service.users_media_path) / user_id / system / fieldname
    target = (base / filename).resolve()
    # Ensure the resolved path stays inside the user's media directory
    if not str(target).startswith(str(base.resolve()) + os.sep):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending media file not found")

    target.write_bytes(content)
    return target

@router.post("/my-pending/crop")
async def crop_my_pending_media(
    system: str = Form(...),
    fieldname: str = Form(...),
    filename: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_media_contributor),
    media_service: MediaService = Depends(get_media_service)
):
    """Replace one of the current user's pending media files with a cropped version."""
    user_id = current_user.get('id')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID not found")
    content = await file.read()
    _overwrite_pending_file(media_service, user_id, system, fieldname, filename, content)
    return {"success": True, "message": "Image cropped successfully"}

@router.post("/pending/crop")
async def crop_pending_media(
    system: str = Form(...),
    fieldname: str = Form(...),
    filename: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Replace a pending media file (any user) with a cropped version. Admin only."""
    content = await file.read()
    _overwrite_pending_file(media_service, user_id, system, fieldname, filename, content)
    return {"success": True, "message": "Image cropped successfully"}

@router.get("/my-pending-preview/{system}/{fieldname}/{filename:path}")
async def get_my_pending_preview(
    system: str,
    fieldname: str,
    filename: str,
    current_user: dict = Depends(require_media_contributor),
    media_service: MediaService = Depends(get_media_service)
):
    """Serve a pending media file for the current authenticated user."""
    from fastapi.responses import FileResponse
    from pathlib import Path

    user_id = current_user.get('id')
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User ID not found")
    if not media_service.users_media_path:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="USERS_MEDIA_PATH not configured")

    file_path = Path(media_service.users_media_path) / user_id / system / fieldname / filename
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return FileResponse(path=str(file_path))

@router.get("/pending-preview/{user_id}/{system}/{fieldname}/{filename:path}")
async def get_pending_media_preview(
    user_id: str,
    system: str,
    fieldname: str,
    filename: str,
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Get preview of pending media file.
    
    New path structure: /pending-preview/{user_id}/{system}/{fieldname}/{filename}
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    
    try:
        if not media_service.users_media_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="USERS_MEDIA_PATH is not configured"
            )
        
        # New path structure: USERS_MEDIA_PATH/userid/system/fieldname/filename
        file_path = Path(media_service.users_media_path) / user_id / system / fieldname / filename
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        return FileResponse(
            path=str(file_path),
            media_type="image/png"  # Default, will be detected automatically
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving pending media preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while serving media preview"
        )

