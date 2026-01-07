"""Discord OAuth2 and API service."""
import httpx
import json
import logging
from typing import Optional, Dict, List
from app.config import settings

logger = logging.getLogger(__name__)

# Global Redis client for caching (initialized on first use)
_redis_cache_client = None

def get_redis_cache_client():
    """Get or create Redis client for caching Discord data."""
    global _redis_cache_client
    
    if _redis_cache_client is not None:
        return _redis_cache_client
    
    try:
        import redis.asyncio as aioredis
        redis_url = settings.REDIS_URL
        # Use a different database (1) for cache to separate from sessions (0)
        # Or use the same database with different key prefix
        if '/0' in redis_url:
            redis_url = redis_url.replace('/0', '/1')
        elif redis_url.endswith('/'):
            redis_url = redis_url + '1'
        else:
            redis_url = redis_url + '/1'
        
        _redis_cache_client = aioredis.from_url(
            redis_url,
            decode_responses=True,  # Cache uses text (JSON)
            encoding='utf-8'
        )
        logger.info(f"Redis cache client initialized (URL: {redis_url})")
        return _redis_cache_client
    except ImportError:
        logger.debug("Redis not available for caching (redis library not installed)")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Redis cache client: {e}")
        return None

class DiscordService:
    """Service for Discord OAuth2 and API interactions."""
    
    def __init__(self):
        self.client_id = settings.DISCORD_CLIENT_ID
        self.client_secret = settings.DISCORD_CLIENT_SECRET
        self.redirect_uri = settings.DISCORD_REDIRECT_URI
        self.bot_token = settings.DISCORD_BOT_TOKEN
        self.required_guild_id = settings.DISCORD_GUILD_ID
        self.api_base = "https://discord.com/api"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    def get_auth_url(self) -> str:
        """Generate Discord OAuth2 authorization URL."""
        if not self.client_id:
            logger.error("DISCORD_CLIENT_ID is not set")
            raise ValueError("DISCORD_CLIENT_ID is not configured")
        if not self.redirect_uri:
            logger.error("DISCORD_REDIRECT_URI is not set")
            raise ValueError("DISCORD_REDIRECT_URI is not configured")
        
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': 'identify guilds',
            'prompt': 'consent',
        }
        
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        auth_url = f"{self.api_base}/oauth2/authorize?{query_string}"
        
        logger.info(f"Generated Discord auth URL: {auth_url}")
        return auth_url
    
    async def get_access_token(self, code: str) -> Dict:
        """Exchange authorization code for access token."""
        try:
            logger.info(f"Requesting access token with code: {code[:5]}...")
            
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self.redirect_uri,
                'scope': 'identify guilds',
            }
            
            response = await self.client.post(
                f"{self.api_base}/oauth2/token",
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            response.raise_for_status()
            
            result = response.json()
            
            if 'scope' in result:
                scopes = result['scope'].split(' ')
                has_identify = 'identify' in scopes
                has_guilds = 'guilds' in scopes
                logger.info(f"Access token scopes: {result['scope']}")
                logger.info(f"Has identify scope: {has_identify}, Has guilds scope: {has_guilds}")
            
            logger.info("Successfully obtained access token")
            return result
        except httpx.HTTPError as e:
            logger.error(f"Discord OAuth error: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return {}
    
    async def get_user(self, access_token: str) -> Dict:
        """Get Discord user information."""
        try:
            logger.info("Fetching user info with access token")
            
            response = await self.client.get(
                f"{self.api_base}/users/@me",
                headers={'Authorization': f"Bearer {access_token}"}
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"User info fetched: ID={result.get('id', 'unknown')}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"Discord user fetch error: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return {}
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get Discord user information by user ID using bot token."""
        try:
            if not self.bot_token:
                logger.error("DISCORD_BOT_TOKEN is not set, cannot fetch user info")
                return None
            
            bot_token = self.bot_token
            if bot_token.startswith('Bot '):
                bot_token = bot_token[4:]
            
            response = await self.client.get(
                f"{self.api_base}/users/{user_id}",
                headers={'Authorization': f"Bot {bot_token}"}
            )
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"User info fetched for ID {user_id}: {result.get('username', 'unknown')}")
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"User {user_id} not found in Discord")
            else:
                logger.error(f"Error fetching user {user_id}: {e.response.status_code}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"Discord user fetch error for {user_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching user {user_id}: {e}", exc_info=True)
            return None
    
    async def get_user_guilds(self, access_token: str) -> List[Dict]:
        """Get user's Discord guilds (servers)."""
        try:
            logger.info("Fetching user guilds with access token")
            
            max_attempts = 3
            backoff_seconds = 1
            
            for attempt in range(max_attempts):
                try:
                    response = await self.client.get(
                        f"{self.api_base}/users/@me/guilds",
                        headers={'Authorization': f"Bearer {access_token}"}
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    logger.info(f"Found {len(result)} guilds for user")
                    return result
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        # Rate limited
                        retry_after = e.response.headers.get('retry-after', backoff_seconds)
                        if isinstance(retry_after, str):
                            retry_after = float(retry_after)
                        
                        logger.warning(f"Rate limited. Retry after: {retry_after}s. Attempt {attempt + 1}/{max_attempts}")
                        
                        if attempt < max_attempts - 1:
                            import asyncio
                            await asyncio.sleep(retry_after)
                            backoff_seconds *= 2
                    else:
                        logger.error(f"Discord guilds fetch error: {e}")
                        break
                except httpx.HTTPError as e:
                    logger.error(f"Discord guilds fetch error: {e}")
                    break
            
            logger.error(f"Failed to fetch guilds after {max_attempts} attempts")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in get_user_guilds: {e}")
            return []
    
    async def is_guild_member(self, user_id: str, access_token: str, guild_id: Optional[str] = None) -> bool:
        """Check if user is a member of the required guild."""
        guild_id = guild_id or self.required_guild_id
        logger.info(f"Checking if user {user_id} is member of guild {guild_id}")
        
        guilds = await self.get_user_guilds(access_token)
        
        if not guilds:
            logger.warning(f"No guilds returned for user {user_id}")
            return False
        
        logger.info(f"User is in {len(guilds)} guilds")
        
        for guild in guilds:
            logger.info(f"User guild: {guild['id']} - {guild['name']}")
            if guild['id'] == guild_id:
                logger.info(f"User {user_id} is member of guild {guild_id} ({guild['name']})")
                return True
        
        logger.info(f"User {user_id} is not member of guild {guild_id}")
        return False
    
    async def is_guild_member_by_name(self, user_id: str, access_token: str, guild_name: str) -> bool:
        """Check if user is a member of a guild by name."""
        logger.info(f"Checking if user {user_id} is member of guild '{guild_name}'")
        
        guilds = await self.get_user_guilds(access_token)
        
        if not guilds:
            logger.warning(f"No guilds returned for user {user_id}")
            return False
        
        logger.info(f"User is in {len(guilds)} guilds")
        
        for guild in guilds:
            logger.info(f"User guild: {guild['id']} - {guild['name']}")
            if guild['name'].lower() == guild_name.lower():
                logger.info(f"User {user_id} is member of guild '{guild_name}' (ID: {guild['id']})")
                return True
        
        logger.info(f"User {user_id} is not member of guild '{guild_name}'")
        return False
    
    async def get_member_roles(self, user_id: str, guild_id: Optional[str] = None) -> List[str]:
        """Get member roles for a specific guild."""
        guild_id = guild_id or self.required_guild_id
        
        try:
            logger.info(f"Getting roles for user {user_id} in guild {guild_id}")
            
            if not self.bot_token:
                logger.error("DISCORD_BOT_TOKEN environment variable is missing or empty")
                return []
            
            # Remove "Bot " prefix if present
            bot_token = self.bot_token
            if bot_token.startswith('Bot '):
                bot_token = bot_token[4:]
            
            max_attempts = 3
            backoff_seconds = 1
            
            for attempt in range(max_attempts):
                try:
                    response = await self.client.get(
                        f"{self.api_base}/guilds/{guild_id}/members/{user_id}",
                        headers={'Authorization': f"Bot {bot_token}"}
                    )
                    response.raise_for_status()
                    
                    member = response.json()
                    
                    if 'roles' in member and isinstance(member['roles'], list):
                        # Normalize role IDs to strings
                        roles = [str(role_id) for role_id in member['roles']]
                        roles_count = len(roles)
                        logger.info(f"Found {roles_count} roles for user: {roles}")
                        return roles
                    elif 'roles' not in member:
                        logger.warning(f"No 'roles' key in member data. Keys: {member.keys()}")
                    else:
                        logger.warning(f"Member 'roles' is not a list: {type(member['roles'])}")
                    
                    logger.warning("No roles found in member data")
                    return []
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        retry_after = e.response.headers.get('retry-after', backoff_seconds)
                        if isinstance(retry_after, str):
                            retry_after = float(retry_after)
                        
                        logger.warning(f"Rate limited. Retry after: {retry_after}s. Attempt {attempt + 1}/{max_attempts}")
                        
                        if attempt < max_attempts - 1:
                            import asyncio
                            await asyncio.sleep(retry_after)
                            backoff_seconds *= 2
                    elif e.response.status_code == 403:
                        logger.error(f"Bot does not have permission to view guild members (403 Forbidden). Bot needs 'View Server Members' permission.")
                        logger.error(f"Response: {e.response.text}")
                        break
                    elif e.response.status_code == 404:
                        logger.error(f"User {user_id} not found in guild {guild_id} (404 Not Found)")
                        logger.error(f"Response: {e.response.text}")
                        break
                    else:
                        logger.error(f"Discord member roles fetch error: {e.response.status_code}")
                        logger.error(f"Response: {e.response.text}")
                        break
                except httpx.HTTPError as e:
                    logger.error(f"Discord member roles fetch error: {e}")
                    break
            
            logger.error(f"Failed to get member roles after {max_attempts} attempts")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in get_member_roles: {e}")
            return []
    
    async def _get_guild_roles_cached(self, guild_id: str) -> Optional[List[Dict]]:
        """Get guild roles from Redis cache or None if not cached."""
        redis_client = get_redis_cache_client()
        if not redis_client:
            return None
        
        try:
            cache_key = f"discord:guild_roles:{guild_id}"
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                roles = json.loads(cached_data)
                logger.debug(f"Retrieved {len(roles)} roles from Redis cache for guild {guild_id}")
                return roles
        except Exception as e:
            logger.debug(f"Error reading from Redis cache: {e}")
        
        return None
    
    async def _set_guild_roles_cache(self, guild_id: str, roles: List[Dict], ttl: int = 86400):
        """Store guild roles in Redis cache with TTL (default 24 hours)."""
        redis_client = get_redis_cache_client()
        if not redis_client:
            return
        
        try:
            cache_key = f"discord:guild_roles:{guild_id}"
            cached_data = json.dumps(roles)
            await redis_client.setex(cache_key, ttl, cached_data)
            logger.debug(f"Cached {len(roles)} roles in Redis for guild {guild_id} (TTL: {ttl}s)")
        except Exception as e:
            logger.debug(f"Error writing to Redis cache: {e}")
    
    async def _clear_guild_roles_cache(self, guild_id: str):
        """Clear cached guild roles (e.g., on server restart)."""
        redis_client = get_redis_cache_client()
        if not redis_client:
            return
        
        try:
            cache_key = f"discord:guild_roles:{guild_id}"
            await redis_client.delete(cache_key)
            logger.debug(f"Cleared Redis cache for guild {guild_id}")
        except Exception as e:
            logger.debug(f"Error clearing Redis cache: {e}")
    
    async def check_roles(self, user_id: str, role_names: List[str], guild_id: Optional[str] = None) -> Dict[str, bool]:
        """Check if user has multiple roles in the guild. Returns a dict mapping role names to boolean values.
        
        This is more efficient than calling has_role multiple times as it only fetches
        the roles list and user member info once. Guild roles are cached in Redis for 24h.
        """
        guild_id = guild_id or self.required_guild_id
        logger.info(f"Checking if user {user_id} has roles {role_names} in guild {guild_id}")
        
        if not self.bot_token:
            logger.error("DISCORD_BOT_TOKEN is not set in environment variables")
            return {role_name: False for role_name in role_names}
        
        # Remove "Bot " prefix if present
        bot_token = self.bot_token
        if bot_token.startswith('Bot '):
            bot_token = bot_token[4:]
        
        result = {role_name: False for role_name in role_names}
        
        try:
            # Try to get roles from cache first
            roles = await self._get_guild_roles_cached(guild_id)
            
            if roles is None:
                # Cache miss - fetch from API
                logger.debug(f"Cache miss for guild {guild_id} roles, fetching from Discord API")
                response = await self.client.get(
                    f"{self.api_base}/guilds/{guild_id}/roles",
                    headers={'Authorization': f"Bot {bot_token}"}
                )
                response.raise_for_status()
                
                roles = response.json()
                logger.info(f"Retrieved {len(roles)} roles from Discord API")
                
                # Cache the roles for 24 hours
                await self._set_guild_roles_cache(guild_id, roles, ttl=86400)
            else:
                logger.debug(f"Cache hit for guild {guild_id} roles")
            
            # Log all available roles for debugging
            available_role_names = [r['name'] for r in roles]
            logger.info(f"Available roles in guild: {available_role_names}")
            
            # Build a map of role names (lowercase) to role IDs
            role_name_to_id = {}
            for role in roles:
                role_name_to_id[role['name'].lower()] = str(role['id'])
            
            # Find role IDs for all requested roles
            requested_role_ids = {}
            for role_name in role_names:
                role_id = role_name_to_id.get(role_name.lower())
                if role_id:
                    requested_role_ids[role_name] = role_id
                    logger.info(f"Found role ID {role_id} for role '{role_name}' (case-insensitive match)")
                else:
                    logger.warning(f"Role '{role_name}' not found in guild {guild_id}")
            
            if not requested_role_ids:
                logger.warning(f"None of the requested roles were found in guild")
                return result
            
            # Get the user's roles (once)
            user_roles = await self.get_member_roles(user_id, guild_id)
            logger.info(f"User roles retrieved: {user_roles}")
            
            # Check each role
            for role_name, role_id in requested_role_ids.items():
                has_role = role_id in user_roles
                result[role_name] = has_role
                logger.info(f"User {'HAS' if has_role else 'DOES NOT HAVE'} the '{role_name}' role (ID: {role_id})")
            
            return result
        except httpx.HTTPError as e:
            logger.error(f"Error fetching guild roles: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            return result
        except Exception as e:
            logger.error(f"Unexpected error in check_roles: {e}", exc_info=True)
            return result
    
    async def has_role(self, user_id: str, role_name: str, guild_id: Optional[str] = None) -> bool:
        """Check if user has a specific role in the guild.
        
        For checking multiple roles, use check_roles() instead for better performance.
        """
        results = await self.check_roles(user_id, [role_name], guild_id)
        return results.get(role_name, False)
    
    def get_required_guild_id(self) -> str:
        """Get the required guild ID."""
        return self.required_guild_id
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

