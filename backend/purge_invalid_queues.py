import sys
import os
import logging

# Add the parent directory to the path so we can import from app
# backend/purge_invalid_queues.py -> backend/
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from app.database import SessionLocal, DownloadQueue
    from sqlalchemy import or_
    
    def purge_invalid_queues():
        """Remove download queue items with missing system_id."""
        db = SessionLocal()
        try:
            # Find items with missing system_id
            # We check for None or empty string
            query = db.query(DownloadQueue).filter(
                or_(
                    DownloadQueue.system_id == None,
                    DownloadQueue.system_id == ''
                )
            )
            
            count = query.count()
            
            if count == 0:
                logger.info("No invalid queue items found (all have system_id).")
                return
                
            logger.info(f"Found {count} items with missing system_id.")
            
            # Delete identified items
            current = query.all()
            for item in current:
               db.delete(item)
            
            db.commit()
            
            logger.info(f"Successfully deleted {count} invalid items.")
            
        except Exception as e:
            logger.error(f"Error purging queues: {e}")
            db.rollback()
        finally:
            db.close()

    if __name__ == "__main__":
        purge_invalid_queues()

except ImportError as e:
    logger.error(f"Import Error: {e}")
    logger.error("Please run this script from the backend directory using valid python environment.")
