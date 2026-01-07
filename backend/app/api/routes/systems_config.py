"""Systems configuration routes."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db, System
from app.api.middleware.roles import require_admin_role
from app.services.system_import import SystemImportService
from app.services.system_image import SystemImageService
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

def get_system_image_service() -> SystemImageService:
    """Get system image service instance."""
    return SystemImageService()

class SystemUpdate(BaseModel):
    """System update model."""
    fullname: str = None
    hardware: str = None
    release: str = None
    manufacturer: str = None
    batocera_system: str = None
    retrobat_system: str = None
    enabled: bool = None
    download_enabled: bool = None

@router.get("/systems")
async def get_systems(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Get all systems from database."""
    systems = db.query(System).order_by(System.name).all()
    return {
        "systems": [
            {
                "id": s.id,
                "name": s.name,
                "fullname": s.fullname,
                "hardware": s.hardware,
                "release": s.release,
                "manufacturer": s.manufacturer,
                "batocera_system": s.batocera_system,
                "retrobat_system": s.retrobat_system,
                "enabled": s.enabled,
                "download_enabled": s.download_enabled,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in systems
        ]
    }

@router.post("/systems/import")
async def import_systems(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Import systems from GAMES_PATH and update with info from es_systems*.cfg."""
    logger.info(f"Admin {current_user.get('username')} requested system import")
    
    try:
        import_service = SystemImportService()
        result = import_service.import_systems(db)
        return result
    except Exception as e:
        logger.error(f"Error importing systems: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import systems: {str(e)}"
        )

@router.put("/systems/{system_id}")
async def update_system(
    system_id: str,
    system_update: SystemUpdate,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Update a system."""
    db_system = db.query(System).filter(System.id == system_id).first()
    
    if not db_system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System not found"
        )
    
    # Update fields if provided
    if system_update.fullname is not None:
        db_system.fullname = system_update.fullname
    if system_update.hardware is not None:
        db_system.hardware = system_update.hardware
    if system_update.release is not None:
        db_system.release = system_update.release
    if system_update.manufacturer is not None:
        db_system.manufacturer = system_update.manufacturer
    if system_update.batocera_system is not None:
        db_system.batocera_system = system_update.batocera_system
    if system_update.retrobat_system is not None:
        db_system.retrobat_system = system_update.retrobat_system
    if system_update.enabled is not None:
        db_system.enabled = system_update.enabled
    if system_update.download_enabled is not None:
        db_system.download_enabled = system_update.download_enabled
    
    db.commit()
    db.refresh(db_system)
    
    return {
        "id": db_system.id,
        "name": db_system.name,
        "fullname": db_system.fullname,
        "hardware": db_system.hardware,
        "release": db_system.release,
        "manufacturer": db_system.manufacturer,
        "batocera_system": db_system.batocera_system,
        "retrobat_system": db_system.retrobat_system,
        "enabled": db_system.enabled,
        "download_enabled": db_system.download_enabled,
    }

@router.post("/systems/{system_id}/image")
async def upload_system_image(
    system_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
    image_service: SystemImageService = Depends(get_system_image_service)
):
    """Upload system image and convert to WebP."""
    # Verify system exists
    db_system = db.query(System).filter(System.id == system_id).first()
    if not db_system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System not found"
        )
    
    # Validate file type
    allowed_extensions = ['png', 'jpg', 'jpeg', 'gif', 'webp']
    file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Read file content
    try:
        file_content = await file.read()
    except Exception as e:
        logger.error(f"Error reading uploaded file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read uploaded file"
        )
    
    # Upload and convert to WebP
    success = image_service.upload_system_image(system_id, file_content, file_extension)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload and convert system image"
        )
    
    return {
        "success": True,
        "message": f"System image uploaded and converted to {system_id}.webp"
    }

