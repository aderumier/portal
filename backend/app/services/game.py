"""Game catalog service for parsing gamelist.xml files."""
import os
import xml.etree.ElementTree as ET
import logging
import pickle
import hashlib
import time
from typing import List, Dict, Optional
from pathlib import Path
from app.config import settings
from app.services.game_utils import normalize_game_name

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
        self.search_index = {}  # Partitioned search index: search_index[first_letter][normalized_name] = [games]
        self._index_built = False
        self.catalog = {}  # Pre-processed catalog: catalog[system_id][rompath] = {game fields dict}
        self.catalog_sorted_keys = {}  # Pre-sorted rompaths per system: catalog_sorted_keys[system_id] = [sorted rompaths by name]
        self.catalog_responses = {}  # Pre-computed response dictionaries: catalog_responses[system_id][rompath] = {response dict}
        self.systems_list = []  # Cached systems list with game counts
        self._gamelists_loaded = False
        self.system_hardware = {}  # Cache: system_id -> hardware category
        self.system_manufacturer = {}  # Cache: system_id -> manufacturer
        self.system_release = {}  # Cache: system_id -> release year
        self.system_fullname = {}  # Cache: system_id -> full name
        self._hardware_loaded = False
        self.subdirectory_counts = {}  # Cache: system_id -> {subdirectory: count}
        self._catalog_timestamp = None  # Timestamp when catalog was last loaded/refreshed for ETag generation
        
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
    
    def _load_system_hardware(self) -> Dict[str, str]:
        """Load system hardware categories, manufacturers, release years, and full names from es_systems*.cfg files.
        
        Parses es_systems.cfg first, then es_systems_*.cfg files which can override or add systems.
        Stores hardware category, manufacturer, release year, and full name for each system.
        
        Returns:
            dict: Mapping of system_id -> hardware category
        """
        logger.info("_load_system_hardware() called")
        if self._hardware_loaded:
            logger.info(f"Hardware already loaded, returning {len(self.system_hardware)} systems")
            return self.system_hardware
        
        hardware_map = {}
        manufacturer_map = {}
        release_map = {}
        fullname_map = {}
        
        # Try multiple paths to find data/systemscfg directory
        # game.py is at: backend/app/services/game.py
        # We need to go up 4 levels to reach project root: backend/app/services -> backend/app -> backend -> project_root
        # 1. Relative to project root (development): project_root/data/systemscfg
        # 2. Relative to installation directory (production: /opt/batocera-games-catalog)
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / 'data' / 'systemscfg',  # Development: project_root/data/systemscfg
            Path('/opt/batocera-games-catalog/data/systemscfg'),  # Production installation
            Path(__file__).parent.parent.parent / 'data' / 'systemscfg',  # Fallback: backend/data/systemscfg (if data is in backend)
        ]
        
        logger.info(f"Searching for systemscfg directory in: {possible_paths}")
        systemcfg_dir = None
        for path in possible_paths:
            logger.debug(f"Checking path: {path} (exists: {path.exists()})")
            if path.exists():
                systemcfg_dir = path
                logger.info(f"Found systemscfg directory at: {systemcfg_dir}")
                break
        
        if not systemcfg_dir:
            logger.error(f"System config directory not found. Tried: {possible_paths}")
            self._hardware_loaded = True
            return hardware_map
        
        # First, parse es_systems.cfg
        main_config = systemcfg_dir / 'es_systems.cfg'
        logger.info(f"Checking for main config file: {main_config} (exists: {main_config.exists()})")
        if main_config.exists():
            try:
                logger.info(f"Parsing {main_config}")
                tree = ET.parse(main_config)
                root = tree.getroot()
                logger.debug(f"Root element: {root.tag}")
                # The root should be <systemList>, find all <system> elements
                systems = root.findall('.//system')
                logger.info(f"Found {len(systems)} systems in {main_config.name}")
                parsed_count = 0
                for system in systems:
                    name_elem = system.find('name')
                    hardware_elem = system.find('hardware')
                    manufacturer_elem = system.find('manufacturer')
                    release_elem = system.find('release')
                    fullname_elem = system.find('fullname')
                    if name_elem is not None and name_elem.text and hardware_elem is not None and hardware_elem.text:
                        system_id = name_elem.text.strip()
                        hardware = hardware_elem.text.strip()
                        manufacturer = manufacturer_elem.text.strip() if manufacturer_elem is not None and manufacturer_elem.text else 'Unknown'
                        release = release_elem.text.strip() if release_elem is not None and release_elem.text else 'Unknown'
                        fullname = fullname_elem.text.strip() if fullname_elem is not None and fullname_elem.text else None
                        if system_id and hardware:
                            hardware_map[system_id] = hardware
                            manufacturer_map[system_id] = manufacturer
                            release_map[system_id] = release
                            if fullname:
                                fullname_map[system_id] = fullname
                            parsed_count += 1
                            if parsed_count <= 5:  # Log first 5 for debugging
                                logger.info(f"Loaded hardware for {system_id}: {hardware}, manufacturer: {manufacturer}, release: {release}, fullname: {fullname}")
                    else:
                        # Log missing elements for debugging (only first few)
                        if parsed_count < 3:
                            if name_elem is None or not name_elem.text:
                                logger.warning(f"System missing <name> element in {main_config.name}")
                            if hardware_elem is None or not hardware_elem.text:
                                logger.warning(f"System missing <hardware> element in {main_config.name}")
                logger.info(f"Successfully parsed {parsed_count} systems from {main_config.name}")
            except Exception as e:
                logger.error(f"Error parsing {main_config}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.error(f"Main config file not found: {main_config}")
        
        # Then, parse all es_systems_*.cfg files (these can override or add systems)
        additional_files = sorted(systemcfg_dir.glob('es_systems_*.cfg'))
        logger.info(f"Found {len(additional_files)} additional es_systems_*.cfg files")
        for cfg_file in additional_files:
            if cfg_file.name == 'es_systems.cfg':
                continue  # Skip main file, already processed
            try:
                logger.debug(f"Parsing {cfg_file.name}")
                tree = ET.parse(cfg_file)
                root = tree.getroot()
                systems = root.findall('.//system')
                logger.debug(f"Found {len(systems)} systems in {cfg_file.name}")
                parsed_count = 0
                for system in systems:
                    name_elem = system.find('name')
                    hardware_elem = system.find('hardware')
                    manufacturer_elem = system.find('manufacturer')
                    release_elem = system.find('release')
                    fullname_elem = system.find('fullname')
                    if name_elem is not None and name_elem.text and hardware_elem is not None and hardware_elem.text:
                        system_id = name_elem.text.strip()
                        hardware = hardware_elem.text.strip()
                        manufacturer = manufacturer_elem.text.strip() if manufacturer_elem is not None and manufacturer_elem.text else 'Unknown'
                        release = release_elem.text.strip() if release_elem is not None and release_elem.text else 'Unknown'
                        fullname = fullname_elem.text.strip() if fullname_elem is not None and fullname_elem.text else None
                        if system_id and hardware:
                            # Override or add (later files override earlier ones)
                            hardware_map[system_id] = hardware
                            manufacturer_map[system_id] = manufacturer
                            release_map[system_id] = release
                            if fullname:
                                fullname_map[system_id] = fullname
                            parsed_count += 1
                if parsed_count > 0:
                    logger.debug(f"Parsed {parsed_count} systems from {cfg_file.name}")
            except Exception as e:
                logger.error(f"Error parsing {cfg_file}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        self.system_hardware = hardware_map
        self.system_manufacturer = manufacturer_map
        self.system_release = release_map
        self.system_fullname = fullname_map
        self._hardware_loaded = True
        logger.info(f"=== Loaded hardware categories for {len(hardware_map)} systems ===")
        logger.info(f"=== Loaded manufacturers for {len(manufacturer_map)} systems ===")
        logger.info(f"=== Loaded release years for {len(release_map)} systems ===")
        logger.info(f"=== Loaded full names for {len(fullname_map)} systems ===")
        if hardware_map:
            # Log a few examples for debugging
            sample_systems = [(k, hardware_map[k], manufacturer_map.get(k, 'Unknown'), release_map.get(k, 'Unknown'), fullname_map.get(k, None)) for k in list(hardware_map.keys())[:10]]
            logger.info(f"Sample mappings (first 10): {sample_systems}")
        else:
            logger.warning("No hardware mappings loaded! Check if es_systems.cfg files exist and are properly formatted.")
        return hardware_map
    
    def preload_all_gamelists(self) -> None:
        """Preload all gamelist.xml files into memory at startup."""
        if self._gamelists_loaded:
            logger.info("Gamelists already loaded")
            return
        
        logger.info("Preloading all gamelist.xml files into memory...")
        
        # Load system hardware mapping once (parsed and kept in memory)
        if not self._hardware_loaded:
            self._load_system_hardware()
        
        # Get enabled systems from database
        enabled_systems = set()
        try:
            from app.database import get_db, System
            db = next(get_db())
            enabled_systems_db = db.query(System).filter(System.enabled == True).all()
            enabled_systems = {s.id for s in enabled_systems_db}
            logger.info(f"Found {len(enabled_systems)} enabled systems in database")
        except Exception as e:
            logger.warning(f"Could not load enabled systems from database: {e}. Will load all systems.")
        
        systems = []
        self.catalog = {}  # catalog[system_id][rompath] = {game fields dict}
        self.catalog_responses = {}  # catalog_responses[system_id][rompath] = {response dict}
        
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
            
            gamelist_path = os.path.join(dir_path, 'gamelist.xml')
            if not os.path.isfile(gamelist_path) or not os.access(gamelist_path, os.R_OK):
                logger.warning(f"No gamelist.xml found for system: {dir_name}")
                continue
            
            # Skip if system is not enabled in database (if database check succeeded)
            if enabled_systems and dir_name not in enabled_systems:
                logger.debug(f"Skipping disabled system: {dir_name}")
                continue
            
            # Parse XML and build catalog dictionary (excluding hidden games)
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                
                # Initialize catalog entry for this system
                self.catalog[dir_name] = {}
                
                # Helper function to normalize media path (defined once, outside loop)
                def normalize_media_path(path_value: str) -> str:
                    """Normalize media path by adding system prefix if needed."""
                    if not path_value:
                        return ''
                    path = path_value.lstrip('./')
                    if not path.startswith(f"{dir_name}/"):
                        path = f"{dir_name}/{path}"
                    return path
                
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
                    game_data = {}
                    for child in game:
                        tag = child.tag
                        text = child.text or ''
                        game_data[tag] = text
                    
                    # Ensure 'path' field exists (use rompath)
                    game_data['path'] = rompath
                    
                    # Pre-compute catalog_image with priority: thumbnail > boxart > extra1 > image
                    thumbnail = game_data.get('thumbnail', '')
                    boxart = game_data.get('boxart', '')
                    extra1 = game_data.get('extra1', '')
                    image = game_data.get('image', '')
                    
                    # Select best image using priority and normalize it
                    if thumbnail:
                        catalog_image = normalize_media_path(thumbnail)
                    elif boxart:
                        catalog_image = normalize_media_path(boxart)
                    elif extra1:
                        catalog_image = normalize_media_path(extra1)
                    elif image:
                        catalog_image = normalize_media_path(image)
                    else:
                        catalog_image = ''
                    
                    # Add pre-computed catalog_image to game_data
                    game_data['catalog_image'] = catalog_image
                    
                    # Store in catalog: catalog[system][rompath] = game_data
                    self.catalog[dir_name][rompath] = game_data
                    games_list.append((rompath, game_data))
                    game_count += 1
                
                # Pre-sort games by name (case-insensitive) and store sorted keys
                games_list.sort(key=lambda x: x[1].get('name', '').lower())
                self.catalog_sorted_keys[dir_name] = [rompath for rompath, _ in games_list]
                
                # Compute subdirectory counts (pre-compute during catalog build)
                # First pass: collect all hidden folder paths
                hidden_directories = set()
                for folder in root.findall('.//folder'):
                    if _is_folder_hidden(folder):
                        folder_path = folder.findtext('path', '')
                        if folder_path:
                            # Normalize the path
                            path = folder_path.lstrip('./')
                            if path.startswith(f"{dir_name}/"):
                                path = path[len(dir_name) + 1:]
                            # Remove trailing slash if present
                            path = path.rstrip('/')
                            hidden_directories.add(path)
                
                # Second pass: count games by subdirectory, skipping games in hidden directories
                subdirectory_counts = {}
                for rompath, game_data in games_list:
                    # Check if game is inside a hidden directory
                    subdir = self._get_game_subdirectory(rompath, dir_name)
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
                    subdirectory_counts[key] = subdirectory_counts.get(key, 0) + 1
                
                # Store pre-computed subdirectory counts
                self.subdirectory_counts[dir_name] = subdirectory_counts
                
                # Pre-compute system name for response structure
                # Use fullname if available, otherwise fall back to get_system_name
                base_system_id_temp = dir_name
                if dir_name.endswith('_batocera'):
                    base_system_id_temp = dir_name[:-9]
                elif dir_name.endswith('_retrobat'):
                    base_system_id_temp = dir_name[:-9]
                elif dir_name.endswith('_lite'):
                    base_system_id_temp = dir_name[:-5]
                
                fullname_temp = self.system_fullname.get(base_system_id_temp, None)
                if not fullname_temp and len(self.system_fullname) > 0:
                    fullname_temp = self.system_fullname.get(dir_name, None)
                
                system_name_temp = fullname_temp if fullname_temp else self.get_system_name(base_system_id_temp)
                
                # Pre-compute response structures for all games (ready to return, no dict building needed)
                self.catalog_responses[dir_name] = {}
                for rompath, game_data in games_list:
                    # Create response-ready dictionary once during catalog build
                    self.catalog_responses[dir_name][rompath] = {
                        'id': rompath,
                        'name': game_data.get('name', ''),
                        'description': game_data.get('desc', ''),
                        'image': game_data.get('catalog_image', ''),
                        'system': dir_name,
                        'systemName': system_name_temp
                    }
                
                # Handle systems with _batocera, _retrobat, or _lite suffix
                # Map to base system name in es_systems.cfg
                base_system_id = dir_name
                suffix = None
                suffix_display = None
                
                if dir_name.endswith('_batocera'):
                    base_system_id = dir_name[:-9]  # Remove '_batocera' suffix
                    suffix = 'batocera'
                    suffix_display = '(Batocera)'
                elif dir_name.endswith('_retrobat'):
                    base_system_id = dir_name[:-9]  # Remove '_retrobat' suffix
                    suffix = 'retrobat'
                    suffix_display = '(Retrobat)'
                elif dir_name.endswith('_lite'):
                    base_system_id = dir_name[:-5]  # Remove '_lite' suffix
                    suffix = 'lite'
                    suffix_display = '(Lite)'
                
                # Get hardware category, manufacturer, release year, and full name from in-memory mapping
                # Try base system name first (for _batocera/_retrobat systems)
                hardware = self.system_hardware.get(base_system_id, 'unknown')
                manufacturer = self.system_manufacturer.get(base_system_id, 'Unknown')
                release = self.system_release.get(base_system_id, 'Unknown')
                fullname = self.system_fullname.get(base_system_id, None)
                
                # If not found with base name, try original dir_name
                if hardware == 'unknown' and len(self.system_hardware) > 0:
                    hardware = self.system_hardware.get(dir_name, 'unknown')
                    if hardware != 'unknown':
                        manufacturer = self.system_manufacturer.get(dir_name, 'Unknown')
                        release = self.system_release.get(dir_name, 'Unknown')
                        fullname = self.system_fullname.get(dir_name, None)
                
                # Log if hardware not found (for debugging)
                if hardware == 'unknown' and len(self.system_hardware) > 0:
                    # Check if there's a similar name (case-insensitive)
                    dir_name_lower = dir_name.lower()
                    base_system_id_lower = base_system_id.lower()
                    matching_systems = [k for k in self.system_hardware.keys() if k.lower() == dir_name_lower or k.lower() == base_system_id_lower]
                    if matching_systems:
                        matched_id = matching_systems[0]
                        logger.warning(f"System '{dir_name}' not found in hardware map, but found case-insensitive match: {matched_id}")
                        hardware = self.system_hardware[matched_id]
                        manufacturer = self.system_manufacturer.get(matched_id, 'Unknown')
                        release = self.system_release.get(matched_id, 'Unknown')
                        fullname = self.system_fullname.get(matched_id, None)
                    else:
                        logger.debug(f"Hardware not found for system '{dir_name}' (base: '{base_system_id}'). Available systems (first 20): {list(self.system_hardware.keys())[:20]}")
                
                # Use fullname if available, otherwise fall back to get_system_name
                display_name = fullname if fullname else self.get_system_name(base_system_id)
                
                # Append suffix to fullname if system has _batocera, _retrobat, or _lite suffix
                if suffix_display and display_name:
                    display_name = f"{display_name} {suffix_display}"
                
                # Skip systems with hardware category "library"
                if hardware.lower() == 'library':
                    logger.debug(f"Skipping system with library hardware category: {dir_name}")
                    continue
                
                system = {
                    'id': dir_name,
                    'name': display_name,
                    'gameCount': game_count,
                    'hardware': hardware,
                    'manufacturer': manufacturer,
                    'release': release
                }
                
                systems.append(system)
                logger.debug(f"Loaded {dir_name}: {game_count} games")
            except Exception as e:
                logger.error(f"Error parsing gamelist for {dir_name}: {e}")
                continue
        
        self.systems_list = systems
        self._gamelists_loaded = True
        self._catalog_timestamp = time.time()  # Set timestamp when catalog is loaded
        logger.info(f"Preloaded {len(systems)} systems with {sum(s['gameCount'] for s in systems)} total games (catalog timestamp: {self._catalog_timestamp})")
    
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
    
    def get_games_by_system(self, system: str, page: int = 1, limit: int = 12, search: str = '') -> List[Dict]:
        """Get games for a specific system with pagination and optional search (from memory cache)."""
        logger.info(f"Getting games for system: {system}, page: {page}, limit: {limit}")
        
        cache_key = f"games_{system}_{page}_{limit}_{search}"
        if cache_key in self.cache:
            logger.info(f"Returning cached games for: {cache_key}")
            return self.cache[cache_key]
        
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Check if system exists in pre-computed responses (games list uses catalog_responses)
        if system not in self.catalog_responses:
            logger.warning(f"System not found in catalog_responses: {system}")
            logger.warning(f"Available systems: {list(self.catalog_responses.keys())[:20]}")  # Log first 20 systems
            # Try case-insensitive match
            system_lower = system.lower()
            for loaded_system in self.catalog_responses.keys():
                if loaded_system.lower() == system_lower:
                    logger.info(f"Found case-insensitive match: '{system}' -> '{loaded_system}'")
                    system = loaded_system
                    break
            else:
                return []
        
        try:
            # Get pre-sorted rompaths (already sorted by name, case-insensitive)
            sorted_rompaths = self.catalog_sorted_keys.get(system, [])
            
            # Get pre-computed response structures (zero dict building overhead)
            system_responses = self.catalog_responses.get(system, {})
            
            # Filter by search query if provided (optimized: use pre-computed responses)
            if search:
                search_lower = search.lower()  # Cache lowercase search
                # Filter using pre-computed response data (no need to access system_catalog)
                sorted_rompaths = [
                    rompath for rompath in sorted_rompaths
                    if rompath in system_responses and search_lower in system_responses[rompath].get('name', '').lower()
                ]
            
            total_games = len(sorted_rompaths)
            logger.info(f"Total visible games found: {total_games}")
            
            # Apply pagination (already sorted, no need to sort again)
            offset = (page - 1) * limit
            paginated_rompaths = sorted_rompaths[offset:offset + limit]
            logger.info(f"Games after pagination: {len(paginated_rompaths)}")
            
            # Return pre-computed response structures (zero dict building overhead)
            # Responses are already built during catalog initialization - just return them
            games = [system_responses[rompath] for rompath in paginated_rompaths if rompath in system_responses]
            
            logger.info(f"Returning {len(games)} games")
            self.cache[cache_key] = games
            
            # Subdirectory counts are now pre-computed during catalog build
            # No need to compute them on-demand
            
            return games
        except Exception as e:
            logger.error(f"Failed to parse gamelist.xml for system {system}: {e}")
            return []
    
    def has_more_games(self, system: str, page: int, limit: int) -> bool:
        """Check if there are more games available for a system (from memory cache)."""
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        if system not in self.catalog:
            return False
        
        try:
            system_catalog = self.catalog[system]
            visible_games = len(system_catalog)  # Already filtered for hidden games
            
            return visible_games > (page * limit)
        except Exception as e:
            logger.error(f"Error checking for more games: {e}")
            return False
    
    def get_catalog_etag(self, system: str, search: str = '') -> str:
        """Generate ETag for a system's games list.
        
        ETag changes when catalog is reloaded/refreshed.
        Includes search query to differentiate ETags for different searches.
        
        Args:
            system: System ID
            search: Optional search query
            
        Returns:
            ETag string (e.g., 'W/"c64-t1234567890-search"')
        """
        # Use weak ETag (W/) to allow byte-range requests
        # Use timestamp (converted to int) for catalog version
        catalog_version = int(self._catalog_timestamp) if self._catalog_timestamp else 0
        search_hash = hashlib.md5(search.encode()).hexdigest()[:8] if search else 'all'
        return f'W/"{system}-t{catalog_version}-{search_hash}"'
    
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
                            'description': game_data.get('desc', ''),
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
    
    def get_game_by_id(self, game_id: str) -> Optional[Dict]:
        """Get a specific game by its ID (path from gamelist.xml).
        
        The game_id is the path as stored in gamelist.xml, which is relative to the system directory.
        Full path is always: GAMES_PATH/<systemid>/<rompath>
        """
        logger.info(f"Getting game by ID: {game_id}")
        
        # Clean up the game ID (remove leading ./ if present)
        clean_game_id = game_id.lstrip('./')
        logger.info(f"Cleaned game ID: {clean_game_id}")
        
        # Ensure catalog is loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Search all systems in catalog for a game with matching path
        # The path in gamelist.xml is relative to the system directory
        system_id = None
        found_game_data = None
        
        for loaded_system_id in self.catalog.keys():
            system_catalog = self.catalog[loaded_system_id]
            
            # Check if game exists in this system's catalog
            # Try both with and without ./ prefix
            if clean_game_id in system_catalog:
                system_id = loaded_system_id
                found_game_data = system_catalog[clean_game_id]
                logger.info(f"Game found in system {system_id} with path: {clean_game_id}")
                break
            elif f'./{clean_game_id}' in system_catalog:
                system_id = loaded_system_id
                found_game_data = system_catalog[f'./{clean_game_id}']
                logger.info(f"Game found in system {system_id} with path: ./{clean_game_id}")
                break
        
        if not found_game_data:
            logger.warning(f"Game not found in any system with path: {clean_game_id}")
            return None
        
        if not system_id or system_id not in self.catalog:
            logger.warning(f"System ID not determined or catalog not found: {system_id}")
            return None
        
        try:
            # Create a copy of game_data and add system-specific fields
            game_data = found_game_data.copy()
            game_data['id'] = clean_game_id
            game_data['system'] = system_id
            game_data['systemName'] = self.get_system_name(system_id)
            
            # Map 'desc' field from gamelist.xml to 'description' for frontend
            if 'desc' in game_data and 'description' not in game_data:
                game_data['description'] = game_data.get('desc', '')
            
            # Ensure required fields exist (with defaults if missing)
            if 'name' not in game_data:
                game_data['name'] = ''
            if 'description' not in game_data:
                game_data['description'] = ''
            
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
    
    def get_subdirectory_counts(self, system_id: str) -> dict:
        """Get subdirectory counts for a system.
        
        Subdirectory counts are pre-computed during catalog build for optimal performance.
        
        Args:
            system_id: System ID
            
        Returns:
            Dictionary mapping subdirectory names to game counts
        """
        # Ensure gamelists are loaded (this will pre-compute subdirectory counts)
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Subdirectory counts are now always pre-computed during catalog build
        return self.subdirectory_counts.get(system_id, {})
    
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
    
    def _get_index_hash_file_path(self) -> str:
        """Get the path to the index hash file (for cache invalidation)."""
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
        return os.path.join(data_dir, 'search_index.hash')
    
    def _calculate_games_hash(self) -> str:
        """Calculate a hash of all gamelist.xml files to detect changes."""
        systems = self.get_systems()
        hash_data = []
        
        for system in systems:
            system_id = system['id']
            gamelist_path = os.path.join(self.games_path, system_id, 'gamelist.xml')
            
            if os.path.isfile(gamelist_path) and os.access(gamelist_path, os.R_OK):
                # Use file modification time and size as hash input
                stat = os.stat(gamelist_path)
                hash_data.append(f"{system_id}:{stat.st_mtime}:{stat.st_size}")
        
        hash_string = '|'.join(sorted(hash_data))
        return hashlib.md5(hash_string.encode()).hexdigest()
    
    def _load_index_from_cache(self) -> Optional[Dict]:
        """Load search index from pickle file if it exists and is valid."""
        index_file = self._get_index_file_path()
        hash_file = self._get_index_hash_file_path()
        
        if not os.path.isfile(index_file) or not os.path.isfile(hash_file):
            logger.info("No cached search index found")
            return None
        
        try:
            # Check if hash matches current games state
            current_hash = self._calculate_games_hash()
            with open(hash_file, 'r') as f:
                cached_hash = f.read().strip()
            
            if current_hash != cached_hash:
                logger.info("Games have changed, invalidating cached index")
                return None
            
            # Load index from pickle
            with open(index_file, 'rb') as f:
                index = pickle.load(f)
            
            logger.info(f"Loaded search index from cache: {len(index)} letters")
            return index
            
        except Exception as e:
            logger.warning(f"Failed to load cached index: {e}")
            return None
    
    def _save_index_to_cache(self, index: Dict) -> None:
        """Save search index to pickle file."""
        index_file = self._get_index_file_path()
        hash_file = self._get_index_hash_file_path()
        
        try:
            # Save index
            with open(index_file, 'wb') as f:
                pickle.dump(index, f)
            
            # Save hash for cache validation
            current_hash = self._calculate_games_hash()
            with open(hash_file, 'w') as f:
                f.write(current_hash)
            
            logger.info(f"Saved search index to cache: {index_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save index to cache: {e}")
    
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
    
    def build_search_index(self) -> Dict:
        """Build a global partitioned search index with normalized game names.
        
        Only indexes games from systems that are enabled in the database.
        """
        # Check in-memory cache first
        if self._index_built and 'search_index' in self.cache:
            logger.info("Returning in-memory cached search index")
            return self.cache['search_index']
        
        # Try to load from pickle file
        cached_index = self._load_index_from_cache()
        if cached_index:
            self.search_index = cached_index
            self._index_built = True
            self.cache['search_index'] = cached_index
            return cached_index
        
        # Build new index
        logger.info("Building global search index...")
        index = {}
        
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Get enabled systems from database
        enabled_systems = self._get_enabled_systems_set()
        
        systems = self.get_systems()
        total_games = 0
        
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
                logger.debug(f"Skipping disabled system in search index: {system_id}")
                continue
            
            if system_id not in self.catalog:
                continue
            
            try:
                system_catalog = self.catalog[system_id]
                
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
                    
                    # Get game data with image priority: thumbnail > boxart > extra1 > image
                    # Only compute path for the first media type that exists (optimized)
                    display_image = ''
                    for media_type in ['thumbnail', 'boxart', 'extra1', 'image']:
                        raw_path = game_data.get(media_type, '')
                        if raw_path:
                            display_image = get_media_path(media_type, game_data, system_id)
                            break  # Found first available, stop checking
                    
                    result_game_data = {
                        'id': rompath,
                        'name': game_name,
                        'description': game_data.get('desc', ''),
                        'image': display_image,
                        'system': system_id,
                        'systemName': self.get_system_name(system_id)
                    }
                    
                    # Add to index (normalized name -> list of games)
                    if normalized not in index[first_letter]:
                        index[first_letter][normalized] = []
                    
                    index[first_letter][normalized].append(result_game_data)
                    total_games += 1
                    
            except Exception as e:
                logger.error(f"Error building index for system {system_id}: {e}")
                continue
        
        self.search_index = index
        self._index_built = True
        self.cache['search_index'] = index
        
        # Save to cache for next time
        self._save_index_to_cache(index)
        
        logger.info(f"Search index built: {len(index)} letters, {total_games} games indexed")
        return index
    
    def refresh_catalog(self) -> dict:
        """Refresh catalog cache and search index by clearing cache and reloading everything."""
        logger.info("Refreshing catalog cache and search index...")
        
        # Clear all caches
        self.cache = {}
        self.catalog = {}  # Clear pre-processed catalog
        self.catalog_sorted_keys = {}  # Clear pre-sorted keys
        self.catalog_responses = {}  # Clear pre-computed response structures
        self.systems_list = []
        self.search_index = {}
        self.subdirectory_counts = {}  # Clear subdirectory counts
        
        # Reset flags
        self._gamelists_loaded = False
        self._index_built = False
        self._hardware_loaded = False
        
        # Clear hardware mappings
        self.system_hardware = {}
        self.system_manufacturer = {}
        self.system_release = {}
        self.system_fullname = {}
        
        # Reload everything
        self.preload_all_gamelists()
        self.build_search_index()
        # Compute subdirectory counts for all systems
        self._compute_all_subdirectory_counts()
        
        logger.info("Catalog cache and search index refreshed successfully")
        
        return {
            "success": True,
            "systems_count": len(self.systems_list),
            "total_games": sum(s['gameCount'] for s in self.systems_list)
        }
    
    def search_indexed_games(self, query: str, limit: int = 50) -> List[Dict]:
        """Search games using the partitioned index.
        
        Only returns games from systems that are enabled in the database.
        """
        if not query:
            return []
        
        # Normalize search query
        normalized_query = normalize_game_name(query, remove_paranthesis=True, remove_articles=True)
        
        if not normalized_query:
            return []
        
        # Build index if not already built
        if not self._index_built:
            self.build_search_index()
        
        # Ensure search_index exists
        if not hasattr(self, 'search_index') or not self.search_index:
            self.build_search_index()
        
        # Get enabled systems from database
        enabled_systems = self._get_enabled_systems_set()
        
        results = []
        query_lower = normalized_query.lower()
        
        # Search in all partitions
        for first_letter, games_dict in self.search_index.items():
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
                    # Filter by enabled systems
                    for game in games:
                        # Only include games from enabled systems
                        if enabled_systems and game['system'] not in enabled_systems:
                            continue
                        results.append((relevance, game))
        
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

