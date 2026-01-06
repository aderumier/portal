"""Service for importing systems from GAMES_PATH and es_systems*.cfg files."""
import os
import xml.etree.ElementTree as ET
from pathlib import Path
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
        # Try multiple paths to find data/systemscfg directory (same logic as game.py)
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / 'data' / 'systemscfg',  # Development: project_root/data/systemscfg
            Path('/opt/batocera-games-catalog/data/systemscfg'),  # Production installation
            Path(__file__).parent.parent.parent / 'data' / 'systemscfg',  # Fallback: backend/data/systemscfg
        ]
        
        self.systemscfg_path = None
        for path in possible_paths:
            if path.exists():
                self.systemscfg_path = str(path)
                logger.info(f"Found systemscfg directory at: {self.systemscfg_path}")
                break
        
        if not self.systemscfg_path:
            logger.warning(f"Systemscfg directory not found. Tried: {possible_paths}")
            self.systemscfg_path = str(possible_paths[0])  # Use first path as default for error messages
    
    def parse_es_systems_cfg(self) -> Dict[str, Dict]:
        """Parse all es_systems*.cfg files and return system information."""
        systems_info = {}
        
        if not self.systemscfg_path or not os.path.isdir(self.systemscfg_path):
            logger.warning(f"Systemscfg directory not found: {self.systemscfg_path}")
            return systems_info
        
        # Find all es_systems*.cfg files
        cfg_files = []
        try:
            for file in os.listdir(self.systemscfg_path):
                if file.startswith('es_systems') and file.endswith('.cfg'):
                    cfg_files.append(os.path.join(self.systemscfg_path, file))
        except Exception as e:
            logger.error(f"Error listing files in {self.systemscfg_path}: {e}")
            return systems_info
        
        # Sort to process es_systems.cfg first, then es_systems_*.cfg (overrides)
        cfg_files.sort(key=lambda x: (not x.endswith('es_systems.cfg'), x))
        
        logger.info(f"Found {len(cfg_files)} es_systems*.cfg files to parse in {self.systemscfg_path}")
        
        for cfg_file_path in cfg_files:
            try:
                tree = ET.parse(cfg_file_path)
                root = tree.getroot()
                systems = root.findall('system')
                
                parsed_count = 0
                for system in systems:
                    name_elem = system.find('name')
                    hardware_elem = system.find('hardware')
                    manufacturer_elem = system.find('manufacturer')
                    release_elem = system.find('release')
                    fullname_elem = system.find('fullname')
                    path_elem = system.find('path')
                    
                    if name_elem is not None and name_elem.text:
                        system_id = name_elem.text.strip()
                        
                        # Extract information
                        hardware = hardware_elem.text.strip() if hardware_elem is not None and hardware_elem.text else None
                        manufacturer = manufacturer_elem.text.strip() if manufacturer_elem is not None and manufacturer_elem.text else None
                        release = release_elem.text.strip() if release_elem is not None and release_elem.text else None
                        fullname = fullname_elem.text.strip() if fullname_elem is not None and fullname_elem.text else None
                        path = path_elem.text.strip() if path_elem is not None and path_elem.text else None
                        
                        # Determine if this is batocera or retrobat based on filename
                        is_batocera = 'batocera' in os.path.basename(cfg_file_path).lower()
                        is_retrobat = 'retrobat' in os.path.basename(cfg_file_path).lower()
                        
                        if system_id:
                            if system_id not in systems_info:
                                systems_info[system_id] = {
                                    'name': system_id,
                                    'fullname': fullname,
                                    'hardware': hardware,
                                    'release': release,
                                    'manufacturer': manufacturer,
                                    'batocera_system': None,
                                    'retrobat_system': None,
                                }
                            
                            # Update with new information (later files override)
                            # Always update if value exists (even if None, to allow clearing)
                            if fullname is not None:
                                systems_info[system_id]['fullname'] = fullname
                            if hardware is not None:
                                systems_info[system_id]['hardware'] = hardware
                            if manufacturer is not None:
                                systems_info[system_id]['manufacturer'] = manufacturer
                            if release is not None:
                                systems_info[system_id]['release'] = release
                            
                            # Set system name based on file type (extract last directory from path)
                            if path:
                                # Extract last directory from path
                                # Handle both Unix and Windows paths
                                path_clean = path.rstrip('/').rstrip('\\')
                                last_dir = os.path.basename(path_clean) if path_clean else None
                                
                                if last_dir:
                                    if is_batocera:
                                        systems_info[system_id]['batocera_system'] = last_dir
                                    elif is_retrobat:
                                        systems_info[system_id]['retrobat_system'] = last_dir
                                    else:
                                        # Default es_systems.cfg - set as batocera if not set
                                        if not systems_info[system_id]['batocera_system']:
                                            systems_info[system_id]['batocera_system'] = last_dir
                            
                            parsed_count += 1
                
                if parsed_count > 0:
                    logger.info(f"Parsed {parsed_count} systems from {os.path.basename(cfg_file_path)}")
            except Exception as e:
                logger.error(f"Error parsing {cfg_file_path}: {e}", exc_info=True)
        
        return systems_info
    
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
        """Import systems from GAMES_PATH and update database with info from es_systems*.cfg."""
        logger.info("Starting system import...")
        
        # Get systems from GAMES_PATH
        systems_from_path = self.get_systems_from_games_path()
        logger.info(f"Found {len(systems_from_path)} systems in GAMES_PATH")
        
        # Parse es_systems*.cfg files
        systems_info = self.parse_es_systems_cfg()
        logger.info(f"Parsed {len(systems_info)} systems from es_systems*.cfg files")
        if systems_info:
            # Log first few systems for debugging
            for sys_id, info in list(systems_info.items())[:5]:
                logger.info(f"Sample system info: {sys_id} -> fullname={info.get('fullname')}, hardware={info.get('hardware')}, manufacturer={info.get('manufacturer')}, release={info.get('release')}")
        
        imported_count = 0
        updated_count = 0
        
        for system_id in systems_from_path:
            # Get base system ID (remove suffixes like _batocera, _retrobat, _lite, _spirit)
            base_system_id = system_id
            if system_id.endswith('_batocera'):
                base_system_id = system_id[:-9]
            elif system_id.endswith('_retrobat'):
                base_system_id = system_id[:-9]
            elif system_id.endswith('_lite'):
                base_system_id = system_id[:-5]
            elif system_id.endswith('_spirit'):
                base_system_id = system_id[:-7]
            
            # Get info from es_systems*.cfg (use base system ID)
            info = systems_info.get(base_system_id, {})
            
            if info:
                logger.debug(f"Found info for {system_id} (base: {base_system_id}): {info}")
            else:
                logger.debug(f"No info found in es_systems*.cfg for {system_id} (base: {base_system_id})")
            
            # Check if system already exists
            db_system = db.query(System).filter(System.id == system_id).first()
            
            if db_system:
                # Update existing system - always update from cfg if info exists
                db_system.name = system_id
                if 'fullname' in info:
                    db_system.fullname = info.get('fullname')
                if 'hardware' in info:
                    db_system.hardware = info.get('hardware')
                if 'release' in info:
                    db_system.release = info.get('release')
                if 'manufacturer' in info:
                    db_system.manufacturer = info.get('manufacturer')
                
                # Update system names if provided
                if 'batocera_system' in info:
                    db_system.batocera_system = info.get('batocera_system')
                if 'retrobat_system' in info:
                    db_system.retrobat_system = info.get('retrobat_system')
                
                # Fill retrobat_system with batocera_system if retrobat_system is empty
                if not db_system.retrobat_system and db_system.batocera_system:
                    db_system.retrobat_system = db_system.batocera_system
                
                logger.debug(f"Updated system {system_id}: fullname={db_system.fullname}, hardware={db_system.hardware}, manufacturer={db_system.manufacturer}, release={db_system.release}")
                updated_count += 1
            else:
                # Create new system
                batocera_system = info.get('batocera_system')
                retrobat_system = info.get('retrobat_system')
                
                # Fill retrobat_system with batocera_system if retrobat_system is empty
                if not retrobat_system and batocera_system:
                    retrobat_system = batocera_system
                
                db_system = System(
                    id=system_id,
                    name=system_id,
                    fullname=info.get('fullname'),
                    hardware=info.get('hardware'),
                    release=info.get('release'),
                    manufacturer=info.get('manufacturer'),
                    batocera_system=batocera_system,
                    retrobat_system=retrobat_system,
                    enabled=True
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

