"""Download queue service."""
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timezone
from app.database import DownloadQueue, System
from app.services.game import GameService
from app.services.bandwidth import BandwidthManager
from app.config import settings

logger = logging.getLogger(__name__)

def parse_m3u_file(m3u_file_path: str) -> List[str]:
    """Parse a .m3u file and return list of file paths (relative to m3u file location).
    
    Args:
        m3u_file_path: Full path to the .m3u file
        
    Returns:
        List of file paths relative to the .m3u file directory (including the .m3u file itself)
    """
    files_to_download = []
    
    try:
        # Get the directory containing the .m3u file
        m3u_dir = os.path.dirname(m3u_file_path)
        m3u_filename = os.path.basename(m3u_file_path)
        
        # Always include the .m3u file itself
        files_to_download.append(m3u_filename)
        
        # Read and parse the .m3u file
        if not os.path.exists(m3u_file_path):
            logger.warning(f".m3u file not found: {m3u_file_path}")
            return files_to_download
        
        with open(m3u_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and lines starting with # (comments)
                if not line or line.startswith('#'):
                    continue
                
                # This is a file path (always relative to the .m3u file location)
                # Normalize the path (remove leading ./ if present) and path separators
                file_path = line.lstrip('./').replace('\\', '/')
                files_to_download.append(file_path)
        
        logger.info(f"Parsed .m3u file {m3u_file_path}: found {len(files_to_download)} files to download")
        return files_to_download
        
    except Exception as e:
        logger.error(f"Error parsing .m3u file {m3u_file_path}: {e}", exc_info=True)
        # Return at least the .m3u file itself
        return [os.path.basename(m3u_file_path)]


def parse_m3u_ps3_directory(m3u_file_path: str) -> Optional[str]:
    """Parse a PS3 .m3u file and extract the directory name from paths like \dev_hdd0\game\{directory_name}\...
    
    Args:
        m3u_file_path: Full path to the .m3u file
        
    Returns:
        Directory name (e.g., "NPUA30032") or None if not found
    """
    try:
        if not os.path.exists(m3u_file_path):
            logger.warning(f".m3u file not found: {m3u_file_path}")
            return None
        
        import re
        with open(m3u_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and lines starting with # (comments)
                if not line or line.startswith('#'):
                    continue
                
                # Look for pattern: \dev_hdd0\game\{directory_name}\ or /dev_hdd0/game/{directory_name}/
                # Match both Windows (\) and Unix (/) path separators
                pattern = r'[\\/]dev_hdd0[\\/]game[\\/]([^\\/]+)[\\/]'
                match = re.search(pattern, line)
                if match:
                    directory_name = match.group(1)
                    logger.info(f"Parsed PS3 .m3u file {m3u_file_path}: found directory '{directory_name}'")
                    return directory_name
        
        logger.warning(f"No directory name found in PS3 .m3u file: {m3u_file_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing PS3 .m3u file {m3u_file_path}: {e}", exc_info=True)
        return None


def parse_cue_file(cue_file_path: str) -> List[str]:
    """Parse a .cue file and return list of file paths (relative to cue file location).
    
    Args:
        cue_file_path: Full path to the .cue file
        
    Returns:
        List of file paths relative to the .cue file directory (including the .cue file itself)
    """
    files_to_download = []
    
    try:
        # Get the directory containing the .cue file
        cue_dir = os.path.dirname(cue_file_path)
        cue_filename = os.path.basename(cue_file_path)
        
        # Always include the .cue file itself
        files_to_download.append(cue_filename)
        
        # Read and parse the .cue file
        if not os.path.exists(cue_file_path):
            logger.warning(f".cue file not found: {cue_file_path}")
            return files_to_download
        
        import re
        with open(cue_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines
                if not line:
                    continue
                
                # Parse lines starting with FILE keyword
                # Format: FILE "filename.bin" BINARY
                if line.upper().startswith('FILE'):
                    # Extract filename from quotes
                    # Match pattern: FILE "filename" [TYPE]
                    match = re.match(r'FILE\s+"([^"]+)"', line, re.IGNORECASE)
                    if match:
                        filename = match.group(1)
                        # Files are always in the same directory as the .cue file
                        # Normalize path separators
                        file_path = filename.replace('\\', '/')
                        files_to_download.append(file_path)
        
        logger.info(f"Parsed .cue file {cue_file_path}: found {len(files_to_download)} files to download")
        return files_to_download
        
    except Exception as e:
        logger.error(f"Error parsing .cue file {cue_file_path}: {e}", exc_info=True)
        # Return at least the .cue file itself
        return [os.path.basename(cue_file_path)]


def parse_xbox360_file(xbox360_file_path: str) -> str:
    """Parse a .xbox360 file and return the directory name to download.
    
    Args:
        xbox360_file_path: Full path to the .xbox360 file
        
    Returns:
        Directory name relative to the .xbox360 file's directory
    """
    try:
        # Read and parse the .xbox360 file
        if not os.path.exists(xbox360_file_path):
            logger.warning(f".xbox360 file not found: {xbox360_file_path}")
            return None
        
        with open(xbox360_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines
                if not line:
                    continue
                
                # Parse line format: /Age of Booty (World)/584108F0/000D0000/...
                # Extract the first directory (relative to .xbox360 file's directory)
                if line.startswith('/'):
                    # Remove leading slash
                    line = line[1:]
                    # Extract first directory name
                    parts = line.split('/')
                    if parts:
                        directory_name = parts[0]
                        logger.info(f"Parsed .xbox360 file {xbox360_file_path}: found directory '{directory_name}'")
                        return directory_name
        
        logger.warning(f"No valid directory found in .xbox360 file: {xbox360_file_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing .xbox360 file {xbox360_file_path}: {e}", exc_info=True)
        return None


def parse_psvita_file(psvita_file_path: str) -> str:
    """Parse a .psvita file and return the directory name to download.
    
    Args:
        psvita_file_path: Full path to the .psvita file
        
    Returns:
        Directory name (e.g., "PCSE00349")
    """
    try:
        # Read and parse the .psvita file
        if not os.path.exists(psvita_file_path):
            logger.warning(f".psvita file not found: {psvita_file_path}")
            return None
        
        with open(psvita_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines
                if not line:
                    continue
                
                # The file contains just the directory name (e.g., "PCSE00349")
                directory_name = line
                logger.info(f"Parsed .psvita file {psvita_file_path}: found directory '{directory_name}'")
                return directory_name
        
        logger.warning(f"No valid directory found in .psvita file: {psvita_file_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing .psvita file {psvita_file_path}: {e}", exc_info=True)
        return None


def parse_psn_file(psn_file_path: str) -> str:
    """Parse a .psn file and return the directory name to download.
    
    Args:
        psn_file_path: Full path to the .psn file
        
    Returns:
        Directory name (e.g., "BLUS12345")
    """
    try:
        # Read and parse the .psn file
        if not os.path.exists(psn_file_path):
            logger.warning(f".psn file not found: {psn_file_path}")
            return None
        
        with open(psn_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines
                if not line:
                    continue
                
                # The file contains just the directory name (e.g., "BLUS12345")
                directory_name = line
                logger.info(f"Parsed .psn file {psn_file_path}: found directory '{directory_name}'")
                return directory_name
        
        logger.warning(f"No valid directory found in .psn file: {psn_file_path}")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing .psn file {psn_file_path}: {e}", exc_info=True)
        return None


def detect_and_parse_special_file(file_path: str, system: Optional[str] = None) -> Optional[Dict]:
    """Detect and parse special file types that require additional files to be downloaded.
    
    Args:
        file_path: Full path to the file
        system: Optional system name (e.g., 'ps3') to enable system-specific handling
        
    Returns:
        Dict with parsed information, or None if not a special file type:
        {
            'files': List[str],  # List of relative file paths or directory name for special cases
            'base_path_type': str,  # 'file' for .m3u/.cue (files relative to file's dir), 'directory' for .xbox360/regular dirs
            'source_file': str  # Original file that was parsed (e.g., "game.cue")
        }
    """
    if not os.path.isfile(file_path):
        return None
    
    file_lower = file_path.lower()
    source_filename = os.path.basename(file_path)
    
    # Check for .m3u files
    if file_lower.endswith('.m3u'):
        # Special handling for PS3 system .m3u files
        if system and system.lower() == 'ps3':
            directory_name = parse_m3u_ps3_directory(file_path)
            if directory_name:
                # Return structure similar to .psn files
                return {
                    'files': [directory_name],  # This will be treated as a directory path
                    'base_path_type': 'file',
                    'source_file': source_filename
                }
        # Regular .m3u file handling
        files = parse_m3u_file(file_path)
        return {
            'files': files,
            'base_path_type': 'file',
            'source_file': source_filename
        }
    
    # Check for .cue files
    if file_lower.endswith('.cue'):
        files = parse_cue_file(file_path)
        return {
            'files': files,
            'base_path_type': 'file',
            'source_file': source_filename
        }
    
    # Check for .xbox360 files
    if file_lower.endswith('.xbox360'):
        directory_name = parse_xbox360_file(file_path)
        if directory_name:
            # For .xbox360 files, we return the directory name as a single-item list
            # The actual directory walk will happen in the API endpoint
            # Use base_path_type='file' so client adjusts dest_base_path to the .xbox360 file's directory
            # The relative paths returned will include the directory name, so files are placed correctly
            return {
                'files': [directory_name],  # This will be treated as a directory path
                'base_path_type': 'file',
                'source_file': source_filename
            }
    
    # Check for .psvita files
    if file_lower.endswith('.psvita'):
        directory_name = parse_psvita_file(file_path)
        if directory_name:
            # For .psvita files, we return the directory name as a single-item list
            # Similar to .xbox360, but the source directory path is different
            return {
                'files': [directory_name],  # This will be treated as a directory path
                'base_path_type': 'file',
                'source_file': source_filename
            }
    
    # Check for msu-md, nes-msu, and snes-msu1 systems: return all files from the ROM file's directory
    if system and system.lower() in ('msu-md', 'nes-msu', 'snes-msu1'):
        source_dir = os.path.dirname(file_path)
        if os.path.exists(source_dir) and os.path.isdir(source_dir):
            try:
                # Security check: ensure directory is within GAMES_PATH
                from app.config import settings
                if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(source_dir)]) == os.path.abspath(settings.GAMES_PATH):
                    # List all files in the directory
                    files = []
                    for filename in os.listdir(source_dir):
                        file_full_path = os.path.join(source_dir, filename)
                        # Only include files, not directories
                        if os.path.isfile(file_full_path):
                            # Calculate relative path from source directory
                            rel_path = os.path.relpath(file_full_path, source_dir).replace('\\', '/')
                            files.append(rel_path)
                    
                    logger.info(f"{system}: Found {len(files)} files in directory {source_dir}")
                    return {
                        'files': files,
                        'base_path_type': 'file',
                        'source_file': source_filename
                    }
            except ValueError:
                logger.warning(f"{system}: Security check failed for directory {source_dir}")
            except Exception as e:
                logger.error(f"{system}: Error scanning directory {source_dir}: {e}", exc_info=True)
    
    # Check for .psn files
    if file_lower.endswith('.psn'):
        directory_name = parse_psn_file(file_path)
        if directory_name:
            # For .psn files, we return the directory name as a single-item list
            # Similar to .psvita, but the source directory path is different
            return {
                'files': [directory_name],  # This will be treated as a directory path
                'base_path_type': 'file',
                'source_file': source_filename
            }

    # Check for namco2x6 system with .zip extension
    # For this system, we check if there is a directory with the same name as the zip file
    if system and system.lower() == 'namco2x6' and file_lower.endswith('.zip'):
        # Get directory name (filename without extension)
        # file_path is /path/to/game.zip
        # We want to check /path/to/game/
        directory_name = os.path.splitext(source_filename)[0]
        source_dir = os.path.dirname(file_path)
        dir_full_path = os.path.join(source_dir, directory_name)
        
        if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
            try:
                # Security check: ensure directory is within GAMES_PATH
                from app.config import settings
                if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                    # Include the main zip file as well as the directory files
                    files = [source_filename]
                    # Walk the directory to find all files
                    for root, dirs, filenames in os.walk(dir_full_path):
                        for filename in filenames:
                            file_full_path = os.path.join(root, filename)
                            # Get path relative to the ROM directory (source_dir)
                            # e.g. game/subdir/file.bin
                            rel_path = os.path.relpath(file_full_path, source_dir).replace('\\', '/')
                            files.append(rel_path)
                    
                    logger.info(f"Namco 2x6: Found {len(files)} associated files in directory {directory_name}")
                    
                    return {
                        'files': files,
                        'base_path_type': 'file',
                        'source_file': source_filename
                    }
            except Exception as e:
                logger.error(f"Namco 2x6: Error scanning directory {directory_name}: {e}", exc_info=True)

    # Check for mame and mame_lite systems with .zip extension
    # For these systems, we check if there is a directory with the same name as the zip file
    if system and system.lower() in ('mame', 'mame_lite', 'naomi', 'naomi2') and file_lower.endswith('.zip'):
        # Get directory name (filename without extension)
        # file_path is /path/to/game.zip
        # We want to check /path/to/game/
        directory_name = os.path.splitext(source_filename)[0]
        source_dir = os.path.dirname(file_path)
        dir_full_path = os.path.join(source_dir, directory_name)
        
        if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
            try:
                # Security check: ensure directory is within GAMES_PATH
                from app.config import settings
                if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                    # Include the main zip file as well as the directory files
                    files = [source_filename]
                    # Walk the directory to find all files
                    for root, dirs, filenames in os.walk(dir_full_path):
                        for filename in filenames:
                            file_full_path = os.path.join(root, filename)
                            # Get path relative to the ROM directory (source_dir)
                            # e.g. game/subdir/file.bin
                            rel_path = os.path.relpath(file_full_path, source_dir).replace('\\', '/')
                            files.append(rel_path)
                    
                    logger.info(f"{system}: Found {len(files)} associated files in directory {directory_name}")
                    
                    return {
                        'files': files,
                        'base_path_type': 'file',
                        'source_file': source_filename
                    }
            except Exception as e:
                logger.error(f"{system}: Error scanning directory {directory_name}: {e}", exc_info=True)
    
    return None

class DownloadService:
    """Service for managing download queue."""
    
    def __init__(self, db: Session, game_service: GameService):
        self.db = db
        self.game_service = game_service
        self.bandwidth_manager = BandwidthManager(db)
    
    def _normalize_media_path_for_frontend(self, path_value: str, system_id: str) -> str:
        """Normalize media path to include system prefix for frontend display.
        
        For Releases catalog, paths already include the snapshot prefix (e.g., 'bbc/.zfs/snapshot/v1/media/image.png').
        For WIP catalog, paths need the system prefix added (e.g., 'bbc/media/image.png').
        """
        if not path_value:
            return ''
        
        # Only remove './' prefix if present, preserve paths starting with '.zfs'
        path = path_value
        if path.startswith('./'):
            path = path[2:]
        
        # For Releases catalog paths (already normalized with snapshot prefix), they should already have system prefix
        # Check if path already starts with system_id (including snapshot paths like 'system/.zfs/snapshot/...')
        if path and not path.startswith(f"{system_id}/"):
            # Only add system prefix for WIP catalog paths (paths without snapshot prefix)
            # This ensures we don't break Releases catalog paths that already have the full path
            path = f"{system_id}/{path}"
        
        return path
    
    def _get_media_download_url(self, media_path: str, system_id: str, catalog_version: Optional[str], base_url: str) -> str:
        """Construct download URL for a media file.
        
        For WIP catalog: {base_url}/media/{system_id}/{media_path}
        For Releases catalog: {base_url}/media/{system_id}/.zfs/snapshot/{catalog_version}/{media_path}
        
        Args:
            media_path: Media path from gamelist.xml (may include ./ prefix, may include system prefix)
            system_id: System ID (e.g., "atari2600")
            catalog_version: Catalog version for Releases (e.g., "v2-RGS_bbc") or None for WIP
            base_url: Base URL for API (e.g., "https://rgs-retro.ddns.net")
        
        Returns:
            Complete download URL for the media file
        """
        if not media_path:
            return ''
        
        import urllib.parse
        
        # Remove './' prefix if present
        clean_path = media_path.lstrip('./')
        
        # For Releases catalog, construct URL with snapshot path
        if catalog_version:
            # Remove system prefix if present (media_path might be "system/media/..." or just "media/...")
            if clean_path.startswith(f"{system_id}/"):
                # Already has system prefix, check if snapshot path is already included
                if f".zfs/snapshot/{catalog_version}" in clean_path:
                    # Path already includes snapshot, use as-is
                    full_path = clean_path
                else:
                    # Need to insert snapshot path: system/media/... -> system/.zfs/snapshot/vX/media/...
                    # Extract the part after system_id/
                    path_after_system = clean_path[len(system_id) + 1:]
                    full_path = f"{system_id}/.zfs/snapshot/{catalog_version}/{path_after_system}"
            else:
                # No system prefix, add both system and snapshot
                full_path = f"{system_id}/.zfs/snapshot/{catalog_version}/{clean_path}"
        else:
            # WIP catalog - no snapshot path
            if clean_path.startswith(f"{system_id}/"):
                # Already has system prefix
                full_path = clean_path
            else:
                # Add system prefix
                full_path = f"{system_id}/{clean_path}"
        
        # URL encode the path components
        encoded_path = '/'.join(urllib.parse.quote(part, safe='') for part in full_path.split('/'))
        
        return f"{base_url}/media/{encoded_path}"
    
    def _remove_snapshot_path_from_media_path(self, path_value: str, system_id: str, catalog_version: Optional[str]) -> str:
        """Remove snapshot path from media path for download client destination paths.
        
        For Releases catalog games, media paths include snapshot prefix (e.g., 'system/.zfs/snapshot/v1/media/image.png').
        The download client should save to destination without snapshot path (e.g., 'system/media/image.png').
        
        Args:
            path_value: Media path that may include snapshot prefix
            system_id: System ID
            catalog_version: Catalog version (if None, it's WIP catalog)
        
        Returns:
            Media path without snapshot prefix for destination path
        """
        if not path_value or not catalog_version:
            # WIP catalog or empty path - return as-is
            return path_value
        
        # For Releases catalog, remove snapshot path
        # Path format: 'system/.zfs/snapshot/vX.Y/media/...' -> 'system/media/...'
        import re
        escaped_version = re.escape(catalog_version)
        # Pattern to match snapshot path: system/.zfs/snapshot/vX.Y/
        pattern = re.compile(rf'^{re.escape(system_id)}/\.zfs/snapshot/{escaped_version}/(.+)$')
        match = pattern.match(path_value)
        
        if match:
            # Extract path after snapshot directory
            path_after_snapshot = match.group(1)
            # Reconstruct path without snapshot: system/path_after_snapshot
            return f"{system_id}/{path_after_snapshot}"
        
        # If pattern doesn't match, return original path
        return path_value
    
    def _remove_snapshot_path_from_game_id(self, game_id: str, catalog_version: Optional[str]) -> str:
        """Remove snapshot path from game_id for download client destination paths.
        
        For Releases catalog games, game_id includes snapshot prefix (e.g., '.zfs/snapshot/v1/game.rom').
        The download client should save to destination without snapshot path (e.g., 'game.rom').
        This also applies to directory paths (e.g., '.zfs/snapshot/v1/game_dir/' -> 'game_dir/').
        
        Args:
            game_id: Game ID (rom path) that may include snapshot prefix
            catalog_version: Catalog version (if None, it's WIP catalog)
        
        Returns:
            Game ID without snapshot prefix for destination path
        """
        if not game_id or not catalog_version:
            # WIP catalog or empty path - return as-is (but remove ./ if present)
            if game_id and game_id.startswith('./'):
                return game_id[2:]
            return game_id
        
        # For Releases catalog, remove snapshot path
        # Path format: '.zfs/snapshot/vX.Y/game.rom' -> 'game.rom'
        # Or: '.zfs/snapshot/vX.Y/game_dir/' -> 'game_dir/'
        import re
        escaped_version = re.escape(catalog_version)
        # Pattern to match snapshot path: .zfs/snapshot/vX.Y/
        pattern = re.compile(rf'^\.zfs/snapshot/{escaped_version}/(.+)$')
        match = pattern.match(game_id)
        
        if match:
            # Extract path after snapshot directory
            return match.group(1)
        
        # If pattern doesn't match, try removing ./ prefix if present
        if game_id.startswith('./'):
            return game_id[2:]
        
        # Return as-is
        return game_id
    
    def _normalize_game_details_for_client(self, game: Dict, catalog_version: Optional[str]) -> Dict:
        """Add download URLs for media fields while keeping original paths unchanged.
        
        The download client will use download URLs for downloading media files.
        All original paths from gamelist.xml are preserved as-is.
        
        Args:
            game: Game dictionary with original paths from gamelist.xml (format: "./media/...")
            catalog_version: Catalog version (if None, it's WIP catalog)
        
        Returns:
            Game dictionary with download URLs added for each media field, original paths preserved
        """
        if not game:
            return game
        
        # Create a copy to avoid modifying original
        enriched_game = game.copy()
        
        system_id = game.get('system', '')
        
        # Get base URL for media downloads
        base_url = settings.DOWNLOAD_FILE_URL if settings.DOWNLOAD_FILE_URL else settings.API_URL
        
        # Helper function to check if a field value looks like a media path
        def is_media_path(value: str) -> bool:
            """Check if value looks like a media path."""
            if not value or not isinstance(value, str):
                return False
            value = value.lstrip('./')
            return 'media/' in value
        
        # Add download_url for each field that contains a media path
        # Keep original paths in fields as-is
        # Iterate over a copy of items to avoid "dictionary changed size during iteration" error
        for field_name, field_value in list(enriched_game.items()):
            # Skip already processed fields and internal metadata
            if field_name.endswith('_download_url') or field_name in {'id', 'system', 'systemName', 'catalog_image'}:
                continue
            
            # Check if this field contains a media path
            if field_value and is_media_path(str(field_value)):
                # Get original path (may have ./ prefix)
                original_path = str(field_value)
                # Construct download URL from original path
                # _get_media_download_url expects original format, so we need to normalize for URL construction
                download_url = self._get_media_download_url(original_path, system_id, catalog_version, base_url)
                # Add download URL with field name suffix
                enriched_game[f"{field_name}_download_url"] = download_url
        
        return enriched_game
    
    def _resolve_unified_rom_key(self, game_id: str, system_id: str, platform: Optional[str], catalog_type: str = 'releases') -> str:
        """Resolve unified ROM key to actual ROM path based on platform.
        
        If game_id is a unified key (e.g., "path/to/game.(z64|n64)"), resolves it
        to the actual ROM path based on platform using stored _original_batocera_path
        and _original_retrobat_path from the catalog.
        
        Args:
            game_id: Unified ROM key or regular ROM path (may include snapshot path for releases)
            system_id: System ID
            platform: 'linux' or 'windows' (None defaults to linux)
            catalog_type: 'wip' or 'releases'
            
        Returns:
            str: Resolved ROM path, or original game_id if not a unified key or stored paths not available
        """
        import re
        
        # Strip snapshot path prefix if present (for releases catalog)
        # Catalog stores unified keys without snapshot paths, so we need to remove it for lookup
        lookup_game_id = game_id
        snapshot_prefix = None
        if catalog_type == 'releases' and '.zfs/snapshot' in game_id:
            # Extract snapshot prefix and game_id without snapshot
            parts = game_id.split('.zfs/snapshot/', 1)
            if len(parts) > 1:
                after_snapshot = parts[1]
                if '/' in after_snapshot:
                    snapshot_version = after_snapshot.split('/')[0]
                    lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                    snapshot_prefix = f".zfs/snapshot/{snapshot_version}/"
                else:
                    lookup_game_id = after_snapshot
                    snapshot_prefix = f".zfs/snapshot/{after_snapshot}/"
        
        # Check if lookup_game_id matches unified key pattern: path.(ext1|ext2)
        unified_pattern = r'^(.+)\.\(([^|]+)\|([^|]+)\)$'
        match = re.match(unified_pattern, lookup_game_id)
        
        if not match:
            # Not a unified key, return as-is
            return game_id
        
        # Get the game from catalog to use stored original paths (use lookup_game_id without snapshot)
        game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
        if not game:
            logger.warning(f"Game not found in catalog for unified key '{lookup_game_id}' (catalog_type: {catalog_type}), cannot resolve")
            return game_id
        
        platform_lower = (platform or 'linux').lower()
        if platform_lower == 'windows':
            original_path = game.get('_original_retrobat_path')
        else:
            original_path = game.get('_original_batocera_path')
        
        if not original_path:
            logger.warning(f"Stored original path not found for unified key '{lookup_game_id}' (platform: {platform_lower}), cannot resolve")
            return game_id
        
        # Reconstruct with snapshot path prefix if it was present in the original game_id
        if snapshot_prefix:
            resolved_path = f"{snapshot_prefix}{original_path}"
        else:
            resolved_path = original_path
        
        logger.debug(f"Resolved unified ROM key '{game_id}' using stored path '{resolved_path}' (platform: {platform_lower})")
        return resolved_path
    

    
    async def add_to_queue(self, user_id: str, game_id: str, system_id: str, user_has_fastdownload: bool = False, token_id: Optional[int] = None, catalog_version: Optional[str] = None) -> bool:
        """Add a game to the user's FIFO queue."""
        try:
            logger.info(f"Adding to user queue - Game ID: {game_id}, System ID: {system_id}, User ID: {user_id}, catalog_version: {catalog_version}")
            
            # Clean up the game path by removing ./ prefix only if it's actually "./"
            # But preserve leading dot in snapshot paths like ".zfs/snapshot/..."
            if game_id.startswith('./'):
                game_id = game_id[2:]  # Remove './' prefix only
            logger.info(f"Cleaned game ID: {game_id}")
            
            # Determine queue type based on user role (will be used when promoted to global queue)
            queue_type = 'fast' if user_has_fastdownload else 'slow'
            logger.info(f"Queue type determined: {queue_type}")
            
            # Determine catalog_type from catalog_version (if version exists, it's Releases, otherwise WIP)
            catalog_type = 'releases' if catalog_version else 'wip'
            logger.info(f"Catalog type: {catalog_type}, version: {catalog_version}")
            
            # Check if game exists
            # Remove snapshot path prefix to get original game_id for lookup if needed
            lookup_game_id = game_id
            if catalog_type == 'releases' and catalog_version:
                # Extract original game_id after snapshot path
                # game_id format: ".zfs/snapshot/v10.5/game.zip"
                import re
                
                # Pattern to match: .zfs/snapshot/v2-RGS_bbc/(.*) where catalog_version is "v2-RGS_bbc"
                # Escape the version string in case it has special regex characters
                escaped_version = re.escape(catalog_version)
                pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                match = pattern.match(game_id)
                
                if match:
                    lookup_game_id = match.group(1)
                    logger.info(f"Extracted original game_id: '{lookup_game_id}' from: '{game_id}'")
                else:
                    logger.warning(f"Could not extract original game_id from: {game_id} (catalog_version: {catalog_version})")
            
            game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
            if not game:
                logger.warning(f"Game not found: {lookup_game_id} in system {system_id} (catalog_type: {catalog_type}, catalog_version: {catalog_version}, original game_id: {game_id})")
                return False
            
            logger.info(f"Game found, adding to user queue: {game['name']}")
            
            # Check if already in queue (any status) - also check catalog_version to avoid duplicates
            existing = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id,
                    DownloadQueue.catalog_version == catalog_version,
                    DownloadQueue.status.in_(['user_queue', 'downloading'])
                )
            ).first()
            
            if existing:
                logger.warning(f"Game already in queue: {game_id} (status: {existing.status})")
                return False
            
            # Get file size if possible (game_id is rompath, need to prepend system)
            # Handle both files and directories, including special file types (.m3u, .cue, .xbox360)
            # For unified keys (e.g., game.(ext1|ext2)), we need to resolve to actual path or check both
            file_size = None
            if settings.GAMES_PATH:
                system = game.get('system', '')
                
                # Check if game_id is a unified key: ends with .(ext1|ext2) pattern
                import re
                unified_pattern = r'\.\([^|]+\|[^)]+\)$'
                is_unified_key = bool(re.search(unified_pattern, game_id))
                
                if is_unified_key:
                    # For unified keys, we can't check file existence without knowing the platform
                    # But we can check if at least one of the possible files exists
                    # Extract the base path and extensions
                    # Handle snapshot paths: .zfs/snapshot/v2-RGS_singe/Tittie_Tussle.(daphne|hypseus)
                    # Match pattern: (optional snapshot path) + base_path.(ext1|ext2)
                    # For snapshot: .zfs/snapshot/version/base_path.(ext1|ext2)
                    # For non-snapshot: base_path.(ext1|ext2)
                    match = re.match(r'^(.*?)([^/]+)\.\(([^|]+)\|([^)]+)\)$', game_id)
                    if match:
                        prefix = match.group(1)  # Could be empty or snapshot path like ".zfs/snapshot/v2-RGS_singe/"
                        base_path = match.group(2)  # Base filename without extension
                        ext1 = match.group(3)
                        ext2 = match.group(4)
                        
                        # Reconstruct full paths with both extensions
                        path_with_ext1 = f"{prefix}{base_path}.{ext1}" if prefix else f"{base_path}.{ext1}"
                        path_with_ext2 = f"{prefix}{base_path}.{ext2}" if prefix else f"{base_path}.{ext2}"
                        
                        # Build full file system paths for both possible extensions
                        if system:
                            path1 = os.path.join(settings.GAMES_PATH, system, path_with_ext1)
                            path2 = os.path.join(settings.GAMES_PATH, system, path_with_ext2)
                        else:
                            path1 = os.path.join(settings.GAMES_PATH, path_with_ext1)
                            path2 = os.path.join(settings.GAMES_PATH, path_with_ext2)
                        
                        # Check if at least one exists, use the first one that exists for size calculation
                        if os.path.exists(path1):
                            game_path = path1
                            logger.info(f"Unified key resolved to existing file: {path1}")
                        elif os.path.exists(path2):
                            game_path = path2
                            logger.info(f"Unified key resolved to existing file: {path2}")
                        else:
                            # Neither file exists, log warning but allow adding to queue
                            # (file will be resolved later based on client platform)
                            logger.warning(f"Unified key game_id has no existing files: {game_id} (checked {path1} and {path2})")
                            logger.info("Allowing unified key to be added to queue - will resolve based on client platform later")
                            game_path = None
                    else:
                        # Pattern didn't match, treat as regular path
                        logger.warning(f"Could not parse unified key pattern: {game_id}")
                        if system:
                            game_path = os.path.join(settings.GAMES_PATH, system, game_id)
                        else:
                            game_path = os.path.join(settings.GAMES_PATH, game_id)
                else:
                    # Regular game_id (not unified key)
                    if system:
                        game_path = os.path.join(settings.GAMES_PATH, system, game_id)
                    else:
                        game_path = os.path.join(settings.GAMES_PATH, game_id)
                
                if game_path and os.path.exists(game_path):
                    # Check if it's a special file type that needs parsing
                    parsed_info = detect_and_parse_special_file(game_path, system=game.get('system', ''))
                    
                    if parsed_info:
                        # It's a special file type (.m3u, .cue, .xbox360)
                        # Calculate total size of all files that will be downloaded
                        source_dir = os.path.dirname(game_path)
                        base_path_type = parsed_info['base_path_type']
                        parsed_files = parsed_info['files']
                        source_file = parsed_info['source_file']
                        
                        total_size = 0
                        
                        if base_path_type == 'file':
                            if source_file.lower().endswith('.xbox360'):
                                # For .xbox360 files: parsed_files contains the directory name
                                if parsed_files:
                                    directory_name = parsed_files[0]
                                    dir_full_path = os.path.normpath(os.path.join(source_dir, directory_name))
                                    
                                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                        # Security check: ensure directory is within games directory
                                        try:
                                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                                # Walk the directory and sum all file sizes
                                                for root, dirs, files in os.walk(dir_full_path):
                                                    for filename in files:
                                                        file_full_path = os.path.join(root, filename)
                                                        if os.path.isfile(file_full_path):
                                                            total_size += os.path.getsize(file_full_path)
                                        except ValueError:
                                            logger.warning(f"Directory {dir_full_path} path validation failed, skipping from size calculation")
                                    
                                    # Include the .xbox360 file itself in the total size
                                    if os.path.exists(game_path) and os.path.isfile(game_path):
                                        total_size += os.path.getsize(game_path)
                            elif source_file.lower().endswith('.psvita'):
                                # For .psvita files: parsed_files contains the directory name
                                # Source directory is at {GAMES_PATH}/_saves_/psvita/vita3k/ux0/app/{directory_name}
                                if parsed_files:
                                    directory_name = parsed_files[0]
                                    # Build path to save directory (different from .xbox360 which uses relative paths)
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'psvita', 'vita3k', 'ux0', 'app', directory_name)
                                    dir_full_path = os.path.normpath(save_dir_path)
                                    
                                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                        # Security check: ensure directory is within games directory
                                        try:
                                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                                # Walk the directory and sum all file sizes
                                                for root, dirs, files in os.walk(dir_full_path):
                                                    for filename in files:
                                                        file_full_path = os.path.join(root, filename)
                                                        if os.path.isfile(file_full_path):
                                                            total_size += os.path.getsize(file_full_path)
                                        except ValueError:
                                            logger.warning(f"Directory {dir_full_path} path validation failed, skipping from size calculation")
                                    else:
                                        logger.warning(f"PS Vita save directory not found: {dir_full_path}")
                                    
                                    # Include the .psvita file itself in the total size
                                    if os.path.exists(game_path) and os.path.isfile(game_path):
                                        total_size += os.path.getsize(game_path)
                            elif source_file.lower().endswith('.psn'):
                                # For .psn files: parsed_files contains the directory name
                                # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                                if parsed_files:
                                    directory_name = parsed_files[0]
                                    # Build path to save directory
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                                    dir_full_path = os.path.normpath(save_dir_path)
                                    
                                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                        # Security check: ensure directory is within games directory
                                        try:
                                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                                # Walk the directory and sum all file sizes
                                                for root, dirs, files in os.walk(dir_full_path):
                                                    for filename in files:
                                                        file_full_path = os.path.join(root, filename)
                                                        if os.path.isfile(file_full_path):
                                                            total_size += os.path.getsize(file_full_path)
                                        except ValueError:
                                            logger.warning(f"Directory {dir_full_path} path validation failed, skipping from size calculation")
                                    else:
                                        logger.warning(f"PS3 save directory not found: {dir_full_path}")
                                    
                                    # Include the .psn file itself in the total size
                                    if os.path.exists(game_path) and os.path.isfile(game_path):
                                        total_size += os.path.getsize(game_path)
                            elif source_file.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                                # For PS3 .m3u files: parsed_files contains the directory name
                                # Source directory is at {GAMES_PATH}/_saves_/ps3/rpcs3/dev_hdd0/game/{directory_name}
                                if parsed_files:
                                    directory_name = parsed_files[0]
                                    # Build path to save directory (same as .psn)
                                    save_dir_path = os.path.join(settings.GAMES_PATH, '_saves_', 'ps3', 'rpcs3', 'dev_hdd0', 'game', directory_name)
                                    dir_full_path = os.path.normpath(save_dir_path)
                                    
                                    if os.path.exists(dir_full_path) and os.path.isdir(dir_full_path):
                                        # Security check: ensure directory is within games directory
                                        try:
                                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(dir_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                                # Walk the directory and sum all file sizes
                                                for root, dirs, files in os.walk(dir_full_path):
                                                    for filename in files:
                                                        file_full_path = os.path.join(root, filename)
                                                        if os.path.isfile(file_full_path):
                                                            total_size += os.path.getsize(file_full_path)
                                        except ValueError:
                                            logger.warning(f"Directory {dir_full_path} path validation failed, skipping from size calculation")
                                    else:
                                        logger.warning(f"PS3 save directory not found: {dir_full_path}")
                                    
                                    # Include the .m3u file itself in the total size
                                    if os.path.exists(game_path) and os.path.isfile(game_path):
                                        total_size += os.path.getsize(game_path)
                            else:
                                # For .m3u and .cue files: files are relative to the source file's directory
                                for rel_file in parsed_files:
                                    file_full_path = os.path.normpath(os.path.join(source_dir, rel_file))
                                    if os.path.exists(file_full_path) and os.path.isfile(file_full_path):
                                        # Security check: ensure file is within games directory
                                        try:
                                            if os.path.commonpath([os.path.abspath(settings.GAMES_PATH), os.path.abspath(file_full_path)]) == os.path.abspath(settings.GAMES_PATH):
                                                total_size += os.path.getsize(file_full_path)
                                        except ValueError:
                                            logger.warning(f"File {file_full_path} path validation failed, skipping from size calculation")
                                            
                                # Include the source file itself in the total size
                                if source_file and os.path.exists(game_path) and os.path.isfile(game_path):
                                    total_size += os.path.getsize(game_path)
                        
                        file_size = total_size
                        logger.info(f"Special file ({source_file}) total size: {file_size} bytes ({len(parsed_files)} items parsed)")
                    
                    elif game_path and os.path.isfile(game_path):
                        # Regular file
                        file_size = os.path.getsize(game_path)
                        logger.info(f"File size: {file_size} bytes")
                    elif game_path and os.path.isdir(game_path):
                        # Regular directory
                        total_size = 0
                        for dirpath, dirnames, filenames in os.walk(game_path):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                if os.path.isfile(filepath):
                                    total_size += os.path.getsize(filepath)
                        file_size = total_size
                        logger.info(f"Directory size: {file_size} bytes ({len([f for r, d, files in os.walk(game_path) for f in files])} files)")
                elif game_path is None:
                    # Unified key with no existing files found - set file_size to None
                    # Will be resolved later based on client platform
                    file_size = None
                    logger.info("Unified key game - file size will be determined when download starts")
            
            # Add to user's FIFO queue (status: 'user_queue')
            queue_item = DownloadQueue(
                user_id=user_id,
                game_id=game_id,
                system_id=system_id,  # Store system identifier to prevent ambiguity
                status='user_queue',  # User queue status
                queue_type=queue_type,  # Store queue type for when promoted
                file_size=file_size,
                token_id=token_id,  # Associate with token if provided
                catalog_version=catalog_version  # Store catalog version (e.g., "v2-RGS_bbc") for Releases, None for WIP
            )
            
            self.db.add(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully added game to user queue: {game_id}")
            
            # Notify connected WebSocket clients if any
            if token_id is not None:
                try:
                    from app.services.websocket_manager import get_websocket_manager
                    ws_manager = get_websocket_manager()
                    if ws_manager.has_connection(token_id):
                        await ws_manager.send_notification(token_id, {
                            "type": "download_available",
                            "queue_type": queue_type
                        })
                        logger.info(f"Sent WebSocket notification to token_id {token_id} for queue_type {queue_type}")
                except Exception as e:
                    # Don't fail the queue addition if notification fails
                    logger.warning(f"Failed to send WebSocket notification: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error adding to download queue: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False
    
    async def get_queue(self, user_id: str) -> List[Dict]:
        """Get download queue for a user (includes user_queue, pending, downloading). Completed downloads are removed from the queue.
        
        For active downloads (status='downloading'), progress data is read from Redis only (no SQLite fallback).
        """
        try:
            from app.database import ApiToken
            from app.services.redis_downloads import RedisDownloadTracker
            
            # Filter out completed downloads - they should be deleted, but filter just in case
            queue_items = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.status != 'completed'  # Exclude completed downloads (they should be deleted)
                )
            ).order_by(DownloadQueue.created_at.asc()).all()  # FIFO: oldest first
            
            # Enrich queue items with game information
            enriched_items = []
            for item in queue_items:
                # Get catalog_version from queue item and derive catalog_type
                catalog_version = item.catalog_version
                catalog_type = 'releases' if catalog_version else 'wip'
                # Remove snapshot path prefix to get original game_id for lookup
                lookup_game_id = item.game_id
                if catalog_type == 'releases' and catalog_version:
                    # Extract original game_id after snapshot path
                    # game_id format: ".zfs/snapshot/v2-RGS_bbc/game.rom"
                    import re
                    escaped_version = re.escape(catalog_version)
                    pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                    match = pattern.match(item.game_id)
                    if match:
                        lookup_game_id = match.group(1)
                
                
                # Get system_id - must be stored in queue item
                system_id = item.system_id
                if not system_id:
                    logger.warning(f"System ID missing for game in queue: {lookup_game_id}, skipping")
                    continue
                    
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
                if game:
                    # For active downloads, get data from Redis only (no SQLite fallback)
                    bytes_transferred = item.bytes_transferred
                    bandwidth_used = item.bandwidth_used
                    status = item.status
                    
                    # Get p2p_remote_token_id from Redis (for P2P transfers)
                    p2p_remote_token_id = None
                    p2p_remote_token_name = None
                    
                    if item.status == 'downloading':
                        # Active downloads MUST be in Redis - get latest data from Redis
                        redis_status = await RedisDownloadTracker.get_download_status(item.id)
                        if redis_status:
                            bytes_transferred = redis_status.get('bytes_transferred', 0)
                            bandwidth_used = redis_status.get('bytes_per_second', 0)
                            status = redis_status.get('status', status)
                            p2p_remote_token_id = redis_status.get('p2p_remote_token_id')
                        else:
                            # Download marked as 'downloading' but not in Redis - log warning
                            logger.warning(f"Download {item.id} has status 'downloading' but not found in Redis")
                            # Use defaults (0) for active downloads not in Redis
                            bytes_transferred = 0
                            bandwidth_used = 0
                        
                        # If not in redis_status, try dedicated p2p_remote_token_id field
                        if not p2p_remote_token_id:
                            p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(item.id)
                        
                        # Get token name for p2p_remote_token_id if available
                        if p2p_remote_token_id:
                            remote_token = self.db.query(ApiToken).filter(
                                ApiToken.id == p2p_remote_token_id
                            ).first()
                            if remote_token:
                                p2p_remote_token_name = remote_token.name
                    
                    # Calculate progress for active downloads
                    progress_percent = 0
                    file_size = item.file_size
                    if status == 'downloading' and file_size and file_size > 0:
                        progress_percent = min(100, int((bytes_transferred / file_size) * 100))
                    
                    # Get token name if token_id exists
                    token_name = None
                    if item.token_id:
                        token = self.db.query(ApiToken).filter(
                            ApiToken.id == item.token_id
                        ).first()
                        if token:
                            token_name = token.name
                    
                    enriched_item = {
                        'id': item.id,
                        'user_id': item.user_id,
                        'game_id': item.game_id,  # Keep original game_id (matches database)
                        'status': status,  # Use status from Redis if available
                        'queue_type': item.queue_type,
                        'created_at': item.created_at.isoformat() if item.created_at else None,
                        'started_at': item.started_at.isoformat() if item.started_at else None,
                        'game_name': game['name'],
                        'image': self._normalize_media_path_for_frontend(game.get('image', ''), game.get('system', '')),
                        'system_name': self.game_service.get_system_name(game.get('system', '')),
                        'progress_percent': progress_percent,
                        'bytes_transferred': bytes_transferred,  # From Redis for active downloads
                        'file_size': file_size,
                        'bandwidth_used': bandwidth_used,  # From Redis for active downloads
                        'token_name': token_name,
                        'download_id': item.id,  # Include download_id for pause/resume actions
                        'catalog_version': catalog_version,  # Include catalog version (e.g., "v2-RGS_bbc")
                        'client_version': item.client_version,  # Include client version (e.g., "0.1")
                        'p2p_remote_token_id': p2p_remote_token_id,  # Token ID of P2P source peer (if P2P transfer)
                        'p2p_remote_token_name': p2p_remote_token_name  # Token name of P2P source peer
                    }
                    enriched_items.append(enriched_item)
            
            return enriched_items
        except Exception as e:
            logger.error(f"Error getting download queue: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def get_active_uploads(self, user_id: str) -> List[Dict]:
        """Get active P2P uploads for a user (downloads where user's tokens are the p2p_remote_token_id).
        
        This shows what the user is currently uploading to other peers.
        """
        try:
            from app.database import ApiToken, User
            from app.services.redis_downloads import RedisDownloadTracker
            
            # Get all token IDs for this user
            user_tokens = self.db.query(ApiToken).filter(
                ApiToken.user_id == user_id
            ).all()
            
            if not user_tokens:
                return []
            
            user_token_ids = {token.id for token in user_tokens}
            user_token_names = {token.id: token.name for token in user_tokens}
            
            # Find active downloads where p2p_remote_token_id matches one of user's tokens
            # We need to scan all active downloads (status='downloading')
            active_downloads = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'downloading'
            ).all()
            
            uploads = []
            for download in active_downloads:
                # Get p2p_remote_token_id from Redis
                p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(download.id)
                
                if p2p_remote_token_id and p2p_remote_token_id in user_token_ids:
                    # This download is using one of user's tokens as source - it's an upload for this user
                    
                    # Get download progress from Redis
                    redis_status = await RedisDownloadTracker.get_download_status(download.id)
                    bytes_transferred = 0
                    bandwidth_used = 0
                    
                    if redis_status:
                        bytes_transferred = redis_status.get('bytes_transferred', 0)
                        bandwidth_used = redis_status.get('bytes_per_second', 0)
                    
                    # Get game info
                    catalog_version = download.catalog_version
                    catalog_type = 'releases' if catalog_version else 'wip'
                    lookup_game_id = download.game_id
                    if catalog_type == 'releases' and catalog_version:
                        import re
                        escaped_version = re.escape(catalog_version)
                        pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                        match = pattern.match(download.game_id)
                        if match:
                            lookup_game_id = match.group(1)
                    
                    
                    # Get system_id - must be stored in queue item
                    system_id = download.system_id
                    if not system_id:
                        logger.warning(f"System ID missing for game: {lookup_game_id}, cannot retrieve active download info")
                        continue
                    game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
                    if game:
                        # Calculate progress
                        file_size = download.file_size
                        progress_percent = 0
                        if file_size and file_size > 0:
                            progress_percent = min(100, int((bytes_transferred / file_size) * 100))
                        
                        # Get downloader's token name
                        downloader_token_name = None
                        if download.token_id:
                            downloader_token = self.db.query(ApiToken).filter(
                                ApiToken.id == download.token_id
                            ).first()
                            if downloader_token:
                                downloader_token_name = downloader_token.name
                        
                        # Get downloader's username
                        downloader_username = None
                        downloader_user = self.db.query(User).filter(
                            User.user_id == download.user_id
                        ).first()
                        if downloader_user:
                            downloader_username = downloader_user.username
                        
                        upload_item = {
                            'id': download.id,
                            'download_id': download.id,
                            'type': 'upload',  # Mark as upload
                            'game_id': download.game_id,
                            'game_name': game['name'],
                            'image': self._normalize_media_path_for_frontend(game.get('image', ''), game.get('system', '')),
                            'system_name': self.game_service.get_system_name(game.get('system', '')),
                            'progress_percent': progress_percent,
                            'bytes_transferred': bytes_transferred,
                            'file_size': file_size,
                            'bandwidth_used': bandwidth_used,
                            'catalog_version': catalog_version,
                            'source_token_id': p2p_remote_token_id,
                            'source_token_name': user_token_names.get(p2p_remote_token_id, 'Unknown'),
                            'target_token_name': downloader_token_name,
                            'target_username': downloader_username,
                            'started_at': download.started_at.isoformat() if download.started_at else None
                        }
                        uploads.append(upload_item)
            
            return uploads
        except Exception as e:
            logger.error(f"Error getting active uploads: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def get_all_active_downloads(self) -> Dict:
        """Get all active downloads from all queues (admin only)."""
        try:
            from app.database import User
            
            # Get all downloads with status 'user_queue' or 'downloading'
            all_downloads = self.db.query(DownloadQueue).filter(
                DownloadQueue.status.in_(['user_queue', 'downloading'])
            ).order_by(DownloadQueue.created_at.asc()).all()
            
            # Collect unique user IDs and fetch usernames from User table
            unique_user_ids = set(item.user_id for item in all_downloads)
            username_cache = {}
            
            if unique_user_ids:
                users = self.db.query(User).filter(User.user_id.in_(list(unique_user_ids))).all()
                for user in users:
                    username_cache[user.user_id] = user.username or user.user_id
            
            # Group by queue type
            fast_queue = []
            slow_queue = []
            
            for item in all_downloads:
                game = {}
                lookup_game_id = item.game_id
                catalog_version = item.catalog_version
                
                try:
                    # Get catalog_version from queue item and derive catalog_type
                    catalog_type = 'releases' if catalog_version else 'wip'
                    
                    # Remove snapshot path prefix to get original game_id for lookup
                    if catalog_type == 'releases' and catalog_version:
                        # Extract original game_id after snapshot path
                        # game_id format: ".zfs/snapshot/v2-RGS_bbc/game.rom"
                        import re
                        escaped_version = re.escape(catalog_version)
                        pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                        match = pattern.match(item.game_id)
                        if match:
                            lookup_game_id = match.group(1)
                            logger.debug(f"Extracted lookup_game_id: {lookup_game_id} from game_id: {item.game_id}")
                        else:
                            logger.warning(f"Could not extract lookup_game_id from: {item.game_id} (catalog_version: {catalog_version})")
                    
                    logger.debug(f"Looking up game: lookup_game_id={lookup_game_id}, catalog_type={catalog_type}, catalog_version={catalog_version}")
                    
                    # Get system_id - must be stored in queue item
                    system_id = item.system_id
                    
                    # If system_id is missing, try to infer from game_id
                    if not system_id and '/' in lookup_game_id:
                        parts = lookup_game_id.split('/')
                        if len(parts) > 1:
                            # Assume first part is system_id (e.g. "snes/game.zip")
                            possible_system_id = parts[0]
                            # Try to verify if this is a valid system or if we can find the game with it
                            if self.game_service.get_system(possible_system_id):
                                system_id = possible_system_id
                                logger.info(f"Inferred system_id '{system_id}' from game_id '{lookup_game_id}'")
                    
                    if system_id:
                        game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
                        
                    if not game:
                        logger.warning(f"Game not found: lookup_game_id={lookup_game_id}, catalog_type={catalog_type}, catalog_version={catalog_version}, original game_id={item.game_id}")
                        # Provide fallback data
                        game = {
                            'name': lookup_game_id,  # Use ID as name fallback
                            'system': system_id or 'unknown',
                            'image': None
                        }
                except Exception as e:
                    logger.error(f"Error processing download item {item.id}: {e}", exc_info=True)
                    # Use fallback data even on error
                    game = {
                        'name': item.game_id,
                        'system': item.system_id or 'unknown',
                        'image': None
                    }
                
                # Calculate progress percentage
                progress_percent = 0
                if item.file_size and item.file_size > 0:
                    progress_percent = int((item.bytes_transferred / item.file_size) * 100)
                
                download_item = {
                    'id': item.id,
                    'user_id': item.user_id,
                    'username': username_cache.get(item.user_id, item.user_id),
                    'game_id': item.game_id,
                    'game_name': game.get('name', item.game_id),
                    'system': game.get('system', system_id or item.system_id or ''),
                    'system_name': self.game_service.get_system_name(game.get('system', system_id or item.system_id or '')),
                    'image': self._normalize_media_path_for_frontend(game.get('image', ''), game.get('system', '')),
                    'status': item.status,
                    'queue_type': item.queue_type,
                    'active_download': item.active_download,
                    'bytes_transferred': item.bytes_transferred,
                    'file_size': item.file_size,
                    'bandwidth_used': item.bandwidth_used,
                    'progress_percent': progress_percent,
                    'started_at': item.started_at.isoformat() if item.started_at else None,
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                    'assigned_to_service': item.assigned_to_service,
                    'catalog_version': catalog_version,  # Include catalog version (e.g., "v2-RGS_bbc")
                    'client_version': item.client_version  # Include client version (e.g., "0.1")
                }
                
                if item.queue_type == 'fast':
                    fast_queue.append(download_item)
                else:
                    slow_queue.append(download_item)
            
            # Separate user_queue items from downloading
            user_queue_fast = [d for d in fast_queue if d['status'] == 'user_queue']
            user_queue_slow = [d for d in slow_queue if d['status'] == 'user_queue']
            downloading_fast = [d for d in fast_queue if d['status'] == 'downloading']
            downloading_slow = [d for d in slow_queue if d['status'] == 'downloading']
            
            return {
                'fast_queue': fast_queue,
                'slow_queue': slow_queue,
                'user_queue_fast': user_queue_fast,
                'user_queue_slow': user_queue_slow,
                'downloading_fast': downloading_fast,
                'downloading_slow': downloading_slow,
                'total_active': len([d for d in all_downloads if d.active_download]),
                'total_user_queue': len([d for d in all_downloads if d.status == 'user_queue'])
            }
        except Exception as e:
            logger.error(f"Error getting all active downloads: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'fast_queue': [],
                'slow_queue': [],
                'user_queue_fast': [],
                'user_queue_slow': [],
                'downloading_fast': [],
                'downloading_slow': [],
                'total_active': 0,
                'total_user_queue': 0
            }
    
    async def remove_from_queue(self, user_id: str, game_id: str) -> bool:
        """Remove a game from the download queue."""
        try:
            logger.info(f"Removing from queue - Game ID: {game_id}, User ID: {user_id}")
            
            # Clean up the game ID - only remove './' prefix, preserve paths starting with '.zfs'
            if game_id.startswith('./'):
                game_id = game_id[2:]  # Remove './' prefix only
            logger.info(f"Cleaned game ID: {game_id}")
            
            queue_item = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.user_id == user_id,
                    DownloadQueue.game_id == game_id
                )
            ).first()
            
            if not queue_item:
                logger.warning(f"Game not found in queue: {game_id}")
                return False
            
            download_id = queue_item.id
            
            # Check if this is a P2P download and notify remote peer before archiving
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                from app.services.websocket_manager import get_websocket_manager
                
                logger.info(f"Checking for P2P remote token for download_id={download_id} before cancellation")
                # Get p2p_remote_token_id from Redis before removing
                p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(download_id)
                logger.info(f"Retrieved p2p_remote_token_id={p2p_remote_token_id} from Redis for download_id={download_id}")
                
                if p2p_remote_token_id:
                    logger.info(f"Download {download_id} cancelled: Notifying remote peer token_id={p2p_remote_token_id}")
                    ws_manager = get_websocket_manager()
                    notification_sent = await ws_manager.send_notification(
                        p2p_remote_token_id,
                        {
                            "type": "p2p_download_cancelled",
                            "download_id": download_id,
                            "message": "Download was cancelled by the downloading client"
                        }
                    )
                    if notification_sent:
                        logger.info(f"Sent cancellation notification to remote peer token_id={p2p_remote_token_id} for download_id={download_id}")
                    else:
                        logger.warning(f"Failed to send cancellation notification to remote peer token_id={p2p_remote_token_id} for download_id={download_id}")
                else:
                    logger.info(f"No p2p_remote_token_id found in Redis for download_id={download_id} - not a P2P download or token not stored")
                
                # Remove from Redis
                await RedisDownloadTracker.remove_download(download_id)
                logger.info(f"Removed download_id={download_id} from Redis")
            except Exception as e:
                logger.error(f"Error notifying remote peer or removing from Redis for download_id={download_id}: {e}", exc_info=True)
            
            # Archive the download before deletion (user cancelled)
            await self.archive_download(download_id, 'cancelled')
            
            self.db.delete(queue_item)
            self.db.commit()
            
            logger.info(f"Successfully removed game from queue: {game_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing game from queue: {e}")
            self.db.rollback()
            return False
    
    async def clear_queue(self, user_id: str) -> bool:
        """Clear all games from the download queue for a user."""
        try:
            # Get all downloads before deleting to notify remote peers
            downloads = self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
            ).all()
            
            download_ids = [d.id for d in downloads]
            
            # Notify remote peers for P2P downloads before clearing
            if download_ids:
                try:
                    from app.services.redis_downloads import RedisDownloadTracker
                    from app.services.websocket_manager import get_websocket_manager
                    
                    ws_manager = get_websocket_manager()
                    for download_id in download_ids:
                        # Get p2p_remote_token_id from Redis before removing
                        p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(download_id)
                        
                        if p2p_remote_token_id:
                            logger.info(f"Download {download_id} cancelled (queue cleared): Notifying remote peer token_id={p2p_remote_token_id}")
                            notification_sent = await ws_manager.send_notification(
                                p2p_remote_token_id,
                                {
                                    "type": "p2p_download_cancelled",
                                    "download_id": download_id,
                                    "message": "Download was cancelled (queue cleared)"
                                }
                            )
                            if notification_sent:
                                logger.info(f"Sent cancellation notification to remote peer token_id={p2p_remote_token_id} for download_id={download_id}")
                        
                        # Remove from Redis
                        await RedisDownloadTracker.remove_download(download_id)
                except Exception as e:
                    logger.warning(f"Error notifying remote peers or removing from Redis: {e}")
            
            # Archive all downloads before deletion
            for download in downloads:
                await self.archive_download(download.id, 'cancelled')
            
            # Delete all downloads
            self.db.query(DownloadQueue).filter(
                DownloadQueue.user_id == user_id
            ).delete()
            self.db.commit()
            
            logger.info(f"Successfully cleared queue for user: {user_id} ({len(download_ids)} downloads)")
            return True
        except Exception as e:
            logger.error(f"Error clearing queue: {e}")
            self.db.rollback()
            return False
    
    def pause_download(self, user_id: str, download_id: int) -> bool:
        """Pause a download (only if it's pending or downloading)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.id == download_id,
                    DownloadQueue.user_id == user_id
                )
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for user {user_id}")
                return False
            
            # Only allow pausing if status is downloading
            if download.status != 'downloading':
                logger.warning(f"Cannot pause download {download_id} with status {download.status}")
                return False
            
            # Set status to paused and clear active_download flag
            download.status = 'paused'
            download.active_download = False
            download.assigned_to_service = None  # Release service assignment
            
            # Release bandwidth
            if download.bandwidth_used > 0:
                self.bandwidth_manager.update_usage(download.queue_type, -download.bandwidth_used)
                download.bandwidth_used = 0
            
            self.db.commit()
            
            # Update Redis status
            try:
                import asyncio
                from app.services.redis_downloads import RedisDownloadTracker
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(RedisDownloadTracker.update_status(download_id, 'paused'))
                    else:
                        loop.run_until_complete(RedisDownloadTracker.update_status(download_id, 'paused'))
                except RuntimeError:
                    asyncio.run(RedisDownloadTracker.update_status(download_id, 'paused'))
            except Exception as e:
                logger.debug(f"Failed to update Redis status for pause: {e}")
            
            logger.info(f"Paused download {download_id} for user {user_id}")
            
            # Send WebSocket notification to client (if token_id exists)
            if download.token_id:
                try:
                    from app.services.websocket_manager import get_websocket_manager
                    ws_manager = get_websocket_manager()
                    # Note: We can't await here since this is a sync method
                    # The endpoint will handle the async notification
                    pass
                except Exception as e:
                    logger.debug(f"Could not get websocket manager in pause_download: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error pausing download: {e}")
            self.db.rollback()
            return False
    
    def resume_download(self, user_id: str, download_id: int) -> bool:
        """Resume a paused download (change status back to user_queue)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                and_(
                    DownloadQueue.id == download_id,
                    DownloadQueue.user_id == user_id
                )
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for user {user_id}")
                return False
            
            # Only allow resuming if status is paused
            if download.status != 'paused':
                logger.warning(f"Cannot resume download {download_id} with status {download.status}")
                return False
            
            # Change status back to user_queue (will be picked up by download service)
            download.status = 'user_queue'
            download.active_download = False
            
            self.db.commit()
            
            # Remove from Redis (back to user queue, not active)
            try:
                import asyncio
                from app.services.redis_downloads import RedisDownloadTracker
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(RedisDownloadTracker.remove_download(download_id))
                    else:
                        loop.run_until_complete(RedisDownloadTracker.remove_download(download_id))
                except RuntimeError:
                    asyncio.run(RedisDownloadTracker.remove_download(download_id))
            except Exception as e:
                logger.debug(f"Failed to remove from Redis on resume: {e}")
            
            logger.info(f"Resumed download {download_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            self.db.rollback()
            return False
    
    def enrich_queue_items(self, queue_items: List[Dict]) -> List[Dict]:
        """Enrich queue items with game metadata."""
        enriched = []
        for item in queue_items:
            catalog_type = item.get('catalog_type', 'releases')
            game_id = item.get('game_id', '')
            # Remove snapshot path prefix if needed to get original game_id for lookup
            lookup_game_id = game_id
            if catalog_type == 'releases' and '.zfs/snapshot' in game_id:
                parts = game_id.split('.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    if '/' in after_snapshot:
                        lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        lookup_game_id = after_snapshot
            
            
            # Get system_id - must be stored in queue item
            system_id = item.system_id
            if not system_id:
                logger.warning(f"System ID missing for game: {lookup_game_id}, cannot process download")
                return None
            game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
            if game:
                enriched_item = item.copy()
                enriched_item['game_name'] = game['name']
                enriched_item['image'] = self._normalize_media_path_for_frontend(game.get('image', ''), game.get('system', ''))
                enriched_item['system_name'] = self.game_service.get_system_name(game.get('system', ''))
                enriched.append(enriched_item)
            else:
                enriched.append(item)
        return enriched
    
    def _promote_user_queue_to_global(self, queue_type: Optional[str] = None, token_id: Optional[int] = None) -> bool:
        """This method is no longer needed - downloads go directly from user_queue to downloading.
        
        Kept for backward compatibility but does nothing now. get_next_download now looks for user_queue items directly.
        """
        # No longer needed - get_next_download now looks for user_queue items directly
        # No status change needed - items stay in user_queue until picked up
        return False
    
    def check_available_downloads(self, token_id: Optional[int] = None) -> Dict[str, bool]:
        """Check if there are any downloads available for a token_id.
        
        Checks for:
        - Downloads in user_queue
        - Resumable downloads (downloading status that can be resumed)
        
        Args:
            token_id: The API token ID to check
            
        Returns:
            Dict with keys 'has_user_queue', 'has_resumable', 'has_any'
        """
        if token_id is None:
            return {'has_user_queue': False, 'has_resumable': False, 'has_any': False}
        
        try:
            # Check for items in user_queue
            user_queue_count = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'user_queue',
                DownloadQueue.token_id == token_id
            ).count()
            has_user_queue = user_queue_count > 0
            
            # Check for resumable downloads
            # Since only one connection per token_id is allowed, any download in "downloading" 
            # status for this token_id is potentially resumable (the service may have restarted).
            # Note: Paused downloads are not considered "resumable" here - they need to be manually
            # resumed by the user, at which point they become 'user_queue' and will be picked up.
            resumable_count = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'downloading',
                DownloadQueue.active_download == True,
                DownloadQueue.token_id == token_id,
                DownloadQueue.status != 'paused'
            ).count()
            has_resumable = resumable_count > 0
            
            has_any = has_user_queue or has_resumable
            
            return {
                'has_user_queue': has_user_queue,
                'has_resumable': has_resumable,
                'has_any': has_any,
                'user_queue_count': user_queue_count,
                'resumable_count': resumable_count
            }
        except Exception as e:
            logger.error(f"Error checking available downloads: {e}")
            return {'has_user_queue': False, 'has_resumable': False, 'has_any': False}
    
    async def get_next_download(self, queue_type: Optional[str] = None, service_id: str = 'default', token_id: Optional[int] = None, platform: Optional[str] = None, client_version: Optional[str] = None) -> Optional[Dict]:
        """Get next available download from queue, including resumable interrupted downloads.
        
        Only returns downloads associated with the specified token_id.
        
        If queue_type is None, searches both fast and slow queues for downloads with matching token_id.
        """
        try:
            # First, try to promote items from user queues to global queue for this token
            # When queue_type is None, promote from both queues
            if queue_type is None:
                self._promote_user_queue_to_global('fast', token_id=token_id)
                self._promote_user_queue_to_global('slow', token_id=token_id)
            else:
                self._promote_user_queue_to_global(queue_type, token_id=token_id)
            
            # Then, check for downloads that are marked as downloading but might be interrupted
            # (e.g., service crashed, network issue). Allow resuming if assigned to same service
            # or if no progress in last 5 minutes (configurable timeout)
            from datetime import timedelta
            timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
            
            # Check for resumable downloads (downloading status, same service or timed out)
            # Since only one connection per token_id is allowed, if token_id is specified,
            # we should include all downloads for this token_id that are in downloading status.
            # Only for the authenticated token (exclude paused)
            if token_id is not None:
                # For token_id-based filtering, include all downloads for this token_id
                # that are in downloading status (since only one connection per token is allowed)
                resumable_query = self.db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'downloading',
                    DownloadQueue.active_download == True,
                    DownloadQueue.token_id == token_id,
                    DownloadQueue.status != 'paused'  # Exclude paused downloads
                )
            else:
                # No token_id filter - use service_id and timeout criteria
                resumable_query = self.db.query(DownloadQueue).filter(
                    DownloadQueue.status == 'downloading',
                    DownloadQueue.active_download == True,
                    or_(
                        DownloadQueue.assigned_to_service == service_id,
                        DownloadQueue.started_at < timeout_threshold
                    )
                ).filter(
                    DownloadQueue.status != 'paused'  # Exclude paused downloads
                )
            
            # Filter by queue_type if specified, otherwise search all queues
            if queue_type:
                resumable_query = resumable_query.filter(DownloadQueue.queue_type == queue_type)
            
            resumable_download = resumable_query.order_by(DownloadQueue.started_at.asc()).first()
            
            if resumable_download:
                logger.info(f"Found resumable download: {resumable_download.id} (bytes_transferred: {resumable_download.bytes_transferred})")
                # Update service assignment in case it changed
                resumable_download.assigned_to_service = service_id
                # Update last_progress_at to current time (download is being resumed)
                resumable_download.last_progress_at = datetime.now(timezone.utc)
                # Update client_version if provided
                if client_version:
                    resumable_download.client_version = client_version
                self.db.commit()
                
                # Get game info
                # Get catalog_version from download queue item and derive catalog_type
                catalog_version = resumable_download.catalog_version
                catalog_type = 'releases' if catalog_version else 'wip'
                # Remove snapshot path prefix if needed to get original game_id for lookup
                lookup_game_id = resumable_download.game_id
                if catalog_type == 'releases' and '.zfs/snapshot' in resumable_download.game_id:
                    parts = resumable_download.game_id.split('.zfs/snapshot/', 1)
                    if len(parts) > 1:
                        after_snapshot = parts[1]
                        if '/' in after_snapshot:
                            lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                        else:
                            lookup_game_id = after_snapshot
                
                
                # Get system_id - must be stored in queue item
                system_id = resumable_download.system_id
                if not system_id:
                    logger.warning(f"System ID missing for resumable download: {lookup_game_id}")
                    return None
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
                if not game:
                    logger.warning(f"Game not found: {lookup_game_id} (catalog_type: {catalog_type}, version: {catalog_version})")
                    # Archive and remove from queue since game doesn't exist
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                system = game.get('system', '')
                
                # Get system info from System table - use retrobat_system for Windows, batocera_system for Linux
                db_system = self.db.query(System).filter(System.id == system).first()
                if not db_system:
                    logger.error(f"System not found in database: {system}")
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                # Determine which system prefix to use based on client platform
                is_windows = platform and platform.lower() == 'windows'
                if is_windows:
                    target_system = db_system.retrobat_system
                    system_type = 'retrobat_system'
                else:
                    target_system = db_system.batocera_system
                    system_type = 'batocera_system'
                
                if not target_system:
                    logger.error(f"{system_type} not set for system: {system}")
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    return None
                
                logger.info(f"Using {system_type}='{target_system}' for client platform (service_id={service_id}, is_windows={is_windows})")
                
                # Resolve unified ROM key if needed (BEFORE checking file existence)
                import re
                original_game_id = resumable_download.game_id
                # Check if game_id is a unified key: ends with .(ext1|ext2) pattern
                unified_pattern = r'\.\([^|]+\|[^)]+\)$'
                is_unified_key = bool(re.search(unified_pattern, original_game_id))
                
                if is_unified_key and not platform:
                    logger.error(f"Cannot resolve unified key '{original_game_id}' - platform not provided. Platform is required for unified keys.")
                    # Archive and remove from queue - cannot proceed without platform info
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    logger.info(f"Removed download {resumable_download.id} from queue - platform required for unified key")
                    return None
                
                resolved_game_id = self._resolve_unified_rom_key(original_game_id, system, platform, catalog_type)
                is_still_unified = bool(re.search(unified_pattern, resolved_game_id))
                
                if resolved_game_id != original_game_id:
                    logger.info(f"Resolved unified ROM key for resumable download: '{original_game_id}' -> '{resolved_game_id}' (platform: {platform})")
                    # Don't update game_id in database - keep original unified key for history
                    # Use resolved_game_id only for file paths and URLs
                elif is_still_unified:
                    # Resolution failed - log detailed error
                    logger.error(f"Failed to resolve unified key '{original_game_id}' - still unified after resolution. Platform: {platform}, System: {system}")
                    # Archive and remove from queue - resolution failed
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    logger.info(f"Removed download {resumable_download.id} from queue - unified key resolution failed")
                    return None
                
                # Build file path using resolved game_id
                file_path = None
                if settings.GAMES_PATH:
                    logger.info(f"Building file path for game_id={resolved_game_id}, system={system}")
                    if system:
                        file_path = os.path.join(settings.GAMES_PATH, system, resolved_game_id)
                        logger.info(f"File path with system: {file_path}")
                    else:
                        logger.error(f"System is empty for game_id={resolved_game_id}, cannot build file path")
                        # Archive and remove from queue since system is missing
                        await self.archive_download(resumable_download.id, 'error')
                        self.db.delete(resumable_download)
                        self.db.commit()
                        return None
                
                # Verify file or directory exists before resuming download
                # (Resolution should have succeeded at this point, so resolved_game_id should not be a unified key)
                if not os.path.exists(file_path):
                    logger.error(f"File or directory does not exist: {file_path} for game_id={resolved_game_id}")
                    # Archive and remove from queue since file doesn't exist
                    await self.archive_download(resumable_download.id, 'error')
                    self.db.delete(resumable_download)
                    self.db.commit()
                    logger.info(f"Removed download {resumable_download.id} from queue - file not found")
                    return None
                
                # Calculate available bandwidth
                allocated_bandwidth = self.bandwidth_manager.allocate_bandwidth(resumable_download.queue_type)
                
                # Get user's custom bandwidth limit if set (capped at role-based limit)
                from app.database import User
                db_user = self.db.query(User).filter(User.user_id == resumable_download.user_id).first()
                if db_user and db_user.bandwidth_limit is not None and db_user.bandwidth_limit > 0:
                    # Cap user's bandwidth_limit at the role-based limit
                    allocated_bandwidth = min(allocated_bandwidth, db_user.bandwidth_limit)
                    logger.info(f"Applied user bandwidth limit: {db_user.bandwidth_limit} bytes/s, effective: {allocated_bandwidth} bytes/s")
                
                # Construct HTTP URL for the file using download_id (simpler and more reliable)
                # Use DOWNLOAD_FILE_URL if set, otherwise fall back to API_URL
                base_url = settings.DOWNLOAD_FILE_URL if settings.DOWNLOAD_FILE_URL else settings.API_URL
                http_url = f"{base_url}/api/download/file?download_id={resumable_download.id}"
                logger.debug(f"Constructed file URL with download_id: {http_url}")
                
                # For client: we need both original game_id (for URL construction) and normalized game_id (for destination paths)
                # Keep resolved game_id and add normalized rom_path for destination
                normalized_game_id = self._remove_snapshot_path_from_game_id(resolved_game_id, catalog_version)
                
                # Check if this is a .psvita file and calculate save_location
                save_location = None
                if resolved_game_id.lower().endswith('.psvita'):
                    # Parse the .psvita file to get directory name (TITLE ID)
                    directory_name = parse_psvita_file(file_path)
                    if directory_name:
                        # Build save_location path based on platform
                        # Linux: psvita/ux0/app/{directory_name}
                        # Windows: psvita/vita3k/app/{directory_name}
                        if is_windows:
                            save_location = f"psvita/vita3k/ux0/app/{directory_name}"
                        else:
                            save_location = f"psvita/ux0/app/{directory_name}"
                        logger.info(f"Detected .psvita file, save_location: {save_location} (platform: {'windows' if is_windows else 'linux'})")
                
                # Check if this is a .psn file and calculate config_location/save_location
                config_location = None
                if resolved_game_id.lower().endswith('.psn'):
                    # Parse the .psn file to get directory name
                    directory_name = parse_psn_file(file_path)
                    if directory_name:
                        # Build location path based on platform
                        # Linux: ps3/rpcs3/dev_hdd0/game/{directory_name} (uses config_location)
                        # Windows: ps3/rpcs3/dev_hdd0/game/{directory_name} (uses save_location)
                        if is_windows:
                            save_location = f"ps3/rpcs3/dev_hdd0/game/{directory_name}"
                            logger.info(f"Detected .psn file, save_location: {save_location} (platform: windows)")
                        else:
                            config_location = f"rpcs3/dev_hdd0/game/{directory_name}"
                            logger.info(f"Detected .psn file, config_location: {config_location} (platform: linux)")
                
                # Check if this is a PS3 .m3u file and calculate save_location
                if resolved_game_id.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                    # Parse the PS3 .m3u file to get directory name
                    directory_name = parse_m3u_ps3_directory(file_path)
                    if directory_name:
                        # Build save_location path (same for both Linux and Windows, uses SAVEDIR)
                        save_location = f"ps3/rpcs3/dev_hdd0/game/{directory_name}"
                        logger.info(f"Detected PS3 .m3u file, save_location: {save_location} (platform: {'windows' if is_windows else 'linux'})")
                
                # Check if this is a win98 .zip file and calculate save_location
                if system and system.lower() == 'win98' and resolved_game_id.lower().endswith('.zip'):
                    # For win98 .zip files, save files go to SAVEDIR/win98/
                    save_location = "win98"
                    logger.info(f"Detected win98 .zip file, save_location: {save_location}")
                
                download_info = {
                    'download_id': resumable_download.id,
                    'game_id': resolved_game_id,  # Use resolved game_id (unified key already resolved)
                    'rom_path': normalized_game_id,  # Normalized path for client destination (without snapshot path)
                    'user_id': resumable_download.user_id,
                    'file_path': file_path,
                    'file_url': http_url,  # HTTP URL for downloading the file
                    'file_size': resumable_download.file_size,
                    'bytes_transferred': resumable_download.bytes_transferred,
                    'allocated_bandwidth': allocated_bandwidth,
                    'queue_type': resumable_download.queue_type,
                    'game_name': game.get('name', ''),
                    'system': game.get('system', ''),  # Include system for download service
                    'batocera_system': target_system,  # Include system prefix for destination path (batocera_system for Linux, retrobat_system for Windows)
                    'game_details': self._normalize_game_details_for_client(game, catalog_version),  # Include full game details for media download (snapshot paths removed)
                    'p2p_enabled': settings.P2P_ENABLED  # Include P2P enabled status
                }
                
                # Add save_location if this is a .psvita or .psn file (Windows)
                if save_location:
                    download_info['save_location'] = save_location
                
                # Add config_location if this is a .psn file (Linux)
                if config_location:
                    download_info['config_location'] = config_location
                
                logger.info(f"Resuming download {resumable_download.id} from {resumable_download.bytes_transferred} bytes")
                return download_info
            
            # Build query for user_queue downloads (exclude paused)
            # Only for the authenticated token
            # Look for user_queue items directly - no pending status anymore
            query = self.db.query(DownloadQueue).filter(
                DownloadQueue.status == 'user_queue'
            )
            
            # Filter by token_id if specified (required for token-based downloads)
            if token_id is not None:
                query = query.filter(DownloadQueue.token_id == token_id)
            
            # Filter by queue_type if specified, otherwise search all queues
            if queue_type:
                query = query.filter(DownloadQueue.queue_type == queue_type)
            
            # Order by created_at (oldest first)
            pending_download = query.order_by(DownloadQueue.created_at.asc()).first()
            
            if not pending_download:
                logger.debug("No user_queue downloads available")
                return None
            
            # Check if we can allocate bandwidth for this queue
            allocated_bandwidth = self.bandwidth_manager.allocate_bandwidth(pending_download.queue_type)
            
            # Get user's custom bandwidth limit if set (capped at role-based limit)
            from app.database import User
            db_user = self.db.query(User).filter(User.user_id == pending_download.user_id).first()
            if db_user and db_user.bandwidth_limit is not None and db_user.bandwidth_limit > 0:
                # Cap user's bandwidth_limit at the role-based limit
                allocated_bandwidth = min(allocated_bandwidth, db_user.bandwidth_limit)
                logger.info(f"Applied user bandwidth limit: {db_user.bandwidth_limit} bytes/s, effective: {allocated_bandwidth} bytes/s")
            
            if allocated_bandwidth <= 0:
                logger.debug(f"No bandwidth available for {pending_download.queue_type} queue")
                return None
            
            # Check if there's already an active download for this token_id
            # Since only one client per token_id is allowed, check per token_id
            if token_id is not None:
                has_active = self.db.query(DownloadQueue).filter(
                    and_(
                        DownloadQueue.token_id == token_id,
                        DownloadQueue.active_download == True,
                        DownloadQueue.status == 'downloading'
                    )
                ).first()
                
                if has_active:
                    logger.debug(f"Token_id {token_id} already has active download (id: {has_active.id}), skipping user_queue item {pending_download.id}")
                    return None
            
            # Also check if user already has active download (bandwidth manager check)
            if not self.bandwidth_manager.can_start_download(pending_download.queue_type, pending_download.user_id):
                logger.warning(f"User {pending_download.user_id} already has active download, skipping")
                return None
            
            # Get catalog_version from download queue item and derive catalog_type
            catalog_version = pending_download.catalog_version
            catalog_type = 'releases' if catalog_version else 'wip'
            # Remove snapshot path prefix if needed to get original game_id for lookup
            lookup_game_id = pending_download.game_id
            if catalog_type == 'releases' and '.zfs/snapshot' in pending_download.game_id:
                parts = pending_download.game_id.split('.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    if '/' in after_snapshot:
                        lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        lookup_game_id = after_snapshot
                        
            # Get game info
            game = None
            # Get detailed game info using system_id (required)
            system_id = pending_download.system_id
            game = None
            if system_id:
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
            else:
                logger.warning(f"System ID missing for download {pending_download.id}, cannot process")

            if not game:
                logger.warning(f"Game not found: {lookup_game_id} (catalog_type: {catalog_type}, version: {catalog_version})")
                # Archive and remove from queue since game doesn't exist
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            system = game.get('system', '')
            
            # Get system info from System table - use retrobat_system for Windows, batocera_system for Linux
            db_system = self.db.query(System).filter(System.id == system).first()
            if not db_system:
                logger.error(f"System not found in database: {system}")
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            # Determine which system prefix to use based on client platform
            is_windows = platform and platform.lower() == 'windows'
            if is_windows:
                target_system = db_system.retrobat_system
                system_type = 'retrobat_system'
            else:
                target_system = db_system.batocera_system
                system_type = 'batocera_system'
            
            if not target_system:
                logger.error(f"{system_type} not set for system: {system}")
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                return None
            
            logger.info(f"Using {system_type}='{target_system}' for client platform (service_id={service_id}, is_windows={is_windows})")
            
            # Resolve unified ROM key if needed (BEFORE checking file existence)
            import re
            original_game_id = pending_download.game_id
            # Check if game_id is a unified key: ends with .(ext1|ext2) pattern
            unified_pattern = r'\.\([^|]+\|[^)]+\)$'
            is_unified_key = bool(re.search(unified_pattern, original_game_id))
            
            if is_unified_key and not platform:
                logger.error(f"Cannot resolve unified key '{original_game_id}' - platform not provided. Platform is required for unified keys.")
                # Archive and remove from queue - cannot proceed without platform info
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                logger.info(f"Removed download {pending_download.id} from queue - platform required for unified key")
                return None
            
            resolved_game_id = self._resolve_unified_rom_key(original_game_id, system, platform, catalog_type)
            is_still_unified = bool(re.search(unified_pattern, resolved_game_id))
            
            if resolved_game_id != original_game_id:
                logger.info(f"Resolved unified ROM key: '{original_game_id}' -> '{resolved_game_id}' (platform: {platform})")
                # Don't update game_id in database - keep original unified key for history
                # Use resolved_game_id only for file paths and URLs
            elif is_still_unified:
                # Resolution failed - log detailed error
                logger.error(f"Failed to resolve unified key '{original_game_id}' - still unified after resolution. Platform: {platform}, System: {system}")
                # Archive and remove from queue - resolution failed
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                logger.info(f"Removed download {pending_download.id} from queue - unified key resolution failed")
                return None
            
            # Build file path using resolved game_id
            file_path = None
            if settings.GAMES_PATH:
                logger.info(f"Building file path for game_id={resolved_game_id}, system={system}")
                if system:
                    file_path = os.path.join(settings.GAMES_PATH, system, resolved_game_id)
                    logger.info(f"File path with system: {file_path}")
                else:
                    logger.error(f"System is empty for game_id={resolved_game_id}, cannot build file path")
                    # Archive and remove from queue since system is missing
                    await self.archive_download(pending_download.id, 'error')
                    self.db.delete(pending_download)
                    self.db.commit()
                    return None
            
            # Verify file or directory exists before assigning download
            # (Resolution should have succeeded at this point, so resolved_game_id should not be a unified key)
            if not os.path.exists(file_path):
                logger.error(f"File or directory does not exist: {file_path} for game_id={resolved_game_id}")
                # Archive and remove from queue since file doesn't exist
                await self.archive_download(pending_download.id, 'error')
                self.db.delete(pending_download)
                self.db.commit()
                logger.info(f"Removed download {pending_download.id} from queue - file not found")
                return None
            
            # Special file parsing is now handled by the API endpoint when the file is requested
            # No need to parse here
            
            # Mark as active
            pending_download.active_download = True
            pending_download.status = 'downloading'
            pending_download.started_at = datetime.now(timezone.utc)
            pending_download.last_progress_at = datetime.now(timezone.utc)  # Initialize progress tracking
            pending_download.assigned_to_service = service_id
            # Store client_version if provided
            if client_version:
                pending_download.client_version = client_version
            self.db.commit()
            
            # Note: Redis storage will be done in the async endpoint after this function returns
            # This avoids async/sync mixing issues
            
            # Construct HTTP URL for the file using download_id (simpler and more reliable)
            # Use DOWNLOAD_FILE_URL if set, otherwise fall back to API_URL
            base_url = settings.DOWNLOAD_FILE_URL if settings.DOWNLOAD_FILE_URL else settings.API_URL
            http_url = f"{base_url}/api/download/file?download_id={pending_download.id}"
            logger.debug(f"Constructed file URL with download_id: {http_url}")
            
            # For client: we need both original game_id (for URL construction) and normalized game_id (for destination paths)
            # Keep resolved game_id and add normalized rom_path for destination
            normalized_game_id = self._remove_snapshot_path_from_game_id(resolved_game_id, catalog_version)
            
            # Check if this is a .psvita file and calculate save_location
            save_location = None
            if resolved_game_id.lower().endswith('.psvita'):
                # Parse the .psvita file to get directory name (TITLE ID)
                directory_name = parse_psvita_file(file_path)
                if directory_name:
                    # Build save_location path based on platform
                    # Linux: psvita/ux0/app/{directory_name}
                    # Windows: psvita/vita3k/app/{directory_name}
                    is_windows_platform = is_windows
                    if is_windows_platform:
                        save_location = f"psvita/vita3k/app/{directory_name}"
                    else:
                        save_location = f"psvita/ux0/app/{directory_name}"
                    logger.info(f"Detected .psvita file, save_location: {save_location} (platform: {'windows' if is_windows_platform else 'linux'})")
            
            # Check if this is a .psn file and calculate config_location/save_location
            config_location = None
            if resolved_game_id.lower().endswith('.psn'):
                # Parse the .psn file to get directory name
                directory_name = parse_psn_file(file_path)
                if directory_name:
                    # Build location path based on platform
                    # Linux: rpcs3/dev_hdd0/game/{directory_name} (uses config_location, joined with CONFIGDIR)
                    # Windows: ps3/rpcs3/dev_hdd0/game/{directory_name} (uses save_location, joined with SAVEDIR)
                    if is_windows:
                        save_location = f"ps3/rpcs3/dev_hdd0/game/{directory_name}"
                        logger.info(f"Detected .psn file, save_location: {save_location} (platform: windows)")
                    else:
                        config_location = f"rpcs3/dev_hdd0/game/{directory_name}"
                        logger.info(f"Detected .psn file, config_location: {config_location} (platform: linux)")
            
            # Check if this is a PS3 .m3u file and calculate save_location
            if resolved_game_id.lower().endswith('.m3u') and system and system.lower() == 'ps3':
                # Parse the PS3 .m3u file to get directory name
                directory_name = parse_m3u_ps3_directory(file_path)
                if directory_name:
                    # Build save_location path (same for both Linux and Windows, uses SAVEDIR)
                    save_location = f"ps3/rpcs3/dev_hdd0/game/{directory_name}"
                    is_windows_platform = is_windows
                    logger.info(f"Detected PS3 .m3u file, save_location: {save_location} (platform: {'windows' if is_windows_platform else 'linux'})")
            
            # Check if this is a win98 .zip file and calculate save_location
            if system and system.lower() == 'win98' and resolved_game_id.lower().endswith('.zip'):
                # For win98 .zip files, save files go to SAVEDIR/win98/
                save_location = "win98"
                logger.info(f"Detected win98 .zip file, save_location: {save_location}")
            
            download_info = {
                'download_id': pending_download.id,
                'game_id': resolved_game_id,  # Use resolved game_id (unified key already resolved)
                'rom_path': normalized_game_id,  # Normalized path for client destination (without snapshot path)
                'user_id': pending_download.user_id,
                'file_path': file_path,
                'file_url': http_url,  # HTTP URL for downloading the file
                'file_size': pending_download.file_size,
                'bytes_transferred': pending_download.bytes_transferred or 0,
                'allocated_bandwidth': allocated_bandwidth,
                'queue_type': pending_download.queue_type,
                'game_name': game.get('name', ''),
                'system': game.get('system', ''),
                'batocera_system': target_system,  # Include system prefix for destination path (batocera_system for Linux, retrobat_system for Windows)
                'game_details': self._normalize_game_details_for_client(game, catalog_version),  # Include full game details for media download (snapshot paths removed)
                'p2p_enabled': settings.P2P_ENABLED  # Include P2P enabled status
            }
            
            # Add save_location if this is a .psvita or .psn file (Windows)
            if save_location:
                download_info['save_location'] = save_location
            
            # Add config_location if this is a .psn file (Linux)
            if config_location:
                download_info['config_location'] = config_location
            
            logger.info(f"Assigned download {pending_download.id} to service {service_id} with {allocated_bandwidth} bytes/s")
            return download_info
            
        except Exception as e:
            logger.error(f"Error getting next download: {e}")
            self.db.rollback()
            return None
    
    def update_progress(self, download_id: int, bytes_transferred: int, bytes_per_second: int, client_version: Optional[str] = None) -> bool:
        """Update download progress (Redis only for active downloads).
        
        Note: This method is only called for user_queue items now. Active downloads
        are updated directly via Redis in the report_progress endpoint.
        """
        try:
            # This should only be called for user_queue items (not active downloads)
            # Active downloads are handled via Redis in report_progress endpoint
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Log previous values for debugging
            old_bytes = download.bytes_transferred
            old_bandwidth = download.bandwidth_used
            
            # Update progress fields - always update even if values seem the same
            # This ensures SQLAlchemy tracks the change
            download.bytes_transferred = bytes_transferred
            download.bandwidth_used = bytes_per_second
            download.last_progress_at = datetime.now(timezone.utc)
            
            # Update client_version if provided (may not have been set initially)
            if client_version:
                download.client_version = client_version
            
            # If status is "stuck", change it back to "downloading" (client reconnected)
            if download.status == 'stuck':
                logger.info(f"Download {download_id} resumed after being stuck, changing status to downloading")
                download.status = 'downloading'
                download.active_download = True
                # Store in Redis when status changes to downloading
                try:
                    import asyncio
                    from app.services.redis_downloads import RedisDownloadTracker
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(RedisDownloadTracker.set_active_download(
                                download_id,
                                status='downloading',
                                bytes_transferred=bytes_transferred,
                                bytes_per_second=bytes_per_second,
                                file_size=download.file_size,
                                queue_type=download.queue_type,
                                assigned_to_service=download.assigned_to_service
                            ))
                        else:
                            loop.run_until_complete(RedisDownloadTracker.set_active_download(
                                download_id,
                                status='downloading',
                                bytes_transferred=bytes_transferred,
                                bytes_per_second=bytes_per_second,
                                file_size=download.file_size,
                                queue_type=download.queue_type,
                                assigned_to_service=download.assigned_to_service
                            ))
                    except RuntimeError:
                        asyncio.run(RedisDownloadTracker.set_active_download(
                            download_id,
                            status='downloading',
                            bytes_transferred=bytes_transferred,
                            bytes_per_second=bytes_per_second,
                            file_size=download.file_size,
                            queue_type=download.queue_type,
                            assigned_to_service=download.assigned_to_service
                        ))
                except Exception as e:
                    logger.warning(f"Failed to store download in Redis: {e}")
            
            # Mark object as modified explicitly (though assignment should do this)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(download, "bytes_transferred")
            flag_modified(download, "bandwidth_used")
            flag_modified(download, "last_progress_at")
            
            # Flush changes to database before commit to ensure they're persisted
            self.db.flush()
            
            # Commit all changes together
            self.db.commit()
            
            # Log the update (use INFO level so we can see it in logs)
            logger.info(f"Updated progress for download {download_id}: {old_bytes} -> {bytes_transferred} bytes, {old_bandwidth} -> {bytes_per_second} bytes/s")
            return True
        except Exception as e:
            logger.error(f"Error updating progress for download {download_id}: {e}", exc_info=True)
            self.db.rollback()
            return False
    
    async def archive_download(self, download_id: int, status: str) -> Tuple[bool, int]:
        """Archive a download before deletion.
        
        This function also syncs bytes_transferred from Redis if available,
        since progress reports update Redis but not the database. This ensures
        accurate archive data and P2P statistics.
        
        Args:
            download_id: Download ID to archive
            status: Download status ('completed', 'error', 'cancelled', 'stuck', etc.)
        
        Returns:
            Tuple[bool, int]: (success, bytes_transferred) - True if archived successfully, 
                              and the synced bytes_transferred value
        """
        try:
            from app.database import DownloadArchive, User
            
            # Get download from queue
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found for archiving")
                return (False, 0)
            
            # Get game information
            # Get catalog_version from download queue item and derive catalog_type
            catalog_version = download.catalog_version
            catalog_type = 'releases' if catalog_version else 'wip'
            
            # Use the original game_id from database (should be unified key if it was one)
            # This preserves the original unified key format in history
            archive_game_id = download.game_id
            
            # Remove snapshot path prefix if needed to get original game_id for lookup
            lookup_game_id = download.game_id
            if catalog_type == 'releases' and '.zfs/snapshot' in download.game_id:
                parts = download.game_id.split('.zfs/snapshot/', 1)
                if len(parts) > 1:
                    after_snapshot = parts[1]
                    if '/' in after_snapshot:
                        lookup_game_id = '/'.join(after_snapshot.split('/')[1:])
                    else:
                        lookup_game_id = after_snapshot
            
            
            # Get system_id - must be stored in queue item
            system_id = download.system_id
            if not system_id:
                logger.warning(f"System ID missing for download {download_id}, cannot retrieve full game details for archive")
                game = None
                # If system_id is not found, game will be None, and the subsequent logic will handle it.
                game = None
            else:
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
            logger.debug(f"Initial game lookup for '{lookup_game_id}' (catalog_type: {catalog_type}): {'found' if game else 'not found'}")
            
            # If the game_id is already a unified key, we're done - use it as-is
            # Otherwise, try to find the unified key version
            import re
            unified_pattern = r'\.\([^|]+\|[^)]+\)$'
            is_unified_in_db = bool(re.search(unified_pattern, lookup_game_id))
            
            if is_unified_in_db:
                logger.debug(f"Game ID in database is already a unified key: '{download.game_id}', using it for archive")
            
            # If game lookup failed, try to find the unified key version
            # (resolved path like Tittie_Tussle.daphne won't exist in catalog, only Tittie_Tussle.(daphne|hypseus))
            if not game:
                # Try to reverse-engineer the unified key from the resolved path
                import re
                import os
                
                # Extract base path and extension from resolved game_id
                # e.g., "Tittie_Tussle.daphne" -> base="Tittie_Tussle", ext="daphne"
                base_name = os.path.splitext(lookup_game_id)[0]
                resolved_ext = os.path.splitext(lookup_game_id)[1].lstrip('.')
                logger.debug(f"Trying to find unified key for base_name: '{base_name}', resolved_ext: '{resolved_ext}'")
                
                # Get the catalog dictionary
                if catalog_type == 'releases':
                    catalog_dict = self.game_service.catalog_releases
                else:
                    catalog_dict = self.game_service.catalog_wip
                
                # Search all systems for a unified key matching this base name
                # Pattern: base_name.(ext1|ext2)
                unified_pattern = re.compile(re.escape(base_name) + r'\.\([^|]+\|[^)]+\)$')
                logger.debug(f"Searching for unified key matching pattern: {unified_pattern.pattern}")
                
                found_unified_key = None
                found_unified_key = None
                
                # Only search in the known system
                system_id = download.system_id
                if system_id and system_id in catalog_dict:
                    games = catalog_dict[system_id]
                    for rompath in games.keys():
                        if unified_pattern.match(rompath):
                            # Found the unified key!
                            found_unified_key = rompath
                            logger.info(f"Found unified key '{rompath}' in system '{system_id}' for resolved path '{lookup_game_id}'")
                            break
                
                if found_unified_key:
                    # Look up the game using the unified key and known system
                    game = self.game_service.get_game_by_id(found_unified_key, system_id, catalog_type=catalog_type)
                    if game:
                        # Use this unified key for archive
                        if catalog_type == 'releases' and catalog_version:
                            archive_game_id = f".zfs/snapshot/{catalog_version}/{found_unified_key}"
                        else:
                            archive_game_id = found_unified_key
                        logger.info(f"Using unified key '{archive_game_id}' for archive (original resolved: '{download.game_id}')")
                    else:
                        logger.warning(f"Unified key '{found_unified_key}' found but game lookup failed")
                else:
                    logger.debug(f"Could not find unified key for base_name '{base_name}' in catalog")
            
            # If game was found and archive_game_id is still the resolved path (not unified),
            # check if the game's path field has a unified key
            if game and not is_unified_in_db and archive_game_id == download.game_id:
                # Check if the game in catalog uses a unified key (which should be the original)
                # The catalog game's path field will have the unified key if it was merged
                game_path = game.get('path', '')
                if game_path:
                    # Remove leading ./ if present
                    clean_path = game_path.lstrip('./')
                    # Remove system prefix if present
                    system = game.get('system', '')
                    if system and clean_path.startswith(f"{system}/"):
                        clean_path = clean_path[len(system) + 1:]
                    
                    # Check if this is a unified key
                    import re
                    unified_pattern = r'\.\([^|]+\|[^)]+\)$'
                    if re.search(unified_pattern, clean_path):
                        # This is a unified key - use it instead of the resolved game_id
                        # Reconstruct with snapshot path if it was a releases catalog download
                        if catalog_type == 'releases' and catalog_version:
                            archive_game_id = f".zfs/snapshot/{catalog_version}/{clean_path}"
                        else:
                            archive_game_id = clean_path
                        logger.info(f"Using unified key from game path for archive: '{archive_game_id}' (original resolved: '{download.game_id}')")
            
            # Get game name and system (game should be found by now if it's a unified key)
            if not game:
                logger.warning(f"Game not found for download {download_id} (game_id: {lookup_game_id}, catalog_type: {catalog_type}, version: {catalog_version}), using game_id as game_name")
                game_name = download.game_id
                system = None
            else:
                game_name = game.get('name', download.game_id)
                system = game.get('system', None)
            
            # Get username from User table
            username = None
            user = self.db.query(User).filter(User.user_id == download.user_id).first()
            if user:
                username = user.username
            
            # Sync bytes_transferred from Redis if available (for accurate archive data and P2P statistics)
            # Progress reports update Redis but not the database, so we sync once when archiving
            # This is especially important for P2P downloads where progress is tracked in Redis
            bytes_transferred = download.bytes_transferred or 0
            logger.info(f"Archive download {download_id}: status={download.status}, db_bytes_transferred={bytes_transferred}, syncing from Redis")
            
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                redis_status = await RedisDownloadTracker.get_download_status(download_id)
                if redis_status:
                    redis_bytes = redis_status.get('bytes_transferred', 0)
                    logger.info(f"Archive download {download_id}: Redis returned bytes_transferred={redis_bytes}, db had={bytes_transferred}")
                    if redis_bytes > bytes_transferred:
                        # Redis has more recent data, use it
                        bytes_transferred = redis_bytes
                        # Update database for consistency
                        download.bytes_transferred = redis_bytes
                        self.db.commit()
                        logger.info(f"Synced bytes_transferred from Redis for archive {download_id}: {redis_bytes} bytes")
                    else:
                        logger.info(f"Archive download {download_id}: Using DB value ({bytes_transferred} bytes), Redis had {redis_bytes} bytes")
                else:
                    logger.info(f"Archive download {download_id}: Redis returned no status, using DB value ({bytes_transferred} bytes)")
            except Exception as e:
                logger.warning(f"Could not sync from Redis for archive {download_id}: {e}, using DB value ({bytes_transferred} bytes)")
            
            logger.info(f"Archive download {download_id}: Final bytes_transferred={bytes_transferred} bytes ({bytes_transferred / (1024*1024):.2f} MB)")
            
            # Create archive entry
            archive_entry = DownloadArchive(
                download_id=download.id,
                timestamp=datetime.now(timezone.utc),
                user_id=download.user_id,
                username=username,
                game_name=game_name,
                system=system,
                rompath=archive_game_id,  # Use unified key if available, otherwise use resolved game_id
                download_status=status,
                bytes_transferred=bytes_transferred,  # Use synced value
                file_size=download.file_size,
                catalog_version=download.catalog_version,  # Store catalog version (e.g., "v2-RGS_bbc") for Releases, None for WIP
                client_version=download.client_version  # Store client version (e.g., "0.1")
            )
            
            self.db.add(archive_entry)
            self.db.commit()
            
            logger.info(f"Archived download {download_id} with status '{status}', bytes_transferred: {bytes_transferred}")
            return (True, bytes_transferred)
        except Exception as e:
            logger.error(f"Error archiving download {download_id}: {e}", exc_info=True)
            self.db.rollback()
            return (False, 0)
    
    def get_user_download_history(self, user_id: str, limit: int = 100) -> List[Dict]:
        """Get download history for a specific user from archive."""
        try:
            from app.database import DownloadArchive
            
            # Get archived downloads for this user, ordered by most recent first
            archive_items = self.db.query(DownloadArchive).filter(
                DownloadArchive.user_id == user_id
            ).order_by(DownloadArchive.timestamp.desc()).limit(limit).all()
            
            history = []
            for item in archive_items:
                # Get catalog_version from archive item and derive catalog_type
                catalog_version = item.catalog_version
                catalog_type = 'releases' if catalog_version else 'wip'
                # Remove snapshot path prefix to get original game_id for lookup
                lookup_game_id = item.rompath
                if catalog_type == 'releases' and catalog_version:
                    # Extract original game_id after snapshot path
                    # rompath format: ".zfs/snapshot/v2-RGS_bbc/game.rom"
                    import re
                    escaped_version = re.escape(catalog_version)
                    pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                    match = pattern.match(item.rompath)
                    if match:
                        lookup_game_id = match.group(1)
                
                # Get game information if available
                system_id = item.system
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type) if (lookup_game_id and system_id) else None
                
                history_item = {
                    'id': item.id,
                    'download_id': item.download_id,
                    'game_name': item.game_name,
                    'system': item.system or '',
                    'system_name': self.game_service.get_system_name(item.system) if item.system else '',
                    'rompath': item.rompath,
                    'status': item.download_status,
                    'bytes_transferred': item.bytes_transferred or 0,
                    'file_size': item.file_size,
                    'timestamp': item.timestamp.isoformat() if item.timestamp else None,
                    'image': '',
                    'catalog_version': catalog_version,  # Include catalog version (e.g., "v2-RGS_bbc")
                    'client_version': item.client_version  # Include client version (e.g., "0.1")
                }
                
                # Add game image if available
                if game:
                    history_item['image'] = self._normalize_media_path_for_frontend(
                        game.get('image', ''), 
                        game.get('system', '')
                    )
                
                history.append(history_item)
            
            return history
        except Exception as e:
            logger.error(f"Error getting download history for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def get_all_download_history(self, limit: int = 100) -> List[Dict]:
        """Get download history for all users from archive (admin only)."""
        try:
            from app.database import DownloadArchive
            
            # Get all archived downloads, ordered by most recent first
            archive_items = self.db.query(DownloadArchive).order_by(
                DownloadArchive.timestamp.desc()
            ).limit(limit).all()
            
            history = []
            for item in archive_items:
                # Get catalog_version from archive item and derive catalog_type
                catalog_version = item.catalog_version
                catalog_type = 'releases' if catalog_version else 'wip'
                # Remove snapshot path prefix to get original game_id for lookup
                lookup_game_id = item.rompath
                if catalog_type == 'releases' and catalog_version:
                    # Extract original game_id after snapshot path
                    # rompath format: ".zfs/snapshot/v2-RGS_bbc/game.rom"
                    import re
                    escaped_version = re.escape(catalog_version)
                    pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                    match = pattern.match(item.rompath)
                    if match:
                        lookup_game_id = match.group(1)
                
                # Get game information if available
                system_id = item.system
                game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type) if (lookup_game_id and system_id) else None
                
                history_item = {
                    'id': item.id,
                    'download_id': item.download_id,
                    'user_id': item.user_id,  # Include user_id for admin view
                    'username': item.username or item.user_id,  # Include username (fallback to user_id if not available)
                    'game_name': item.game_name,
                    'system': item.system or '',
                    'system_name': self.game_service.get_system_name(item.system) if item.system else '',
                    'rompath': item.rompath,
                    'status': item.download_status,
                    'bytes_transferred': item.bytes_transferred or 0,
                    'file_size': item.file_size,
                    'timestamp': item.timestamp.isoformat() if item.timestamp else None,
                    'image': '',
                    'catalog_version': catalog_version,  # Include catalog version (e.g., "v2-RGS_bbc")
                    'client_version': item.client_version  # Include client version (e.g., "0.1")
                }
                
                # Add game image if available
                if game:
                    history_item['image'] = self._normalize_media_path_for_frontend(
                        game.get('image', ''), 
                        game.get('system', '')
                    )
                
                history.append(history_item)
            
            return history
        except Exception as e:
            logger.error(f"Error getting all download history: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def remove_download(self, download_id: int) -> bool:
        """Remove download from queue without updating statistics (e.g., when file doesn't exist)."""
        try:
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Check if this is a P2P download and notify remote peer
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                from app.services.websocket_manager import get_websocket_manager
                
                # Get p2p_remote_token_id from Redis before removing
                p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(download_id)
                
                if p2p_remote_token_id:
                    logger.info(f"Download {download_id} cancelled: Notifying remote peer token_id={p2p_remote_token_id}")
                    ws_manager = get_websocket_manager()
                    notification_sent = await ws_manager.send_notification(
                        p2p_remote_token_id,
                        {
                            "type": "p2p_download_cancelled",
                            "download_id": download_id,
                            "message": "Download was cancelled by the downloading client"
                        }
                    )
                    if notification_sent:
                        logger.info(f"Sent cancellation notification to remote peer token_id={p2p_remote_token_id} for download_id={download_id}")
                    else:
                        logger.warning(f"Failed to send cancellation notification to remote peer token_id={p2p_remote_token_id} (not connected)")
                
                # Remove from Redis
                await RedisDownloadTracker.remove_download(download_id)
            except Exception as e:
                logger.warning(f"Error notifying remote peer or removing from Redis: {e}")
            
            # Archive the download before deletion
            await self.archive_download(download_id, 'cancelled')
            
            # Delete the download without updating statistics
            self.db.delete(download)
            self.db.commit()
            
            logger.info(f"Removed download {download_id} from queue (file not found or invalid)")
            return True
        except Exception as e:
            logger.error(f"Error removing download: {e}")
            self.db.rollback()
            return False
    
    def store_download_log(self, download_id: int, log_content: str) -> bool:
        """Store download log to a file.
        
        Args:
            download_id: Download ID
            log_content: Log content as string
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create download_logs directory in data folder
            from app.config import settings
            from pathlib import Path
            
            # Determine data directory path
            if hasattr(settings, 'DATABASE_URL') and settings.DATABASE_URL:
                # Extract data directory from database URL if possible
                db_path = settings.DATABASE_URL.replace('sqlite:///', '')
                if db_path.startswith('./'):
                    project_root = Path(__file__).parent.parent.parent
                    data_dir = project_root / db_path[2:].split('/')[0]
                elif not os.path.isabs(db_path):
                    project_root = Path(__file__).parent.parent.parent
                    data_dir = project_root / db_path.split('/')[0]
                else:
                    data_dir = Path(db_path).parent
            else:
                # Fallback to backend/data
                data_dir = Path(__file__).parent.parent / 'data'
            
            # Create download_logs subdirectory
            log_dir = data_dir / 'download_logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # Write log to file
            log_file = log_dir / f'queue_{download_id}.log'
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(log_content)
            
            logger.info(f"Stored download log for download {download_id} to {log_file}")
            return True
        except Exception as e:
            logger.error(f"Error storing download log for {download_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def get_download_log(self, download_id: int) -> Optional[str]:
        """Retrieve download log from file.
        
        Args:
            download_id: Download ID
            
        Returns:
            str: Log content if found, None otherwise
        """
        try:
            from app.config import settings
            from pathlib import Path
            
            # Determine data directory path (same logic as store_download_log)
            if hasattr(settings, 'DATABASE_URL') and settings.DATABASE_URL:
                db_path = settings.DATABASE_URL.replace('sqlite:///', '')
                if db_path.startswith('./'):
                    project_root = Path(__file__).parent.parent.parent
                    data_dir = project_root / db_path[2:].split('/')[0]
                elif not os.path.isabs(db_path):
                    project_root = Path(__file__).parent.parent.parent
                    data_dir = project_root / db_path.split('/')[0]
                else:
                    data_dir = Path(db_path).parent
            else:
                data_dir = Path(__file__).parent.parent / 'data'
            
            # Read log file
            log_file = data_dir / 'download_logs' / f'queue_{download_id}.log'
            
            if not log_file.exists():
                logger.debug(f"Log file not found for download {download_id}")
                return None
            
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return content
        except Exception as e:
            logger.error(f"Error reading download log for {download_id}: {e}")
            return None
    
    async def complete_download(self, download_id: int) -> bool:
        """Remove download from queue and update user download statistics.
        
        After completion, checks if there are more items in user_queue for the same token_id
        and promotes one if no active downloads remain, then sends WebSocket notification.
        
        p2p_remote_token_id is read directly from Redis (where client stored it at P2P start).
        
        Args:
            download_id: ID of the download to complete
        """
        try:
            from app.database import User, ApiToken
            from app.services.websocket_manager import get_websocket_manager
            from sqlalchemy import func
            
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Store info before deletion
            user_id = download.user_id
            game_id = download.game_id
            token_id = download.token_id
            catalog_version = download.catalog_version
            
            # Get p2p_remote_token_id from Redis (client stores it at the start of P2P download)
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                p2p_remote_token_id = await RedisDownloadTracker.get_p2p_remote_token_id(download_id)
                logger.info(f"Complete download {download_id}: p2p_remote_token_id={p2p_remote_token_id} from Redis")
            except Exception as e:
                logger.warning(f"Complete download {download_id}: Failed to get p2p_remote_token_id from Redis: {e}")
                p2p_remote_token_id = None
            
            # Archive the download (will sync bytes_transferred from Redis)
            archive_success, downloaded_bytes = await self.archive_download(download_id, 'completed')
            if not archive_success:
                logger.warning(f"Failed to archive download {download_id}, but continuing with completion")
            
            # Calculate downloaded MB (convert bytes to MB: 1 MB = 1024 * 1024 bytes)
            downloaded_mb = downloaded_bytes / (1024 * 1024)
            logger.info(f"Complete download {download_id}: downloaded_bytes={downloaded_bytes} ({downloaded_mb:.2f} MB)")
            
            # Handle P2P traffic tracking if this was a P2P download
            # Validate p2p_remote_token_id is an actual integer token ID (not True/False)
            if p2p_remote_token_id is not None and isinstance(p2p_remote_token_id, int) and p2p_remote_token_id > 0:
                logger.info(f"Complete download {download_id}: Processing P2P stats - downloading_token_id={token_id}, serving_token_id={p2p_remote_token_id}, downloaded_mb={downloaded_mb:.2f}")
                try:
                    # Update target token (downloading client) - add to p2p_total_download_mb
                    target_token = self.db.query(ApiToken).filter(ApiToken.id == token_id).first()
                    if target_token:
                        old_value = target_token.p2p_total_download_mb or 0.0
                        target_token.p2p_total_download_mb += downloaded_mb
                        self.db.commit()
                        logger.info(f"Updated target token {token_id} p2p_total_download_mb: {old_value:.2f} -> {target_token.p2p_total_download_mb:.2f} MB (+{downloaded_mb:.2f} MB)")
                    else:
                        logger.warning(f"Target token {token_id} not found for P2P download tracking")
                    
                    # Update remote token (peer serving the file) - add to p2p_total_upload_mb
                    remote_token = self.db.query(ApiToken).filter(ApiToken.id == p2p_remote_token_id).first()
                    if remote_token:
                        old_value = remote_token.p2p_total_upload_mb or 0.0
                        remote_token.p2p_total_upload_mb += downloaded_mb
                        self.db.commit()
                        logger.info(f"Updated remote token {p2p_remote_token_id} p2p_total_upload_mb: {old_value:.2f} -> {remote_token.p2p_total_upload_mb:.2f} MB (+{downloaded_mb:.2f} MB)")
                    else:
                        logger.warning(f"Remote token {p2p_remote_token_id} not found for P2P upload tracking")
                    
                    # Update user statistics by summing all their tokens' P2P traffic
                    # For target user (downloading client)
                    target_user_tokens = self.db.query(ApiToken).filter(ApiToken.user_id == user_id).all()
                    target_user_download_mb = sum(token.p2p_total_download_mb or 0.0 for token in target_user_tokens)
                    target_user_upload_mb = sum(token.p2p_total_upload_mb or 0.0 for token in target_user_tokens)
                    
                    user = self.db.query(User).filter(User.user_id == user_id).first()
                    if user:
                        old_download = user.p2p_total_download_mb or 0.0
                        old_upload = user.p2p_total_upload_mb or 0.0
                        user.p2p_total_download_mb = target_user_download_mb
                        user.p2p_total_upload_mb = target_user_upload_mb
                        self.db.commit()
                        logger.info(f"Updated target user {user_id} P2P totals: download {old_download:.2f} -> {target_user_download_mb:.2f} MB, upload {old_upload:.2f} -> {target_user_upload_mb:.2f} MB")
                    
                    # For remote user (peer serving the file)
                    if remote_token:
                        remote_user_id = remote_token.user_id
                        remote_user_tokens = self.db.query(ApiToken).filter(ApiToken.user_id == remote_user_id).all()
                        remote_user_download_mb = sum(token.p2p_total_download_mb or 0.0 for token in remote_user_tokens)
                        remote_user_upload_mb = sum(token.p2p_total_upload_mb or 0.0 for token in remote_user_tokens)
                        
                        remote_user = self.db.query(User).filter(User.user_id == remote_user_id).first()
                        if remote_user:
                            old_download = remote_user.p2p_total_download_mb or 0.0
                            old_upload = remote_user.p2p_total_upload_mb or 0.0
                            remote_user.p2p_total_download_mb = remote_user_download_mb
                            remote_user.p2p_total_upload_mb = remote_user_upload_mb
                            self.db.commit()
                            logger.info(f"Updated remote user {remote_user_id} P2P totals: download {old_download:.2f} -> {remote_user_download_mb:.2f} MB, upload {old_upload:.2f} -> {remote_user_upload_mb:.2f} MB")
                        else:
                            # Create user record if it doesn't exist
                            remote_user = User(
                                user_id=remote_user_id,
                                p2p_total_download_mb=remote_user_download_mb,
                                p2p_total_upload_mb=remote_user_upload_mb,
                                created_at=datetime.now(timezone.utc),
                                updated_at=datetime.now(timezone.utc)
                            )
                            self.db.add(remote_user)
                            logger.info(f"Created remote user {remote_user_id} with P2P totals: download={remote_user_download_mb:.2f} MB, upload={remote_user_upload_mb:.2f} MB")
                except Exception as e:
                    logger.error(f"Error tracking P2P traffic: {e}", exc_info=True)
                    # Don't fail the download completion if P2P tracking fails
            else:
                if p2p_remote_token_id is None:
                    logger.info(f"Complete download {download_id}: Not a P2P download (p2p_remote_token_id is None), skipping P2P stats")
                elif not isinstance(p2p_remote_token_id, int):
                    logger.warning(f"Complete download {download_id}: Invalid p2p_remote_token_id type: {type(p2p_remote_token_id).__name__} (value: {p2p_remote_token_id}), skipping P2P stats")
                elif p2p_remote_token_id <= 0:
                    logger.warning(f"Complete download {download_id}: Invalid p2p_remote_token_id value: {p2p_remote_token_id} (must be > 0), skipping P2P stats")
            
            # Update or create user statistics
            user = self.db.query(User).filter(
                User.user_id == user_id
            ).first()
            
            if user:
                # Update existing user
                user.total_download_mb += downloaded_mb
                user.total_download_number += 1
                user.updated_at = datetime.now(timezone.utc)
                logger.info(f"Updated user {user_id} total_download_mb: {user.total_download_mb:.2f} MB (+{downloaded_mb:.2f} MB), total_download_number: {user.total_download_number}")
            else:
                # Create new user record
                user = User(
                    user_id=user_id,
                    total_download_mb=downloaded_mb,
                    total_download_number=1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                self.db.add(user)
                logger.info(f"Created new user record for {user_id} with {downloaded_mb:.2f} MB, total_download_number: 1")
            
            # Remove from Redis before deletion (archive_download already synced from Redis)
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                await RedisDownloadTracker.remove_download(download_id)
            except Exception as e:
                logger.debug(f"Failed to remove download from Redis: {e}")
            
            # Register token_id in p2p_index for the downloaded ROM
            try:
                from app.services.p2p_inventory import P2PInventoryService
                
                # Determine catalog_type from catalog_version
                catalog_type = 'releases' if catalog_version else 'wip'
                
                # Look up the game to get system
                lookup_game_id = game_id
                if catalog_type == 'releases' and catalog_version:
                    # Remove snapshot path prefix to get original game_id for lookup
                    import re
                    escaped_version = re.escape(catalog_version)
                    pattern = re.compile(r'\.zfs/snapshot/' + escaped_version + r'/(.*)')
                    match = pattern.match(game_id)
                    if match:
                        lookup_game_id = match.group(1)
                
                # Get game to extract system
                # Use stored system_id
                system_id = download.system_id
                if system_id:
                    game = self.game_service.get_game_by_id(lookup_game_id, system_id, catalog_type=catalog_type)
                    if game:
                        system = game.get('system', '')
                        if system:
                            # Extract rom_path from game_id
                            # Remove snapshot path if present
                            rom_path = self._remove_snapshot_path_from_game_id(game_id, catalog_version)
                            # Remove system prefix if present (game_id might be "system/rom.rom" or "./rom.rom")
                            if rom_path.startswith(f"{system}/"):
                                rom_path = rom_path[len(system) + 1:]
                            # Remove leading "./" if present
                            rom_path = rom_path.lstrip('./')
                            
                            # Register token_id in p2p_index
                            inventory = {system: [rom_path]}
                            success = await P2PInventoryService.update_inventory(token_id, inventory)
                            if success:
                                logger.info(f"Registered token_id {token_id} in p2p_index for {system}/{rom_path}")
                            else:
                                logger.warning(f"Failed to register token_id {token_id} in p2p_index for {system}/{rom_path}")
                        else:
                            logger.warning(f"Game found but system is empty for game_id: {lookup_game_id}")
                    else:
                        logger.warning(f"Game not found for game_id: {lookup_game_id}, cannot register in p2p_index")
                else:
                    logger.warning(f"Could not find system for game: {lookup_game_id}")
            except Exception as e:
                logger.error(f"Error registering token_id in p2p_index: {e}", exc_info=True)
                # Don't fail the download completion if p2p_index registration fails
            
            # Delete the download from queue instead of marking as completed
            self.db.delete(download)
            self.db.commit()
            
            logger.info(f"Download {download_id} completed and removed from queue. User {user_id} total: {user.total_download_mb:.2f} MB, {user.total_download_number} games")
            
            # Check if there are more items in user_queue for this token_id
            # and promote one if no active downloads remain
            if token_id:
                try:
                    # Check if there are any active downloads for this token_id
                    has_active = self.db.query(DownloadQueue).filter(
                        and_(
                            DownloadQueue.token_id == token_id,
                            DownloadQueue.active_download == True,
                            DownloadQueue.status == 'downloading'
                        )
                    ).first()
                    
                    if not has_active:
                        # No active downloads - check for items in user_queue
                        user_queue_items = self.db.query(DownloadQueue).filter(
                            and_(
                                DownloadQueue.status == 'user_queue',
                                DownloadQueue.token_id == token_id
                            )
                        ).order_by(DownloadQueue.created_at.asc()).all()
                        
                        if user_queue_items:
                            # Item stays in user_queue - will be picked up by get_next_download
                            # No need to change status - get_next_download now looks for user_queue items directly
                            item_to_promote = user_queue_items[0]
                            self.db.commit()  # Ensure any pending changes are committed
                            logger.info(f"Download completed, next user_queue item {item_to_promote.id} (token_id: {token_id}, queue_type: {item_to_promote.queue_type}) will be picked up by get_next_download")
                            
                            # Send WebSocket notification
                            ws_manager = get_websocket_manager()
                            await ws_manager.send_notification(token_id, {
                                "type": "download_available",
                                "queue_type": item_to_promote.queue_type
                            })
                            logger.info(f"Sent download_available notification to token_id {token_id} for queue_type {item_to_promote.queue_type} after download completion")
                except Exception as e:
                    logger.error(f"Error promoting user_queue item after download completion: {e}", exc_info=True)
                    # Don't fail the completion if promotion fails
                    pass
            
            return True
        except Exception as e:
            logger.error(f"Error completing download: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False
    
    async def mark_download_error(self, download_id: int, error_message: str) -> bool:
        """Mark a download as error and remove it from the queue."""
        try:
            from app.services.websocket_manager import get_websocket_manager
            
            download = self.db.query(DownloadQueue).filter(
                DownloadQueue.id == download_id
            ).first()
            
            if not download:
                logger.warning(f"Download {download_id} not found")
                return False
            
            # Store info before deletion
            token_id = download.token_id
            game_id = download.game_id
            user_id = download.user_id
            
            logger.error(f"Download {download_id} (game: {game_id}) failed with error: {error_message}")
            
            # Archive the download with error status before deletion
            await self.archive_download(download_id, 'error')
            
            # Remove from Redis before deletion
            try:
                from app.services.redis_downloads import RedisDownloadTracker
                await RedisDownloadTracker.remove_download(download_id)
            except Exception as e:
                logger.debug(f"Failed to remove download from Redis: {e}")
            
            # Delete the download from queue
            self.db.delete(download)
            self.db.commit()
            
            logger.info(f"Download {download_id} marked as error and removed from queue")
            
            # Check if there are more items in user_queue for this token_id
            # and promote one if no active downloads remain
            if token_id:
                try:
                    # Check if there are any active downloads for this token_id
                    has_active = self.db.query(DownloadQueue).filter(
                        and_(
                            DownloadQueue.token_id == token_id,
                            DownloadQueue.active_download == True,
                            DownloadQueue.status == 'downloading'
                        )
                    ).first()
                    
                    if not has_active:
                        # No active downloads - check for items in user_queue
                        user_queue_items = self.db.query(DownloadQueue).filter(
                            and_(
                                DownloadQueue.status == 'user_queue',
                                DownloadQueue.token_id == token_id
                            )
                        ).order_by(DownloadQueue.created_at.asc()).all()
                        
                        if user_queue_items:
                            # Item stays in user_queue - will be picked up by get_next_download
                            # No need to change status - get_next_download now looks for user_queue items directly
                            item_to_promote = user_queue_items[0]
                            self.db.commit()  # Ensure any pending changes are committed
                            logger.info(f"Download error, next user_queue item {item_to_promote.id} (token_id: {token_id}, queue_type: {item_to_promote.queue_type}) will be picked up by get_next_download")
                            
                            # Send WebSocket notification
                            ws_manager = get_websocket_manager()
                            await ws_manager.send_notification(token_id, {
                                "type": "download_available",
                                "queue_type": item_to_promote.queue_type
                            })
                            logger.info(f"Sent download_available notification to token_id {token_id} for queue_type {item_to_promote.queue_type} after download error")
                except Exception as e:
                    logger.error(f"Error promoting user_queue item after download error: {e}", exc_info=True)
                    # Don't fail the error marking if promotion fails
                    pass
            
            return True
        except Exception as e:
            logger.error(f"Error marking download as error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.db.rollback()
            return False

