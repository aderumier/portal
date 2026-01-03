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
        ("assigned_to_service", "TEXT"),
        ("token_id", "INTEGER NOT NULL DEFAULT 0"),  # Will be updated to actual token IDs
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
    
    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == "__main__":
    migrate_database()

