"""File-based session middleware."""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.services.session_store import FileSessionStore

logger = logging.getLogger(__name__)


class FileSessionMiddleware(BaseHTTPMiddleware):
    """Middleware that provides persistent sessions stored in files."""
    
    def __init__(self, app, session_store: FileSessionStore, secret_key: str, max_age: int = 3600 * 24, same_site: str = "lax"):  # Default: 24 hours
        super().__init__(app)
        self.session_store = session_store
        self.secret_key = secret_key
        self.max_age = max_age
        self.same_site = same_site
        self.session_cookie = "session"
    
    async def dispatch(self, request: Request, call_next):
        """Process request and manage session."""
        # Get session ID from cookie
        session_id = request.cookies.get(self.session_cookie)
        
        # Load session data from file store
        session_data = {}
        if session_id:
            try:
                session_data = self.session_store.get(session_id) or {}
            except Exception as e:
                logger.warning(f"Error loading session: {e}")
                session_id = None
        
        # If no valid session, create new one
        if not session_id or not session_data:
            session_id = secrets.token_urlsafe(32)
            session_data = {}
        
        # Attach session to request scope
        session_dict = SessionDict(session_data, session_id, self)
        request.scope['session'] = session_dict
        request.scope['_file_session_id'] = session_id
        
        # Process request
        response = await call_next(request)
        
        # Save session if modified
        current_session = request.scope.get('session', {})
        session_data = {}
        if isinstance(current_session, SessionDict):
            session_data = dict(current_session)
            if current_session.modified:
                # If session was cleared (empty), delete it from storage
                if len(session_data) == 0:
                    self.session_store.delete(session_id)
                    # Delete cookie
                    response.delete_cookie(
                        key=self.session_cookie,
                        path='/',
                        httponly=True,
                        samesite=self.same_site
                    )
                    return response
                else:
                    self.session_store.set(session_id, session_data, max_age=self.max_age)
        
        # Set session cookie only if session has data
        if session_data:
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
    """Dictionary-like object for session data with modification tracking."""
    
    def __init__(self, data: Dict[str, Any], session_id: str, middleware: FileSessionMiddleware):
        super().__init__(data)
        self.session_id = session_id
        self.middleware = middleware
        self.modified = False
        self._original_data = dict(data)
    
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True
    
    def __delitem__(self, key):
        super().__delitem__(key)
        self.modified = True
    
    def clear(self):
        super().clear()
        self.modified = True
        self.middleware.session_store.delete(self.session_id)
    
    def pop(self, key, default=None):
        result = super().pop(key, default)
        if key in self._original_data:
            self.modified = True
        return result
    
    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.modified = True


