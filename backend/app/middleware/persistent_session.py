"""Persistent session middleware that stores sessions in database."""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session
from app.config import settings
from app.database import UserSession, SessionLocal
import secrets

logger = logging.getLogger(__name__)

class PersistentSessionMiddleware(BaseHTTPMiddleware):
    """Middleware that provides persistent sessions stored in database."""
    
    def __init__(self, app, secret_key: str, max_age: int = 3600 * 24, same_site: str = "lax"):  # Default: 24 hours
        super().__init__(app)
        self.secret_key = secret_key
        self.max_age = max_age
        self.same_site = same_site
        self.serializer = URLSafeSerializer(secret_key)
        self.session_cookie = "session"
    
    async def dispatch(self, request: Request, call_next):
        """Process request and manage session."""
        # Get session ID from cookie
        session_id = request.cookies.get(self.session_cookie)
        
        # Load session data from database
        session_data = {}
        if session_id:
            try:
                session_data = self._load_session(session_id)
            except Exception as e:
                logger.warning(f"Error loading session: {e}")
                session_id = None
        
        # If no valid session, create new one
        if not session_id or not session_data:
            session_id = secrets.token_urlsafe(32)
            session_data = {}
        
        # Attach session to request scope (Starlette's SessionMiddleware stores it here)
        # The request.session property reads from request.scope['session']
        # We use a SessionDict that tracks modifications
        session_dict = SessionDict(session_data, session_id, self)
        request.scope['session'] = session_dict
        # Store session ID for saving later
        request.scope['_persistent_session_id'] = session_id
        
        # Process request
        response = await call_next(request)
        
        # Save session if modified
        current_session = request.scope.get('session', {})
        session_data = {}
        if isinstance(current_session, SessionDict):
            session_data = dict(current_session)
            if current_session.modified:
                # If session was cleared (empty), delete it from database
                if len(session_data) == 0:
                    self._delete_session(session_id)
                    # Delete cookie
                    response.delete_cookie(
                        key=self.session_cookie,
                        path='/',
                        httponly=True,
                        samesite=self.same_site
                    )
                    return response
                else:
                    self._save_session(session_id, session_data)
        
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
    
    def _load_session(self, session_id: str) -> Dict[str, Any]:
        """Load session data from database."""
        db = SessionLocal()
        try:
            session_record = db.query(UserSession).filter(
                UserSession.session_id == session_id
            ).first()
            
            if not session_record:
                return {}
            
            # Check if expired
            if session_record.expires_at < datetime.now(timezone.utc):
                db.delete(session_record)
                db.commit()
                return {}
            
            # Deserialize session data
            try:
                return json.loads(session_record.data)
            except json.JSONDecodeError:
                logger.warning(f"Invalid session data for {session_id}")
                db.delete(session_record)
                db.commit()
                return {}
        finally:
            db.close()
    
    def _save_session(self, session_id: str, data: Dict[str, Any]):
        """Save session data to database."""
        db = SessionLocal()
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.max_age)
            
            session_record = db.query(UserSession).filter(
                UserSession.session_id == session_id
            ).first()
            
            if session_record:
                # Update existing session
                session_record.data = json.dumps(data)
                session_record.expires_at = expires_at
            else:
                # Create new session
                session_record = UserSession(
                    session_id=session_id,
                    data=json.dumps(data),
                    expires_at=expires_at
                )
                db.add(session_record)
            
            db.commit()
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            import traceback
            logger.error(traceback.format_exc())
            db.rollback()
        finally:
            db.close()
    
    def _delete_session(self, session_id: str):
        """Delete session from database."""
        db = SessionLocal()
        try:
            session_record = db.query(UserSession).filter(
                UserSession.session_id == session_id
            ).first()
            
            if session_record:
                db.delete(session_record)
                db.commit()
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            db.rollback()
        finally:
            db.close()


class SessionDict(dict):
    """Dictionary-like object for session data with modification tracking."""
    
    def __init__(self, data: Dict[str, Any], session_id: str, middleware: PersistentSessionMiddleware):
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
        self.middleware._delete_session(self.session_id)
    
    def pop(self, key, default=None):
        result = super().pop(key, default)
        if key in self._original_data:
            self.modified = True
        return result
    
    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.modified = True

