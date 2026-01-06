"""Redis-based session middleware for Starlette/FastAPI."""
import logging
import secrets
import json
import pickle
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)
# Note: Log level is controlled by the application's logging configuration


class RedisSessionMiddleware(BaseHTTPMiddleware):
    """Redis-based session middleware compatible with Starlette's SessionMiddleware API.
    
    This middleware stores session data in Redis, providing persistent sessions
    that survive server restarts and can be shared across multiple server instances.
    
    Usage:
        from app.middleware.redis_session_middleware import RedisSessionMiddleware
        import redis.asyncio as aioredis
        
        redis_client = aioredis.from_url('redis://localhost:6379/0')
        app.add_middleware(
            RedisSessionMiddleware,
            redis=redis_client,
            secret_key="your-secret-key",
            max_age=3600 * 24,  # 24 hours
            same_site="lax",
            key_prefix="session:"
        )
    """
    
    def __init__(
        self,
        app,
        redis,
        secret_key: str,
        max_age: int = 3600 * 24,  # Default: 24 hours
        same_site: str = "lax",
        key_prefix: Optional[str] = "session:"
    ):
        """Initialize Redis session middleware.
        
        Args:
            app: The Starlette/FastAPI application
            redis: Async Redis client (from redis.asyncio)
            secret_key: Secret key for session encryption (not used for Redis, but kept for API compatibility)
            max_age: Session expiration time in seconds (default: 24 hours)
            same_site: SameSite cookie attribute (default: "lax")
            key_prefix: Prefix for Redis keys (default: "session:")
        """
        super().__init__(app)
        self.redis = redis
        self.secret_key = secret_key
        self.max_age = max_age
        self.same_site = same_site
        self.key_prefix = key_prefix or ""
        self.session_cookie = "session"
        
        logger.info(f"RedisSessionMiddleware initialized (prefix: {self.key_prefix}, max_age: {self.max_age}s)")
    
    def _get_redis_key(self, session_id: str) -> str:
        """Get Redis key for a session ID."""
        return f"{self.key_prefix}{session_id}"
    
    async def _load_session(self, session_id: str) -> Dict[str, Any]:
        """Load session data from Redis.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary containing session data, or empty dict if not found
        """
        try:
            redis_key = self._get_redis_key(session_id)
            logger.debug(f"Loading session from Redis key: {redis_key}")
            data = await self.redis.get(redis_key)
            
            if data is None:
                logger.debug(f"Session not found in Redis: {redis_key}")
                return {}
            
            logger.debug(f"Retrieved data from Redis: {len(data)} bytes, type: {type(data)}")
            
            # Try to deserialize as JSON first, fallback to pickle
            try:
                if isinstance(data, bytes):
                    data_str = data.decode('utf-8')
                else:
                    data_str = data
                result = json.loads(data_str)
                logger.info(f"✓ Loaded session from Redis (JSON): {redis_key}, {len(result)} keys")
                return result
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.debug(f"JSON deserialization failed: {e}, trying pickle")
                # Fallback to pickle for complex objects
                if isinstance(data, str):
                    data = data.encode('utf-8')
                result = pickle.loads(data)
                logger.info(f"✓ Loaded session from Redis (pickle): {redis_key}, {len(result)} keys")
                return result
        except Exception as e:
            logger.error(f"Error loading session from Redis: {e}", exc_info=True)
            return {}
    
    async def _save_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """Save session data to Redis.
        
        Args:
            session_id: Session identifier
            session_data: Dictionary containing session data
        """
        try:
            redis_key = self._get_redis_key(session_id)
            logger.debug(f"Saving session to Redis key: {redis_key} with {len(session_data)} keys")
            
            # Try to serialize as JSON first, fallback to pickle
            try:
                data_str = json.dumps(session_data)
                # Convert to bytes for Redis (decode_responses=False expects bytes)
                data = data_str.encode('utf-8')
                logger.debug(f"Serialized session as JSON: {len(data)} bytes")
            except (TypeError, ValueError) as e:
                logger.debug(f"JSON serialization failed: {e}, using pickle")
                # Fallback to pickle for complex objects (already bytes)
                data = pickle.dumps(session_data)
                logger.debug(f"Serialized session as pickle: {len(data)} bytes")
            
            # Store in Redis with expiration
            # Redis client is configured with decode_responses=False, so it expects bytes
            result = await self.redis.setex(
                redis_key,
                self.max_age,
                data
            )
            logger.info(f"✓ Session saved to Redis: {redis_key}, result: {result}, TTL: {self.max_age}s, size: {len(data)} bytes")
        except Exception as e:
            logger.error(f"Error saving session to Redis: {e}", exc_info=True)
    
    async def _delete_session(self, session_id: str) -> None:
        """Delete session from Redis.
        
        Args:
            session_id: Session identifier
        """
        try:
            redis_key = self._get_redis_key(session_id)
            await self.redis.delete(redis_key)
        except Exception as e:
            logger.error(f"Error deleting session from Redis: {e}", exc_info=True)
    
    async def dispatch(self, request: Request, call_next):
        """Process request and manage session.
        
        This method:
        1. Loads session data from Redis based on session cookie
        2. Attaches session to request scope (compatible with Starlette's SessionMiddleware)
        3. Processes the request
        4. Saves modified session data back to Redis
        5. Sets/updates session cookie
        """
        # Get session ID from cookie
        session_id = request.cookies.get(self.session_cookie)
        logger.debug(f"Session cookie value: {session_id[:20] + '...' if session_id and len(session_id) > 20 else session_id}")
        
        # Load session data from Redis
        session_data = {}
        if session_id:
            try:
                session_data = await self._load_session(session_id)
                logger.debug(f"Loaded session from Redis: {len(session_data)} keys")
                if session_data:
                    logger.debug(f"Session keys: {list(session_data.keys())}")
            except Exception as e:
                logger.warning(f"Error loading session: {e}", exc_info=True)
                session_id = None
        
        # If no valid session, create new one
        if not session_id or not session_data:
            if not session_id:
                session_id = secrets.token_urlsafe(32)
                logger.debug(f"Created new session ID: {session_id[:20]}...")
            session_data = {}
        
        # Attach session to request scope (Starlette's SessionMiddleware stores it here)
        # The request.session property reads from request.scope['session']
        # We use a SessionDict that tracks modifications
        session_dict = SessionDict(session_data, session_id, self)
        request.scope['session'] = session_dict
        # Store session ID for saving later
        request.scope['_redis_session_id'] = session_id
        
        # Process request
        response = await call_next(request)
        
        # Get current session after request processing
        current_session = request.scope.get('session', {})
        
        # Check if session should be deleted (e.g., on logout)
        should_delete = False
        if isinstance(current_session, SessionDict):
            should_delete = getattr(current_session, '_should_delete', False)
        
        if should_delete:
            # Delete session from Redis
            try:
                await self._delete_session(session_id)
                logger.info(f"Deleted session from Redis: {session_id[:20]}...")
                # Delete cookie by setting it to expire immediately
                response.delete_cookie(
                    key=self.session_cookie,
                    path='/',
                    httponly=True,
                    samesite=self.same_site
                )
                return response
            except Exception as e:
                logger.error(f"Failed to delete session from Redis: {e}", exc_info=True)
        
        # Always save session if it has data (even if not explicitly marked as modified)
        # This ensures sessions are persisted, especially for new logins
        should_save = False
        session_to_save = {}
        
        if isinstance(current_session, SessionDict):
            session_to_save = dict(current_session)
            should_save = current_session.modified or len(session_to_save) > 0
            logger.debug(f"SessionDict - modified: {current_session.modified}, has data: {len(session_to_save) > 0}, will save: {should_save}")
        elif isinstance(current_session, dict) and current_session:
            session_to_save = current_session
            should_save = True
            logger.debug(f"Regular dict session - will save: {len(session_to_save)} keys")
        
        if should_save and session_to_save:
            try:
                await self._save_session(session_id, session_to_save)
                logger.debug(f"Session saved to Redis: {session_id[:20]}... with {len(session_to_save)} keys")
            except Exception as e:
                logger.error(f"Failed to save session to Redis: {e}", exc_info=True)
        
        # Set session cookie (only if session has data)
        if session_to_save:
            expires = datetime.now(timezone.utc) + timedelta(seconds=self.max_age)
            response.set_cookie(
                key=self.session_cookie,
                value=session_id,
                max_age=self.max_age,
                expires=expires,
                httponly=True,
                secure=False,  # Set to True in production with HTTPS
                samesite=self.same_site,
                path="/"
            )
        
        return response


class SessionDict(dict):
    """Dictionary-like session object that tracks modifications.
    
    This class extends dict to track when session data is modified,
    allowing the middleware to only save sessions that have changed.
    """
    
    def __init__(self, data: Dict[str, Any], session_id: str, middleware: RedisSessionMiddleware):
        """Initialize session dictionary.
        
        Args:
            data: Initial session data
            session_id: Session identifier
            middleware: Reference to the RedisSessionMiddleware instance
        """
        super().__init__(data)
        self.session_id = session_id
        self.middleware = middleware
        self.modified = False
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Set item and mark as modified."""
        super().__setitem__(key, value)
        self.modified = True
    
    def __delitem__(self, key: str) -> None:
        """Delete item and mark as modified."""
        super().__delitem__(key)
        self.modified = True
    
    def update(self, *args, **kwargs) -> None:
        """Update dictionary and mark as modified."""
        super().update(*args, **kwargs)
        self.modified = True
    
    def pop(self, key: str, default: Any = None) -> Any:
        """Pop item and mark as modified."""
        result = super().pop(key, default)
        if key in self:
            self.modified = True
        return result
    
    def popitem(self) -> tuple:
        """Pop item and mark as modified."""
        result = super().popitem()
        self.modified = True
        return result
    
    def clear(self) -> None:
        """Clear dictionary and mark as modified.
        
        Note: Session deletion from Redis should be handled by the logout endpoint
        or middleware, as this method is synchronous and cannot await async operations.
        """
        super().clear()
        self.modified = True
        # Mark that session should be deleted (middleware will handle it)
        self._should_delete = True
    
    def setdefault(self, key: str, default: Any = None) -> Any:
        """Set default value and mark as modified if key didn't exist."""
        if key not in self:
            self.modified = True
        return super().setdefault(key, default)

