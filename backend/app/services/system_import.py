"""Service for importing systems from GAMES_PATH."""
import os
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.database import System
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class SystemImportService:
    """Service for importing and managing systems."""
    
    def __init__(self, games_path: Optional[str] = None):
        self.games_path = games_path or settings.GAMES_PATH
    
    def get_systems_from_games_path(self) -> List[str]:
        """Get list of system directories from GAMES_PATH."""
        systems = []
        
        if not os.path.isdir(self.games_path):
            logger.warning(f"Games directory not found: {self.games_path}")
            return systems
        
        for dir_name in os.listdir(self.games_path):
            if dir_name in ['.', '..']:
                continue
            
            dir_path = os.path.join(self.games_path, dir_name)
            if os.path.isdir(dir_path):
                # Check if it has a gamelist.xml
                gamelist_path = os.path.join(dir_path, 'gamelist.xml')
                if os.path.isfile(gamelist_path):
                    systems.append(dir_name)
        
        return systems
    
    def import_systems(self, db: Session) -> Dict:
        """Import systems from GAMES_PATH (no longer uses es_systems*.cfg files)."""
        logger.info("Starting system import from GAMES_PATH...")
        
        # Get systems from GAMES_PATH
        systems_from_path = self.get_systems_from_games_path()
        logger.info(f"Found {len(systems_from_path)} systems in GAMES_PATH")
        
        imported_count = 0
        updated_count = 0
        
        for system_id in systems_from_path:
            # Check if system already exists
            db_system = db.query(System).filter(System.id == system_id).first()
            
            if db_system:
                # Update existing system - just ensure name is set
                db_system.name = system_id
                logger.debug(f"Updated system {system_id}")
                updated_count += 1
            else:
                # Create new system (without cfg file info)
                db_system = System(
                    id=system_id,
                    name=system_id,
                    fullname=None,
                    hardware=None,
                    release=None,
                    manufacturer=None,
                    batocera_system=None,
                    retrobat_system=None,
                    enabled=True,
                    download_enabled=True  # Downloads enabled by default
                )
                db.add(db_system)
                imported_count += 1
        
        db.commit()
        logger.info(f"Import completed: {imported_count} imported, {updated_count} updated")
        
        return {
            'imported': imported_count,
            'updated': updated_count,
            'total': len(systems_from_path)
        }

