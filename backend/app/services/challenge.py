"""Proof-of-work challenges for browser-only endpoints.

Enqueueing a download is something only the web UI does - the download client
consumes the queue over WebSocket and never POSTs to it. That lets us demand a
proof of work per enqueue: a single click spends a fraction of a second, while a
script looping over a system's game list pays that cost on every game.

Challenges are stateless and HMAC-signed, so any worker can verify one minted by
any other worker without shared storage. Redis is used only to burn a solved
challenge so it cannot be replayed; if Redis is unavailable the signature and
expiry checks still hold, but a solution could be replayed until it expires.
"""
import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Namespaced inside the websocket Redis db (see get_redis_ws_client)
_BURN_KEY_PREFIX = "powchallenge:"

_SIGNATURE_LENGTH = 32


def _sign(payload: str) -> str:
    """Return a truncated HMAC of the challenge payload."""
    digest = hmac.new(
        settings.SECRET_KEY.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest[:_SIGNATURE_LENGTH]


def _leading_zero_bits(digest: bytes) -> int:
    """Count leading zero bits in a digest."""
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def mint_challenge(user_id: str) -> dict:
    """Create a signed, short-lived challenge bound to a user.

    The nonce is ``salt.issued_at.user_id.signature`` - self-describing, so
    verification needs no server-side state.
    """
    salt = base64.urlsafe_b64encode(os.urandom(12)).decode('ascii').rstrip('=')
    issued_at = int(time.time())
    payload = f"{salt}.{issued_at}.{user_id}"
    nonce = f"{payload}.{_sign(payload)}"

    return {
        "nonce": nonce,
        "difficulty": settings.DOWNLOAD_CHALLENGE_BITS,
        "expires_in": settings.DOWNLOAD_CHALLENGE_TTL,
    }


async def _burn_nonce(nonce: str) -> bool:
    """Mark a nonce as spent. Returns False if it was already spent.

    Degrades to allowing the solution through when Redis is unreachable - a
    replay window is preferable to blocking every download if Redis is down.
    """
    try:
        from app.services.websocket_manager import get_redis_ws_client
        redis_client = get_redis_ws_client()
        if not redis_client:
            logger.warning("Redis unavailable - challenge replay protection disabled")
            return True

        key = _BURN_KEY_PREFIX + hashlib.sha256(nonce.encode('utf-8')).hexdigest()
        # SET NX succeeds only the first time this nonce is presented
        stored = await redis_client.set(key, '1', ex=settings.DOWNLOAD_CHALLENGE_TTL, nx=True)
        return bool(stored)
    except Exception as e:
        logger.warning(f"Challenge burn failed, allowing solution through: {e}")
        return True


async def verify_challenge(
    nonce: Optional[str],
    solution: Optional[str],
    user_id: str
) -> tuple[bool, str]:
    """Validate a solved challenge.

    Returns ``(ok, reason)``; ``reason`` is safe to return to the client.
    """
    if not nonce or not solution:
        return False, "Missing proof-of-work challenge"

    payload, separator, signature = nonce.rpartition('.')
    if not separator:
        return False, "Malformed challenge"

    if not hmac.compare_digest(signature, _sign(payload)):
        return False, "Invalid challenge signature"

    parts = payload.split('.', 2)
    if len(parts) != 3:
        return False, "Malformed challenge"
    _salt, issued_at_raw, challenge_user_id = parts

    # A challenge minted for one account must not be spendable by another
    if challenge_user_id != str(user_id):
        return False, "Challenge was issued to a different user"

    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        return False, "Malformed challenge"

    if time.time() - issued_at > settings.DOWNLOAD_CHALLENGE_TTL:
        return False, "Challenge expired"

    digest = hashlib.sha256(f"{nonce}:{solution}".encode('utf-8')).digest()
    if _leading_zero_bits(digest) < settings.DOWNLOAD_CHALLENGE_BITS:
        return False, "Invalid proof-of-work solution"

    if not await _burn_nonce(nonce):
        return False, "Challenge already used"

    return True, ""
