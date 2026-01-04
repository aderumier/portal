"""Media upload and validation service."""
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class MediaService:
    """Service for handling media uploads and validation."""
    
    def __init__(self):
        self.users_media_path = settings.USERS_MEDIA_PATH
        self.games_path = settings.GAMES_PATH
        self.media_mapping = settings.get_media_mapping()
    
    def get_rom_filename(self, game_id: str) -> str:
        """Extract ROM filename without extension from game path."""
        # game_id is typically like "./game.zip" or "system/game.zip"
        # Remove leading ./
        clean_path = game_id.lstrip('./')
        
        # Get just the filename
        filename = os.path.basename(clean_path)
        
        # Remove extension
        name_without_ext = os.path.splitext(filename)[0]
        
        return name_without_ext
    
    def upload_media(
        self, 
        system: str, 
        game_id: str, 
        media_type: str, 
        file_content: bytes,
        file_extension: str = 'png'
    ) -> bool:
        """Upload media file to pending location."""
        try:
            if not self.users_media_path:
                logger.error("USERS_MEDIA_PATH is not configured")
                return False
            
            # Get ROM filename
            rom_filename = self.get_rom_filename(game_id)
            
            # Create directory structure: USERS_MEDIA_PATH/system/fieldname/
            upload_dir = Path(self.users_media_path) / system / media_type
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename: romname.png
            filename = f"{rom_filename}.{file_extension}"
            file_path = upload_dir / filename
            
            # Write file
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            logger.info(f"Media uploaded: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading media: {e}", exc_info=True)
            return False
    
    def get_pending_media(self) -> List[Dict]:
        """Get list of all pending media uploads."""
        pending_media = []
        
        if not self.users_media_path or not os.path.exists(self.users_media_path):
            return pending_media
        
        try:
            users_media_root = Path(self.users_media_path)
            
            # Scan all systems
            for system_dir in users_media_root.iterdir():
                if not system_dir.is_dir():
                    continue
                
                system = system_dir.name
                
                # Scan all fieldname directories
                for fieldname_dir in system_dir.iterdir():
                    if not fieldname_dir.is_dir():
                        continue
                    
                    fieldname = fieldname_dir.name
                    
                    # Scan all files
                    for file_path in fieldname_dir.iterdir():
                        if not file_path.is_file():
                            continue
                        
                        # Get file stats
                        stat = file_path.stat()
                        upload_date = datetime.fromtimestamp(stat.st_mtime)
                        
                        pending_media.append({
                            'system': system,
                            'fieldname': fieldname,
                            'filename': file_path.name,
                            'filepath': str(file_path),
                            'upload_date': upload_date.isoformat(),
                            'size': stat.st_size
                        })
            
            # Sort by upload date (newest first)
            pending_media.sort(key=lambda x: x['upload_date'], reverse=True)
            
            return pending_media
            
        except Exception as e:
            logger.error(f"Error getting pending media: {e}", exc_info=True)
            return []
    
    def validate_media(self, system: str, fieldname: str, filename: str) -> bool:
        """Validate and move media from pending to final location."""
        try:
            if not self.users_media_path or not self.games_path:
                logger.error("USERS_MEDIA_PATH or GAMES_PATH is not configured")
                return False
            
            # Get mapped directory name
            mapped_directory = self.media_mapping.get(fieldname, fieldname)
            
            # Source: USERS_MEDIA_PATH/system/fieldname/filename
            source_path = Path(self.users_media_path) / system / fieldname / filename
            
            if not source_path.exists():
                logger.error(f"Source file not found: {source_path}")
                return False
            
            # Destination: GAMES_PATH/system/media/mapped_directory/filename
            dest_dir = Path(self.games_path) / system / 'media' / mapped_directory
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            dest_path = dest_dir / filename
            
            # Move file
            shutil.move(str(source_path), str(dest_path))
            
            logger.info(f"Media validated and moved: {source_path} -> {dest_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error validating media: {e}", exc_info=True)
            return False
    
    def delete_pending_media(self, system: str, fieldname: str, filename: str) -> bool:
        """Delete pending media file."""
        try:
            if not self.users_media_path:
                logger.error("USERS_MEDIA_PATH is not configured")
                return False
            
            file_path = Path(self.users_media_path) / system / fieldname / filename
            
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False
            
            file_path.unlink()
            
            logger.info(f"Pending media deleted: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting pending media: {e}", exc_info=True)
            return False
    
    def get_media_mapping(self) -> dict:
        """Get media field name to directory mapping."""
        return self.media_mapping.copy()


