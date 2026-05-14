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

logger = logging.getLogger(__name__)

router = APIRouter()

_tracker_redis_client = None


def get_tracker_redis_client():
    global _tracker_redis_client
    if _tracker_redis_client is not None:
        return _tracker_redis_client
    if not settings.TRACKER_REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis
        _tracker_redis_client = aioredis.from_url(
            settings.TRACKER_REDIS_URL,
            decode_responses=True,
        )
        return _tracker_redis_client
    except Exception as e:
        logger.warning(f"Failed to initialize tracker Redis client: {e}")
        return None



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
    redis = get_tracker_redis_client()
    if not redis:
        raise HTTPException(status_code=503, detail="TRACKER_REDIS_URL is not configured")

    prefix = settings.TRACKER_REDIS_KEY_PREFIX
    now = int(time.time())

    t_total = time.time()

    ih_to_system = await _get_ih_system_map()
    logger.warning(f"[tracker] ih_system_map: {time.time()-t_total:.3f}s")

    try:
        # Scan for swarm sorted-set keys (skip :d detail hashes)
        t_scan = time.time()
        swarm_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{prefix}swarm:*", count=500)
            for k in keys:
                if not k.endswith(":d"):
                    swarm_keys.append(k)
            if cursor == 0:
                break
        logger.warning(f"[tracker] SCAN: {time.time()-t_scan:.3f}s  keys={len(swarm_keys)}")

        if not swarm_keys:
            return {"swarms": []}

        prefix_len = len(prefix) + len("swarm:")
        ih_hexes = [key[prefix_len:] for key in swarm_keys]

        # Pipeline 1: fetch active peer IDs for every swarm in one round-trip
        t_p1 = time.time()
        pipe = redis.pipeline()
        for key in swarm_keys:
            pipe.zrangebyscore(key, now, "+inf")
        all_peer_ids: list = await pipe.execute()
        logger.warning(f"[tracker] pipeline1 (zrangebyscore ×{len(swarm_keys)}): {time.time()-t_p1:.3f}s")

        # Pipeline 2: fetch peer data only for non-empty swarms
        non_empty = [(ih, pids) for ih, pids in zip(ih_hexes, all_peer_ids) if pids]
        if not non_empty:
            return {"swarms": []}

        t_p2 = time.time()
        pipe = redis.pipeline()
        for ih_hex, peer_ids in non_empty:
            pipe.hmget(f"{prefix}swarm:{ih_hex}:d", *peer_ids)
        all_vals: list = await pipe.execute()
        logger.warning(f"[tracker] pipeline2 (hmget ×{len(non_empty)}): {time.time()-t_p2:.3f}s")

        results = []
        for (ih_hex, _), vals in zip(non_empty, all_vals):
            seeders  = sum(1 for v in vals if v and v.endswith("|1"))
            leechers = sum(1 for v in vals if v and not v.endswith("|1"))
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

    except Exception as e:
        logger.error(f"Tracker Redis error in list_swarms: {e}")
        raise HTTPException(status_code=503, detail=f"Tracker Redis error: {e}")

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
    redis = get_tracker_redis_client()
    if not redis:
        raise HTTPException(status_code=503, detail="TRACKER_REDIS_URL is not configured")

    prefix = settings.TRACKER_REDIS_KEY_PREFIX
    now = int(time.time())

    swarm_key = f"{prefix}swarm:{info_hash_hex}"
    data_key = f"{prefix}swarm:{info_hash_hex}:d"

    try:
        peer_ids = await redis.zrangebyscore(swarm_key, now, "+inf")
        if not peer_ids:
            return {"peers": []}

        vals = await redis.hmget(data_key, *peer_ids)
    except Exception as e:
        logger.error(f"Tracker Redis error in get_swarm_peers: {e}")
        raise HTTPException(status_code=503, detail=f"Tracker Redis error: {e}")

    ip_to_user = _build_ip_user_map(db)

    peers = []
    for pid, val in zip(peer_ids, vals):
        if not val:
            continue
        parts = val.split("|", 2)
        if len(parts) != 3:
            continue
        ip, port, complete = parts
        user_info = ip_to_user.get(ip)
        peers.append({
            "peer_id": pid[:16] + "…",
            "ip": ip,
            "port": int(port),
            "seeder": complete == "1",
            "username": user_info["username"] if user_info else None,
            "user_id": user_info["user_id"] if user_info else None,
        })

    peers.sort(key=lambda x: (not x["seeder"], x["ip"]))
    return {"peers": peers}
