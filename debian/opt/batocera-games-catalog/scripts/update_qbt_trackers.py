#!/usr/bin/env python3
"""Bulk-update tracker announce URLs across torrents in qBittorrent via its Web API.

Replaces every occurrence of an OLD host/substring with a NEW one in each torrent's
tracker URLs, preserving the path and the ?passkey=... query string.

Defaults to a dry run (preview). Pass --apply to actually change the trackers.

Examples:
    # Preview what would change (reads qBittorrent creds from env):
    python3 update_qbt_trackers.py --old rgs-retro.ddns.net --new www.pixn-retro.com

    # Apply, with explicit connection details:
    python3 update_qbt_trackers.py \
        --url http://localhost:8080 --user admin --password secret \
        --old rgs-retro.ddns.net --new www.pixn-retro.com --apply

Connection defaults fall back to the backend's env vars:
    QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD
"""
import argparse
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.getenv("QBITTORRENT_URL", "http://localhost:8080"),
                        help="qBittorrent WebUI base URL (env: QBITTORRENT_URL)")
    parser.add_argument("--user", default=os.getenv("QBITTORRENT_USERNAME", "admin"),
                        help="WebUI username (env: QBITTORRENT_USERNAME)")
    parser.add_argument("--password", default=os.getenv("QBITTORRENT_PASSWORD"),
                        help="WebUI password (env: QBITTORRENT_PASSWORD)")
    parser.add_argument("--old", required=True,
                        help="Old substring to replace, e.g. rgs-retro.ddns.net")
    parser.add_argument("--new", required=True,
                        help="New substring, e.g. www.pixn-retro.com")
    parser.add_argument("--category", default=None,
                        help="Only process torrents in this category")
    parser.add_argument("--apply", action="store_true",
                        help="Actually apply the changes (default: preview only)")
    args = parser.parse_args()

    if not args.password:
        print("error: no password (pass --password or set QBITTORRENT_PASSWORD)", file=sys.stderr)
        return 2
    if args.old == args.new:
        print("error: --old and --new are identical", file=sys.stderr)
        return 2

    base = args.url.rstrip("/")
    # Referer/Origin matching the base satisfies qBittorrent's CSRF/host-header checks.
    with httpx.Client(base_url=base, timeout=30, follow_redirects=True,
                      headers={"Referer": base, "Origin": base}) as client:
        # --- Authenticate (best effort) ---
        # Some setups bypass auth for whitelisted IPs/localhost, in which case the
        # login is a no-op (and may return 204/empty). So we don't hard-fail on the
        # login response — the real gate is whether we can list torrents below.
        try:
            resp = client.post("/api/v2/auth/login",
                               data={"username": args.user, "password": args.password})
            if resp.text.strip() == "Fails.":
                print("login failed: wrong username/password (qBittorrent returned 'Fails.').",
                      file=sys.stderr)
                return 1
        except httpx.HTTPError as e:
            print(f"warning: login request error ({e}); trying anyway...", file=sys.stderr)

        # --- List torrents (this is the real access check) ---
        params = {"category": args.category} if args.category else {}
        resp = client.get("/api/v2/torrents/info", params=params)
        if resp.status_code in (401, 403):
            print(f"access denied (HTTP {resp.status_code}) listing torrents. "
                  f"Authentication required — check credentials, or qBittorrent's Web UI "
                  f"host-header validation / IP-whitelist settings.", file=sys.stderr)
            return 1
        resp.raise_for_status()
        torrents = resp.json()
        print(f"Found {len(torrents)} torrent(s)"
              + (f" in category '{args.category}'" if args.category else ""))

        changed = 0
        failed = 0

        for t in torrents:
            h = t["hash"]
            name = t.get("name", h)

            resp = client.get("/api/v2/torrents/trackers", params={"hash": h})
            resp.raise_for_status()
            trackers = resp.json()

            for tr in trackers:
                url = tr.get("url", "")
                # Skip the DHT/PeX/LSD pseudo-entries (they look like "** [DHT] **").
                if not url.startswith(("http://", "https://", "udp://")):
                    continue
                if args.old not in url:
                    continue
                new_url = url.replace(args.old, args.new)
                if new_url == url:
                    continue

                print(f"  [{name}]\n      {url}\n   -> {new_url}")
                if not args.apply:
                    changed += 1
                    continue

                # Add the new tracker first, then remove the old one. This is
                # deterministic across qBittorrent versions (5.x's editTracker uses
                # different params and is unreliable), and never leaves the torrent
                # with zero trackers. Adding a duplicate is a no-op in qBittorrent.
                ra = client.post("/api/v2/torrents/addTrackers",
                                 data={"hash": h, "urls": new_url})
                rr = client.post("/api/v2/torrents/removeTrackers",
                                 data={"hash": h, "urls": url})
                if ra.status_code == 200 and rr.status_code == 200:
                    changed += 1
                else:
                    print(f"      ! failed (addTrackers HTTP {ra.status_code} {ra.text.strip()!r}; "
                          f"removeTrackers HTTP {rr.status_code} {rr.text.strip()!r})",
                          file=sys.stderr)
                    failed += 1

        print()
        if args.apply:
            print(f"Done. Changed {changed} tracker URL(s); {failed} failed.")
        else:
            print(f"Preview only: {changed} tracker URL(s) would change. "
                  f"Re-run with --apply to commit.")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
