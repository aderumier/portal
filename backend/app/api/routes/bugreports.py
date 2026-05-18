"""Bug report routes."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from app.database import get_db, BugReport, BugReportComment, User
from app.api.middleware.api_token import require_auth_user
from app.api.middleware.roles import require_admin_role
from app.api.middleware.guild import require_guild_member
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
    os: Optional[str] = None  # 'batocera' or 'retrobat'
    os_version: Optional[str] = None  # OS version string


class UpdateBugReportStatusRequest(BaseModel):
    status: str  # 'new', 'notabug', 'resolved', 'waiting_user_response', 'waiting_admin_response'


class AddBugReportCommentRequest(BaseModel):
    comment: str


@router.post("/bugreports")
async def submit_bug_report(
    request: SubmitBugReportRequest,
    current_user: dict = Depends(require_guild_member),
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
            os=request.os,
            os_version=request.os_version,
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
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    sort_by: Optional[str] = Query(None, description="Sort by: 'date' or 'subject'"),
    sort_order: Optional[str] = Query('desc', description="Sort order: 'asc' or 'desc'"),
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db),
    game_service = Depends(get_game_service)
):
    """Get bug reports (Admin sees all, user sees theirs)."""
    try:
        # Build query
        query = db.query(BugReport, User).join(User, BugReport.iduser == User.user_id)
        
        # Apply user filter if not admin
        if not current_user.get('is_admin', False):
            query = query.filter(BugReport.iduser == current_user['id'])
            
        # Apply status filter
        if status_filter:
            if status_filter == 'open':
                query = query.filter(BugReport.status.in_(['new', 'waiting_user_response', 'waiting_admin_response']))
            else:
                query = query.filter(BugReport.status == status_filter)
        
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
                "os": bug_report.os,
                "os_version": bug_report.os_version,
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
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db),
    game_service = Depends(get_game_service)
):
    """Get bug report details."""
    try:
        bug_report = db.query(BugReport).filter(BugReport.id == bug_report_id).first()
        
        if not bug_report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bug report not found"
            )

        # Check permission
        if not current_user.get('is_admin', False) and bug_report.iduser != current_user['id']:
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
        
        # Get comments
        comments_results = db.query(BugReportComment, User).join(User, BugReportComment.iduser == User.user_id).filter(BugReportComment.bug_report_id == bug_report_id).order_by(asc(BugReportComment.created_at)).all()
        comments = []
        for comment, comment_user in comments_results:
            comments.append({
                "id": comment.id,
                "iduser": comment.iduser,
                "username": comment_user.username,
                "comment": comment.comment,
                "created_at": comment.created_at.isoformat() if comment.created_at else None
            })

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
                "os": bug_report.os,
                "os_version": bug_report.os_version,
                "status": bug_report.status,
                "created_at": bug_report.created_at.isoformat() if bug_report.created_at else None,
                "user": {
                    "id": user.user_id if user else bug_report.iduser,
                    "username": user.username if user else None
                },
                "comments": comments
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
        if request.status not in ['new', 'notabug', 'resolved', 'waiting_user_response', 'waiting_admin_response']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status must be 'new', 'notabug', 'resolved', 'waiting_user_response', or 'waiting_admin_response'"
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
                "os": bug_report.os,
                "os_version": bug_report.os_version,
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


@router.post("/bugreports/{bug_report_id}/comments")
async def add_bug_report_comment(
    bug_report_id: int,
    request: AddBugReportCommentRequest,
    current_user: dict = Depends(require_auth_user),
    db: Session = Depends(get_db)
):
    """Add a comment to a bug report."""
    try:
        bug_report = db.query(BugReport).filter(BugReport.id == bug_report_id).first()
        
        if not bug_report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bug report not found"
            )

        # Check permission (must be admin or the author of the bug report)
        if not current_user.get('is_admin', False) and bug_report.iduser != current_user['id']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to comment on this bug report"
            )
        
        # Determine the user ID to record (e.g. from token vs session)
        user_id = current_user.get('user_id') or current_user.get('id')
        
        if not request.comment or not request.comment.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Comment cannot be empty"
            )

        new_comment = BugReportComment(
            bug_report_id=bug_report_id,
            iduser=user_id,
            comment=request.comment.strip()
        )
        
        db.add(new_comment)
        
        # Check for status transition logic
        is_admin_user = current_user.get('is_admin', False)
        # If the user is definitely not an admin (we check purely for users leaving comments)
        if not is_admin_user and bug_report.status == 'waiting_user_response':
            bug_report.status = 'waiting_admin_response'
            logger.info(f"Transitioned bug report {bug_report_id} status to waiting_admin_response due to user comment")
            
        db.commit()
        db.refresh(new_comment)
        
        logger.info(f"Bug report comment added: ID={new_comment.id}, BugReport={bug_report_id}, User={user_id}")
        
        # Get user info to return with the new comment
        user = db.query(User).filter(User.user_id == user_id).first()
        
        return {
            "success": True,
            "comment": {
                "id": new_comment.id,
                "iduser": new_comment.iduser,
                "username": user.username if user else None,
                "comment": new_comment.comment,
                "created_at": new_comment.created_at.isoformat() if new_comment.created_at else None
            },
            "updated_status": bug_report.status,
            "message": "Comment added successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding bug report comment: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while adding the comment"
        )

