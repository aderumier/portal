"""Script to clear all data from database tables."""
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal, Base, engine
from app.database import DownloadQueue, ApiToken, User, UserSession, Game, System
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clear_all_tables():
    """Clear all data from all database tables."""
    db = SessionLocal()
    try:
        logger.info("Starting database cleanup...")
        
        # Get all table names
        tables = [
            'download_queue',
            'api_tokens',
            'users',
            'sessions',
            'games',
            'systems'
        ]
        
        # Disable foreign key constraints for SQLite
        if 'sqlite' in str(engine.url):
            db.execute(text("PRAGMA foreign_keys = OFF"))
        
        # Clear each table
        for table in tables:
            try:
                result = db.execute(text(f"DELETE FROM {table}"))
                count = result.rowcount
                logger.info(f"Cleared {count} rows from {table}")
            except Exception as e:
                logger.warning(f"Could not clear table {table}: {e}")
        
        # Reset auto-increment counters for SQLite
        if 'sqlite' in str(engine.url):
            db.execute(text("PRAGMA foreign_keys = ON"))
            # Reset sequences
            for table in tables:
                try:
                    db.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
                except:
                    pass  # Table might not have auto-increment
        
        db.commit()
        logger.info("Database cleanup completed successfully!")
        return True
    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("WARNING: This will delete ALL data from ALL database tables!")
    print("=" * 60)
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        if clear_all_tables():
            print("\n✓ Database cleared successfully!")
        else:
            print("\n✗ Failed to clear database. Check logs for details.")
            sys.exit(1)
    else:
        print("Operation cancelled.")
        sys.exit(0)














