"""Database configuration and models."""
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, BigInteger, Float, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from app.config import settings
import os
from pathlib import Path

# Create database directory if it doesn't exist
db_path = settings.DATABASE_URL.replace('sqlite:///', '')
if db_path.startswith('./'):
    # Resolve relative path from project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(project_root, db_path[2:])
elif not os.path.isabs(db_path):
    # If relative path doesn't start with ./, make it relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(project_root, db_path)

# Ensure database directory exists
db_dir = os.path.dirname(db_path)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

# Update DATABASE_URL with absolute path
settings.DATABASE_URL = f'sqlite:///{os.path.abspath(db_path)}'

# Create engine
connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args
)

# For SQLite, enable WAL (Write-Ahead Logging) mode for better concurrency
# WAL allows multiple readers and one writer simultaneously
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Enable WAL mode and performance optimizations for SQLite."""
        # Enable WAL mode (Write-Ahead Logging) for better concurrency
        # Note: WAL file (.wal) is created on first write operation
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        # Good balance between safety and speed (NORMAL is faster than FULL, safer than OFF)
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")
        # 64MB cache (negative value means KB, so -64000 = 64MB)
        dbapi_conn.execute("PRAGMA cache_size=-64000")
        # Enable foreign key constraints
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


class DownloadQueue(Base):
    """Download queue model."""
    __tablename__ = "download_queue"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    game_id = Column(String, nullable=False)
    status = Column(String, default='pending')
    created_at = Column(DateTime, server_default=func.now())
    
    # Bandwidth management fields
    queue_type = Column(String, default='slow', index=True)  # 'fast' or 'slow'
    active_download = Column(Boolean, default=False, index=True)
    bandwidth_used = Column(Integer, default=0)  # Current bytes/second usage
    bytes_transferred = Column(BigInteger, default=0)  # Total bytes transferred
    file_size = Column(BigInteger, nullable=True)  # Total file size in bytes
    started_at = Column(DateTime, nullable=True)  # When download started
    last_progress_at = Column(DateTime, nullable=True)  # When progress was last reported
    assigned_to_service = Column(String, nullable=True)  # Service instance ID handling this download
    token_id = Column(Integer, nullable=False, index=True)  # Associated API token ID (required)
    
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class DownloadArchive(Base):
    """Download archive model for storing completed/cancelled/error downloads."""
    __tablename__ = "download_archive"
    
    id = Column(Integer, primary_key=True, index=True)
    download_id = Column(Integer, nullable=False, index=True)  # Original download queue ID
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=True)  # Discord username at time of archive
    game_name = Column(String, nullable=False)
    system = Column(String, nullable=True)
    rompath = Column(String, nullable=False)  # game_id from download queue
    download_status = Column(String, nullable=False)  # 'completed', 'error', 'cancelled', 'stuck', etc.
    bytes_transferred = Column(BigInteger, default=0)  # Bytes transferred before removal
    file_size = Column(BigInteger, nullable=True)  # Total file size if known
    
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class ApiToken(Base):
    """API token model."""
    __tablename__ = "api_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    
    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class Game(Base):
    """Game cache model (optional)."""
    __tablename__ = "games"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    image = Column(String, nullable=True)
    system = Column(String, nullable=False)


class System(Base):
    """System configuration model."""
    __tablename__ = "systems"
    
    id = Column(String, primary_key=True)  # System ID (e.g., 'nes', 'snes')
    name = Column(String, nullable=False)  # Short name
    fullname = Column(String, nullable=True)  # Full display name
    hardware = Column(String, nullable=True)  # Hardware category
    release = Column(String, nullable=True)  # Release year
    manufacturer = Column(String, nullable=True)  # Manufacturer
    batocera_system = Column(String, nullable=True)  # System name from es_systems.cfg for Batocera (last directory of path)
    retrobat_system = Column(String, nullable=True)  # System name from es_systems.cfg for Retrobat (last directory of path)
    enabled = Column(Boolean, default=True, nullable=False, index=True)  # Whether system is enabled
    download_enabled = Column(Boolean, default=True, nullable=False)  # Whether downloads are enabled for this system
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserSession(Base):
    """Session model for persistent user sessions."""
    __tablename__ = "sessions"
    
    session_id = Column(String, primary_key=True, index=True)
    data = Column(Text, nullable=False)  # JSON-encoded session data
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        {'sqlite_autoincrement': False},
    )


class User(Base):
    """User statistics model."""
    __tablename__ = "users"
    
    user_id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=True)  # Discord username
    total_download_mb = Column(Float, default=0.0, nullable=False)  # Total downloaded MB
    total_download_number = Column(Integer, default=0, nullable=False)  # Total number of games downloaded
    medias_upload = Column(Integer, default=0, nullable=False)  # Total number of media files uploaded
    medias_validated = Column(Integer, default=0, nullable=False)  # Total number of media files validated
    bandwidth_limit = Column(Integer, nullable=True)  # User's custom bandwidth limit in bytes/s (capped at role limit)
    last_login = Column(DateTime, nullable=True)  # Last login datetime
    last_login_ip = Column(String, nullable=True)  # IP address from last login
    country = Column(String, nullable=True)  # Country code from GeoIP lookup
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        {'sqlite_autoincrement': False},
    )


def init_db():
    """Initialize database tables and run migrations."""
    Base.metadata.create_all(bind=engine)
    
    # Run migrations to add any missing columns
    try:
        import sys
        import os
        # Add parent directory to path to import migrate_database
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from migrate_database import migrate_database
        migrate_database()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Migration check failed (this is OK if tables don't exist yet): {e}")


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

