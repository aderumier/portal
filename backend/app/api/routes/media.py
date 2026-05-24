"""Media upload and validation routes."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from typing import List
from sqlalchemy.orm import Session
from app.api.middleware.roles import require_admin_role, require_media_contributor
from app.services.media import MediaService
from app.database import get_db, User
from sqlalchemy import text
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

def get_media_service() -> MediaService:
    """Get media service instance."""
    return MediaService()

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

