"""Game catalog service for parsing gamelist.xml files."""
import os
import io
import xml.etree.ElementTree as ET
import logging
import pickle
import hashlib
import time
from typing import List, Dict, Optional, Tuple
import re
from pathlib import Path
import tarfile
import tempfile
import shutil
from sqlalchemy import func
from app.config import settings
from app.services.game_utils import normalize_game_name
from app.database import SessionLocal, DownloadArchive

logger = logging.getLogger(__name__)

def _is_game_hidden(game: ET.Element) -> bool:
    """Check if a game is hidden by checking both attribute and element.
    
    Supports both formats:
    - <game hidden="true">...</game> (attribute)
    - <game><hidden>true</hidden></game> (element)
    
    Args:
        game: XML Element representing a game
        
    Returns:
        bool: True if the game is hidden, False otherwise
    """
    # Check attribute first (most common format)
    hidden_attr = game.get('hidden', '').lower()
    if hidden_attr in ['true', '1']:
        return True
    
    # Check element (alternative format: <hidden>true</hidden>)
    hidden_elem = game.findtext('hidden', '').lower()
    if hidden_elem in ['true', '1']:
        return True
    
    return False

def _is_folder_hidden(folder: ET.Element) -> bool:
    """Check if a folder is hidden by checking both attribute and element.
    
    Supports both formats:
    - <folder hidden="true">...</folder> (attribute)
    - <folder><hidden>true</hidden></folder> (element)
    
    Args:
        folder: XML Element representing a folder
        
    Returns:
        bool: True if the folder is hidden, False otherwise
    """
    # Check attribute first (most common format)
    hidden_attr = folder.get('hidden', '').lower()
    if hidden_attr in ['true', '1']:
        return True
    
    # Check element (alternative format: <hidden>true</hidden>)
    hidden_elem = folder.findtext('hidden', '').lower()
    if hidden_elem in ['true', '1']:
        return True
    
    return False

class GameService:
    """Service for managing game catalog from gamelist.xml files."""
    
    def __init__(self, games_path: Optional[str] = None):
        self.games_path = games_path or settings.GAMES_PATH
        self.cache = {}
        # Dual catalog structures: WIP (current) and Releases (versioned)
        self.search_index_wip = {}  # Partitioned search index for WIP catalog
        self.search_index_releases = {}  # Partitioned search index for Releases catalog
        self._index_built_wip = False
        self._index_built_releases = False
        self.catalog_wip = {}  # Pre-processed catalog: catalog[system_id][rompath] = {game fields dict}
        self.catalog_releases = {}  # Pre-processed catalog for Releases
        self.catalog_sorted_keys_wip = {}  # Pre-sorted rompaths per system for WIP
        self.catalog_sorted_keys_releases = {}  # Pre-sorted rompaths per system for Releases
        # catalog_responses removed - responses built on-demand from catalog data to save memory
        self.systems_list = []  # Cached systems list with game counts
        self._gamelists_loaded = False
        self.system_hardware = {}  # Cache: system_id -> hardware category
        self.system_manufacturer = {}  # Cache: system_id -> manufacturer
        self.system_release = {}  # Cache: system_id -> release year
        self.system_fullname = {}  # Cache: system_id -> full name
        self.subdirectory_counts_wip = {}  # Cache: system_id -> {subdirectory: count} for WIP
        self.subdirectory_counts_releases = {}  # Cache: system_id -> {subdirectory: count} for Releases
        self._catalog_timestamp = None  # Timestamp when catalog was last loaded/refreshed for ETag generation
        self.system_versions = {}  # Stores latest version per system: {system_id: "v10.5"}
        self.system_snapshot_paths = {}  # Stores snapshot directory path per system: {system_id: ".zfs/snapshot/v10.5/"}
        self.system_gamelist_date_wip = {}  # Cache: system_id -> gamelist.xml modification date (dd-mm-yyyy) for WIP
        self.system_gamelist_date_releases = {}  # Cache: system_id -> gamelist.xml modification date (dd-mm-yyyy) for Releases
        
        # Track file modification times for auto-reload across workers
        self._catalog_file_mtime = None  # Modification time of catalog.pkl when last loaded
        self._index_file_mtime = None  # Modification time of search_index.pkl when last loaded
        
        # System name mapping
        self.system_names = {
            '3do': '3DO',
            'amiga': 'Amiga',
            'amigacd32': 'Amiga CD32',
            'amstradcpc': 'Amstrad CPC',
            'apple2': 'Apple II',
            'arcade': 'Arcade',
            'atari2600': 'Atari 2600',
            'atari5200': 'Atari 5200',
            'atari7800': 'Atari 7800',
            'atarijaguar': 'Atari Jaguar',
            'atarilynx': 'Atari Lynx',
            'atarist': 'Atari ST',
            'c64': 'Commodore 64',
            'colecovision': 'ColecoVision',
            'dreamcast': 'Dreamcast',
            'fba': 'Final Burn Alpha',
            'fds': 'Famicom Disk System',
            'gameandwatch': 'Game & Watch',
            'gamegear': 'Game Gear',
            'gb': 'Game Boy',
            'gba': 'Game Boy Advance',
            'gbc': 'Game Boy Color',
            'gc': 'GameCube',
            'genesis': 'Sega Genesis',
            'gw': 'Game & Watch',
            'intellivision': 'Intellivision',
            'mame': 'MAME',
            'mastersystem': 'Master System',
            'megadrive': 'Mega Drive',
            'msx': 'MSX',
            'msx1': 'MSX1',
            'msx2': 'MSX2',
            'n64': 'Nintendo 64',
            'nds': 'Nintendo DS',
            'neogeo': 'Neo Geo',
            'neogeocd': 'Neo Geo CD',
            'nes': 'NES',
            'ngp': 'Neo Geo Pocket',
            'ngpc': 'Neo Geo Pocket Color',
            'pc': 'PC',
            'pcengine': 'PC Engine',
            'pcenginecd': 'PC Engine CD',
            'pico': 'Sega Pico',
            'pokemini': 'Pokemon Mini',
            'psp': 'PlayStation Portable',
            'psx': 'PlayStation',
            'ps2': 'PlayStation 2',
            'ps3': 'PlayStation 3',
            'saturn': 'Sega Saturn',
            'scummvm': 'ScummVM',
            'sega32x': 'Sega 32X',
            'segacd': 'Sega CD',
            'sg1000': 'SG-1000',
            'snes': 'Super Nintendo',
            'supergrafx': 'SuperGrafx',
            'tg16': 'TurboGrafx-16',
            'tg16cd': 'TurboGrafx-CD',
            'vectrex': 'Vectrex',
            'virtualboy': 'Virtual Boy',
            'wii': 'Nintendo Wii',
            'wiiu': 'Nintendo Wii U',
            'wonderswan': 'WonderSwan',
            'wonderswancolor': 'WonderSwan Color',
            'x68000': 'X68000',
            'zxspectrum': 'ZX Spectrum'
        }
    
    def _find_latest_versioned_gamelist(self, system_path: str) -> Optional[Tuple[str, str, str]]:
        """Find the latest versioned gamelist.xml in .zfs/snapshot/ directories.
        
        Pattern: GAMES_PATH/<system>/.zfs/snapshot/v(\d+)(\S+)/gamelist.xml
        Comparison: Numeric comparison of first number group (e.g., v2024 > v10 > v2 > v1)
        
        Args:
            system_path: Path to the system directory
            
        Returns:
            Tuple of (version_string, snapshot_dir_path, gamelist_path) or None if no versioned gamelist found
            snapshot_dir_path is relative to system_path (e.g., ".zfs/snapshot/v10.5/")
        """
        snapshot_dir = os.path.join(system_path, '.zfs', 'snapshot')
        if not os.path.isdir(snapshot_dir):
            return None
        
        version_pattern = re.compile(r'^v(\d+)(\S*)$')
        found_versions = []
        
        try:
            for entry in os.listdir(snapshot_dir):
                entry_path = os.path.join(snapshot_dir, entry)
                if not os.path.isdir(entry_path):
                    continue
                
                # Match version pattern: v(\d+)(\S+)
                match = version_pattern.match(entry)
                if not match:
                    continue
                
                version_num_str = match.group(1)
                version_suffix = match.group(2)
                
                gamelist_path = os.path.join(entry_path, 'gamelist.xml')
                if not os.path.isfile(gamelist_path):
                    continue
                
                try:
                    version_num = int(version_num_str)
                    # Store snapshot directory path relative to system_path
                    snapshot_dir_path = os.path.join('.zfs', 'snapshot', entry)
                    found_versions.append((version_num, entry, snapshot_dir_path, gamelist_path))
                except ValueError:
                    logger.warning(f"Could not parse version number from '{entry}' for system {os.path.basename(system_path)}")
                    continue
            
            if not found_versions:
                return None
            
            # Sort by version number (descending) and return the latest
            found_versions.sort(key=lambda x: x[0], reverse=True)
            latest_version_num, latest_version_str, latest_snapshot_dir_path, latest_gamelist_path = found_versions[0]
            logger.info(f"Found latest versioned gamelist for {os.path.basename(system_path)}: {latest_version_str} at {latest_gamelist_path}")
            return (latest_version_str, latest_snapshot_dir_path, latest_gamelist_path)
        except Exception as e:
            logger.error(f"Error finding versioned gamelist in {snapshot_dir}: {e}")
            return None
    
    def _load_catalog_from_gamelist(self, system_id: str, gamelist_path: str, catalog_type: str, snapshot_dir_path: Optional[str] = None) -> int:
        """Load catalog from a gamelist.xml file for a specific system.
        
        Args:
            system_id: System identifier
            gamelist_path: Path to the gamelist.xml file
            catalog_type: 'wip' or 'releases'
            snapshot_dir_path: Snapshot directory path relative to system directory (e.g., ".zfs/snapshot/v10.5/") for Releases catalog
            
        Returns:
            Number of games loaded
        """
        # Select appropriate catalog structures based on catalog_type
        if catalog_type == 'wip':
            catalog = self.catalog_wip
            catalog_sorted_keys = self.catalog_sorted_keys_wip
            subdirectory_counts = self.subdirectory_counts_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
            catalog_sorted_keys = self.catalog_sorted_keys_releases
            subdirectory_counts = self.subdirectory_counts_releases
        else:
            raise ValueError(f"Invalid catalog_type: {catalog_type}. Must be 'wip' or 'releases'")
        
        UTF8_BOM = b'\xef\xbb\xbf'
        with open(gamelist_path, 'rb') as _f:
            raw = _f.read()
        while raw.startswith(UTF8_BOM):
            raw = raw[len(UTF8_BOM):]
        tree = ET.parse(io.BytesIO(raw))
        root = tree.getroot()
        
        # Initialize catalog entry for this system
        catalog[system_id] = {}
        
        # Helper function to normalize media path
        def normalize_media_path(path_value: str) -> str:
            """Normalize media path by adding system prefix and snapshot path if needed.
            
            For WIP: returns {system_id}/{media_path}
            For Releases: returns {system_id}/{snapshot_dir_path}/{media_path}
            """
            if not path_value:
                return ''
            path = path_value.lstrip('./')
            
            # For Releases catalog, prepend snapshot directory path
            if catalog_type == 'releases' and snapshot_dir_path:
                # snapshot_dir_path is already in format ".zfs/snapshot/v10.5/" (with leading dot)
                # Just ensure it ends with / for proper joining, but keep the leading dot
                snapshot_path = snapshot_dir_path
                if not snapshot_path.endswith('/'):
                    snapshot_path += '/'
                # Path format: {system_id}/{snapshot_path}{media_path}
                # e.g., "c64/.zfs/snapshot/v10.5/media/image.png"
                # Remove system prefix if already present (media_path from XML is relative to system directory)
                if path.startswith(f"{system_id}/"):
                    path = path[len(system_id) + 1:]
                return f"{system_id}/{snapshot_path}{path}"
            else:
                # For WIP, ensure system prefix is present
                # media_path from XML is relative to system directory, so we add system_id prefix
                if path.startswith(f"{system_id}/"):
                    # Already has system prefix, return as-is
                    return path
                else:
                    # Add system prefix
                    return f"{system_id}/{path}"
        
        # Count games (excluding hidden ones)
        game_count = 0
        games_list = []  # Temporary list for sorting
        
        for game in root.findall('.//game'):
            # Skip hidden games
            if _is_game_hidden(game):
                continue
            
            # Get rompath (game path)
            rompath = game.findtext('path', '').lstrip('./')
            if not rompath:
                continue
            
            # Build game data dictionary with all fields from XML
            # Store ALL fields exactly as they appear in XML without any normalization
            # Skip playcount and gametime fields - these are only aggregated from user gamelists
            game_data = {}
            for child in game:
                tag = child.tag
                # Skip playcount and gametime - these are only from user gamelists
                if tag in ('playcount', 'gametime'):
                    continue
                text = child.text or ''
                game_data[tag] = text
            
            # Ensure 'path' field exists (use rompath - already stripped of './' prefix for lookup)
            # Store original path from XML if available, otherwise use rompath
            if 'path' in game_data and game_data['path']:
                # Keep the original path from XML as-is
                pass  # Already set from XML
            else:
                # Fallback to rompath if path field wasn't in XML (shouldn't happen)
                game_data['path'] = rompath
            
            # Pre-compute catalog_image with priority: thumbnail > boxart > extra1 > image
            # Use original field values (as stored from XML)
            thumbnail = game_data.get('thumbnail', '')
            boxart = game_data.get('boxart', '')
            extra1 = game_data.get('extra1', '')
            image = game_data.get('image', '')
            
            # Select best image using priority (using original values from XML)
            if thumbnail:
                catalog_image = thumbnail
            elif boxart:
                catalog_image = boxart
            elif extra1:
                catalog_image = extra1
            elif image:
                catalog_image = image
            else:
                catalog_image = ''
            
            # Add pre-computed catalog_image to game_data
            game_data['catalog_image'] = catalog_image
            
            # Store in catalog: catalog[system][rompath] = game_data
            catalog[system_id][rompath] = game_data
            games_list.append((rompath, game_data))
            game_count += 1
        
        # Pre-sort games by name (case-insensitive) and store sorted keys
        games_list.sort(key=lambda x: x[1].get('name', '').lower())
        catalog_sorted_keys[system_id] = [rompath for rompath, _ in games_list]
        
        # Compute subdirectory counts (pre-compute during catalog build)
        # First pass: collect all hidden folder paths
        hidden_directories = set()
        for folder in root.findall('.//folder'):
            if _is_folder_hidden(folder):
                folder_path = folder.findtext('path', '')
                if folder_path:
                    # Normalize the path
                    path = folder_path.lstrip('./')
                    if path.startswith(f"{system_id}/"):
                        path = path[len(system_id) + 1:]
                    # Remove trailing slash if present
                    path = path.rstrip('/')
                    hidden_directories.add(path)
        
        # Second pass: count games by subdirectory, skipping games in hidden directories
        subdirectory_counts_dict = {}
        for rompath, game_data in games_list:
            # Check if game is inside a hidden directory
            subdir = self._get_game_subdirectory(rompath, system_id)
            if subdir:
                # Check if subdirectory matches any hidden directory or is nested inside one
                is_in_hidden_dir = False
                for hidden_dir in hidden_directories:
                    if subdir == hidden_dir or subdir.startswith(hidden_dir + '/'):
                        # Game is inside a hidden directory, skip it
                        is_in_hidden_dir = True
                        break
                if is_in_hidden_dir:
                    continue
            
            key = subdir if subdir else '(root)'
            subdirectory_counts_dict[key] = subdirectory_counts_dict.get(key, 0) + 1
        
        # Store pre-computed subdirectory counts
        subdirectory_counts[system_id] = subdirectory_counts_dict
        
        # catalog_responses removed - responses built on-demand to save memory
        
        return game_count
    
    def _get_rom_filename_without_ext(self, rompath: str) -> str:
        """Extract base filename without extension from ROM path.
        
        Args:
            rompath: ROM path (e.g., "path/to/game.zip" or "game.bin")
            
        Returns:
            str: Base path without extension (e.g., "path/to/game" or "game")
        """
        if not rompath:
            return rompath
        
        # Remove leading ./ if present
        clean_path = rompath.lstrip('./')
        
        # Split path and filename
        if '/' in clean_path:
            dir_part = clean_path.rsplit('/', 1)[0]
            filename_part = clean_path.rsplit('/', 1)[1]
        else:
            dir_part = ''
            filename_part = clean_path
        
        # Remove extension from filename
        if '.' in filename_part:
            filename_no_ext = filename_part.rsplit('.', 1)[0]
        else:
            filename_no_ext = filename_part
        
        # Reconstruct path
        if dir_part:
            return f"{dir_part}/{filename_no_ext}"
        else:
            return filename_no_ext
    
    def _create_unified_rom_key(self, base_path: str, batocera_ext: str, retrobat_ext: str) -> str:
        """Create unified ROM key for games with both extensions.
        
        Args:
            base_path: Base path without extension (e.g., "path/to/game")
            batocera_ext: Batocera extension (e.g., ".z64")
            retrobat_ext: Retrobat extension (e.g., ".n64")
            
        Returns:
            str: Unified ROM key (e.g., "path/to/game.(z64|n64)")
        """
        # Remove leading dots from extensions if present
        bat_ext = batocera_ext.lstrip('.') if batocera_ext else ''
        ret_ext = retrobat_ext.lstrip('.') if retrobat_ext else ''
        return f"{base_path}.({bat_ext}|{ret_ext})"
    
    def _parse_extensions(self, ext_str: str) -> list:
        """Parse a comma-separated extension string into a normalized list."""
        exts = []
        for e in ext_str.split(','):
            e = e.strip()
            if e:
                if not e.startswith('.'):
                    e = '.' + e
                exts.append(e)
        return exts

    def _ext_for_rompath(self, rompath: str, exts: list) -> str:
        """Return the first extension from exts that the rompath ends with, or ''."""
        rompath_lower = rompath.lower()
        for ext in exts:
            if rompath_lower.endswith(ext.lower()):
                return ext
        return ''

    def _merge_games_with_extensions(self, system_id: str, catalog_type: str, batocera_ext: str, retrobat_ext: str) -> int:
        """Merge games with different extensions when both ROMs exist.

        When a system has both batocera_extension and retrobat_extension defined,
        finds games with matching base paths but different extensions and creates
        unified ROM keys. Both fields accept comma-separated lists of extensions.

        Args:
            system_id: System identifier
            catalog_type: 'wip' or 'releases'
            batocera_ext: Batocera extension(s), e.g. ".z64" or ".cue,.chd"
            retrobat_ext: Retrobat extension(s), e.g. ".n64" or ".zip"

        Returns:
            int: Number of merged games
        """
        # Select appropriate catalog structures
        if catalog_type == 'wip':
            catalog = self.catalog_wip
            catalog_sorted_keys = self.catalog_sorted_keys_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
            catalog_sorted_keys = self.catalog_sorted_keys_releases
        else:
            raise ValueError(f"Invalid catalog_type: {catalog_type}")

        if system_id not in catalog:
            return 0

        bat_exts = self._parse_extensions(batocera_ext)
        ret_exts = self._parse_extensions(retrobat_ext)

        if not bat_exts or not ret_exts:
            return 0  # Both sides must have at least one extension

        # Build map: base_path -> {'batocera': rompath, 'batocera_ext': ext,
        #                          'retrobat': rompath, 'retrobat_ext': ext}
        # First match in priority order wins for each side.
        base_path_map = {}

        for rompath in catalog[system_id].keys():
            base_path = self._get_rom_filename_without_ext(rompath)
            if base_path not in base_path_map:
                base_path_map[base_path] = {}
            entry = base_path_map[base_path]

            matched_bat = self._ext_for_rompath(rompath, bat_exts)
            if matched_bat and 'batocera' not in entry:
                entry['batocera'] = rompath
                entry['batocera_ext'] = matched_bat
                continue

            matched_ret = self._ext_for_rompath(rompath, ret_exts)
            if matched_ret and 'retrobat' not in entry:
                entry['retrobat'] = rompath
                entry['retrobat_ext'] = matched_ret

        # Find pairs that have both extensions
        merged_count = 0
        unified_keys_to_create = []

        for base_path, paths in base_path_map.items():
            if 'batocera' in paths and 'retrobat' in paths:
                batocera_rompath = paths['batocera']
                retrobat_rompath = paths['retrobat']
                unified_key = self._create_unified_rom_key(base_path, paths['batocera_ext'], paths['retrobat_ext'])

                primary_game_data = catalog[system_id][batocera_rompath]

                # Store unified key with primary game data
                catalog[system_id][unified_key] = primary_game_data.copy()
                # Add metadata about both paths for download resolution
                catalog[system_id][unified_key]['_original_batocera_path'] = batocera_rompath
                catalog[system_id][unified_key]['_original_retrobat_path'] = retrobat_rompath

                # Remove individual ROM paths from catalog
                del catalog[system_id][batocera_rompath]
                del catalog[system_id][retrobat_rompath]

                unified_keys_to_create.append((unified_key, batocera_rompath, retrobat_rompath))
                merged_count += 1
                paths['matched'] = True

        # Fallback: Merge by game name for remaining ROMs
        batocera_unmatched = {}  # name -> rompath
        retrobat_unmatched = {}  # name -> rompath

        for base_path, paths in base_path_map.items():
            if paths.get('matched'):
                continue

            if 'batocera' in paths:
                rompath = paths['batocera']
                name = catalog[system_id][rompath].get('name', '').lower().strip()
                if name:
                    batocera_unmatched[name] = rompath

            if 'retrobat' in paths:
                rompath = paths['retrobat']
                name = catalog[system_id][rompath].get('name', '').lower().strip()
                if name:
                    retrobat_unmatched[name] = rompath

        # Find matches by name
        for name, batocera_rompath in batocera_unmatched.items():
            if name in retrobat_unmatched:
                retrobat_rompath = retrobat_unmatched[name]

                # Use actual extensions of matched rompaths for the unified key
                bat_ext_for_pair = self._ext_for_rompath(batocera_rompath, bat_exts)
                ret_ext_for_pair = self._ext_for_rompath(retrobat_rompath, ret_exts)

                base_path = self._get_rom_filename_without_ext(batocera_rompath)
                unified_key = self._create_unified_rom_key(base_path, bat_ext_for_pair, ret_ext_for_pair)

                # If unified key already exists (unlikely but safe), skip
                if unified_key in catalog[system_id]:
                    continue

                primary_game_data = catalog[system_id][batocera_rompath]

                # Store unified key with primary game data
                catalog[system_id][unified_key] = primary_game_data.copy()
                catalog[system_id][unified_key]['_original_batocera_path'] = batocera_rompath
                catalog[system_id][unified_key]['_original_retrobat_path'] = retrobat_rompath

                # Remove individual ROM paths
                del catalog[system_id][batocera_rompath]
                del catalog[system_id][retrobat_rompath]

                unified_keys_to_create.append((unified_key, batocera_rompath, retrobat_rompath))
                merged_count += 1
        
        # Update sorted keys list - replace old keys with unified key
        if system_id in catalog_sorted_keys:
            sorted_keys = catalog_sorted_keys[system_id]
            new_sorted_keys = []
            for key in sorted_keys:
                # Check if this key was merged
                was_merged = False
                for unified_key, bat_rom, ret_rom in unified_keys_to_create:
                    if key == bat_rom or key == ret_rom:
                        # Replace with unified key (only add once)
                        if unified_key not in new_sorted_keys:
                            new_sorted_keys.append(unified_key)
                        was_merged = True
                        break
                
                if not was_merged:
                    new_sorted_keys.append(key)
            
            # Re-sort by game name (using catalog data)
            new_sorted_keys.sort(key=lambda k: catalog[system_id].get(k, {}).get('name', '').lower())
            catalog_sorted_keys[system_id] = new_sorted_keys
        
        if merged_count > 0:
            logger.info(f"Merged {merged_count} game pairs in {system_id} ({catalog_type}): {bat_exts} <-> {ret_exts}")
        
        return merged_count
    
    def preload_all_gamelists(self, force_reload: bool = False) -> None:
        """Preload all gamelist.xml files into memory at startup.
        Loads both WIP (current) and Releases (versioned) catalogs.
        
        Args:
            force_reload: If True, skip cache and generate from scratch. If False, only loads from cache.
        """
        if self._gamelists_loaded and not force_reload:
            logger.info("Gamelists already loaded")
            return
        
        # Try loading from cache first (unless force_reload is True)
        if not force_reload:
            if self._load_catalog_from_cache():
                logger.info("Catalog loaded from cache")
                return
            
            # Cache doesn't exist - don't generate, just log warning
            logger.warning("Catalog cache file not found - catalog will not be available")
            logger.warning("Call /refresh endpoint to generate catalog and search index")
            # Initialize empty structures to prevent errors
            self.catalog_wip = {}
            self.catalog_releases = {}
            self.catalog_sorted_keys_wip = {}
            self.catalog_sorted_keys_releases = {}
            self.subdirectory_counts_wip = {}
            self.subdirectory_counts_releases = {}
            self.systems_list = []
            self.system_versions = {}
            self.system_snapshot_paths = {}
            self._gamelists_loaded = False  # Keep as False since we don't have data
            self._catalog_timestamp = None
            return
        
        # force_reload=True: Generate catalog from scratch (skip cache)
        logger.info("Force reload requested - generating catalog from scratch (skipping cache)")
        
        # Reset the loaded flag to allow generation
        self._gamelists_loaded = False
        
        # Get enabled systems and their extensions from database
        enabled_systems = set()
        system_extensions = {}  # system_id -> {'batocera_extension': str, 'retrobat_extension': str}
        try:
            from app.database import get_db, System
            db = next(get_db())
            enabled_systems_db = db.query(System).filter(System.enabled == True).all()
            enabled_systems = {s.id for s in enabled_systems_db}
            # Store extensions for each system
            for s in enabled_systems_db:
                if s.batocera_extension and s.retrobat_extension:
                    system_extensions[s.id] = {
                        'batocera_extension': s.batocera_extension,
                        'retrobat_extension': s.retrobat_extension
                    }
            logger.info(f"Found {len(enabled_systems)} enabled systems in database, {len(system_extensions)} with both extensions defined")
        except Exception as e:
            logger.warning(f"Could not load enabled systems from database: {e}. Will load all systems.")
        
        systems = []
        # Initialize catalog structures
        self.catalog_wip = {}
        self.catalog_releases = {}
        self.catalog_sorted_keys_wip = {}
        self.catalog_sorted_keys_releases = {}
        self.subdirectory_counts_wip = {}
        self.subdirectory_counts_releases = {}
        self.system_versions = {}
        self.system_gamelist_date_wip = {}
        self.system_gamelist_date_releases = {}
        
        if not os.path.isdir(self.games_path):
            logger.warning(f"Games directory not found at: {self.games_path}")
            self._gamelists_loaded = True
            self.systems_list = []
            return
        
        for dir_name in os.listdir(self.games_path):
            if dir_name in ['.', '..']:
                continue
            
            # Skip systems with _spirit suffix
            if dir_name.endswith('_spirit'):
                logger.debug(f"Skipping system with _spirit suffix: {dir_name}")
                continue
            
            # Skip system "radio"
            if dir_name == 'radio':
                logger.debug(f"Skipping system: {dir_name}")
                continue
            
            dir_path = os.path.join(self.games_path, dir_name)
            if not os.path.isdir(dir_path) or not os.access(dir_path, os.R_OK):
                logger.warning(f"Directory not readable: {dir_path}")
                continue
            
            # Skip if system is not enabled in database (if database check succeeded)
            if enabled_systems and dir_name not in enabled_systems:
                logger.debug(f"Skipping disabled system: {dir_name}")
                continue
            
            # Load WIP catalog (current gamelist.xml)
            gamelist_path = os.path.join(dir_path, 'gamelist.xml')
            if not os.path.isfile(gamelist_path) or not os.access(gamelist_path, os.R_OK):
                logger.warning(f"No gamelist.xml found for system: {dir_name}")
                continue
            
            try:
                # Load WIP catalog
                game_count_wip = self._load_catalog_from_gamelist(dir_name, gamelist_path, 'wip')
                logger.debug(f"Loaded WIP catalog for {dir_name}: {game_count_wip} games")
                
                # Extract gamelist modification date for WIP
                from datetime import datetime
                mtime_wip = os.path.getmtime(gamelist_path)
                self.system_gamelist_date_wip[dir_name] = datetime.fromtimestamp(mtime_wip).strftime('%d-%m-%Y')
                
                # Merge games with extensions if both extensions are defined for this system
                if dir_name in system_extensions:
                    ext_info = system_extensions[dir_name]
                    merged_count = self._merge_games_with_extensions(
                        dir_name, 'wip',
                        ext_info['batocera_extension'],
                        ext_info['retrobat_extension']
                    )
                    if merged_count > 0:
                        logger.info(f"Merged {merged_count} WIP game pairs for {dir_name}")
                
                # Try to find and load Releases catalog (versioned gamelist.xml)
                version_result = self._find_latest_versioned_gamelist(dir_path)
                if version_result:
                    version_str, snapshot_dir_path, versioned_gamelist_path = version_result
                    try:
                        game_count_releases = self._load_catalog_from_gamelist(dir_name, versioned_gamelist_path, 'releases', snapshot_dir_path)
                        self.system_versions[dir_name] = version_str
                        self.system_snapshot_paths[dir_name] = snapshot_dir_path
                        
                        # Extract gamelist modification date for Releases
                        from datetime import datetime
                        mtime_releases = os.path.getmtime(versioned_gamelist_path)
                        self.system_gamelist_date_releases[dir_name] = datetime.fromtimestamp(mtime_releases).strftime('%d-%m-%Y')
                        
                        logger.info(f"Loaded Releases catalog for {dir_name} (version {version_str}, snapshot: {snapshot_dir_path}): {game_count_releases} games")
                        
                        # Merge games with extensions if both extensions are defined for this system
                        if dir_name in system_extensions:
                            ext_info = system_extensions[dir_name]
                            merged_count = self._merge_games_with_extensions(
                                dir_name, 'releases',
                                ext_info['batocera_extension'],
                                ext_info['retrobat_extension']
                            )
                            if merged_count > 0:
                                logger.info(f"Merged {merged_count} Releases game pairs for {dir_name}")
                    except Exception as e:
                        logger.error(f"Error loading Releases catalog for {dir_name} (version {version_str}): {e}")
                        # Continue with WIP catalog only
                else:
                    logger.debug(f"No versioned gamelist found for {dir_name}")
                
                # Use WIP game count for system list display
                game_count = game_count_wip
                
                # Get hardware category, manufacturer, release year, and full name from in-memory mapping
                hardware = self.system_hardware.get(dir_name, 'unknown')
                manufacturer = self.system_manufacturer.get(dir_name, 'Unknown')
                release = self.system_release.get(dir_name, 'Unknown')
                fullname = self.system_fullname.get(dir_name, None)
                
                # Log if hardware not found (for debugging)
                if hardware == 'unknown' and len(self.system_hardware) > 0:
                    # Check if there's a similar name (case-insensitive)
                    dir_name_lower = dir_name.lower()
                    matching_systems = [k for k in self.system_hardware.keys() if k.lower() == dir_name_lower]
                    if matching_systems:
                        matched_id = matching_systems[0]
                        logger.warning(f"System '{dir_name}' not found in hardware map, but found case-insensitive match: {matched_id}")
                        hardware = self.system_hardware[matched_id]
                        manufacturer = self.system_manufacturer.get(matched_id, 'Unknown')
                        release = self.system_release.get(matched_id, 'Unknown')
                        fullname = self.system_fullname.get(matched_id, None)
                    else:
                        logger.debug(f"Hardware not found for system '{dir_name}'. Available systems (first 20): {list(self.system_hardware.keys())[:20]}")
                
                # Use fullname if available, otherwise fall back to get_system_name
                display_name = fullname if fullname else self.get_system_name(dir_name)
                
                # Skip systems with hardware category "library"
                if hardware.lower() == 'library':
                    logger.debug(f"Skipping system with library hardware category: {dir_name}")
                    continue
                
                # Get version if available
                version = self.system_versions.get(dir_name)
                
                system = {
                    'id': dir_name,
                    'name': display_name,
                    'gameCount': game_count,
                    'hardware': hardware,
                    'manufacturer': manufacturer,
                    'release': release,
                    'version': version  # Add version to system info
                }
                
                systems.append(system)
                logger.debug(f"Loaded {dir_name}: {game_count} games (WIP), version: {version or 'none'}")
            except Exception as e:
                logger.error(f"Error parsing gamelist for {dir_name}: {e}")
                continue
        
        self.systems_list = systems
        self._gamelists_loaded = True
        self._catalog_timestamp = time.time()  # Set timestamp when catalog is loaded
        logger.info(f"Preloaded {len(systems)} systems with {sum(s['gameCount'] for s in systems)} total games (catalog timestamp: {self._catalog_timestamp})")
        logger.info(f"WIP catalog: {len(self.catalog_wip)} systems, Releases catalog: {len(self.catalog_releases)} systems")
    
    def _check_and_reload_catalog_if_updated(self) -> bool:
        """Check if catalog or search index files have been updated and reload if needed.
        
        This allows workers to automatically reload when another worker refreshes the catalog.
        
        Returns:
            True if catalog was reloaded, False otherwise
        """
        worker_id = os.getenv('WORKER_ID', os.getpid())
        
        if not self._gamelists_loaded:
            return False
        
        catalog_file = self._get_catalog_file_path()
        index_file = self._get_index_file_path()
        
        reloaded = False
        
        # Check catalog file
        if os.path.isfile(catalog_file):
            current_mtime = os.path.getmtime(catalog_file)
            if self._catalog_file_mtime is not None and current_mtime > self._catalog_file_mtime:
                logger.info(f"[Worker {worker_id}] Catalog .pkl file has been updated (mtime: {current_mtime} > {self._catalog_file_mtime}), reloading from {catalog_file}...")
                # Clear current data
                self._gamelists_loaded = False
                self._index_built_wip = False
                self._index_built_releases = False
                # Reload catalog
                if self._load_catalog_from_cache():
                    reloaded = True
                    logger.info(f"[Worker {worker_id}] Catalog reloaded successfully from .pkl file: {len(self.systems_list)} systems, WIP: {len(self.catalog_wip)} systems, Releases: {len(self.catalog_releases)} systems")
                else:
                    logger.warning(f"[Worker {worker_id}] Failed to reload catalog from updated .pkl file: {catalog_file}")
        
        # Check search index file
        if os.path.isfile(index_file):
            current_mtime = os.path.getmtime(index_file)
            if self._index_file_mtime is not None and current_mtime > self._index_file_mtime:
                logger.info(f"[Worker {worker_id}] Search index .pkl file has been updated (mtime: {current_mtime} > {self._index_file_mtime}), reloading from {index_file}...")
                # Reload both indexes
                cached_wip = self._load_index_from_cache('wip')
                if cached_wip:
                    self.search_index_wip = cached_wip
                    self._index_built_wip = True
                    self.cache['search_index_wip'] = cached_wip
                    logger.info(f"[Worker {worker_id}] Search index (WIP) reloaded from .pkl file: {len(cached_wip)} letters indexed")
                
                cached_releases = self._load_index_from_cache('releases')
                if cached_releases:
                    self.search_index_releases = cached_releases
                    self._index_built_releases = True
                    self.cache['search_index_releases'] = cached_releases
                    logger.info(f"[Worker {worker_id}] Search index (Releases) reloaded from .pkl file: {len(cached_releases)} letters indexed")
        
        return reloaded
    
    def get_systems(self) -> List[Dict]:
        """Get list of all available systems (from memory cache)."""
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        return self.systems_list.copy()  # Return a copy to prevent modification
    
    def get_system(self, system_id: str) -> Optional[Dict]:
        """Get a specific system by ID."""
        systems = self.get_systems()
        for system in systems:
            if system['id'] == system_id:
                return system
        return None
    
    def get_games_by_system(self, system: str, page: int = 1, limit: int = 12, search: str = '', catalog_type: str = 'wip') -> List[Dict]:
        """Get games for a specific system with pagination and optional search (from memory cache).
        
        Args:
            system: System identifier
            page: Page number (1-based)
            limit: Number of games per page
            search: Optional search query
            catalog_type: 'wip' or 'releases' (default: 'wip')
        """
        logger.info(f"Getting games for system: {system}, page: {page}, limit: {limit}, catalog_type: {catalog_type}")
        
        cache_key = f"games_{system}_{page}_{limit}_{search}_{catalog_type}"
        if cache_key in self.cache:
            logger.info(f"Returning cached games for: {cache_key}")
            return self.cache[cache_key]
        
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Select appropriate catalog structures based on catalog_type
        if catalog_type == 'wip':
            catalog = self.catalog_wip
            catalog_sorted_keys = self.catalog_sorted_keys_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
            catalog_sorted_keys = self.catalog_sorted_keys_releases
        else:
            logger.error(f"Invalid catalog_type: {catalog_type}. Defaulting to 'wip'")
            catalog = self.catalog_wip
            catalog_sorted_keys = self.catalog_sorted_keys_wip
        
        # Check if system exists in catalog
        if system not in catalog:
            logger.warning(f"System not found in catalog ({catalog_type}): {system}")
            logger.warning(f"Available systems: {list(catalog.keys())[:20]}")  # Log first 20 systems
            # Try case-insensitive match
            system_lower = system.lower()
            for loaded_system in catalog.keys():
                if loaded_system.lower() == system_lower:
                    logger.info(f"Found case-insensitive match: '{system}' -> '{loaded_system}'")
                    system = loaded_system
                    break
            else:
                return []
        
        try:
            # Get pre-sorted rompaths (already sorted by name, case-insensitive)
            sorted_rompaths = catalog_sorted_keys.get(system, [])
            system_catalog = catalog.get(system, {})
            
            # Filter by search query if provided
            if search:
                search_lower = search.lower()
                sorted_rompaths = [
                    rompath for rompath in sorted_rompaths
                    if rompath in system_catalog and search_lower in system_catalog[rompath].get('name', '').lower()
                ]
            
            total_games = len(sorted_rompaths)
            logger.info(f"Total visible games found: {total_games}")
            
            # Apply pagination (already sorted, no need to sort again)
            offset = (page - 1) * limit
            paginated_rompaths = sorted_rompaths[offset:offset + limit]
            logger.info(f"Games after pagination: {len(paginated_rompaths)}")
            
            # Build response structures on-demand from catalog data
            games = []
            for rompath in paginated_rompaths:
                if rompath in system_catalog:
                    game_data = system_catalog[rompath]
                    # Build response on-demand
                    game_response = self._build_game_response(system, rompath, game_data, catalog_type)
                    
                    # Add playcount, gametime from raw catalog (already in game_data, but ensure they're in response)
                    if 'playcount' in game_data:
                        game_response['playcount'] = game_data['playcount']
                    if 'gametime' in game_data:
                        game_response['gametime'] = game_data['gametime']
                    
                    games.append(game_response)
            
            logger.info(f"Returning {len(games)} games")
            self.cache[cache_key] = games
            
            return games
        except Exception as e:
            logger.error(f"Failed to get games for system {system} ({catalog_type}): {e}")
            return []
    
    def has_more_games(self, system: str, page: int, limit: int, catalog_type: str = 'wip') -> bool:
        """Check if there are more games available for a system (from memory cache)."""
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Select appropriate catalog based on catalog_type
        if catalog_type == 'wip':
            catalog = self.catalog_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
        else:
            catalog = self.catalog_wip
        
        if system not in catalog:
            return False
        
        try:
            system_catalog = catalog[system]
            visible_games = len(system_catalog)  # Already filtered for hidden games
            
            return visible_games > (page * limit)
        except Exception as e:
            logger.error(f"Error checking for more games: {e}")
            return False
    
    def get_catalog_etag(self, system: str, search: str = '', catalog_type: str = 'wip') -> str:
        """Generate ETag for a system's games list.
        
        ETag changes when catalog is reloaded/refreshed.
        Includes search query and catalog_type to differentiate ETags.
        
        Args:
            system: System ID
            search: Optional search query
            catalog_type: 'wip' or 'releases' (default: 'wip')
            
        Returns:
            ETag string (e.g., 'W/"c64-t1234567890-search-wip"')
        """
        # Use weak ETag (W/) to allow byte-range requests
        # Use timestamp (converted to int) for catalog version
        catalog_version = int(self._catalog_timestamp) if self._catalog_timestamp else 0
        search_hash = hashlib.md5(search.encode()).hexdigest()[:8] if search else 'all'
        return f'W/"{system}-t{catalog_version}-{search_hash}-{catalog_type}"'
    
    def get_systems_etag(self) -> str:
        """Generate ETag for systems list.
        
        ETag changes when catalog is reloaded/refreshed (affects game counts).
        
        Returns:
            ETag string (e.g., 'W/"systems-t1234567890"')
        """
        # Use weak ETag (W/) to allow byte-range requests
        # Use timestamp (converted to int) for catalog version
        catalog_version = int(self._catalog_timestamp) if self._catalog_timestamp else 0
        return f'W/"systems-t{catalog_version}"'
    
    def search_games(self, query: str, page: int = 1, limit: int = 12) -> List[Dict]:
        """Search games across all systems.
        
        Only searches games from systems that are enabled in the database.
        """
        if not query:
            return []
        
        cache_key = f"search_{query}_{page}_{limit}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Get enabled systems from database
        enabled_systems = self._get_enabled_systems_set()
        
        systems = self.get_systems()
        results = []
        
        # Helper function to normalize media path (defined once, outside loops)
        def get_media_path(media_type, game_data, system_id):
            """Normalize media path by adding system prefix if needed."""
            path = game_data.get(media_type, '')
            if path:
                path = path.lstrip('./')
                if not path.startswith(f"{system_id}/"):
                    path = f"{system_id}/{path}"
            return path
        
        for system in systems:
            system_id = system['id']
            
            # Skip if system is not enabled
            if enabled_systems and system_id not in enabled_systems:
                continue
            
            # Use catalog instead of parsing XML
            if system_id not in self.catalog:
                continue
            
            try:
                system_catalog = self.catalog[system_id]
                
                for rompath, game_data in system_catalog.items():
                    name = game_data.get('name', '')
                    if query.lower() in name.lower():
                        # Get game data with image priority: thumbnail > boxart > extra1 > image
                        # Only compute path for the first media type that exists (optimized)
                        display_image = ''
                        for media_type in ['thumbnail', 'boxart', 'extra1', 'image']:
                            raw_path = game_data.get(media_type, '')
                            if raw_path:
                                display_image = get_media_path(media_type, game_data, system_id)
                                break  # Found first available, stop checking
                        
                        results.append({
                            'id': rompath,
                            'name': name,
                            'desc': game_data.get('desc', ''),
                            'image': display_image,
                            'system': system_id,
                            'systemName': self.get_system_name(system_id)
                        })
            except Exception as e:
                logger.error(f"Error searching games in system {system_id}: {e}")
                continue
        
        # Sort results (exact matches first)
        results.sort(key=lambda x: query.lower() not in x['name'].lower())
        
        # Apply pagination
        offset = (page - 1) * limit
        paged_results = results[offset:offset + limit]
        
        self.cache[cache_key] = paged_results
        return paged_results
    
    def has_more_search_results(self, query: str, page: int, limit: int) -> bool:
        """Check if there are more search results."""
        if not query:
            return False
        
        all_results = self.search_games(query, 1, 999999)
        return len(all_results) > (page * limit)
    
    def get_system_name(self, system_id: str) -> str:
        """Get display name for a system ID."""
        return self.system_names.get(system_id.lower(), system_id.capitalize())
    
    def get_game_by_id(self, game_id: str, system_id: str, catalog_type: str = 'wip', normalize_paths: bool = True) -> Optional[Dict]:
        """Get a specific game by its ID (path from gamelist.xml) within a specific system.
        
        The game_id is the path as stored in gamelist.xml, which is relative to the system directory.
        Full path is always: GAMES_PATH/<systemid>/<rompath>
        
        Args:
            game_id: Game path from gamelist.xml
            system_id: System identifier (required) - which system to look in
            catalog_type: 'wip' or 'releases' (default: 'wip')
            normalize_paths: If True, normalize media paths for frontend display. If False, preserve original paths from gamelist.xml (default: True)
        """
        logger.info(f"Getting game by ID: {game_id}, system_id: {system_id}, catalog_type: {catalog_type}")
        
        # Clean up the game ID (remove leading ./ if present)
        clean_game_id = game_id.lstrip('./')
        logger.info(f"Cleaned game ID: {clean_game_id}")
        
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Select appropriate catalog based on catalog_type
        if catalog_type == 'wip':
            catalog = self.catalog_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
        else:
            catalog = self.catalog_wip
        
        # Check if system exists in catalog
        if system_id not in catalog:
            logger.warning(f"System not found in catalog: {system_id} (catalog_type: {catalog_type})")
            return None
        
        system_catalog = catalog[system_id]
        found_game_data = None
        
        # Try to find game in the specified system's catalog
        # Try both with and without ./ prefix
        if clean_game_id in system_catalog:
            found_game_data = system_catalog[clean_game_id]
            logger.info(f"Game found in system {system_id} with path: {clean_game_id}")
        elif f'./{clean_game_id}' in system_catalog:
            found_game_data = system_catalog[f'./{clean_game_id}']
            logger.info(f"Game found in system {system_id} with path: ./{clean_game_id}")
        
        if not found_game_data:
            logger.warning(f"Game not found in system {system_id} with path: {clean_game_id} (catalog_type: {catalog_type})")
            return None
        
        try:
            # Create a copy of game_data and add system-specific fields
            game_data = found_game_data.copy()
            game_data['id'] = clean_game_id
            game_data['system'] = system_id
            game_data['systemName'] = self.get_system_name(system_id)
            
            # Ensure required fields exist (with defaults if missing)
            if 'name' not in game_data:
                game_data['name'] = ''
            
            # Get snapshot path for Releases catalog
            snapshot_dir_path = None
            if catalog_type == 'releases':
                snapshot_dir_path = self.system_snapshot_paths.get(system_id)
            
            # Helper function to normalize media path for frontend
            def normalize_media_path_for_frontend(media_path: str) -> str:
                """Normalize media path for frontend display with system and snapshot prefix."""
                if not media_path:
                    return ''
                # Remove ./ prefix if present
                clean_path = media_path.lstrip('./')
                if catalog_type == 'releases' and snapshot_dir_path:
                    # For Releases: prefix with system_id and snapshot path
                    snapshot_prefix = snapshot_dir_path.rstrip('/') + '/'
                    if not clean_path.startswith(f"{system_id}/"):
                        return f"{system_id}/{snapshot_prefix}{clean_path}"
                    else:
                        # Path already has system prefix, insert snapshot path
                        parts = clean_path.split('/', 1)
                        if len(parts) > 1:
                            return f"{parts[0]}/{snapshot_prefix}{parts[1]}"
                        else:
                            return f"{system_id}/{snapshot_prefix}{clean_path}"
                else:
                    # For WIP: just ensure system prefix is present
                    if not clean_path.startswith(f"{system_id}/"):
                        return f"{system_id}/{clean_path}"
                    else:
                        return clean_path
            
            # Only normalize paths if requested (for frontend display)
            # For download service, preserve original paths from gamelist.xml
            if normalize_paths:
                # Normalize all media fields for frontend display
                media_fields = ['thumbnail', 'boxart', 'image', 'video', 'marquee', 'wheel', 
                               'extra1', 'extra2', 'extra3', 'extra4', 'mix', 'catalog_image',
                               'boxback', 'cartridge', 'titleshot', 'fanart', 'screenshot']
                for field in media_fields:
                    if field in game_data and game_data[field]:
                        game_data[field] = normalize_media_path_for_frontend(game_data[field])
                
                # Set default display image (prefer thumbnail, then image)
                if 'thumbnail' in game_data and game_data['thumbnail']:
                    if 'image' not in game_data or not game_data['image']:
                        game_data['image'] = game_data['thumbnail']
                elif 'image' not in game_data:
                    game_data['image'] = ''
            
            logger.info(f"Game data retrieved: {game_data.get('name', 'Unknown')} ({len(game_data)} fields)")
            return game_data
        except Exception as e:
            logger.error(f"Failed to get game by ID: {e}")
            return None
    
    def _get_game_subdirectory(self, game_path: str, system_id: str) -> Optional[str]:
        """Extract subdirectory from game path.
        
        Args:
            game_path: Game path from gamelist.xml (e.g., "./subdir/game.zip" or "subdir/game.zip")
            system_id: System ID
            
        Returns:
            Subdirectory name (e.g., "subdir") or None if game is in root
        """
        # Remove leading ./
        path = game_path.lstrip('./')
        # Remove system prefix if present
        if path.startswith(f"{system_id}/"):
            path = path[len(system_id) + 1:]
        # Get directory part (everything before the last /)
        last_slash_index = path.rfind('/')
        if last_slash_index == -1:
            return None  # No subdirectory, game is in root
        return path[:last_slash_index]
    
    def _compute_subdirectory_counts(self, system_id: str):
        """Compute subdirectory counts for a specific system.
        
        Args:
            system_id: System ID to compute counts for
        """
        if system_id not in self.catalog:
            return
        
        # Need to parse XML again for folders (folders not in catalog)
        gamelist_path = os.path.join(self.games_path, system_id, 'gamelist.xml')
        if not os.path.isfile(gamelist_path):
            return
        
        try:
            tree = ET.parse(gamelist_path)
            root = tree.getroot()
        except Exception as e:
            logger.error(f"Error parsing gamelist.xml for subdirectory counts: {e}")
            return
        
        counts = {}
        
        # First pass: collect all hidden folder paths
        hidden_directories = set()
        for folder in root.findall('.//folder'):
            if _is_folder_hidden(folder):
                folder_path = folder.findtext('path', '')
                if folder_path:
                    # Normalize the path
                    path = folder_path.lstrip('./')
                    if path.startswith(f"{system_id}/"):
                        path = path[len(system_id) + 1:]
                    # Remove trailing slash if present
                    path = path.rstrip('/')
                    hidden_directories.add(path)
                    logger.debug(f"Found hidden folder: {path} in system {system_id}")
        
        # Second pass: count games from catalog, skipping games in hidden directories
        system_catalog = self.catalog[system_id]
        for rompath, game_data in system_catalog.items():
            # Check if game is inside a hidden directory
            subdir = self._get_game_subdirectory(rompath, system_id)
            if subdir:
                # Check if subdirectory matches any hidden directory or is nested inside one
                is_in_hidden_dir = False
                for hidden_dir in hidden_directories:
                    if subdir == hidden_dir or subdir.startswith(hidden_dir + '/'):
                        # Game is inside a hidden directory, skip it
                        is_in_hidden_dir = True
                        break
                if is_in_hidden_dir:
                    continue
            
            key = subdir if subdir else '(root)'
            counts[key] = counts.get(key, 0) + 1
        
        self.subdirectory_counts[system_id] = counts
        logger.debug(f"Computed subdirectory counts for {system_id}: {len(counts)} subdirectories")
    
    def _compute_all_subdirectory_counts(self):
        """Compute subdirectory counts for all loaded systems."""
        for system_id in self.catalog.keys():
            self._compute_subdirectory_counts(system_id)
        logger.info(f"Computed subdirectory counts for {len(self.subdirectory_counts)} systems")
    
    def get_subdirectory_counts(self, system_id: str, catalog_type: str = 'wip') -> dict:
        """Get subdirectory counts for a system.
        
        Subdirectory counts are pre-computed during catalog build for optimal performance.
        
        Args:
            system_id: System ID
            catalog_type: 'wip' or 'releases' (default: 'wip')
            
        Returns:
            Dictionary mapping subdirectory names to game counts
        """
        # Ensure gamelists are loaded (this will pre-compute subdirectory counts)
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Select appropriate subdirectory counts based on catalog_type
        if catalog_type == 'wip':
            return self.subdirectory_counts_wip.get(system_id, {})
        elif catalog_type == 'releases':
            return self.subdirectory_counts_releases.get(system_id, {})
        else:
            return self.subdirectory_counts_wip.get(system_id, {})
    
    def _get_index_file_path(self) -> str:
        """Get the path to the search index pickle file."""
        # Use the same data directory as the database (project root/data/)
        from app.config import settings
        
        # Get database path and extract the directory (same logic as database.py)
        db_path = settings.DATABASE_URL.replace('sqlite:///', '')
        if db_path.startswith('./'):
            # Resolve relative path from the project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            db_path = os.path.join(project_root, db_path[2:])
        elif not os.path.isabs(db_path):
            # Relative path, resolve from project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            db_path = os.path.join(project_root, db_path)
        
        data_dir = os.path.dirname(db_path)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, 'search_index.pkl')
    def _get_catalog_file_path(self) -> str:
        """Get the path to the catalog pickle file."""
        from app.config import settings
        
        # Get database path and extract the directory (same logic as database.py)
        db_path = settings.DATABASE_URL.replace('sqlite:///', '')
        if db_path.startswith('./'):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            db_path = os.path.join(project_root, db_path[2:])
        elif not os.path.isabs(db_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            db_path = os.path.join(project_root, db_path)
        
        data_dir = os.path.dirname(db_path)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, 'catalog.pkl')
    

    def _load_index_from_cache(self, catalog_type: str = 'wip') -> Optional[Dict]:
        """Load search index from pickle file if it exists and is valid.
        
        Args:
            catalog_type: 'wip' or 'releases' (default: 'wip')
        """
        index_file = self._get_index_file_path()
        
        if not os.path.isfile(index_file):
            logger.info(f"No cached search index found ({catalog_type})")
            return None
        
        try:
            # Hash validation disabled to match catalog loading logic
            # Load indexes from pickle (may contain both wip and releases)
            with open(index_file, 'rb') as f:
                index_data = pickle.load(f)
            
            # Store file modification time after successful load
            self._index_file_mtime = os.path.getmtime(index_file)
            
            worker_id = os.getenv('WORKER_ID', os.getpid())
            logger.info(f"[Worker {worker_id}] Loading search index from .pkl file: {index_file} (type: {catalog_type})")
            
            # If it's a dict with 'wip' and/or 'releases' keys, extract the requested one
            if isinstance(index_data, dict) and (catalog_type in index_data or 'wip' in index_data or 'releases' in index_data):
                if catalog_type in index_data:
                    index = index_data[catalog_type]
                    logger.info(f"[Worker {worker_id}] Search index loaded from .pkl cache ({catalog_type}): {len(index)} letters indexed")
                    return index
                else:
                    # Old format or missing requested type
                    logger.info(f"Index cache exists but doesn't contain {catalog_type} index")
                    return None
            else:
                # Old format: single index (assumed to be wip)
                if catalog_type == 'wip':
                    logger.info(f"Loaded search index from cache (legacy format, WIP): {len(index_data)} letters")
                    return index_data
                else:
                    logger.info(f"Index cache exists in legacy format (WIP only), but {catalog_type} requested")
                    return None
            
        except Exception as e:
            logger.warning(f"Failed to load cached index ({catalog_type}): {e}")
            self._index_file_mtime = None
            return None
    
    def _save_index_to_cache(self, index: Dict, catalog_type: str = 'wip') -> None:
        """Save search index to pickle file.
        
        Args:
            index: The search index dictionary to save
            catalog_type: 'wip' or 'releases' (default: 'wip')
        """
        index_file = self._get_index_file_path()
        
        try:
            # Try to load existing indexes to merge with new one
            index_data = {}
            if os.path.isfile(index_file):
                try:
                    with open(index_file, 'rb') as f:
                        existing_data = pickle.load(f)
                    # If it's a dict with 'wip'/'releases' keys, use it
                    if isinstance(existing_data, dict) and ('wip' in existing_data or 'releases' in existing_data):
                        index_data = existing_data
                except Exception:
                    # If load fails, start fresh
                    pass
            
            # Update with new index
            index_data[catalog_type] = index
            
            # Save merged indexes
            with open(index_file, 'wb') as f:
                pickle.dump(index_data, f)
            
            # Update tracked mtime after saving
            self._index_file_mtime = os.path.getmtime(index_file)
            
            logger.info(f"Saved search index to cache ({catalog_type}): {index_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save index to cache ({catalog_type}): {e}")
    
    def _load_catalog_from_cache(self) -> bool:
        """Load catalog from pickle file if it exists. Returns True if loaded successfully.
        
        Note: Hash validation is disabled - cache will be used if file exists."""
        catalog_file = self._get_catalog_file_path()
        
        logger.info(f"Checking for cached catalog at: {catalog_file}")
        
        if not os.path.isfile(catalog_file):
            logger.info(f"Cached catalog file not found: {catalog_file}")
            self._catalog_file_mtime = None
            return False
        
        # Check if file is newer than when we last loaded (for auto-reload across workers)
        current_mtime = os.path.getmtime(catalog_file)
        if self._catalog_file_mtime is not None and current_mtime <= self._catalog_file_mtime:
            # File hasn't changed since we loaded it
            if self._gamelists_loaded:
                logger.debug("Catalog file hasn't changed, using existing loaded catalog")
                return True
            # File exists but we haven't loaded it yet, continue with loading
        
        logger.info("Cache file found, loading catalog from cache (hash validation disabled)...")
        
        try:
            worker_id = os.getenv('WORKER_ID', os.getpid())
            logger.info(f"[Worker {worker_id}] Loading catalog from .pkl file: {catalog_file}")
            
            # Load catalog from pickle (no hash validation)
            with open(catalog_file, 'rb') as f:
                catalog_data = pickle.load(f)
            
            logger.info(f"[Worker {worker_id}] Pickle file loaded, restoring catalog structures...")
            # Restore catalog structures
            self.catalog_wip = catalog_data.get('catalog_wip', {})
            self.catalog_releases = catalog_data.get('catalog_releases', {})
            self.catalog_sorted_keys_wip = catalog_data.get('catalog_sorted_keys_wip', {})
            self.catalog_sorted_keys_releases = catalog_data.get('catalog_sorted_keys_releases', {})
            self.subdirectory_counts_wip = catalog_data.get('subdirectory_counts_wip', {})
            self.subdirectory_counts_releases = catalog_data.get('subdirectory_counts_releases', {})
            self.systems_list = catalog_data.get('systems_list', [])
            self.system_versions = catalog_data.get('system_versions', {})
            self.system_snapshot_paths = catalog_data.get('system_snapshot_paths', {})
            self.system_gamelist_date_wip = catalog_data.get('system_gamelist_date_wip', {})
            self.system_gamelist_date_releases = catalog_data.get('system_gamelist_date_releases', {})
            self._catalog_timestamp = catalog_data.get('_catalog_timestamp', time.time())
            
            # catalog_responses removed - responses built on-demand to save memory
            
            self._gamelists_loaded = True
            
            # Store file modification time after successful load
            self._catalog_file_mtime = current_mtime
            logger.debug(f"[Worker {worker_id}] Catalog loaded from cache, mtime: {self._catalog_file_mtime}")
            
            logger.info(f"[Worker {worker_id}] Catalog loaded from .pkl file: {len(self.systems_list)} systems, WIP: {len(self.catalog_wip)} systems, Releases: {len(self.catalog_releases)} systems")
            logger.info("Catalog loaded from cache - aggregated playcount/gametime stats (if any) are preserved from cache")
            
            # When loading from cache, we trust that playcount/gametime in the cache are already
            # aggregated stats (since refresh_catalog now clears system gamelist.xml playcount/gametime
            # before aggregating user stats and saving to cache). However, if user gamelist files have
            # been updated since the cache was created, we should re-aggregate to get the latest stats.
            
            # Re-aggregate user stats to ensure we have the latest (user gamelists may have been updated)
            logger.info("Re-aggregating playcount/gametime from user gamelists to ensure latest stats...")
            aggregated_stats = self._aggregate_users_playcount_gametime()
            
            if aggregated_stats:
                logger.info(f"Found aggregated stats for {len(aggregated_stats)} systems, merging into catalogs...")
                
                # Get system mappings from database (batocera_system/retrobat_system -> catalog system IDs)
                system_mappings = self._get_system_mappings()
                
                # Merge aggregated stats into both catalogs (this will overwrite any cached stats with latest)
                catalog_types = ['WIP', 'Releases']
                for catalog_type_idx, catalog in enumerate([self.catalog_wip, self.catalog_releases]):
                    catalog_type = catalog_types[catalog_type_idx]
                    merged_count = 0
                    
                    for user_system_id, games_stats in aggregated_stats.items():
                        # Find catalog systems that match this user system via batocera_system/retrobat_system
                        catalog_system_ids = system_mappings.get(user_system_id, [])
                        
                        # Also try direct match (in case user system name matches catalog system name)
                        if user_system_id in catalog:
                            if user_system_id not in catalog_system_ids:
                                catalog_system_ids.append(user_system_id)
                        
                        # Merge stats into all matching catalog systems
                        for catalog_system_id in catalog_system_ids:
                            if catalog_system_id not in catalog:
                                continue
                            
                            for rompath, stats in games_stats.items():
                                # Try to find the game in catalog
                                matched = False
                                if rompath in catalog[catalog_system_id]:
                                    catalog[catalog_system_id][rompath]['playcount'] = stats['playcount']
                                    catalog[catalog_system_id][rompath]['gametime'] = stats['gametime']
                                    merged_count += 1
                                    matched = True
                                else:
                                    # Try to match by normalized path
                                    catalog_normalized = rompath.lstrip('./')
                                    for catalog_rompath, game_data in catalog[catalog_system_id].items():
                                        cat_normalized = catalog_rompath.lstrip('./')
                                        if catalog_normalized == cat_normalized:
                                            game_data['playcount'] = stats['playcount']
                                            game_data['gametime'] = stats['gametime']
                                            merged_count += 1
                                            matched = True
                                            break
                    
                    logger.info(f"  {catalog_type} catalog: merged stats for {merged_count} games")
                logger.info("Finished updating aggregated user stats in cached catalog")
            else:
                logger.info("No user gamelist stats found - using cached stats if available")
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to load cached catalog: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._catalog_file_mtime = None
            return False
    
    def _build_game_response(self, system_id: str, rompath: str, game_data: Dict, catalog_type: str) -> Dict:
        """Build a single game response dictionary from raw catalog data (computed on-demand to save memory).
        
        Args:
            system_id: System identifier
            rompath: ROM path (game ID)
            game_data: Raw game data from catalog
            catalog_type: 'wip' or 'releases'
            
        Returns:
            Dictionary with game response structure
        """
        # Get system name
        fullname_temp = self.system_fullname.get(system_id, None)
        system_name_temp = fullname_temp if fullname_temp else self.get_system_name(system_id)
        
        # Get snapshot path for Releases catalog
        snapshot_dir_path = None
        if catalog_type == 'releases':
            snapshot_dir_path = self.system_snapshot_paths.get(system_id)
        
        # Normalize media paths for frontend display
        catalog_image = game_data.get('catalog_image', '')
        if catalog_image:
            # Remove ./ prefix if present
            clean_path = catalog_image.lstrip('./')
            if catalog_type == 'releases' and snapshot_dir_path:
                # For Releases: prefix with system_id and snapshot path
                snapshot_prefix = snapshot_dir_path.rstrip('/') + '/'
                if not clean_path.startswith(f"{system_id}/"):
                    catalog_image = f"{system_id}/{snapshot_prefix}{clean_path}"
                else:
                    # Path already has system prefix, insert snapshot path
                    parts = clean_path.split('/', 1)
                    if len(parts) > 1:
                        catalog_image = f"{parts[0]}/{snapshot_prefix}{parts[1]}"
                    else:
                        catalog_image = f"{system_id}/{snapshot_prefix}{clean_path}"
            else:
                # For WIP: just ensure system prefix is present
                if not clean_path.startswith(f"{system_id}/"):
                    catalog_image = f"{system_id}/{clean_path}"
                else:
                    catalog_image = clean_path
        
        # Create response-ready dictionary
        return {
            'id': rompath,
            'name': game_data.get('name', ''),
            'desc': game_data.get('desc', ''),
            'image': catalog_image,
            'system': system_id,
            'systemName': system_name_temp,
            'favorite': game_data.get('favorite', ''),
            'publisher': game_data.get('publisher', ''),
            'releasedate': game_data.get('releasedate', ''),
            'download_count': game_data.get('download_count', 0)
        }
    
    def _save_catalog_to_cache(self) -> None:
        """Save catalog to pickle file.
        
        Note: catalog_responses are NOT saved to reduce memory usage.
        They are computed on-demand when loading from cache.
        """
        catalog_file = self._get_catalog_file_path()
        
        try:
            catalog_data = {
                'catalog_wip': self.catalog_wip,
                'catalog_releases': self.catalog_releases,
                # catalog_responses_wip and catalog_responses_releases are NOT saved
                # to reduce memory usage - they are computed on-demand when loading
                'catalog_sorted_keys_wip': self.catalog_sorted_keys_wip,
                'catalog_sorted_keys_releases': self.catalog_sorted_keys_releases,
                'subdirectory_counts_wip': self.subdirectory_counts_wip,
                'subdirectory_counts_releases': self.subdirectory_counts_releases,
                'systems_list': self.systems_list,
                'system_versions': self.system_versions,
                'system_snapshot_paths': self.system_snapshot_paths,
                'system_gamelist_date_wip': self.system_gamelist_date_wip,
                'system_gamelist_date_releases': self.system_gamelist_date_releases,
                '_catalog_timestamp': self._catalog_timestamp
            }
            
            # Save catalog
            with open(catalog_file, 'wb') as f:
                pickle.dump(catalog_data, f)
            
            # Update tracked mtime after saving
            self._catalog_file_mtime = os.path.getmtime(catalog_file)
            
            logger.info(f"Saved catalog to cache: {catalog_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save catalog to cache: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _get_system_mappings(self) -> Dict[str, List[str]]:
        """Get mapping from batocera_system/retrobat_system to catalog system IDs.
        
        Returns:
            Dictionary mapping user system names to list of catalog system IDs.
            Example: {'nesicax': ['batocera_nesicax', 'retrobat_nesicax']}
        """
        from app.database import SessionLocal, System
        
        mapping = {}  # {user_system: [catalog_system_ids]}
        
        try:
            db = SessionLocal()
            try:
                systems = db.query(System).filter(System.enabled == True).all()
                for system in systems:
                    # Map batocera_system to this catalog system
                    if system.batocera_system:
                        if system.batocera_system not in mapping:
                            mapping[system.batocera_system] = []
                        mapping[system.batocera_system].append(system.id)
                    
                    # Map retrobat_system to this catalog system
                    if system.retrobat_system:
                        if system.retrobat_system not in mapping:
                            mapping[system.retrobat_system] = []
                        mapping[system.retrobat_system].append(system.id)
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to load system mappings from database: {e}")
        
        return mapping
    
    def _get_enabled_systems_set(self) -> set:
        """Get set of enabled system IDs from database."""
        enabled_systems = set()
        try:
            from app.database import get_db, System
            db = next(get_db())
            enabled_systems_db = db.query(System).filter(System.enabled == True).all()
            enabled_systems = {s.id for s in enabled_systems_db}
            logger.debug(f"Found {len(enabled_systems)} enabled systems in database")
        except Exception as e:
            logger.warning(f"Could not load enabled systems from database: {e}. Will use all loaded systems.")
            # If database check fails, use systems from self.systems_list (which should already be filtered)
            if self._gamelists_loaded:
                enabled_systems = {s['id'] for s in self.systems_list}
        return enabled_systems
    
    def build_search_index(self, catalog_type: str = 'wip', force_build: bool = False) -> Dict:
        """Build a global partitioned search index with normalized game names.
        
        Only indexes games from systems that are enabled in the database.
        
        Args:
            catalog_type: 'wip' or 'releases' (default: 'wip')
            force_build: If True, build index even if cache exists. If False, only build if cache doesn't exist.
                        Set to True when called from refresh_catalog().
        
        Returns:
            Dictionary with search index structure
        """
        # Check in-memory cache first
        cache_key = f'search_index_{catalog_type}'
        index_built_flag = '_index_built_wip' if catalog_type == 'wip' else '_index_built_releases'
        index_attr = 'search_index_wip' if catalog_type == 'wip' else 'search_index_releases'
        
        if getattr(self, index_built_flag, False) and cache_key in self.cache:
            logger.info(f"Returning in-memory cached search index ({catalog_type})")
            return self.cache[cache_key]
        
        # Try loading from pickle cache
        if not force_build:
            cached_index = self._load_index_from_cache(catalog_type)
            if cached_index:
                setattr(self, index_attr, cached_index)
                setattr(self, index_built_flag, True)
                self.cache[cache_key] = cached_index
                logger.info(f"Loaded search index from cache ({catalog_type})")
                return cached_index
            else:
                # Cache doesn't exist and force_build is False - don't build
                logger.warning(f"Search index cache not found for {catalog_type} and force_build=False")
                logger.warning("Index will not be available until /refresh endpoint is called")
                empty_index = {}
                setattr(self, index_attr, empty_index)
                setattr(self, index_built_flag, False)
                return empty_index
        
        # Build new index (only when force_build=True, typically from refresh_catalog)
        logger.info(f"Building global search index ({catalog_type})...")
        index = {}
        
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Select appropriate catalog based on catalog_type
        if catalog_type == 'wip':
            catalog = self.catalog_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
        else:
            catalog = self.catalog_wip
        
        # Get enabled systems from database
        enabled_systems = self._get_enabled_systems_set()
        
        systems = self.get_systems()
        total_games = 0
        
        # Helper function to normalize media path
        def get_media_path(media_type, game_data, system_id):
            """Normalize media path by adding system prefix and snapshot path if needed.
            
            Media paths in catalog are stored exactly as in XML (no normalization),
            so we need to normalize them here for search results.
            
            For WIP: returns {system_id}/{media_path}
            For Releases: returns {system_id}/{snapshot_dir_path}/{media_path}
            """
            path = game_data.get(media_type, '')
            if not path:
                return ''
            
            # Strip leading ./ if present
            path = path.lstrip('./')
            
            # For Releases catalog, prepend snapshot directory path
            if catalog_type == 'releases':
                snapshot_path = self.system_snapshot_paths.get(system_id, '')
                if snapshot_path:
                    # snapshot_path is in format ".zfs/snapshot/v10.5/" (with leading dot)
                    # Ensure it ends with / for proper joining
                    snapshot_prefix = snapshot_path.rstrip('/') + '/'
                    # Remove system prefix if already present
                    if path.startswith(f"{system_id}/"):
                        path = path[len(system_id) + 1:]
                    # Add system prefix and snapshot path
                    return f"{system_id}/{snapshot_prefix}{path}"
            
            # For WIP, ensure system prefix is present
            if path.startswith(f"{system_id}/"):
                # Already has system prefix, return as-is
                return path
            else:
                # Add system prefix
                return f"{system_id}/{path}"
        
        for system in systems:
            system_id = system['id']
            
            # Skip if system is not enabled
            if enabled_systems and system_id not in enabled_systems:
                logger.debug(f"Skipping disabled system in search index: {system_id}")
                continue
            
            if system_id not in catalog:
                continue
            
            try:
                system_catalog = catalog[system_id]
                
                for rompath, game_data in system_catalog.items():
                    game_name = game_data.get('name', '')
                    if not game_name:
                        continue
                    
                    # Normalize game name (without parentheses, without articles)
                    normalized = normalize_game_name(game_name, remove_paranthesis=True, remove_articles=True)
                    
                    if not normalized:
                        continue
                    
                    # Get first letter (use '#' for non-alphabetic)
                    first_letter = normalized[0].upper() if normalized[0].isalpha() else '#'
                    
                    # Initialize first letter if needed
                    if first_letter not in index:
                        index[first_letter] = {}
                    
                    # Store only minimal data in index: id, name, system
                    # Full game data will be built on-demand from catalog when returning results
                    minimal_game_data = {
                        'id': rompath,
                        'name': game_name,
                        'system': system_id
                    }
                    
                    # Add to index (normalized name -> list of games)
                    if normalized not in index[first_letter]:
                        index[first_letter][normalized] = []
                    
                    index[first_letter][normalized].append(minimal_game_data)
                    total_games += 1
                    
            except Exception as e:
                logger.error(f"Error building index for system {system_id}: {e}")
                continue
        
        # Store index in appropriate attribute
        setattr(self, index_attr, index)
        setattr(self, index_built_flag, True)
        self.cache[cache_key] = index
        
        # Save to cache after building
        self._save_index_to_cache(index, catalog_type)
        
        logger.info(f"Search index built ({catalog_type}): {len(index)} letters, {total_games} games indexed")
        return index
    
    def _normalize_game_path(self, path: str, system_id: str = None) -> Tuple[Optional[str], Optional[str]]:
        """Normalize a game path from user gamelist to match catalog structure.
        
        Args:
            path: Path from user gamelist.xml (e.g., "./game.zip", "system/game.zip", "game.zip")
            system_id: Optional system ID to help normalize
            
        Returns:
            Tuple of (system_id, rompath) or (None, None) if unable to normalize
        """
        if not path:
            return None, None
        
        # Remove leading ./
        normalized = path.lstrip('./')
        
        # If path contains a system prefix (e.g., "system/game.zip")
        # Extract system and rompath
        parts = normalized.split('/', 1)
        if len(parts) == 2:
            # Has system prefix
            potential_system, rompath = parts
            if system_id and potential_system == system_id:
                # Matches expected system
                return system_id, rompath
            elif system_id is None:
                # Try to determine system from path
                return potential_system, rompath
            else:
                # System mismatch, but return what we have
                return potential_system, rompath
        else:
            # No system prefix - need system_id to proceed
            if system_id:
                return system_id, normalized
            # Can't determine system without system_id
            return None, normalized
    
    def _aggregate_users_playcount_gametime(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """Parse user gamelist.xml files from tar.gz archives and aggregate playcount/gametime.
        
        Scans backend/data/users_gamelist/*/ for all *.tar.gz files, extracts them,
        parses gamelist.xml files, and aggregates playcount and gametime across all users.
        
        Returns:
            Dictionary: {system_id: {rompath: {'playcount': int, 'gametime': int}}}
        """
        aggregated_stats = {}  # {system_id: {rompath: {'playcount': int, 'gametime': int}}}
        
        # Determine users_gamelist path
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent.parent.parent / 'data' / 'users_gamelist',  # backend/data/users_gamelist
            Path(__file__).parent.parent.parent.parent / 'data' / 'users_gamelist',  # project_root/data/users_gamelist
            Path('/opt/batocera-games-catalog/data/users_gamelist'),  # Production
            Path(settings.USERS_GAMELIST_PATH),  # From config
        ]
        
        users_gamelist_path = None
        for path in possible_paths:
            if path.exists() and path.is_dir():
                users_gamelist_path = path
                break
        
        if not users_gamelist_path:
            logger.warning(f"Users gamelist directory not found. Tried: {possible_paths}")
            return aggregated_stats
        
        logger.info(f"Scanning for user gamelist files in: {users_gamelist_path}")
        
        # Create temporary directory for extraction
        temp_dir = tempfile.mkdtemp(prefix='gamelist_extract_')
        logger.info(f"Created temporary extraction directory: {temp_dir}")
        
        try:
            # Find all tar.gz files in user directories
            tar_files = []
            for user_dir in users_gamelist_path.iterdir():
                if not user_dir.is_dir():
                    continue
                
                logger.info(f"Scanning user directory: {user_dir.name}")
                for tar_file in user_dir.glob('*.tar.gz'):
                    tar_files.append(tar_file)
                    logger.info(f"  Found tar.gz: {tar_file.name} ({tar_file.stat().st_size} bytes)")
            
            if not tar_files:
                logger.info("No tar.gz files found in users_gamelist directory")
                return aggregated_stats
            
            logger.info(f"Found {len(tar_files)} tar.gz file(s) to process")
            
            # Process each tar.gz file
            for tar_file in tar_files:
                try:
                    logger.info(f"Processing tar.gz: {tar_file.name}")
                    # Extract to temporary directory
                    extract_dir = os.path.join(temp_dir, tar_file.stem)
                    os.makedirs(extract_dir, exist_ok=True)
                    
                    with tarfile.open(tar_file, 'r:gz') as tar:
                        tar.extractall(extract_dir)
                        logger.info(f"  Extracted {len(tar.getnames())} files to {extract_dir}")
                    
                    # Find all gamelist.xml files (may be in subdirectories)
                    gamelist_files = []
                    for root, dirs, files in os.walk(extract_dir):
                        if 'gamelist.xml' in files:
                            gamelist_files.append(os.path.join(root, 'gamelist.xml'))
                    
                    logger.info(f"  Found {len(gamelist_files)} gamelist.xml file(s)")
                    
                    # Parse each gamelist.xml
                    for gamelist_path in gamelist_files:
                        try:
                            # Try to determine system from directory structure
                            # gamelist.xml is typically in: extract_dir/system_id/gamelist.xml
                            # or extract_dir/system_id/.../gamelist.xml
                            rel_path = os.path.relpath(gamelist_path, extract_dir)
                            path_parts = rel_path.split(os.sep)
                            
                            # If gamelist.xml is in a subdirectory, use that as system_id
                            system_id_from_path = None
                            if len(path_parts) > 1:
                                # First directory component is likely the system_id
                                system_id_from_path = path_parts[0]
                            
                            tree = ET.parse(gamelist_path)
                            root = tree.getroot()
                            
                            games_with_stats = 0
                            games_processed = 0
                            
                            for game in root.findall('.//game'):
                                games_processed += 1
                                # Get path
                                path_elem = game.find('path')
                                if path_elem is None or not path_elem.text:
                                    continue
                                
                                game_path = path_elem.text
                                
                                # Get playcount and gametime
                                playcount_elem = game.find('playcount')
                                gametime_elem = game.find('gametime')
                                
                                playcount = 0
                                gametime = 0
                                
                                if playcount_elem is not None and playcount_elem.text:
                                    try:
                                        playcount = int(playcount_elem.text)
                                    except (ValueError, TypeError):
                                        pass
                                
                                if gametime_elem is not None and gametime_elem.text:
                                    try:
                                        gametime = int(gametime_elem.text)
                                    except (ValueError, TypeError):
                                        pass
                                
                                # Skip corrupted entries (EmulationStation runaway counter bug)
                                MAX_PLAYCOUNT = 5000
                                MAX_GAMETIME = 7_776_000  # 3 months in seconds
                                if playcount > MAX_PLAYCOUNT or gametime > MAX_GAMETIME:
                                    logger.warning(f"    Skipping corrupted stats for {game_path}: playcount={playcount}, gametime={gametime}")
                                    continue

                                # Skip if both are zero
                                if playcount == 0 and gametime == 0:
                                    continue
                                
                                # Normalize path
                                system_id, rompath = self._normalize_game_path(game_path, system_id_from_path)
                                
                                if not system_id or not rompath:
                                    # Couldn't determine system or rompath, skip
                                    logger.debug(f"    Skipping game (couldn't normalize path): {game_path} -> system_id={system_id}, rompath={rompath}")
                                    continue
                                
                                games_with_stats += 1
                                
                                # Initialize nested dictionaries if needed
                                if system_id not in aggregated_stats:
                                    aggregated_stats[system_id] = {}
                                    logger.debug(f"    Created new system entry: {system_id}")
                                if rompath not in aggregated_stats[system_id]:
                                    aggregated_stats[system_id][rompath] = {'playcount': 0, 'gametime': 0}
                                
                                # Add to aggregated stats
                                aggregated_stats[system_id][rompath]['playcount'] += playcount
                                aggregated_stats[system_id][rompath]['gametime'] += gametime
                            
                        except Exception as e:
                            logger.error(f"Error parsing gamelist.xml from {gamelist_path}: {e}")
                            continue
                
                except Exception as e:
                    logger.error(f"Error processing tar.gz file {tar_file}: {e}")
                    continue
        
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Error cleaning up temp directory {temp_dir}: {e}")
        
        total_games = sum(len(games) for games in aggregated_stats.values())
        logger.info(f"Aggregated playcount/gametime stats for {total_games} games across {len(aggregated_stats)} systems")
        
        return aggregated_stats
    
    def _aggregate_download_counts(self) -> Dict[str, Dict[str, int]]:
        """Aggregate download counts from download_archive table.
        
        Returns:
            Dictionary: {system_id: {rompath: count}}
        """
        aggregated_stats = {}  # {system_id: {rompath: count}}
        
        try:
            db = SessionLocal()
            try:
                # Query download counts by system and rompath
                # Filter for successful downloads only
                results = db.query(
                    DownloadArchive.system,
                    DownloadArchive.rompath,
                    func.count(DownloadArchive.id).label('count')
                ).filter(
                    DownloadArchive.download_status == 'completed'
                ).group_by(
                    DownloadArchive.system,
                    DownloadArchive.rompath
                ).all()
                
                for system_id, rompath, count in results:
                    if not system_id or not rompath:
                        continue
                        
                    if system_id not in aggregated_stats:
                        aggregated_stats[system_id] = {}
                    
                    aggregated_stats[system_id][rompath] = count
                    
                total_downloads = sum(sum(sys_stats.values()) for sys_stats in aggregated_stats.values())
                logger.info(f"Aggregated download counts: {total_downloads} total downloads across {len(aggregated_stats)} systems")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error aggregating download counts: {e}")
            
        return aggregated_stats

    def refresh_catalog(self) -> dict:
        """Refresh catalog cache and search index by clearing cache and reloading everything."""
        logger.info("Refreshing catalog cache and search index (WIP and Releases)...")
        
        # Clear all caches
        self.cache = {}
        self.catalog_wip = {}  # Clear WIP catalog
        self.catalog_releases = {}  # Clear Releases catalog
        self.catalog_sorted_keys_wip = {}  # Clear pre-sorted keys
        self.catalog_sorted_keys_releases = {}
        # catalog_responses removed - no longer stored
        self.systems_list = []
        self.search_index_wip = {}  # Clear search indexes
        self.search_index_releases = {}
        self.subdirectory_counts_wip = {}  # Clear subdirectory counts
        self.subdirectory_counts_releases = {}
        self.system_versions = {}  # Clear version info
        self.system_snapshot_paths = {}  # Clear snapshot path info
        
        # Reset flags
        self._gamelists_loaded = False
        self._index_built_wip = False
        self._index_built_releases = False
        
        # Clear hardware mappings
        self.system_hardware = {}
        self.system_manufacturer = {}
        self.system_release = {}
        self.system_fullname = {}
        
        # Delete cache file to force full reload (ensures enabled systems are re-queried from database)
        catalog_file = self._get_catalog_file_path()
        if os.path.exists(catalog_file):
            try:
                os.remove(catalog_file)
                logger.info(f"Deleted catalog cache file: {catalog_file}")
            except Exception as e:
                logger.warning(f"Could not delete catalog cache file {catalog_file}: {e}")
        
        # Reload everything (force generation from scratch)
        self.preload_all_gamelists(force_reload=True)
        
        # Clear any existing playcount/gametime from all games in catalogs
        # These should only come from user gamelists, not from system gamelist.xml files
        logger.info("Clearing playcount/gametime fields from catalogs (they will be replaced with aggregated user stats)...")
        for catalog in [self.catalog_wip, self.catalog_releases]:
            for system_id in catalog:
                for rompath, game_data in catalog[system_id].items():
                    # Remove playcount and gametime if they exist
                    if 'playcount' in game_data:
                        del game_data['playcount']
                    if 'gametime' in game_data:
                        del game_data['gametime']
        
        # Aggregate playcount and gametime from users' gamelist files
        logger.info("Aggregating playcount and gametime from users' gamelist files...")
        aggregated_stats = self._aggregate_users_playcount_gametime()
        
        logger.info(f"Aggregated stats summary: {len(aggregated_stats)} systems with stats")
        for system_id, games_stats in aggregated_stats.items():
            total_playcount = sum(s['playcount'] for s in games_stats.values())
            total_gametime = sum(s['gametime'] for s in games_stats.values())
            logger.info(f"  System {system_id}: {len(games_stats)} games, total playcount={total_playcount}, total gametime={total_gametime}")
        
        # Get system mappings from database (batocera_system/retrobat_system -> catalog system IDs)
        system_mappings = self._get_system_mappings()
        logger.info(f"Loaded system mappings: {len(system_mappings)} user systems mapped to catalog systems")
        
        # Merge aggregated stats into both catalogs
        catalog_types = ['WIP', 'Releases']
        for catalog_type_idx, catalog in enumerate([self.catalog_wip, self.catalog_releases]):
            catalog_type = catalog_types[catalog_type_idx]
            logger.info(f"Merging stats into {catalog_type} catalog...")
            merged_count = 0
            skipped_system_count = 0
            skipped_game_count = 0
            
            for user_system_id, games_stats in aggregated_stats.items():
                # Find catalog systems that match this user system via batocera_system/retrobat_system
                catalog_system_ids = system_mappings.get(user_system_id, [])
                
                # Also try direct match (in case user system name matches catalog system name)
                if user_system_id in catalog:
                    if user_system_id not in catalog_system_ids:
                        catalog_system_ids.append(user_system_id)
                
                if not catalog_system_ids:
                    logger.warning(f"  User system '{user_system_id}' not mapped to any catalog systems, skipping {len(games_stats)} games")
                    skipped_system_count += 1
                    continue
                
                logger.info(f"  User system '{user_system_id}' mapped to {len(catalog_system_ids)} catalog system(s): {catalog_system_ids}")
                
                # Merge stats into all matching catalog systems
                for catalog_system_id in catalog_system_ids:
                    if catalog_system_id not in catalog:
                        logger.debug(f"    Catalog system '{catalog_system_id}' not found in {catalog_type} catalog, skipping")
                        continue
                    
                    logger.debug(f"    Processing catalog system '{catalog_system_id}' ({len(games_stats)} games with stats)...")
                    
                    for rompath, stats in games_stats.items():
                        # Try to find the game in catalog
                        # rompath might match directly or might need normalization
                        matched = False
                        if rompath in catalog[catalog_system_id]:
                            catalog[catalog_system_id][rompath]['playcount'] = stats['playcount']
                            catalog[catalog_system_id][rompath]['gametime'] = stats['gametime']
                            merged_count += 1
                            matched = True
                        else:
                            # Try to match by normalized path (handle variations)
                            # Check all games in this system
                            catalog_normalized = rompath.lstrip('./')
                            
                            for catalog_rompath, game_data in catalog[catalog_system_id].items():
                                # Normalize both paths for comparison
                                cat_normalized = catalog_rompath.lstrip('./')
                                
                                if catalog_normalized == cat_normalized:
                                    game_data['playcount'] = stats['playcount']
                                    game_data['gametime'] = stats['gametime']
                                    merged_count += 1
                                    matched = True
                                    break
                            
                            if not matched:
                                skipped_game_count += 1
            
            logger.info(f"  {catalog_type} catalog merge complete: {merged_count} games merged, {skipped_system_count} systems skipped, {skipped_game_count} games not matched")
        
        logger.info("Finished merging playcount and gametime stats into catalogs")
        
        # Aggregate download counts from download_archive
        logger.info("Aggregating download counts from archive...")
        download_counts = self._aggregate_download_counts()
        
        if download_counts:
            logger.info(f"Merging download counts for {len(download_counts)} systems")
            for catalog in [self.catalog_wip, self.catalog_releases]:
                for system_id, rom_counts in download_counts.items():
                    if system_id not in catalog:
                        continue
                        
                    for rompath, count in rom_counts.items():
                        # Try exact match first
                        if rompath in catalog[system_id]:
                            catalog[system_id][rompath]['download_count'] = count
                        else:
                            # Try with ./ prefix
                            alt_path = f"./{rompath}" if not rompath.startswith("./") else rompath.lstrip("./")
                            if alt_path in catalog[system_id]:
                                catalog[system_id][alt_path]['download_count'] = count
                            else:
                                # Try normalized match
                                normalized = rompath.lstrip("./")
                                for cat_rompath, game_data in catalog[system_id].items():
                                    if cat_rompath.lstrip("./") == normalized:
                                        game_data['download_count'] = count
                                        break
        
        logger.info("Finished merging download counts into catalogs")
        
        # Update catalog timestamp to invalidate ETags and force clients to refresh
        # This ensures clients get the updated catalog with stats after refresh
        self._catalog_timestamp = time.time()
        logger.info(f"Updated catalog timestamp to {self._catalog_timestamp} to invalidate ETags (forcing cache refresh)")
        
        # Build search indexes with force_build=True to ensure they're generated
        self.build_search_index('wip', force_build=True)
        self.build_search_index('releases', force_build=True)
        
        # Save catalog and search index to cache
        self._save_catalog_to_cache()
        if hasattr(self, 'search_index_wip') and self.search_index_wip:
            self._save_index_to_cache(self.search_index_wip, 'wip')
        if hasattr(self, 'search_index_releases') and self.search_index_releases:
            self._save_index_to_cache(self.search_index_releases, 'releases')
        
        logger.info("Catalog cache and search index refreshed successfully")
        
        return {
            "success": True,
            "systems_count": len(self.systems_list),
            "total_games": sum(s['gameCount'] for s in self.systems_list),
            "media_version": int(self._catalog_timestamp),
        }
    
    def search_indexed_games(self, query: str, limit: int = 50, catalog_type: str = 'wip') -> List[Dict]:
        """Search games using the partitioned index.
        
        Only returns games from systems that are enabled in the database.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            catalog_type: 'wip' or 'releases' (default: 'wip')
        """
        if not query:
            return []
        
        # Normalize search query
        normalized_query = normalize_game_name(query, remove_paranthesis=True, remove_articles=True)
        
        if not normalized_query:
            return []
        
        # Select appropriate index and build if needed
        index_built_flag = '_index_built_wip' if catalog_type == 'wip' else '_index_built_releases'
        index_attr = 'search_index_wip' if catalog_type == 'wip' else 'search_index_releases'
        
        # Select appropriate catalog for enriching results
        if catalog_type == 'wip':
            raw_catalog = self.catalog_wip
        elif catalog_type == 'releases':
            raw_catalog = self.catalog_releases
        else:
            raw_catalog = self.catalog_wip
        
        # Build index if not already built
        if not getattr(self, index_built_flag, False):
            self.build_search_index(catalog_type)
        
        # Ensure search_index exists
        search_index = getattr(self, index_attr, {})
        if not search_index:
            self.build_search_index(catalog_type)
            search_index = getattr(self, index_attr, {})
        
        # Get enabled systems from database
        enabled_systems = self._get_enabled_systems_set()
        
        results = []
        query_lower = normalized_query.lower()
        
        # Search in all partitions
        for first_letter, games_dict in search_index.items():
            for normalized_name, games in games_dict.items():
                normalized_name_lower = normalized_name.lower()
                
                # Check if normalized query matches normalized name
                if query_lower in normalized_name_lower:
                    # Calculate relevance: 0=exact match, 1=starts with, 2=contains
                    if normalized_name_lower == query_lower:
                        relevance = 0  # Exact match
                    elif normalized_name_lower.startswith(query_lower):
                        relevance = 1  # Starts with
                    else:
                        relevance = 2  # Contains
                    
                    # Add all games with this normalized name, with relevance score
                    # Filter by enabled systems and build responses on-demand
                    for minimal_game in games:
                        system_id = minimal_game['system']
                        rompath = minimal_game['id']
                        
                        # Only include games from enabled systems
                        if enabled_systems and system_id not in enabled_systems:
                            continue
                        
                        # Build game response on-demand from raw catalog
                        enriched_game = None
                        raw_game_data = None
                        
                        if system_id in raw_catalog:
                            # Try exact match first
                            if rompath in raw_catalog[system_id]:
                                raw_game_data = raw_catalog[system_id][rompath]
                            else:
                                # Try with ./ prefix
                                alt_rompath = f'./{rompath}' if not rompath.startswith('./') else rompath.lstrip('./')
                                if alt_rompath in raw_catalog[system_id]:
                                    raw_game_data = raw_catalog[system_id][alt_rompath]
                                else:
                                    # Try normalized path matching
                                    rompath_normalized = rompath.lstrip('./')
                                    for catalog_rompath in raw_catalog[system_id].keys():
                                        cat_normalized = catalog_rompath.lstrip('./')
                                        if cat_normalized == rompath_normalized:
                                            raw_game_data = raw_catalog[system_id][catalog_rompath]
                                            break
                        
                        if raw_game_data:
                            # Build full response from raw catalog data
                            enriched_game = self._build_game_response(system_id, rompath, raw_game_data, catalog_type)
                            # Add playcount/gametime if present
                            if 'playcount' in raw_game_data:
                                enriched_game['playcount'] = raw_game_data['playcount']
                            if 'gametime' in raw_game_data:
                                enriched_game['gametime'] = raw_game_data['gametime']
                        else:
                            # Fallback: build minimal game dict from search index data
                            enriched_game = minimal_game.copy()
                            enriched_game['systemName'] = self.get_system_name(system_id)
                        
                        results.append((relevance, enriched_game))
        
        # Remove duplicates (same game might appear multiple times if indexed multiple ways)
        # Keep the one with the best relevance score
        seen = {}
        for relevance, game in results:
            game_key = (game['system'], game['id'])
            if game_key not in seen or seen[game_key][0] > relevance:
                seen[game_key] = (relevance, game)
        
        # Convert back to list of games with their relevance scores
        scored_results = [(relevance, game) for game_key, (relevance, game) in seen.items()]
        
        # Sort results: exact matches first, then starts-with, then contains, then by name
        scored_results.sort(key=lambda x: (
            x[0],  # Relevance score (0=exact, 1=starts with, 2=contains)
            normalize_game_name(x[1]['name'], remove_paranthesis=True, remove_articles=True).lower()
        ))
        
        # Extract games and limit results
        unique_results = [game for relevance, game in scored_results]
        return unique_results[:limit]
        
    def get_top_games(self, limit: int = 100, catalog_type: str = 'releases', sort_by: str = 'download_count') -> List[Dict]:
        """Get top games sorted by criteria.
        
        Args:
            limit: Maximum number of games to return
            catalog_type: 'wip' or 'releases'
            sort_by: 'download_count', 'playcount', or 'gametime'
            
        Returns:
            List of game dictionaries sorted by criteria
        """
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
            
        # Select appropriate catalog
        if catalog_type == 'wip':
            catalog = self.catalog_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
        else:
            catalog = self.catalog_releases
            
        all_games = []
        
        # Helper to safely get numeric value
        def get_value(data, key):
            val = data.get(key, 0)
            if isinstance(val, str):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return 0
            return val if isinstance(val, (int, float)) else 0

        # Iterate over all systems and games
        for system_id, system_games in catalog.items():
            for rompath, game_data in system_games.items():
                val = get_value(game_data, sort_by)
                if val > 0:
                    all_games.append((system_id, rompath, game_data))
                    
        # Sort by criteria (descending)
        all_games.sort(key=lambda x: get_value(x[2], sort_by), reverse=True)
        
        # Take top N
        top_games = all_games[:limit]
        
        # Build responses
        results = []
        for system_id, rompath, game_data in top_games:
            game_response = self._build_game_response(system_id, rompath, game_data, catalog_type)
            # Ensure all stats are included
            game_response['download_count'] = game_data.get('download_count', 0)
            if 'playcount' in game_data:
                game_response['playcount'] = game_data['playcount']
            if 'gametime' in game_data:
                game_response['gametime'] = game_data['gametime']
            results.append(game_response)
            
        return results

    def get_top_systems(self, limit: int = 100, catalog_type: str = 'releases', sort_by: str = 'download_count') -> List[Dict]:
        """Get top systems sorted by criteria (aggregated from games).
        
        Args:
            limit: Maximum number of systems to return
            catalog_type: 'wip' or 'releases'
            sort_by: 'download_count', 'playcount', or 'gametime'
            
        Returns:
            List of system dictionaries with aggregated stats
        """
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
            
        # Select appropriate catalog
        if catalog_type == 'wip':
            catalog = self.catalog_wip
        elif catalog_type == 'releases':
            catalog = self.catalog_releases
        else:
            catalog = self.catalog_releases
            
        system_stats = {}
        
        # Helper to safely get numeric value
        def get_value(data, key):
            val = data.get(key, 0)
            if isinstance(val, str):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return 0
            return val if isinstance(val, (int, float)) else 0

        # Iterate over all systems and games
        for system_id, system_games in catalog.items():
            total_val = 0
            for rompath, game_data in system_games.items():
                val = get_value(game_data, sort_by)
                total_val += val
            
            if total_val > 0:
                system_stats[system_id] = total_val
                
        # Sort by total value (descending)
        sorted_systems = sorted(system_stats.items(), key=lambda x: x[1], reverse=True)
        
        # Take top N
        top_systems = sorted_systems[:limit]
        
        # Build results
        results = []
        for system_id, total_val in top_systems:
            # Get system info
            system_info = next((s for s in self.systems_list if s['id'] == system_id), None)
            
            if system_info:
                result = {
                    'id': system_id,
                    'name': system_info['name'],
                    'gameCount': system_info['gameCount'],
                    'hardware': system_info['hardware'],
                    'manufacturer': system_info['manufacturer'],
                    'release': system_info['release'],
                    sort_by: total_val
                }
                results.append(result)
            
        return results

