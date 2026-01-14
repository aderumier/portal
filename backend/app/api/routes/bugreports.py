"""Bug report routes."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from app.database import get_db, BugReport, User
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.roles import require_admin_role
from app.api.routes.catalog import get_game_service
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class SubmitBugReportRequest(BaseModel):
    rompath: str
    system: str
    catalog: str  # 'wip' or 'releases'
    subject: str
    description: str
    device: Optional[str] = None  # Token name


class UpdateBugReportStatusRequest(BaseModel):
    status: str  # 'new', 'notabug', 'resolved'


@router.post("/bugreports")
async def submit_bug_report(
    request: SubmitBugReportRequest,
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db)
):
    """Submit a bug report."""
    try:
        # Validate catalog value
        if request.catalog not in ['wip', 'releases']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Catalog must be 'wip' or 'releases'"
            )
        
        # Create bug report
        bug_report = BugReport(
            rompath=request.rompath,
            system=request.system,
            catalog=request.catalog,
            iduser=current_user['id'],
            subject=request.subject,
            description=request.description,
            device=request.device,
            status='new'  # Default status
        )
        
        db.add(bug_report)
        db.commit()
        db.refresh(bug_report)
        
        logger.info(f"Bug report created: ID={bug_report.id}, User={current_user['id']}, System={request.system}")
        
        return {
            "success": True,
            "id": bug_report.id,
            "message": "Bug report submitted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting bug report: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while submitting the bug report"
        )


@router.get("/bugreports")
async def get_bug_reports(
    sort_by: Optional[str] = Query(None, description="Sort by: 'date' or 'subject'"),
    sort_order: Optional[str] = Query('desc', description="Sort order: 'asc' or 'desc'"),
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
    game_service = Depends(get_game_service)
):
    """Get all bug reports (admin only)."""
    try:
        # Build query
        query = db.query(BugReport, User).join(User, BugReport.iduser == User.user_id)
        
        # Apply sorting
        if sort_by == 'date':
            if sort_order == 'asc':
                query = query.order_by(asc(BugReport.created_at))
            else:
                query = query.order_by(desc(BugReport.created_at))
        elif sort_by == 'subject':
            if sort_order == 'asc':
                query = query.order_by(asc(BugReport.subject))
            else:
                query = query.order_by(desc(BugReport.subject))
        else:
            # Default: sort by date descending
            query = query.order_by(desc(BugReport.created_at))
        
        results = query.all()
        
        # Ensure catalog is loaded
        if not game_service._gamelists_loaded:
            game_service.preload_all_gamelists()
        
        # Format response
        bug_reports = []
        for bug_report, user in results:
            # Get game name from catalog
            game_name = bug_report.rompath  # Default to rompath
            try:
                if bug_report.catalog == 'wip':
                    catalog = game_service.catalog_wip
                else:
                    catalog = game_service.catalog_releases
                
                if bug_report.system in catalog and bug_report.rompath in catalog[bug_report.system]:
                    game_data = catalog[bug_report.system][bug_report.rompath]
                    game_name = game_data.get('name', bug_report.rompath)
            except Exception as e:
                logger.debug(f"Could not get game name for {bug_report.rompath}: {e}")
                # Keep default rompath as game_name
            
            bug_reports.append({
                "id": bug_report.id,
                "rompath": bug_report.rompath,
                "game_name": game_name,
                "system": bug_report.system,
                "catalog": bug_report.catalog,
                "subject": bug_report.subject,
                "description": bug_report.description,
                "device": bug_report.device,
                "status": bug_report.status,
                "created_at": bug_report.created_at.isoformat() if bug_report.created_at else None,
                "user": {
                    "id": user.user_id,
                    "username": user.username
                }
            })
        
        return {
            "success": True,
            "bug_reports": bug_reports
        }
        
    except Exception as e:
        logger.error(f"Error fetching bug reports: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching bug reports"
        )


@router.get("/bugreports/{bug_report_id}")
async def get_bug_report(
    bug_report_id: int,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
    game_service = Depends(get_game_service)
):
    """Get bug report details (admin only)."""
    try:
        bug_report = db.query(BugReport).filter(BugReport.id == bug_report_id).first()
        
        if not bug_report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bug report not found"
            )
        
        # Get user info
        user = db.query(User).filter(User.user_id == bug_report.iduser).first()
        
        # Get game name from catalog
        game_name = bug_report.rompath  # Default to rompath
        try:
            if not game_service._gamelists_loaded:
                game_service.preload_all_gamelists()
            
            if bug_report.catalog == 'wip':
                catalog = game_service.catalog_wip
            else:
                catalog = game_service.catalog_releases
            
            if bug_report.system in catalog and bug_report.rompath in catalog[bug_report.system]:
                game_data = catalog[bug_report.system][bug_report.rompath]
                game_name = game_data.get('name', bug_report.rompath)
        except Exception as e:
            logger.debug(f"Could not get game name for {bug_report.rompath}: {e}")
            # Keep default rompath as game_name
        
        return {
            "success": True,
            "bug_report": {
                "id": bug_report.id,
                "rompath": bug_report.rompath,
                "game_name": game_name,
                "system": bug_report.system,
                "catalog": bug_report.catalog,
                "subject": bug_report.subject,
                "description": bug_report.description,
                "device": bug_report.device,
                "status": bug_report.status,
                "created_at": bug_report.created_at.isoformat() if bug_report.created_at else None,
                "user": {
                    "id": user.user_id if user else bug_report.iduser,
                    "username": user.username if user else None
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bug report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching the bug report"
        )


@router.patch("/bugreports/{bug_report_id}")
async def update_bug_report_status(
    bug_report_id: int,
    request: UpdateBugReportStatusRequest,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
    game_service = Depends(get_game_service)
):
    """Update bug report status (admin only)."""
    try:
        # Validate status value
        if request.status not in ['new', 'notabug', 'resolved']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status must be 'new', 'notabug', or 'resolved'"
            )
        
        bug_report = db.query(BugReport).filter(BugReport.id == bug_report_id).first()
        
        if not bug_report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bug report not found"
            )
        
        # Update status
        bug_report.status = request.status
        db.commit()
        db.refresh(bug_report)
        
        logger.info(f"Bug report status updated: ID={bug_report_id}, Status={request.status}")
        
        # Get user info
        user = db.query(User).filter(User.user_id == bug_report.iduser).first()
        
        # Get game name from catalog
        game_name = bug_report.rompath  # Default to rompath
        try:
            if not game_service._gamelists_loaded:
                game_service.preload_all_gamelists()
            
            if bug_report.catalog == 'wip':
                catalog = game_service.catalog_wip
            else:
                catalog = game_service.catalog_releases
            
            if bug_report.system in catalog and bug_report.rompath in catalog[bug_report.system]:
                game_data = catalog[bug_report.system][bug_report.rompath]
                game_name = game_data.get('name', bug_report.rompath)
        except Exception as e:
            logger.debug(f"Could not get game name for {bug_report.rompath}: {e}")
            # Keep default rompath as game_name
        
        return {
            "success": True,
            "bug_report": {
                "id": bug_report.id,
                "rompath": bug_report.rompath,
                "game_name": game_name,
                "system": bug_report.system,
                "catalog": bug_report.catalog,
                "subject": bug_report.subject,
                "description": bug_report.description,
                "device": bug_report.device,
                "status": bug_report.status,
                "created_at": bug_report.created_at.isoformat() if bug_report.created_at else None,
                "user": {
                    "id": user.user_id if user else bug_report.iduser,
                    "username": user.username if user else None
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating bug report status: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the bug report status"
        )

