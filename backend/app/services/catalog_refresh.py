"""Background catalog refresh, with a status any worker can report.

Rebuilding the catalog reads every system's gamelist off ZFS snapshots and takes minutes, so
serving it from the request would hold an HTTP connection open the whole time. The proxy or the
browser eventually gives up, the admin sees a failure, and the refresh they were told had failed
carries on and completes anyway. Instead the request only starts the job and returns.

Status lives in Redis rather than in the process, because the refresh runs in one uvicorn worker
while the polling request can land on any of them.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.services.discord import get_redis_cache_client

logger = logging.getLogger(__name__)

STATUS_KEY = 'catalog:refresh:status'

# A refresh that dies with its worker must not leave the catalog looking busy forever
STATUS_TTL_SECONDS = 2 * 60 * 60


async def _write_status(status: Dict[str, Any]) -> None:
    redis_client = get_redis_cache_client()
    if not redis_client:
        return
    try:
        await redis_client.set(STATUS_KEY, json.dumps(status), ex=STATUS_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Could not write catalog refresh status: {e}")


async def get_status() -> Dict[str, Any]:
    """Current refresh state, for the admin UI to poll."""
    redis_client = get_redis_cache_client()
    if not redis_client:
        return {'state': 'unknown'}
    try:
        raw = await redis_client.get(STATUS_KEY)
    except Exception as e:
        logger.warning(f"Could not read catalog refresh status: {e}")
        return {'state': 'unknown'}

    if not raw:
        return {'state': 'idle'}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {'state': 'unknown'}


async def start_refresh(game_service, username: Optional[str]) -> Dict[str, Any]:
    """Kick off a refresh in the background unless one is already running.

    Returns the status the caller should report back.
    """
    current = await get_status()
    if current.get('state') == 'running':
        return current

    started_at = datetime.now(timezone.utc).isoformat()
    running = {'state': 'running', 'started_at': started_at, 'requested_by': username}
    await _write_status(running)

    async def run() -> None:
        try:
            # refresh_catalog() blocks for minutes; keep it off the event loop or this worker
            # stops serving every other request while it runs.
            result = await asyncio.to_thread(game_service.refresh_catalog)
            await _write_status({
                'state': 'completed',
                'started_at': started_at,
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'requested_by': username,
                'result': result,
            })
            logger.info("Background catalog refresh finished")
        except Exception as e:
            logger.error(f"Background catalog refresh failed: {e}", exc_info=True)
            await _write_status({
                'state': 'failed',
                'started_at': started_at,
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'requested_by': username,
                'error': str(e),
            })

    asyncio.create_task(run())
    return running
