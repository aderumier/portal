"""Media upload and validation routes."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from typing import List
from sqlalchemy.orm import Session
from app.api.middleware.roles import require_admin_role, require_media_contributor
from app.services.media import MediaService
from app.database import get_db, User
from sqlalchemy import text
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
        image_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
        video_extensions = ['mp4', 'mkv', 'avi', 'webm']
        file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''

        is_video_upload = media_type == 'video'
        allowed_extensions = video_extensions if is_video_upload else image_extensions

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
    """Get list of pending media uploads with username information."""
    try:
        pending = media_service.get_pending_media()
        
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

