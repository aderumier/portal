"""Media upload and validation service."""
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple
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
        file_extension: str = 'png',
        user_id: str = None
    ) -> bool:
        """Upload media file to pending location.
        
        Stores files in: USERS_MEDIA_PATH/userid/system/mediafield/romfilename.png
        """
        try:
            if not self.users_media_path:
                logger.error("USERS_MEDIA_PATH is not configured")
                return False
            
            if not user_id:
                logger.error("user_id is required for media upload")
                return False
            
            # Get ROM filename
            rom_filename = self.get_rom_filename(game_id)
            
            # Create directory structure: USERS_MEDIA_PATH/userid/system/mediafield/
            upload_dir = Path(self.users_media_path) / user_id / system / media_type
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
        """Get list of all pending media uploads.
        
        Scans structure: USERS_MEDIA_PATH/userid/system/mediafield/romfilename.png
        """
        pending_media = []
        
        if not self.users_media_path or not os.path.exists(self.users_media_path):
            return pending_media
        
        try:
            users_media_root = Path(self.users_media_path)
            
            # Scan all user directories
            for user_dir in users_media_root.iterdir():
                if not user_dir.is_dir():
                    continue
                
                user_id = user_dir.name
                
                # Scan all systems
                for system_dir in user_dir.iterdir():
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
                                'user_id': user_id,
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
    
    def validate_media(self, system: str, fieldname: str, filename: str, user_id: str = None) -> Tuple[bool, Optional[str]]:
        """Validate and move media from pending to final location.
        
        Returns: (success: bool, user_id: str)
        If user_id is not provided, it will be extracted from the file path.
        """
        try:
            if not self.users_media_path or not self.games_path:
                logger.error("USERS_MEDIA_PATH or GAMES_PATH is not configured")
                return False, None
            
            # Get mapped directory name
            mapped_directory = self.media_mapping.get(fieldname, fieldname)
            
            # If user_id not provided, try to find the file by scanning user directories
            if not user_id:
                users_media_root = Path(self.users_media_path)
                source_path = None
                found_user_id = None
                
                # Scan all user directories to find the file
                for user_dir in users_media_root.iterdir():
                    if not user_dir.is_dir():
                        continue
                    
                    potential_path = user_dir / system / fieldname / filename
                    if potential_path.exists():
                        source_path = potential_path
                        found_user_id = user_dir.name
                        break
                
                if not source_path:
                    logger.error(f"Source file not found: {system}/{fieldname}/{filename}")
                    return False, None
                
                user_id = found_user_id
            else:
                # Source: USERS_MEDIA_PATH/userid/system/fieldname/filename
                source_path = Path(self.users_media_path) / user_id / system / fieldname / filename
            
            if not source_path.exists():
                logger.error(f"Source file not found: {source_path}")
                return False, user_id
            
            # Destination: GAMES_PATH/system/media/mapped_directory/filename
            dest_dir = Path(self.games_path) / system / 'media' / mapped_directory
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            dest_path = dest_dir / filename
            
            # Move file
            shutil.move(str(source_path), str(dest_path))
            
            logger.info(f"Media validated and moved: {source_path} -> {dest_path}")
            return True, user_id
            
        except Exception as e:
            logger.error(f"Error validating media: {e}", exc_info=True)
            return False, user_id if 'user_id' in locals() else None
    
    def delete_pending_media(self, system: str, fieldname: str, filename: str, user_id: str = None) -> bool:
        """Delete pending media file.
        
        If user_id is not provided, will search for the file in all user directories.
        """
        try:
            if not self.users_media_path:
                logger.error("USERS_MEDIA_PATH is not configured")
                return False
            
            if user_id:
                file_path = Path(self.users_media_path) / user_id / system / fieldname / filename
            else:
                # Search for file in all user directories
                users_media_root = Path(self.users_media_path)
                file_path = None
                
                for user_dir in users_media_root.iterdir():
                    if not user_dir.is_dir():
                        continue
                    
                    potential_path = user_dir / system / fieldname / filename
                    if potential_path.exists():
                        file_path = potential_path
                        break
                
                if not file_path:
                    logger.error(f"File not found: {system}/{fieldname}/{filename}")
                    return False
            
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


