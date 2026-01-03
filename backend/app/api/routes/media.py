"""Media upload and validation routes."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from typing import List
from app.api.middleware.roles import require_admin_role
from app.services.media import MediaService
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
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Upload media file for a game."""
    try:
        # Validate file type (images only for now)
        allowed_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
        file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''
        
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
        
        # Check file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size exceeds 10MB limit"
            )
        
        # Upload file
        success = media_service.upload_media(
            system=system,
            game_id=game_id,
            media_type=media_type,
            file_content=file_content,
            file_extension=file_extension
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload media file"
            )
        
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
    media_service: MediaService = Depends(get_media_service)
):
    """Get list of pending media uploads."""
    try:
        pending = media_service.get_pending_media()
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
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Validate and move media from pending to final location."""
    try:
        success = media_service.validate_media(system, fieldname, filename)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to validate media file"
            )
        
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
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Delete pending media file."""
    try:
        success = media_service.delete_pending_media(system, fieldname, filename)
        
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

@router.get("/pending-preview/{system}/{fieldname}/{filename:path}")
async def get_pending_media_preview(
    system: str,
    fieldname: str,
    filename: str,
    current_user: dict = Depends(require_admin_role),
    media_service: MediaService = Depends(get_media_service)
):
    """Get preview of pending media file."""
    from fastapi.responses import FileResponse
    from pathlib import Path
    
    try:
        if not media_service.users_media_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="USERS_MEDIA_PATH is not configured"
            )
        
        file_path = Path(media_service.users_media_path) / system / fieldname / filename
        
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

