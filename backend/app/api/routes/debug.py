"""Debug routes for admin tools."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from app.api.middleware.roles import require_admin_role
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class SetForcedTargetRequest(BaseModel):
    source_token_id: int
    target_token_id: int


@router.get("/p2p-forced-targets")
async def get_forced_targets(
    request: Request,
    current_user: dict = Depends(require_admin_role)
):
    """Get all forced P2P targets from session."""
    try:
        forced_targets = request.session.get('p2p_forced_targets', {})
        return {
            "forced_targets": forced_targets
        }
    except Exception as e:
        logger.error(f"Error getting forced targets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while getting forced targets"
        )


@router.post("/p2p-forced-targets")
async def set_forced_target(
    request_body: SetForcedTargetRequest,
    request: Request,
    current_user: dict = Depends(require_admin_role)
):
    """Set a forced P2P target for a source token_id."""
    try:
        # Initialize forced_targets if it doesn't exist
        if 'p2p_forced_targets' not in request.session:
            request.session['p2p_forced_targets'] = {}
        
        # Set the forced target in session
        request.session['p2p_forced_targets'][str(request_body.source_token_id)] = request_body.target_token_id
        request.session.modified = True
        
        # Also store in Redis for access from download client requests
        try:
            from app.services.websocket_manager import get_redis_ws_client
            redis_ws_client = get_redis_ws_client()
            if redis_ws_client:
                redis_key = f"p2p:forced_target:{request_body.source_token_id}"
                await redis_ws_client.set(redis_key, str(request_body.target_token_id))
                logger.debug(f"Stored forced target in Redis: {redis_key} = {request_body.target_token_id}")
        except Exception as e:
            logger.warning(f"Failed to store forced target in Redis: {e}")
            # Continue anyway - session storage is primary
        
        logger.info(f"Admin {current_user.get('id')} set forced P2P target: source_token_id={request_body.source_token_id}, target_token_id={request_body.target_token_id}")
        
        return {
            "success": True,
            "message": "Forced target set successfully"
        }
    except Exception as e:
        logger.error(f"Error setting forced target: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while setting forced target"
        )


@router.delete("/p2p-forced-targets/{source_token_id}")
async def remove_forced_target(
    source_token_id: int,
    request: Request,
    current_user: dict = Depends(require_admin_role)
):
    """Remove a forced P2P target for a source token_id."""
    try:
        # Check if forced_targets exists in session
        if 'p2p_forced_targets' not in request.session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No forced targets found in session"
            )
        
        source_token_id_str = str(source_token_id)
        
        # Check if the forced target exists
        if source_token_id_str not in request.session['p2p_forced_targets']:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forced target for source_token_id {source_token_id} not found"
            )
        
        # Remove the forced target from session
        del request.session['p2p_forced_targets'][source_token_id_str]
        request.session.modified = True
        
        # Also remove from Redis
        try:
            from app.services.websocket_manager import get_redis_ws_client
            redis_ws_client = get_redis_ws_client()
            if redis_ws_client:
                redis_key = f"p2p:forced_target:{source_token_id}"
                await redis_ws_client.delete(redis_key)
                logger.debug(f"Removed forced target from Redis: {redis_key}")
        except Exception as e:
            logger.warning(f"Failed to remove forced target from Redis: {e}")
            # Continue anyway - session removal is primary
        
        logger.info(f"Admin {current_user.get('id')} removed forced P2P target for source_token_id={source_token_id}")
        
        return {
            "success": True,
            "message": "Forced target removed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing forced target: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while removing forced target"
        )
