"""Database migration script to add missing columns to download_queue table."""
import sqlite3
import os
from pathlib import Path
from app.config import settings

def migrate_database():
    """Add missing columns to download_queue table if they don't exist."""
    # Get database path
    db_path = settings.DATABASE_URL.replace('sqlite:///', '')
    if db_path.startswith('./'):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        db_path = os.path.join(project_root, db_path[2:])
    elif not os.path.isabs(db_path):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        db_path = os.path.join(project_root, db_path)
    
    db_path = os.path.abspath(db_path)
    print(f"Database path resolved to: {db_path}")
    
    # Also check common alternative locations
    alternative_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'database.sqlite'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', 'data', 'database.sqlite'),
    ]
    
    if not os.path.exists(db_path):
        # Try alternative paths
        for alt_path in alternative_paths:
            alt_path = os.path.abspath(alt_path)
            if os.path.exists(alt_path):
                print(f"Found database at alternative location: {alt_path}")
                db_path = alt_path
                break
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}, it will be created on first run.")
        return
    
    print(f"Migrating database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get current columns
    cursor.execute("PRAGMA table_info(download_queue)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    print(f"Existing columns: {existing_columns}")
    
    # Columns to add
    columns_to_add = [
        ("queue_type", "TEXT DEFAULT 'slow'"),
        ("active_download", "INTEGER DEFAULT 0"),
        ("bandwidth_used", "INTEGER DEFAULT 0"),
        ("bytes_transferred", "INTEGER DEFAULT 0"),
        ("file_size", "INTEGER"),
        ("started_at", "TEXT"),
        ("last_progress_at", "TEXT"),
        ("assigned_to_service", "TEXT"),
        ("token_id", "INTEGER NOT NULL DEFAULT 0"),  # Will be updated to actual token IDs
        ("catalog_version", "TEXT"),  # Version string (e.g., "v2-RGS_bbc") for Releases catalog, NULL for WIP
        ("client_version", "TEXT"),  # Download client version (e.g., "0.1")
    ]
    
    # Add missing columns
    for col_name, col_def in columns_to_add:
        if col_name not in existing_columns:
            try:
                alter_sql = f"ALTER TABLE download_queue ADD COLUMN {col_name} {col_def}"
                print(f"Adding column {col_name}...")
                cursor.execute(alter_sql)
                print(f"  ✓ Added column {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Error adding column {col_name}: {e}")
        else:
            print(f"  - Column {col_name} already exists")
    
    # Create indexes if they don't exist
    indexes_to_create = [
        ("idx_download_queue_queue_type", "download_queue(queue_type)"),
        ("idx_download_queue_active_download", "download_queue(active_download)"),
        ("idx_download_queue_token_id", "download_queue(token_id)"),
        ("idx_download_queue_catalog_version", "download_queue(catalog_version)"),
    ]
    
    for idx_name, idx_def in indexes_to_create:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            print(f"  ✓ Created/verified index {idx_name}")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error creating index {idx_name}: {e}")
    
    # Create sessions table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✓ Created/verified sessions table")
    
    # Create index on expires_at for cleanup
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
        print("  ✓ Created/verified index idx_sessions_expires_at")
    except sqlite3.OperationalError as e:
        print(f"  ✗ Error creating index idx_sessions_expires_at: {e}")
    
    # Create users table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            total_download_mb REAL NOT NULL DEFAULT 0.0,
            total_download_number INTEGER NOT NULL DEFAULT 0,
            last_login TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✓ Created/verified users table")
    
    # Check existing columns and add missing ones
    cursor.execute("PRAGMA table_info(users)")
    existing_user_columns = [col[1] for col in cursor.fetchall()]
    
    columns_to_add = [
        ("total_download_number", "INTEGER NOT NULL DEFAULT 0"),
        ("username", "TEXT"),
        ("last_login", "TEXT"),
        ("medias_upload", "INTEGER NOT NULL DEFAULT 0"),
        ("medias_validated", "INTEGER NOT NULL DEFAULT 0"),
        ("bandwidth_limit", "INTEGER"),
        ("last_login_ip", "TEXT"),
        ("country", "TEXT"),
    ]
    
    for col_name, col_def in columns_to_add:
        if col_name not in existing_user_columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                print(f"  ✓ Added column {col_name} to users table")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Error adding column {col_name}: {e}")
        else:
            print(f"  - Column {col_name} already exists")
    
    # Create index on user_id (though it's already the primary key, this ensures it exists)
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        print("  ✓ Created/verified index idx_users_user_id")
    except sqlite3.OperationalError as e:
        print(f"  ✗ Error creating index idx_users_user_id: {e}")
    
    # Create download_archive table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS download_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            download_id INTEGER NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            game_name TEXT NOT NULL,
            system TEXT,
            rompath TEXT NOT NULL,
            download_status TEXT NOT NULL,
            bytes_transferred INTEGER DEFAULT 0,
            file_size INTEGER,
            catalog_version TEXT
        )
    """)
    print("  ✓ Created/verified download_archive table")
    
    # Check existing columns and add catalog_version and client_version if missing
    cursor.execute("PRAGMA table_info(download_archive)")
    existing_archive_columns = [col[1] for col in cursor.fetchall()]
    
    if 'catalog_version' not in existing_archive_columns:
        try:
            cursor.execute("ALTER TABLE download_archive ADD COLUMN catalog_version TEXT")
            print("  ✓ Added column catalog_version to download_archive table")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error adding column catalog_version: {e}")
    else:
        print("  - Column catalog_version already exists in download_archive table")
    
    if 'client_version' not in existing_archive_columns:
        try:
            cursor.execute("ALTER TABLE download_archive ADD COLUMN client_version TEXT")
            print("  ✓ Added column client_version to download_archive table")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error adding column client_version: {e}")
    else:
        print("  - Column client_version already exists in download_archive table")
    
    # Create indexes for download_archive
    indexes_to_create = [
        ("idx_download_archive_download_id", "download_archive(download_id)"),
        ("idx_download_archive_timestamp", "download_archive(timestamp)"),
        ("idx_download_archive_user_id", "download_archive(user_id)"),
    ]
    
    for idx_name, idx_def in indexes_to_create:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            print(f"  ✓ Created/verified index {idx_name}")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error creating index {idx_name}: {e}")
    
    # Create systems table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS systems (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            fullname TEXT,
            hardware TEXT,
            release TEXT,
            manufacturer TEXT,
            batocera_system TEXT,
            retrobat_system TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✓ Created/verified systems table")
    
    # Check existing columns and add missing ones
    cursor.execute("PRAGMA table_info(systems)")
    existing_system_columns = [col[1] for col in cursor.fetchall()]
    
    system_columns_to_add = [
        ("fullname", "TEXT"),
        ("hardware", "TEXT"),
        ("release", "TEXT"),
        ("manufacturer", "TEXT"),
        ("batocera_system", "TEXT"),
        ("retrobat_system", "TEXT"),
        ("enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("download_enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
    ]
    
    # Migrate old columns if they exist (extract last directory from path)
    if 'batocerapath' in existing_system_columns and 'batocera_system' not in existing_system_columns:
        try:
            cursor.execute("ALTER TABLE systems ADD COLUMN batocera_system TEXT")
            # Get all rows with batocerapath and update with last directory
            cursor.execute("SELECT id, batocerapath FROM systems WHERE batocerapath IS NOT NULL")
            rows = cursor.fetchall()
            for row_id, path in rows:
                if path:
                    # Extract last directory from path
                    path_clean = path.rstrip('/').rstrip('\\')
                    last_dir = os.path.basename(path_clean) if path_clean else None
                    if last_dir:
                        cursor.execute("UPDATE systems SET batocera_system = ? WHERE id = ?", (last_dir, row_id))
            print(f"  ✓ Migrated batocerapath to batocera_system (extracted last directory from {len(rows)} rows)")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error migrating batocerapath: {e}")
    
    if 'retrobatpath' in existing_system_columns and 'retrobat_system' not in existing_system_columns:
        try:
            cursor.execute("ALTER TABLE systems ADD COLUMN retrobat_system TEXT")
            # Get all rows with retrobatpath and update with last directory
            cursor.execute("SELECT id, retrobatpath FROM systems WHERE retrobatpath IS NOT NULL")
            rows = cursor.fetchall()
            for row_id, path in rows:
                if path:
                    # Extract last directory from path
                    path_clean = path.rstrip('/').rstrip('\\')
                    last_dir = os.path.basename(path_clean) if path_clean else None
                    if last_dir:
                        cursor.execute("UPDATE systems SET retrobat_system = ? WHERE id = ?", (last_dir, row_id))
            print(f"  ✓ Migrated retrobatpath to retrobat_system (extracted last directory from {len(rows)} rows)")
        except sqlite3.OperationalError as e:
            print(f"  ✗ Error migrating retrobatpath: {e}")
    
    for col_name, col_def in system_columns_to_add:
        if col_name not in existing_system_columns:
            try:
                cursor.execute(f"ALTER TABLE systems ADD COLUMN {col_name} {col_def}")
                print(f"  ✓ Added column {col_name} to systems table")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Error adding column {col_name}: {e}")
        else:
            print(f"  - Column {col_name} already exists")
    
    # Create index on enabled for filtering
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_systems_enabled ON systems(enabled)")
        print("  ✓ Created/verified index idx_systems_enabled")
    except sqlite3.OperationalError as e:
        print(f"  ✗ Error creating index idx_systems_enabled: {e}")
    
    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == "__main__":
    migrate_database()

