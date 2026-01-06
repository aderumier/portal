#!/usr/bin/env python3
"""Script to enable WAL mode on an existing SQLite database."""
import sqlite3
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.config import settings

def enable_wal_mode():
    """Enable WAL mode on the SQLite database."""
    # Get database path
    db_path = settings.DATABASE_URL.replace('sqlite:///', '')
    if db_path.startswith('./'):
        project_root = os.path.dirname(os.path.dirname(__file__))
        db_path = os.path.join(project_root, db_path[2:])
    elif not os.path.isabs(db_path):
        project_root = os.path.dirname(os.path.dirname(__file__))
        db_path = os.path.join(project_root, db_path)
    
    db_path = os.path.abspath(db_path)
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("WAL mode will be enabled automatically when the database is first created.")
        return
    
    print(f"Connecting to database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check current journal mode
        cursor.execute("PRAGMA journal_mode")
        current_mode = cursor.fetchone()[0]
        print(f"Current journal mode: {current_mode}")
        
        if current_mode.upper() == 'WAL':
            print("WAL mode is already enabled!")
        else:
            # Enable WAL mode
            print("Enabling WAL mode...")
            cursor.execute("PRAGMA journal_mode=WAL")
            new_mode = cursor.fetchone()[0]
            print(f"New journal mode: {new_mode}")
            
            if new_mode.upper() == 'WAL':
                print("✓ WAL mode enabled successfully!")
                print("You should now see a .wal file next to your database file.")
            else:
                print(f"⚠ Warning: Failed to enable WAL mode. Current mode: {new_mode}")
        
        # Set other optimizations
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA foreign_keys=ON")
        
        # Verify settings
        cursor.execute("PRAGMA journal_mode")
        print(f"Journal mode: {cursor.fetchone()[0]}")
        cursor.execute("PRAGMA synchronous")
        print(f"Synchronous: {cursor.fetchone()[0]}")
        cursor.execute("PRAGMA cache_size")
        cache_size = cursor.fetchone()[0]
        print(f"Cache size: {cache_size} KB ({abs(cache_size) // 1024} MB)")
        cursor.execute("PRAGMA foreign_keys")
        print(f"Foreign keys: {cursor.fetchone()[0]}")
        
        conn.close()
        print("\n✓ Database configuration updated successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    enable_wal_mode()


