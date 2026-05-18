"""Systems configuration routes."""
import threading
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db, System, User
from app.api.middleware.roles import require_admin_role
from app.services.system_import import SystemImportService
from app.services.system_image import SystemImageService
from app.services import torrent as torrent_service
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# One generation at a time; released by the background thread when done
_generation_lock = threading.Lock()
# system_id -> {'status': 'generating'|'done'|'error', 'message': str}
_generation_status: dict = {}


def _run_generate_torrent(system_id: str, snapshot_name: str) -> None:
    """Background thread: generate torrent and update status."""
    import time
    logger.info(f"[torrent-gen] START system={system_id} snapshot={snapshot_name}")
    t0 = time.monotonic()
    try:
        torrent_service.generate_torrent_from_snapshot(system_id, snapshot_name)
        elapsed = time.monotonic() - t0
        msg = f"Torrent generated from snapshot {snapshot_name} in {elapsed:.1f}s"
        _generation_status[system_id] = {"status": "done", "message": msg}
        logger.info(f"[torrent-gen] DONE system={system_id} elapsed={elapsed:.1f}s")
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.error(
            f"[torrent-gen] FAILED system={system_id} elapsed={elapsed:.1f}s error={e}",
            exc_info=True,
        )
        _generation_status[system_id] = {"status": "error", "message": str(e)}
    finally:
        _generation_lock.release()

router = APIRouter()

def get_system_image_service() -> SystemImageService:
    """Get system image service instance."""
    return SystemImageService()

class GenerateTorrentRequest(BaseModel):
    snapshot: str


class SystemUpdate(BaseModel):
    """System update model."""
    fullname: str = None
    hardware: str = None
    release: str = None
    manufacturer: str = None
    batocera_system: str = None
    retrobat_system: str = None
    batocera_extension: str = None
    retrobat_extension: str = None
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
                "batocera_extension": s.batocera_extension or "",
                "retrobat_extension": s.retrobat_extension or "",
                "enabled": s.enabled,
                "download_enabled": s.download_enabled,
                "torrent_available": torrent_service.base_torrent_exists(s.id),
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
    """Import systems from GAMES_PATH."""
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
    if system_update.batocera_extension is not None:
        db_system.batocera_extension = system_update.batocera_extension
    if system_update.retrobat_extension is not None:
        db_system.retrobat_extension = system_update.retrobat_extension
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
        "batocera_extension": db_system.batocera_extension or "",
        "retrobat_extension": db_system.retrobat_extension or "",
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


@router.post("/systems/{system_id}/torrent")
async def upload_system_torrent(
    system_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Upload a base .torrent file for a system (admin only)."""
    db_system = db.query(System).filter(System.id == system_id).first()
    if not db_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    if not file.filename.lower().endswith(".torrent"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a .torrent file")

    try:
        content = await file.read()
    except Exception as e:
        logger.error(f"Error reading torrent file: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to read uploaded file")

    # Basic validation: try parsing with torf
    try:
        import torf
        torf.Torrent.read_stream(content)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid torrent file: {e}")

    torrent_service.save_base_torrent(system_id, content)
    return {"success": True, "message": f"Torrent uploaded for system {system_id}"}


@router.get("/systems/{system_id}/snapshots")
async def list_system_snapshots(
    system_id: str,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """List available ZFS snapshots for a system (admin only)."""
    db_system = db.query(System).filter(System.id == system_id).first()
    if not db_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    snapshots = torrent_service.list_zfs_snapshots(system_id)
    return {"snapshots": snapshots}


@router.post("/systems/{system_id}/generate-torrent")
async def generate_system_torrent(
    system_id: str,
    request: GenerateTorrentRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Start background torrent generation from a ZFS snapshot (admin only).

    Returns immediately; poll /systems/{system_id}/torrent-generation-status for progress.
    Only one generation may run at a time across all systems.
    """
    db_system = db.query(System).filter(System.id == system_id).first()
    if not db_system:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    if not _generation_lock.acquire(blocking=False):
        busy = next(
            (sid for sid, s in _generation_status.items() if s.get("status") == "generating"),
            "another system",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Torrent generation already in progress for {busy}",
        )

    _generation_status[system_id] = {
        "status": "generating",
        "message": f"Hashing files from snapshot {request.snapshot}…",
    }
    # BackgroundTasks runs sync functions in a threadpool (anyio), so this won't
    # block the event loop. The lock is released inside _run_generate_torrent.
    background_tasks.add_task(_run_generate_torrent, system_id, request.snapshot)

    return {"status": "generating", "message": f"Generation started for {system_id}"}


@router.get("/systems/{system_id}/torrent-generation-status")
async def get_torrent_generation_status(
    system_id: str,
    current_user: dict = Depends(require_admin_role),
):
    """Poll the status of an in-progress or completed torrent generation."""
    return _generation_status.get(system_id, {"status": "idle"})


@router.delete("/users/{user_id}/torrent-ip")
async def reset_torrent_ip(
    user_id: str,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """Reset a user's torrent IP lock so they can re-announce from a new IP (admin only)."""
    db_user = db.query(User).filter(User.user_id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    db_user.torrent_locked_ip = None
    db.commit()
    logger.info(f"Admin {current_user.get('username')} reset torrent IP lock for user {user_id}")
    return {"success": True, "message": f"Torrent IP lock reset for user {user_id}"}

