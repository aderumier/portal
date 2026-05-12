"""Torrent file storage and per-user announce URL rewriting."""
import os
import uuid
import logging
from pathlib import Path
from typing import Optional

import torf

from app.config import settings

logger = logging.getLogger(__name__)

# Base torrent files are stored here: data/torrents/{system_id}.torrent
TORRENTS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "torrents"


def _ensure_dir():
    TORRENTS_DIR.mkdir(parents=True, exist_ok=True)


def torrent_path(system_id: str) -> Path:
    return TORRENTS_DIR / f"{system_id}.torrent"


def save_base_torrent(system_id: str, content: bytes) -> None:
    """Persist the admin-uploaded base torrent file."""
    _ensure_dir()
    torrent_path(system_id).write_bytes(content)
    logger.info(f"Saved base torrent for system {system_id}")


def base_torrent_exists(system_id: str) -> bool:
    return torrent_path(system_id).exists()


def generate_passkey() -> str:
    return uuid.uuid4().hex


def build_user_torrent(system_id: str, passkey: str) -> Optional[bytes]:
    """
    Read the base torrent, replace every announce URL with the user-specific
    one, set private=True, and return the modified torrent as bytes.
    Returns None if no base torrent exists or TRACKER_ANNOUNCE_URL is not set.
    """
    path = torrent_path(system_id)
    if not path.exists():
        return None

    announce_base = settings.TRACKER_ANNOUNCE_URL.rstrip("/")
    if not announce_base:
        logger.warning("TRACKER_ANNOUNCE_URL is not configured")
        return None

    user_announce = f"{announce_base}/announce?passkey={passkey}"

    t = torf.Torrent.read(str(path))
    t.trackers = [[user_announce]]
    t.private = True

    return t.dump()
