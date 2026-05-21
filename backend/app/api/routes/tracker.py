"""Internal tracker API — called by the Go BitTorrent tracker, not by browser clients."""
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db, User
from app.config import settings
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_TORRENT_IPS = 4
TORRENT_IP_TTL = 6 * 3600  # 6 hours in seconds


def parse_locked_ips(raw: str) -> dict[str, int]:
    """Parse 'ip@timestamp,...' into {ip: last_seen}.
    Entries without a timestamp (old format) get ts=0 and are treated as expired."""
    result = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "@" in entry:
            ip, _, ts_str = entry.rpartition("@")
            try:
                result[ip] = int(ts_str)
            except ValueError:
                result[ip] = 0
        else:
            result[entry] = 0  # old format — will expire immediately
    return result


def serialize_locked_ips(ips: dict[str, int]) -> str:
    return ",".join(f"{ip}@{ts}" for ip, ts in ips.items())


def _require_tracker_secret(x_tracker_secret: Optional[str] = Header(None)):
    if not settings.TRACKER_API_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Tracker API not configured")
    if x_tracker_secret != settings.TRACKER_API_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid tracker secret")


class PasskeyRequest(BaseModel):
    passkey: str
    ip: str


@router.post("/check-passkey")
def check_passkey(
    req: PasskeyRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_require_tracker_secret),
):
    """
    Validate a passkey and enforce a per-user IP allowlist (max 4 IPs, 6-hour TTL).

    - Unknown passkey → 403
    - Known IP → refresh its timestamp, allow
    - Unknown IP + expired/free slot → claim slot, allow
    - Unknown IP + 4 active slots → 403
    """
    user = db.query(User).filter(User.torrent_passkey == req.passkey).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid passkey")

    now = int(time.time())
    locked = parse_locked_ips(user.torrent_locked_ip)

    # Drop slots that haven't announced in 6 hours
    locked = {ip: ts for ip, ts in locked.items() if now - ts < TORRENT_IP_TTL}

    if req.ip in locked:
        locked[req.ip] = now
        user.torrent_locked_ip = serialize_locked_ips(locked)
        db.commit()
        return {"ok": True}

    if len(locked) < MAX_TORRENT_IPS:
        locked[req.ip] = now
        user.torrent_locked_ip = serialize_locked_ips(locked)
        db.commit()
        return {"ok": True}

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access denied from this IP")
