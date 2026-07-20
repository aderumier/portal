#!/usr/bin/env python3
"""Report (and optionally clear) partial ws:connections:* entries.

A healthy entry is written by WebSocketManager.add_connection() and always carries
ip/platform/client_version/connected_at/process_id plus a TTL. If Redis evicts or
loses the hash while the websocket is still open, the pre-fix refresher recreated it
holding only 'last_updated' and then kept that stub alive forever.

These stubs typically belong to REAL, still-connected clients: the socket lives in
worker memory, so the client keeps working, but every Redis-only field is gone. That
degrades more than the admin page - reverse-P2P ip lookup, platform detection and
P2P peer selection all read these fields.

Deleting a stub is only meaningful once the websocket_manager fix is deployed: the
owning worker's refresher then rebuilds the full entry from its in-memory metadata
within 60s. Before the fix, deletion just gets a fresh stub written back.

Usage:
    python cleanup_ws_zombies.py            # dry run: report only
    python cleanup_ws_zombies.py --apply    # delete partial entries (post-fix only)
"""
import asyncio
import sys

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402

REQUIRED_FIELDS = ("connected_at", "process_id", "ip")


async def main(apply: bool) -> None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    partial, healthy = [], 0
    cursor = 0
    while True:
        cursor, keys = await client.scan(cursor, match="ws:connections:*", count=100)
        for key in keys:
            data = await client.hgetall(key)
            ttl = await client.ttl(key)

            missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
            no_ttl = ttl == -1

            if missing or no_ttl:
                partial.append((key, ttl, sorted(data.keys()), missing, no_ttl))
            else:
                healthy += 1
        if cursor == 0:
            break

    print(f"healthy entries: {healthy}")
    print(f"partial entries: {len(partial)}\n")

    for key, ttl, fields, missing, no_ttl in partial:
        reason = []
        if missing:
            reason.append(f"missing={','.join(missing)}")
        if no_ttl:
            reason.append("no-ttl")
        print(f"  {key} ttl={ttl} [{'; '.join(reason)}]")
        print(f"      fields: {fields}")

    if not partial:
        print("nothing to clean up")
    elif apply:
        for key, *_ in partial:
            await client.delete(key)
        print(f"\ndeleted {len(partial)} partial entries")
        print("owning workers will rebuild the full entries within 60s (post-fix)")
    else:
        print(f"\ndry run - re-run with --apply to delete these {len(partial)} entries")
        print("only meaningful once the websocket_manager fix is deployed")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
