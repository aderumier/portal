"""P2P matcher service for finding available peers for file downloads."""
import logging
import random
from typing import Optional, Dict, Set, List
from app.services.p2p_inventory import P2PInventoryService, get_redis_p2p_client
from app.services.websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)

class P2PMatcherService:
    """Service for matching download requests with available peers."""
    
    @staticmethod
    async def find_peers(system: str, rom_path: str, exclude_token_ids: Optional[Set[int]] = None, max_results: int = 5) -> List[int]:
        """Find available peers that have a specific ROM.
        
        Args:
            system: System identifier
            rom_path: ROM path
            exclude_token_ids: Set of token_ids to exclude (e.g., requesting client)
            max_results: Maximum number of peers to return
        
        Returns:
            List of token_ids that have this ROM and are online
        """
        if exclude_token_ids is None:
            exclude_token_ids = set()
        
        try:
            # Find all clients that have this ROM
            candidate_token_ids = await P2PInventoryService.find_clients_with_rom(system, rom_path)
            
            # Exclude specified token_ids
            candidate_token_ids = candidate_token_ids - exclude_token_ids
            
            if not candidate_token_ids:
                return []
            
            # Filter to only online clients (check WebSocket connections)
            ws_manager = get_websocket_manager()
            online_token_ids = []
            for token_id in candidate_token_ids:
                if ws_manager.has_connection(token_id):
                    online_token_ids.append(token_id)
            
            # Randomly shuffle and limit results
            random.shuffle(online_token_ids)
            return online_token_ids[:max_results]
        except Exception as e:
            logger.error(f"Error finding peers for {system}/{rom_path}: {e}")
            return []
    
    @staticmethod
    async def get_peer_connection_info(token_id: int) -> Optional[Dict]:
        """Get peer connection information for a token_id.
        
        Args:
            token_id: API token ID of the peer
        
        Returns:
            Dictionary with connection info (external_ip, external_port, etc.) or None
        """
        try:
            redis_client = get_redis_p2p_client()
            if not redis_client:
                return None
            
            # Get peer connection info from Redis
            # This will be stored by the peer registration endpoint
            client_key = f"p2p:client:{token_id}"
            client_info_str = await redis_client.get(client_key)
            if client_info_str:
                import json
                return json.loads(client_info_str)
            return None
        except Exception as e:
            logger.error(f"Error getting peer connection info for token_id {token_id}: {e}")
            return None
    
    @staticmethod
    async def request_peer(system: str, rom_path: str, requesting_token_id: int, max_attempts: int = 5) -> Optional[Dict]:
        """Request a peer for file download.
        
        Args:
            system: System identifier
            rom_path: ROM path
            requesting_token_id: Token ID of the requesting client
            max_attempts: Maximum number of peers to try
        
        Returns:
            Dictionary with peer connection info or None if no peer found
            Format: {token_id, external_ip, external_port, internal_port, peer_url}
        """
        try:
            # Find available peers
            exclude_set = {requesting_token_id}
            peer_token_ids = await P2PMatcherService.find_peers(
                system, rom_path, exclude_token_ids=exclude_set, max_results=max_attempts
            )
            
            if not peer_token_ids:
                logger.debug(f"No peers found for {system}/{rom_path}")
                return None
            
            # Get connection info for the first available peer
            # (peers are already shuffled in find_peers)
            for peer_token_id in peer_token_ids:
                peer_info = await P2PMatcherService.get_peer_connection_info(peer_token_id)
                if peer_info:
                    peer_info['token_id'] = peer_token_id
                    # Build peer URL
                    external_ip = peer_info.get('external_ip')
                    external_port = peer_info.get('external_port')
                    if external_ip and external_port:
                        peer_info['peer_url'] = f"http://{external_ip}:{external_port}"
                    else:
                        # Fallback to internal port if external not available
                        internal_port = peer_info.get('internal_port')
                        if internal_port:
                            # Use localhost for internal connections
                            peer_info['peer_url'] = f"http://127.0.0.1:{internal_port}"
                        else:
                            continue
                    return peer_info
            
            return None
        except Exception as e:
            logger.error(f"Error requesting peer for {system}/{rom_path}: {e}")
            return None


