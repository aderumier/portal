"""P2P inventory service for tracking client ROM files."""
import json
import logging
import time
from typing import Optional, Dict, Set, List
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client for P2P inventory (initialized on first use)
_redis_p2p_client = None

def get_redis_p2p_client():
    """Get or create Redis client for P2P inventory."""
    global _redis_p2p_client
    
    if _redis_p2p_client is not None:
        return _redis_p2p_client
    
    try:
        import redis.asyncio as aioredis
        redis_url = settings.REDIS_URL
        # Use database 3 for P2P to separate from sessions (0), cache (1), downloads (2)
        if '/0' in redis_url:
            redis_url = redis_url.replace('/0', '/3')
        elif '/1' in redis_url:
            redis_url = redis_url.replace('/1', '/3')
        elif '/2' in redis_url:
            redis_url = redis_url.replace('/2', '/3')
        elif redis_url.endswith('/'):
            redis_url = redis_url + '3'
        else:
            redis_url = redis_url + '/3'
        
        _redis_p2p_client = aioredis.from_url(
            redis_url,
            decode_responses=True,  # P2P uses text (JSON)
            encoding='utf-8'
        )
        logger.info(f"Redis P2P client initialized (URL: {redis_url})")
        return _redis_p2p_client
    except ImportError:
        logger.debug("Redis not available for P2P inventory (redis library not installed)")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Redis P2P client: {e}")
        return None

class P2PInventoryService:
    """Service for managing P2P client ROM inventory in Redis."""

    # A peer must re-advertise a ROM within this window or it ages out of the
    # reverse index. The client re-uploads its full inventory every 24h (and on
    # restart), so this must stay comfortably above that interval to avoid
    # evicting live peers. This is what lets deleted files / deleted gamelists /
    # emptied clients drop out without keeping a per-token map.
    INDEX_STALE_SECONDS = 48 * 3600

    @staticmethod
    async def _zadd_index(redis_client, index_key: str, token_str: str, now_ts: int) -> int:
        """Add/refresh a peer in a ROM's reverse index, scored by last-seen time.

        Migrates a legacy plain-SET key to a sorted set on the fly, so no manual
        catalog refresh is needed after deploy: the first write to each key
        converts it, grandfathering existing members with the current timestamp so
        no peer is lost. Returns 1 only when token_str is a brand-new member
        (a score refresh returns 0), matching the old SADD semantics.
        """
        try:
            return await redis_client.zadd(index_key, {token_str: now_ts})
        except Exception as e:
            if 'WRONGTYPE' not in str(e):
                raise
            try:
                old_members = await redis_client.smembers(index_key)
            except Exception:
                old_members = set()
            await redis_client.delete(index_key)
            mapping = {m: now_ts for m in old_members}
            mapping[token_str] = now_ts
            await redis_client.zadd(index_key, mapping)
            return 0 if token_str in old_members else 1

    @staticmethod
    def _get_index_key(system: str, rom_path: str) -> str:
        """Get Redis key for reverse index (which clients have this ROM).
        
        Args:
            system: System identifier
            rom_path: ROM path
        """
        return f"p2p:index:{system}/{rom_path}"
    
    @staticmethod
    async def update_inventory(token_id: int, inventory: Dict[str, List[str]]) -> bool:
        """Update client ROM inventory.
        
        Args:
            token_id: API token ID of the client
            inventory: Dictionary mapping system to list of ROM paths
                      Format: {system: [path1, path2, ...], system2: [path1, path2, ...], ...}
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            # Track which ROMs are new for this token (to count accurately)
            new_roms_count = 0
            now_ts = int(time.time())
            token_str = str(token_id)

            # Add/refresh inventory entries in the reverse index (a time-scored
            # sorted set). Re-advertising refreshes the score; anything the peer
            # stops advertising is not refreshed and ages out on its own.
            for system, paths in inventory.items():
                for rom_path in paths:
                    index_key = P2PInventoryService._get_index_key(system, rom_path)
                    added_count = await P2PInventoryService._zadd_index(
                        redis_client, index_key, token_str, now_ts
                    )

                    # Count new ROMs (ones where token_id wasn't already present)
                    if added_count == 1:
                        new_roms_count += 1

                    # Reclaim the key itself once no peer refreshes this ROM.
                    await redis_client.expire(index_key, P2PInventoryService.INDEX_STALE_SECONDS)
            
            total_paths = sum(len(paths) for paths in inventory.values())
            logger.info(f"Updated P2P inventory for token_id {token_id}: {len(inventory)} systems, {total_paths} ROM paths ({new_roms_count} new ROMs)")
            
            # Update game count in database
            try:
                from app.database import SessionLocal, ApiToken
                db = SessionLocal()
                try:
                    token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
                    if token:
                        if total_paths > 1:
                            # Full inventory update: set count to total paths
                            token.p2p_game_count = total_paths
                            db.commit()
                            logger.info(f"Updated game count for token_id {token_id} (full inventory): {token.p2p_game_count} games")
                        elif total_paths == 1 and new_roms_count == 1:
                            # Incremental update: newly added game, increment by 1
                            token.p2p_game_count = (token.p2p_game_count or 0) + 1
                            db.commit()
                            logger.info(f"Updated game count for token_id {token_id} (incremental): {token.p2p_game_count} games (+1)")
                        # If total_paths == 1 and new_roms_count == 0, game already existed, don't change count
                    else:
                        logger.warning(f"Token {token_id} not found in database when updating game count")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error updating game count for token_id {token_id}: {e}", exc_info=True)
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error accessing database for game count update: {e}", exc_info=True)
            
            return True
        except Exception as e:
            logger.error(f"Error updating P2P inventory for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def find_clients_with_rom(system: str, rom_path: str) -> Set[int]:
        """Find all clients that have a specific ROM.
        
        Args:
            system: System identifier
            rom_path: ROM path
        
        Returns:
            Set of token_ids that have this ROM
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return set()
        
        try:
            index_key = P2PInventoryService._get_index_key(system, rom_path)
            min_score = int(time.time()) - P2PInventoryService.INDEX_STALE_SECONDS
            try:
                # Only peers that re-advertised within the staleness window.
                token_ids_str = await redis_client.zrangebyscore(index_key, min_score, '+inf')
                # Opportunistically drop members that have aged out.
                await redis_client.zremrangebyscore(index_key, '-inf', f'({min_score}')
            except Exception as e:
                if 'WRONGTYPE' not in str(e):
                    raise
                # Legacy plain-SET key not yet converted by an upload: read as-is so
                # P2P keeps working during the transition (no scores to filter on).
                token_ids_str = await redis_client.smembers(index_key)
            return {int(token_id) for token_id in token_ids_str if token_id.isdigit()}
        except Exception as e:
            logger.error(f"Error finding clients with ROM {system}/{rom_path}: {e}")
            return set()
    
    @staticmethod
    async def remove_inventory(token_id: int) -> bool:
        """Remove client inventory (when client disconnects or token revoked).
        
        Args:
            token_id: API token ID of the client
        
        Returns:
            True if successful, False otherwise
        
        Note:
            The peer's reverse-index memberships are not removed here (no per-token
            map is kept, to save memory). They age out once the peer stops
            re-advertising, via the last-seen score window (INDEX_STALE_SECONDS).
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False

        try:
            # Remove client connection info. Reverse-index memberships age out via
            # the last-seen score window rather than being enumerated here.
            client_key = f"p2p:client:{token_id}"
            await redis_client.delete(client_key)
            
            logger.info(f"Removed P2P client connection info for token_id {token_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing P2P client connection info for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def update_client_connection_info(token_id: int, connection_info: Dict) -> bool:
        """Update client connection info for P2P transfers.
        
        Args:
            token_id: API token ID of the client
            connection_info: Dictionary with connection info (external_ip, external_port, internal_port, upnp_enabled, etc.)
        
        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            client_key = f"p2p:client:{token_id}"
            # Store with 48 hour TTL (clients re-register periodically)
            await redis_client.setex(client_key, 48 * 3600, json.dumps(connection_info))
            logger.info(f"Updated P2P client connection info in Redis for token_id {token_id}: external_ip={connection_info.get('external_ip')}, external_port={connection_info.get('external_port')}, upnp_enabled={connection_info.get('upnp_enabled')}")
            return True
        except Exception as e:
            logger.error(f"Error updating P2P client connection info for token_id {token_id}: {e}")
            return False
    
    @staticmethod
    async def get_client_connection_info(token_id: int) -> Optional[Dict]:
        """Get client connection info for P2P transfers.
        
        Args:
            token_id: API token ID of the client
        
        Returns:
            Connection info dictionary (external_ip, external_port, internal_port, upnp_enabled, etc.) or None if not found
            Note: If custom_public_port is set in database, it will override external_port from Redis
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return None
        
        try:
            client_key = f"p2p:client:{token_id}"
            connection_info_str = await redis_client.get(client_key)
            if connection_info_str:
                connection_info = json.loads(connection_info_str)
                
                # Check database for custom_public_port and override external_port if set
                try:
                    from app.database import SessionLocal, ApiToken
                    db = SessionLocal()
                    try:
                        token = db.query(ApiToken).filter(ApiToken.id == token_id).first()
                        if token and token.custom_public_port is not None:
                            # Override external_port with custom port
                            connection_info['external_port'] = token.custom_public_port
                            logger.debug(f"Using custom public port {token.custom_public_port} for token_id {token_id} (overriding Redis external_port)")
                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"Error checking custom_public_port for token_id {token_id}: {e}")
                    # Continue with Redis value if database check fails
                
                # Fallback: if no external_port (no UPnP, no custom), use internal_port (defaults to 8765)
                if connection_info.get('external_port') is None:
                    internal_port = connection_info.get('internal_port')
                    if internal_port:
                        connection_info['external_port'] = internal_port
                        logger.debug(f"Using internal_port {internal_port} as external_port fallback for token_id {token_id}")
                    else:
                        # Ultimate fallback to default P2P port
                        from app.config import settings
                        connection_info['external_port'] = settings.P2P_PORT
                        logger.debug(f"Using default P2P_PORT {settings.P2P_PORT} as external_port fallback for token_id {token_id}")
                
                return connection_info
            return None
        except Exception as e:
            logger.error(f"Error getting P2P client connection info for token_id {token_id}: {e}")
            return None
    
    @staticmethod
    async def find_eligible_peers(system: str, rom_path: str, exclude_token_id: int, limit: int = 20, rom_file_size_bytes: Optional[int] = None) -> List[Dict]:
        """Find eligible P2P peers that have a specific ROM.
        
        Args:
            system: System identifier
            rom_path: ROM path (relative to system directory)
            exclude_token_id: Token ID of the requesting client (to exclude)
            limit: Maximum number of peers to return (default: 20)
            rom_file_size_bytes: Optional ROM file size in bytes (used for filtering slow peers for large files)
        
        Returns:
            List of peer dictionaries, each containing: external_ip, external_port, token_id
            Sorted by upload_bandwidth (descending, None values last)
        """
        redis_p2p_client = get_redis_p2p_client()
        if not redis_p2p_client:
            return []
        
        try:
            # Get Redis WebSocket client for connection info (database 4)
            from app.services.websocket_manager import get_redis_ws_client
            redis_ws_client = get_redis_ws_client()
            
            # Get requesting client's external IP to exclude
            requesting_client_info = await P2PInventoryService.get_client_connection_info(exclude_token_id)
            requesting_external_ip = requesting_client_info.get('external_ip') if requesting_client_info else None
            
            # Get requesting client's port accessibility status
            requesting_port_accessible = False
            if redis_ws_client:
                try:
                    requesting_ws_key = f"ws:connections:{exclude_token_id}"
                    requesting_port_accessible_str = await redis_ws_client.hget(requesting_ws_key, 'p2p_port_accessible')
                    if requesting_port_accessible_str:
                        requesting_port_accessible = requesting_port_accessible_str == 'true'
                except Exception as e:
                    logger.debug(f"Error getting requesting client's port accessibility for token_id {exclude_token_id}: {e}")
            
            # Find all clients that have this ROM
            candidate_token_ids = await P2PInventoryService.find_clients_with_rom(system, rom_path)
            logger.info(f"P2P peer selection for {system}/{rom_path}: Found {len(candidate_token_ids)} candidate clients with ROM")
            
            # Remove the requesting client
            candidate_token_ids.discard(exclude_token_id)
            logger.info(f"P2P peer selection: Excluding requesting client token_id={exclude_token_id}, {len(candidate_token_ids)} candidates remaining")
            
            if not candidate_token_ids:
                logger.info(f"P2P peer selection: No eligible peers found for {system}/{rom_path}")
                return []
            
            eligible_peers = []
            filtered_count = 0
            
            # For each candidate, get connection info and filter
            for token_id in candidate_token_ids:
                try:
                    # Get P2P connection info (external_ip, external_port)
                    p2p_info = await P2PInventoryService.get_client_connection_info(token_id)
                    if not p2p_info:
                        continue
                    
                    external_ip = p2p_info.get('external_ip')
                    external_port = p2p_info.get('external_port')
                    
                    if not external_ip or not external_port:
                        continue
                    
                    # Exclude if same external IP as requesting client
                    if requesting_external_ip and external_ip == requesting_external_ip:
                        continue
                    
                    # Get WebSocket connection info (upload_bandwidth, p2p_port_accessible)
                    upload_bandwidth = None
                    p2p_port_accessible = False
                    if redis_ws_client:
                        try:
                            ws_key = f"ws:connections:{token_id}"
                            # Connection info is stored as a hash, not JSON
                            upload_bandwidth_str = await redis_ws_client.hget(ws_key, 'upload_bandwidth')
                            p2p_port_accessible_str = await redis_ws_client.hget(ws_key, 'p2p_port_accessible')
                            
                            if upload_bandwidth_str:
                                try:
                                    upload_bandwidth = float(upload_bandwidth_str)
                                except (ValueError, TypeError):
                                    pass
                            
                            if p2p_port_accessible_str:
                                p2p_port_accessible = p2p_port_accessible_str == 'true'
                        except Exception as e:
                            logger.debug(f"Error getting WebSocket info for token_id {token_id}: {e}")
                    
                    # Filter: exclude if both peer AND requesting client have closed ports
                    # (cannot do normal P2P if peer's port is closed, cannot do reverse P2P if requesting client's port is closed)
                    if not p2p_port_accessible and not requesting_port_accessible:
                        filtered_count += 1
                        logger.debug(f"P2P peer selection: Filtered out token_id={token_id} (both peer and requesting client have closed ports)")
                        continue
                    
                    # Filter: Skip if file is large (>100MB) and peer has slow upload (<20 Mbits/s)
                    if rom_file_size_bytes is not None and rom_file_size_bytes > 104857600:  # 100MB in bytes
                        if upload_bandwidth is None or upload_bandwidth < 20.0:
                            filtered_count += 1
                            logger.debug(f"P2P peer selection: Filtered out token_id={token_id} (slow upload: {upload_bandwidth} Mbits/s for large file: {rom_file_size_bytes} bytes)")
                            continue  # Skip slow peers for large files
                    
                    eligible_peers.append({
                        'external_ip': external_ip,
                        'external_port': external_port,
                        'token_id': token_id,
                        'upload_bandwidth': upload_bandwidth if upload_bandwidth is not None else 0.0,
                        'p2p_port_accessible': p2p_port_accessible  # Include port accessibility status
                    })
                    
                except Exception as e:
                    logger.debug(f"Error processing candidate token_id {token_id}: {e}")
                    continue
            
            # Fetch total upload for all eligible peers in one DB query
            if eligible_peers:
                try:
                    from app.database import SessionLocal, ApiToken
                    db = SessionLocal()
                    try:
                        peer_ids = [p['token_id'] for p in eligible_peers]
                        tokens = db.query(ApiToken.id, ApiToken.p2p_total_upload_mb) \
                            .filter(ApiToken.id.in_(peer_ids)).all()
                        upload_map = {t.id: t.p2p_total_upload_mb or 0.0 for t in tokens}
                    finally:
                        db.close()
                except Exception as e:
                    logger.debug(f"P2P peer selection: Could not fetch upload totals: {e}")
                    upload_map = {}

                for peer in eligible_peers:
                    peer['total_upload_mb'] = upload_map.get(peer['token_id'], 0.0)

            # Sort by total upload ascending (peers that have uploaded least get priority),
            # then by upload_bandwidth descending as tiebreaker
            eligible_peers.sort(key=lambda x: (x.get('total_upload_mb', 0.0), -x['upload_bandwidth']))

            # Log selection summary
            logger.info(f"P2P peer selection for {system}/{rom_path}: {len(eligible_peers)} eligible peers found (filtered out {filtered_count} candidates)")
            if eligible_peers:
                bandwidths = [p['upload_bandwidth'] for p in eligible_peers]
                uploads = [p.get('total_upload_mb', 0.0) for p in eligible_peers]
                logger.info(f"P2P peer selection: Upload bandwidths - min={min(bandwidths):.2f}, max={max(bandwidths):.2f}, avg={sum(bandwidths)/len(bandwidths):.2f} Mbits/s")
                logger.info(f"P2P peer selection: Total upload MB - min={min(uploads):.1f}, max={max(uploads):.1f}")
            
            # Include p2p_port_accessible in results (needed for client decision-making)
            peers_to_send = []
            for peer in eligible_peers:
                peer_data = {
                    'external_ip': peer['external_ip'],
                    'external_port': peer['external_port'],
                    'token_id': peer['token_id'],
                    'p2p_port_accessible': peer.get('p2p_port_accessible', False)  # Include port accessibility status
                }
                peers_to_send.append(peer_data)
            
            # Return up to limit entries
            final_peers = peers_to_send[:limit]
            peer_list_str = ', '.join([f"{p['external_ip']}:{p['external_port']}" for p in final_peers])
            logger.info(f"P2P peer selection for {system}/{rom_path}: Returning {len(final_peers)} peers (limit={limit}): [{peer_list_str}]")
            return final_peers
            
        except Exception as e:
            logger.error(f"Error finding eligible peers for {system}/{rom_path}: {e}", exc_info=True)
            return []
    
    @staticmethod
    async def p2p_index_garbage_collector() -> bool:
        """Garbage collect the p2p_index.

        Process:
        1. Get all connected token_ids from WebSocket connections and P2P client info
        2. Scan all existing p2p:index:* keys
        3. For each scored (zset) key, drop members that aged out of the last-seen
           window or whose client is disconnected, and delete empty keys. For legacy
           plain-SET keys, stamp a TTL so they expire if never re-advertised.

        Returns:
            True if successful, False otherwise
        """
        redis_client = get_redis_p2p_client()
        if not redis_client:
            return False
        
        try:
            logger.info("Starting p2p_index cleanup")
            
            # Step 1: Get all connected token_ids from WebSocket connections (Redis DB 4)
            connected_token_ids = set()
            try:
                from app.services.websocket_manager import get_redis_ws_client
                redis_ws_client = get_redis_ws_client()
                if redis_ws_client:
                    cursor = 0
                    while True:
                        cursor, keys = await redis_ws_client.scan(cursor, match="ws:connections:*", count=1000)
                        for key in keys:
                            try:
                                # Extract token_id from key format: ws:connections:{token_id}
                                token_id_str = key.split(':')[-1]
                                if token_id_str.isdigit():
                                    connected_token_ids.add(int(token_id_str))
                            except (ValueError, IndexError):
                                continue
                        if cursor == 0:
                            break
            except Exception as e:
                logger.warning(f"Error getting WebSocket connections: {e}")
            
            # Step 2: Get all connected token_ids from P2P client info (Redis DB 3)
            try:
                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(cursor, match="p2p:client:*", count=1000)
                    for key in keys:
                        try:
                            # Extract token_id from key format: p2p:client:{token_id}
                            token_id_str = key.split(':')[-1]
                            if token_id_str.isdigit():
                                connected_token_ids.add(int(token_id_str))
                        except (ValueError, IndexError):
                            continue
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Error getting P2P client info: {e}")
            
            logger.info(f"Found {len(connected_token_ids)} connected clients")
            
            # Step 3: Scan all index keys. For sorted-set keys, drop members that
            # aged out of the last-seen window or whose client is disconnected, and
            # delete empty keys. For legacy plain-SET keys (from before the scored
            # index), stamp a 48h TTL if they have none so they clear out on their
            # own if no client re-advertises them (a re-advertisement converts them
            # to a scored zset). This is what makes a restart start clearing stale
            # keys without keeping a per-token map.
            min_score = int(time.time()) - P2PInventoryService.INDEX_STALE_SECONDS
            keys_updated = 0
            keys_deleted = 0
            legacy_stamped = 0
            token_ids_removed = 0

            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match="p2p:index:*", count=1000)
                for key in keys:
                    try:
                        key_type = await redis_client.type(key)

                        if key_type == 'set':
                            if await redis_client.ttl(key) == -1:
                                await redis_client.expire(key, P2PInventoryService.INDEX_STALE_SECONDS)
                                legacy_stamped += 1
                            continue

                        if key_type != 'zset':
                            continue

                        # Drop members not re-advertised within the window.
                        aged = await redis_client.zremrangebyscore(key, '-inf', f'({min_score}')
                        token_ids_removed += aged

                        # Drop members whose client is currently disconnected.
                        members = await redis_client.zrange(key, 0, -1)
                        disconnected = [
                            m for m in members
                            if m.isdigit() and int(m) not in connected_token_ids
                        ]
                        if disconnected:
                            await redis_client.zrem(key, *disconnected)
                            token_ids_removed += len(disconnected)
                            keys_updated += 1

                        # Delete the key if no peers remain.
                        if await redis_client.zcard(key) == 0:
                            await redis_client.delete(key)
                            keys_deleted += 1
                    except Exception as e:
                        logger.warning(f"Error processing index key {key}: {e}")
                        continue

                if cursor == 0:
                    break

            logger.info(
                f"p2p_index cleanup completed: {keys_updated} keys pruned, "
                f"{keys_deleted} keys deleted, {token_ids_removed} memberships removed, "
                f"{legacy_stamped} legacy keys stamped for expiry"
            )
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning up p2p_index: {e}", exc_info=True)
            return False

