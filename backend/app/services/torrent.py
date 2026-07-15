"""Torrent file storage and per-user announce URL rewriting."""
import os
import re
import uuid
import logging
from pathlib import Path
from typing import List, Optional

import httpx
import torf

from app.config import settings

logger = logging.getLogger(__name__)

# torf defaults MAX_TORRENT_FILE_SIZE to 10 MB and, when reading a file-like
# object, *silently truncates* the read to that many bytes (torf _torrent.py
# read_stream). Systems with very many files produce a large 'pieces' blob, so
# the .torrent easily exceeds 10 MB — the truncated read then fails to bdecode
# and raises BdecodeError. Raise the cap so large torrents read back and the
# bytes-based read_stream in push_torrent_to_qbittorrent doesn't raise either.
torf.Torrent.MAX_TORRENT_FILE_SIZE = int(200e6)  # 200 MB

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


def list_zfs_snapshots(system_id: str) -> List[str]:
    """List available ZFS snapshot names for a system, newest first."""
    snapshot_dir = Path(settings.ROMS_PATH) / system_id / ".zfs" / "snapshot"
    if not snapshot_dir.exists():
        return []
    names = sorted(
        [e.name for e in snapshot_dir.iterdir() if e.is_dir()],
        reverse=True,
    )
    return names


def generate_torrent_from_snapshot(system_id: str, snapshot_name: str) -> bytes:
    """Generate a torrent from a ZFS snapshot directory and save it as the base torrent.

    Hidden entries (names starting with '.') at the root of the snapshot are excluded.
    The tracker announce URL is read from settings.TRACKER_ANNOUNCE_URL.
    """
    snapshot_path = Path(settings.ROMS_PATH) / system_id / ".zfs" / "snapshot" / snapshot_name

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_name}")

    announce_base = _normalize_announce_base(settings.TRACKER_ANNOUNCE_URL)
    if not announce_base:
        raise ValueError("TRACKER_ANNOUNCE_URL is not configured")

    # Walk the snapshot root, skipping hidden entries (names starting with '.') only at
    # the top level. Files inside non-hidden subdirectories are included unconditionally.
    file_paths: List[Path] = []
    for entry in sorted(snapshot_path.iterdir(), key=lambda e: e.name):
        if entry.name.startswith("."):
            continue
        if entry.is_file():
            file_paths.append(entry)
        elif entry.is_dir():
            for child in sorted(entry.rglob("*")):
                if child.is_file():
                    file_paths.append(child)

    if not file_paths:
        raise ValueError("No files found in snapshot after filtering hidden entries")

    logger.info(
        f"[torrent-gen] {system_id}: {len(file_paths)} files collected, starting piece hashing"
    )

    t = torf.Torrent()
    t.private = True
    t.trackers = [[f"{announce_base}/announce"]]
    t.filepaths = file_paths   # common parent (snapshot_path) becomes the implicit root
    t.name = snapshot_name     # top-level folder in the torrent = snapshot name

    _last_pct = [-1]

    def _progress(torrent, filepath, pieces_done, pieces_total):
        if pieces_total == 0:
            return
        pct = int(pieces_done / pieces_total * 100)
        # Log every 10 % milestone to avoid flooding
        milestone = pct - (pct % 10)
        if milestone > _last_pct[0]:
            _last_pct[0] = milestone
            logger.info(
                f"[torrent-gen] {system_id}: hashing {milestone}% "
                f"({pieces_done}/{pieces_total} pieces) — {filepath}"
            )

    t.generate(callback=_progress, interval=1)

    data = t.dump()
    _ensure_dir()

    dest = torrent_path(system_id)
    replacing = dest.exists()
    # Atomic write: write to a temp file then rename over the destination so a
    # crash mid-write never leaves a corrupt torrent behind.
    tmp = dest.with_suffix(".torrent.tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)

    if replacing:
        logger.info(
            f"[torrent-gen] {system_id}: replaced existing torrent "
            f"({len(file_paths)} files, {len(data)} bytes)"
        )
    else:
        logger.info(
            f"[torrent-gen] {system_id}: torrent written "
            f"({len(file_paths)} files, {len(data)} bytes)"
        )

    base = settings.QBITTORRENT_SAVE_BASE or settings.ROMS_PATH
    save_path = str(Path(base) / system_id / ".zfs" / "snapshot")
    push_torrent_to_qbittorrent(system_id, data, save_path)
    return data


def push_torrent_to_qbittorrent(system_id: str, torrent_data: bytes, save_path: str) -> None:
    """Upload a torrent file to the configured qBittorrent instance via its Web API.

    The announce URL is rewritten to QBITTORRENT_ANNOUNCE_URL before uploading
    so the seeding client uses the correct passkey.
    """
    url = settings.QBITTORRENT_URL.rstrip("/")
    if not url:
        logger.debug("[qbt] QBITTORRENT_URL not configured, skipping push")
        return

    announce_url = settings.QBITTORRENT_ANNOUNCE_URL
    if not announce_url:
        logger.warning("[qbt] QBITTORRENT_ANNOUNCE_URL not configured, skipping push")
        return

    try:
        t = torf.Torrent.read_stream(torrent_data)
        t.trackers = [[announce_url]]
        name = t.name
        payload = t.dump()
    except Exception as exc:
        logger.error(f"[qbt] {system_id}: failed to rewrite announce URL: {exc}")
        return

    try:
        with httpx.Client(base_url=url, timeout=30) as client:
            resp = client.post(
                "/api/v2/auth/login",
                data={"username": settings.QBITTORRENT_USERNAME, "password": settings.QBITTORRENT_PASSWORD},
            )
            resp.raise_for_status()
            if resp.text == "Fails.":
                raise ValueError("qBittorrent login failed (invalid credentials)")

            resp = client.post(
                "/api/v2/torrents/add",
                data={"savepath": save_path},
                files={"torrents": (f"{system_id}.torrent", payload, "application/x-bittorrent")},
            )
            # A torrent whose content already exists is reported as 409 Conflict
            # (v1 torrents) or 200 "Fails." (hybrid v1+v2 torrents). The info-hash
            # is derived from the files only, so re-pushing the same snapshot —
            # e.g. only to refresh the tracker after a domain migration — collides
            # with the existing torrent. Update its trackers in place rather than
            # treating it as an error.
            if resp.status_code == 409 or (
                resp.status_code == 200 and resp.text.strip() == "Fails."
            ):
                _sync_qbt_trackers(client, system_id, name, announce_url, url)
                return
            resp.raise_for_status()
            logger.info(f"[qbt] {system_id}: torrent pushed to qBittorrent ({url})")
    except Exception as exc:
        logger.error(f"[qbt] {system_id}: failed to push torrent to qBittorrent: {exc}")


def _sync_qbt_trackers(
    client: "httpx.Client", system_id: str, name: str, announce_url: str, url: str
) -> None:
    """Point an already-present qBittorrent torrent at announce_url. Used when
    /torrents/add reports the content already exists. The torrent is located by
    name rather than by torf's v1 info-hash, because hybrid (v1+v2) torrents are
    indexed in qBittorrent under a hash that differs from torf's value."""
    resp = client.get("/api/v2/torrents/info")
    resp.raise_for_status()
    matches = [it for it in resp.json() if it.get("name") == name]
    if not matches:
        # add said it exists, yet no torrent carries this name — surface it.
        logger.error(
            f"[qbt] {system_id}: add reported the torrent already exists but no "
            f"torrent named {name!r} was found"
        )
        return
    qbt_hash = matches[0]["hash"]

    resp = client.get("/api/v2/torrents/trackers", params={"hash": qbt_hash})
    resp.raise_for_status()
    # Drop the synthetic DHT/PEX/LSD entries (urls like '** [DHT] **').
    old_urls = [
        tr["url"] for tr in resp.json()
        if tr.get("url", "").startswith(("http://", "https://"))
    ]
    if old_urls == [announce_url]:
        logger.info(
            f"[qbt] {system_id}: torrent already present with current tracker, nothing to do"
        )
        return

    resp = client.post(
        "/api/v2/torrents/addTrackers",
        data={"hash": qbt_hash, "urls": announce_url},
    )
    resp.raise_for_status()
    stale = [u for u in old_urls if u != announce_url]
    if stale:
        # removeTrackers expects URLs separated by '|' (addTrackers uses newlines).
        resp = client.post(
            "/api/v2/torrents/removeTrackers",
            data={"hash": qbt_hash, "urls": "|".join(stale)},
        )
        resp.raise_for_status()
    logger.info(
        f"[qbt] {system_id}: existing torrent found, trackers updated to {announce_url} ({url})"
    )


def _normalize_announce_base(url: str) -> str:
    """Clean a configured announce base URL so a stray slash can't produce an
    invalid tracker URL (e.g. 'https:///host' -> 'https://host').

    Returns '' if the value is empty/unset.
    """
    url = (url or "").strip()
    if not url:
        return ""
    url = url.rstrip("/")
    # Collapse accidental extra slashes right after the scheme.
    url = re.sub(r"^(https?:)/+", r"\1//", url)
    return url


def build_user_torrent(system_id: str, passkey: str) -> Optional[bytes]:
    """
    Read the base torrent, replace every announce URL with the user-specific
    one, set private=True, and return the modified torrent as bytes.
    Returns None if no base torrent exists or TRACKER_ANNOUNCE_URL is not set.
    """
    path = torrent_path(system_id)
    if not path.exists():
        return None

    announce_base = _normalize_announce_base(settings.TRACKER_ANNOUNCE_URL)
    if not announce_base:
        logger.warning("TRACKER_ANNOUNCE_URL is not configured")
        return None

    user_announce = f"{announce_base}/announce?passkey={passkey}"

    try:
        t = torf.Torrent.read(str(path))
    except torf.TorfError as exc:
        # A corrupt/truncated/non-bencode base file must not surface as an
        # unhandled 500 traceback — log it and let the caller report a clean
        # error to the client.
        logger.error(f"[torrent] {system_id}: base torrent is unreadable ({path}): {exc}")
        return None

    t.trackers = [[user_announce]]
    t.private = True

    return t.dump()
