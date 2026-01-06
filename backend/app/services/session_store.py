"""File-based session store for persistent sessions across server restarts."""
import os
import json
import pickle
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class FileSessionStore:
    """File-based session store that persists sessions across server restarts."""
    
    def __init__(self, session_dir: str = None):
        if session_dir is None:
            # Default to data/sessions directory
            project_root = Path(__file__).parent.parent.parent
            session_dir = project_root / 'data' / 'sessions'
        
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Session store initialized at: {self.session_dir}")
    
    def _get_session_path(self, session_id: str) -> Path:
        """Get file path for a session ID."""
        # Use hash to avoid filesystem issues with special characters
        session_hash = hashlib.md5(session_id.encode()).hexdigest()
        return self.session_dir / f"{session_hash}.session"
    
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by session ID."""
        try:
            session_path = self._get_session_path(session_id)
            if not session_path.exists():
                return None
            
            # Check if session is expired
            if self._is_expired(session_path):
                self.delete(session_id)
                return None
            
            with open(session_path, 'rb') as f:
                session_data = pickle.load(f)
            
            return session_data.get('data', {})
        except Exception as e:
            logger.error(f"Error reading session {session_id}: {e}")
            return None
    
    def set(self, session_id: str, data: Dict[str, Any], max_age: int = 3600 * 24 * 7):
        """Set session data."""
        try:
            session_path = self._get_session_path(session_id)
            
            session_data = {
                'data': data,
                'created_at': datetime.utcnow().isoformat(),
                'max_age': max_age
            }
            
            with open(session_path, 'wb') as f:
                pickle.dump(session_data, f)
            
            # Set file modification time for expiration checking
            expires_at = datetime.utcnow() + timedelta(seconds=max_age)
            expires_timestamp = expires_at.timestamp()
            os.utime(session_path, (expires_timestamp, expires_timestamp))
            
        except Exception as e:
            logger.error(f"Error writing session {session_id}: {e}")
    
    def delete(self, session_id: str):
        """Delete a session."""
        try:
            session_path = self._get_session_path(session_id)
            if session_path.exists():
                session_path.unlink()
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
    
    def _is_expired(self, session_path: Path) -> bool:
        """Check if session file is expired."""
        try:
            # Check file modification time
            mtime = session_path.stat().st_mtime
            expires_at = datetime.fromtimestamp(mtime)
            return datetime.utcnow() > expires_at
        except Exception:
            return True
    
    def cleanup_expired(self):
        """Clean up expired session files."""
        try:
            expired_count = 0
            for session_file in self.session_dir.glob('*.session'):
                if self._is_expired(session_file):
                    session_file.unlink()
                    expired_count += 1
            
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired sessions")
        except Exception as e:
            logger.error(f"Error cleaning up expired sessions: {e}")




