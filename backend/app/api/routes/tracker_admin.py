"""Admin routes for torrent tracker monitoring (reads peer data from Redis)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db, User
from app.api.middleware.roles import require_admin_role
from app.config import settings
import asyncio
import hashlib
import time
import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()


async def _tracker_api_get(path: str) -> dict:
    """GET a JSON resource from the tracker's admin API (secret-authenticated).

    The tracker owns the peer-state Redis; the backend reads swarm/peer data over
    HTTP instead of connecting to that Redis directly.
    """
    base = settings.TRACKER_API_URL
    if not base:
        raise HTTPException(status_code=503, detail="TRACKER_API_URL is not configured")
    url = base.rstrip("/") + path
    headers = {"X-Tracker-Secret": settings.TRACKER_API_SECRET}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Tracker API error {e.response.status_code} for {path}")
        raise HTTPException(status_code=503, detail=f"Tracker API error: HTTP {e.response.status_code}")
    except Exception as e:
        logger.error(f"Tracker API unreachable for {path}: {e}")
        raise HTTPException(status_code=503, detail=f"Tracker API unreachable: {e}")



def _build_ip_user_map(db: Session) -> dict:
    """Return {ip: {username, user_id}} from active torrent_locked_ip entries."""
    users = db.query(User).filter(User.torrent_locked_ip.isnot(None)).all()
    now = int(time.time())
    ttl = 7 * 24 * 3600
    ip_map = {}
    for u in users:
        for entry in (u.torrent_locked_ip or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            if "@" in entry:
                ip, _, ts_str = entry.rpartition("@")
                try:
                    if now - int(ts_str) < ttl:
                        ip_map[ip] = {"username": u.username, "user_id": u.user_id}
                except ValueError:
                    pass
    return ip_map


# ---------------------------------------------------------------------------
# Minimal bencode helpers — used to extract info_hash without loading torf.
# ---------------------------------------------------------------------------

def _bc_skip(data: bytes, pos: int) -> int:
    """Return the index just past the bencoded value at pos (iterative)."""
    depth = 0
    while True:
        c = data[pos]
        if c == ord('i'):
            pos = data.index(b'e', pos + 1) + 1
            if depth == 0:
                return pos
        elif c in (ord('l'), ord('d')):
            depth += 1
            pos += 1
        elif c == ord('e'):
            depth -= 1
            pos += 1
            if depth == 0:
                return pos
        elif ord('0') <= c <= ord('9'):
            colon = data.index(b':', pos)
            n = int(data[pos:colon])
            pos = colon + 1 + n
            if depth == 0:
                return pos
        else:
            raise ValueError(f"bad bencode byte 0x{c:02x} at {pos}")


def _bc_decode(data: bytes, pos: int):
    """Decode one bencoded value. Returns (value, end_pos)."""
    c = data[pos]
    if c == ord('i'):
        end = data.index(b'e', pos + 1)
        return int(data[pos + 1:end]), end + 1
    elif c == ord('l'):
        pos += 1
        lst = []
        while data[pos] != ord('e'):
            val, pos = _bc_decode(data, pos)
            lst.append(val)
        return lst, pos + 1
    elif c == ord('d'):
        pos += 1
        dct = {}
        while data[pos] != ord('e'):
            key, pos = _bc_decode(data, pos)
            val, pos = _bc_decode(data, pos)
            dct[key] = val
        return dct, pos + 1
    elif ord('0') <= c <= ord('9'):
        colon = data.index(b':', pos)
        n = int(data[pos:colon])
        start = colon + 1
        return data[start:start + n], start + n
    raise ValueError(f"bad bencode byte 0x{c:02x} at {pos}")


def _bc_encode(val) -> bytes:
    """Encode a value to canonical bencode (dict keys sorted)."""
    if isinstance(val, int):
        return b'i' + str(val).encode() + b'e'
    elif isinstance(val, bytes):
        return str(len(val)).encode() + b':' + val
    elif isinstance(val, list):
        return b'l' + b''.join(_bc_encode(v) for v in val) + b'e'
    elif isinstance(val, dict):
        return b'd' + b''.join(
            _bc_encode(k) + _bc_encode(val[k]) for k in sorted(val)
        ) + b'e'
    raise TypeError(f"cannot bencode {type(val)}")


def _extract_info_raw(data: bytes) -> bytes:
    """Return the raw bencoded bytes of the 'info' value from a torrent file."""
    if not data or data[0] != ord('d'):
        raise ValueError("not a bencoded dict")
    pos = 1
    while data[pos] != ord('e'):
        key, key_end = _bc_decode(data, pos)
        val_start = key_end
        if key == b'info':
            return data[val_start:_bc_skip(data, val_start)]
        pos = _bc_skip(data, val_start)
    raise ValueError("'info' key not found")


def _info_hashes(fpath: str):
    """
    Compute (ih_original, ih_with_private_true, is_already_private) from a .torrent file.
    Uses raw bencode + hashlib — no torf, no piece-hash validation.
    """
    with open(fpath, 'rb') as f:
        data = f.read()
    info_raw = _extract_info_raw(data)
    ih1 = hashlib.sha1(info_raw, usedforsecurity=False).hexdigest()  # noqa: S324
    info_dict, _ = _bc_decode(info_raw, 0)
    is_private = bool(info_dict.get(b'private', 0))
    if is_private:
        return ih1, ih1, True
    info_dict[b'private'] = 1
    ih2 = hashlib.sha1(_bc_encode(info_dict), usedforsecurity=False).hexdigest()  # noqa: S324
    return ih1, ih2, False


# ---------------------------------------------------------------------------

def _build_ih_system_map_from_disk() -> dict:
    """SHA1-hash every .torrent file via raw bencode. Call only via the cached wrapper."""
    import os
    from app.services.torrent import TORRENTS_DIR
    ih_map: dict = {}
    if not TORRENTS_DIR.is_dir():
        return ih_map

    t_glob = time.time()
    fnames = [f for f in os.listdir(TORRENTS_DIR) if f.endswith(".torrent")]
    logger.warning(f"[tracker] disk: {len(fnames)} torrent files to process")

    for fname in fnames:
        system_id = fname[:-8]
        fpath = str(TORRENTS_DIR / fname)
        try:
            t0 = time.time()
            ih1, ih2, is_private = _info_hashes(fpath)
            logger.warning(f"[tracker]  {fname}: {time.time()-t0:.3f}s")
            ih_map[ih1.lower()] = {"name": system_id, "private": is_private}
            if ih2 != ih1:
                ih_map[ih2.lower()] = {"name": system_id, "private": True}
        except Exception as exc:
            logger.debug(f"Could not process torrent {fname}: {exc}")

    logger.warning(f"[tracker] disk total: {time.time()-t_glob:.3f}s for {len(fnames)} files")
    return ih_map


async def _get_ih_system_map() -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_ih_system_map_from_disk)


@router.get("/swarms")
async def list_swarms(
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
):
    """List all active torrent swarms with seeder/leecher counts."""
    t_total = time.time()

    # Swarm counts come from the tracker's admin API; system-name resolution
    # stays here because it needs the local .torrent files.
    data = await _tracker_api_get("/api/swarms")
    ih_to_system = await _get_ih_system_map()

    results = []
    for s in data.get("swarms", []):
        ih_hex = str(s.get("info_hash", "")).lower()
        seeders = int(s.get("seeders", 0))
        leechers = int(s.get("leechers", 0))
        if seeders + leechers == 0:
            continue
        meta = ih_to_system.get(ih_hex)
        results.append({
            "info_hash": ih_hex,
            "system_name": meta["name"] if meta else None,
            "private": meta["private"] if meta else None,
            "seeders": seeders,
            "leechers": leechers,
            "total_peers": seeders + leechers,
        })

    results.sort(key=lambda x: x["total_peers"], reverse=True)
    logger.warning(f"[tracker] TOTAL: {time.time()-t_total:.3f}s  swarms={len(results)}")
    return {"swarms": results}


@router.get("/swarms/{info_hash_hex}/peers")
async def get_swarm_peers(
    info_hash_hex: str,
    current_user: dict = Depends(require_admin_role),
    db: Session = Depends(get_db),
):
    """Get detailed peer list for a swarm, with username resolution."""
    data = await _tracker_api_get(f"/api/swarms/{info_hash_hex}/peers")

    # IP→username resolution stays here because it needs the application DB.
    ip_to_user = _build_ip_user_map(db)

    peers = []
    for p in data.get("peers", []):
        ip = p.get("ip")
        pid = str(p.get("peer_id", ""))
        user_info = ip_to_user.get(ip)
        peers.append({
            "peer_id": (pid[:16] + "…") if pid else "",
            "ip": ip,
            "port": p.get("port"),
            "seeder": bool(p.get("seeder")),
            "username": user_info["username"] if user_info else None,
            "user_id": user_info["user_id"] if user_info else None,
        })

    peers.sort(key=lambda x: (not x["seeder"], x["ip"]))
    return {"peers": peers}
