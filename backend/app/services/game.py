"""Game catalog service for parsing gamelist.xml files."""
import os
import xml.etree.ElementTree as ET
import logging
import pickle
import hashlib
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

class GameService:
    """Service for managing game catalog from gamelist.xml files."""
    
    def __init__(self, games_path: Optional[str] = None):
        self.games_path = games_path or settings.GAMES_PATH
        self.cache = {}
        self.search_index = {}  # Partitioned search index: search_index[first_letter][normalized_name] = [games]
        self._index_built = False
        self.gamelists = {}  # In-memory storage: gamelists[system_id] = root_element
        self.systems_list = []  # Cached systems list with game counts
        self._gamelists_loaded = False
        self.system_hardware = {}  # Cache: system_id -> hardware category
        self.system_manufacturer = {}  # Cache: system_id -> manufacturer
        self.system_release = {}  # Cache: system_id -> release year
        self.system_fullname = {}  # Cache: system_id -> full name
        self._hardware_loaded = False
        
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
        self.gamelists = {}
        
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
            
            # Parse and store XML in memory
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                self.gamelists[dir_name] = root
                
                # Count games (excluding hidden ones)
                game_count = 0
                for game in root.findall('.//game'):
                    if not _is_game_hidden(game):
                        game_count += 1
                
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
        logger.info(f"Preloaded {len(systems)} systems with {sum(s['gameCount'] for s in systems)} total games")
    
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
        
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Get root from memory cache
        if system not in self.gamelists:
            logger.warning(f"gamelist.xml not found in memory for system: {system}")
            return []
        
        games = []
        root = self.gamelists[system]
        
        try:
            all_games = root.findall('.//game')
            
            # Filter by search query if provided
            if search:
                filtered_games = []
                for game in all_games:
                    name = game.findtext('name', '')
                    if search.lower() in name.lower():
                        filtered_games.append(game)
                all_games = filtered_games
            
            # Filter out hidden games
            visible_games = []
            for game in all_games:
                if not _is_game_hidden(game):
                    visible_games.append(game)
            
            total_games = len(visible_games)
            logger.info(f"Total visible games found: {total_games}")
            
            # Apply pagination
            offset = (page - 1) * limit
            paginated_games = visible_games[offset:offset + limit]
            logger.info(f"Games after pagination: {len(paginated_games)}")
            
            for game in paginated_games:
                # Get all media fields
                def get_media_path(media_type):
                    path = game.findtext(media_type, '')
                    if path:
                        path = path.lstrip('./')
                        if not path.startswith(f"{system}/"):
                            path = f"{system}/{path}"
                    return path
                
                thumbnail_path = get_media_path('thumbnail')
                boxart_path = get_media_path('boxart')
                extra1_path = get_media_path('extra1')
                image_path = get_media_path('image')
                
                # Prefer thumbnail, fallback to boxart, then extra1, then image
                display_image = thumbnail_path if thumbnail_path else (boxart_path if boxart_path else (extra1_path if extra1_path else image_path))
                
                game_data = {
                    'id': game.findtext('path', ''),
                    'name': game.findtext('name', ''),
                    'description': game.findtext('desc', ''),
                    'image': display_image,
                    'thumbnail': thumbnail_path,
                    'boxart': boxart_path,
                    'extra1': extra1_path,
                    'system': system,
                    'systemName': self.get_system_name(system)
                }
                
                logger.debug(f"Adding game: {game_data['name']}")
                games.append(game_data)
            
            logger.info(f"Returning {len(games)} games")
            self.cache[cache_key] = games
            return games
        except Exception as e:
            logger.error(f"Failed to parse gamelist.xml for system {system}: {e}")
            return []
    
    def has_more_games(self, system: str, page: int, limit: int) -> bool:
        """Check if there are more games available for a system (from memory cache)."""
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        if system not in self.gamelists:
            return False
        
        try:
            root = self.gamelists[system]
            visible_games = 0
            for game in root.findall('.//game'):
                if not _is_game_hidden(game):
                    visible_games += 1
            
            return visible_games > (page * limit)
        except Exception as e:
            logger.error(f"Error checking for more games: {e}")
            return False
    
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
        
        for system in systems:
            system_id = system['id']
            
            # Skip if system is not enabled
            if enabled_systems and system_id not in enabled_systems:
                continue
            
            gamelist_path = os.path.join(self.games_path, system_id, 'gamelist.xml')
            
            if not os.path.isfile(gamelist_path) or not os.access(gamelist_path, os.R_OK):
                continue
            
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                
                for game in root.findall('.//game'):
                    # Skip hidden games
                    if _is_game_hidden(game):
                        continue
                    
                    name = game.findtext('name', '')
                    if query.lower() in name.lower():
                        thumbnail_path = game.findtext('thumbnail', '')
                        image_path = game.findtext('image', '')
                        
                        display_image = thumbnail_path if thumbnail_path else image_path
                        display_image = display_image.lstrip('./')
                        
                        if display_image and not display_image.startswith(f"{system_id}/"):
                            display_image = f"{system_id}/{display_image}"
                        
                        results.append({
                            'id': game.findtext('path', ''),
                            'name': name,
                            'description': game.findtext('desc', ''),
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
        
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        # Search all systems for a game with matching path
        # The path in gamelist.xml is relative to the system directory
        system_id = None
        found_game = None
        
        for loaded_system_id in self.gamelists.keys():
            root = self.gamelists[loaded_system_id]
            
            for game in root.findall('.//game'):
                game_path = game.findtext('path', '')
                clean_game_path = game_path.lstrip('./')
                
                # Check if game is hidden
                if _is_game_hidden(game):
                    continue
                
                # Match the path exactly (with or without ./ prefix)
                if (clean_game_path == clean_game_id or
                    game_path == f'./{clean_game_id}' or
                    game_path == clean_game_id):
                    system_id = loaded_system_id
                    found_game = game
                    logger.info(f"Game found in system {system_id} with path: {game_path}")
                    break
            
            if found_game:
                break
        
        if not found_game:
            logger.warning(f"Game not found in any system with path: {clean_game_id}")
            return None
        
        if not system_id or system_id not in self.gamelists:
            logger.warning(f"System ID not determined or gamelist not found: {system_id}")
            return None
        
        try:
            
            # Get all media types
            def get_media_path(media_type):
                path = found_game.findtext(media_type, '')
                if path:
                    path = path.lstrip('./')
                    if not path.startswith(f"{system_id}/"):
                        path = f"{system_id}/{path}"
                return path
            
            # Get all game information
            game_data = {
                'id': found_game.findtext('path', ''),
                'name': found_game.findtext('name', ''),
                'description': found_game.findtext('desc', ''),
                'system': system_id,
                'systemName': self.get_system_name(system_id),
                
                # Metadata
                'developer': found_game.findtext('developer', ''),
                'publisher': found_game.findtext('publisher', ''),
                'genre': found_game.findtext('genre', ''),
                'releaseDate': found_game.findtext('releasedate', ''),
                'players': found_game.findtext('players', ''),
                'rating': found_game.findtext('rating', ''),
                'region': found_game.findtext('region', ''),
                'lang': found_game.findtext('lang', ''),
                
                # Media types
                'thumbnail': get_media_path('thumbnail'),
                'image': get_media_path('image'),
                'boxart': get_media_path('boxart'),
                'extra1': get_media_path('extra1'),
                'spine': get_media_path('spine'),
                'boxback': get_media_path('boxback'),
                'marquee': get_media_path('marquee'),
                'fanart': get_media_path('fanart'),
                'cartridge': get_media_path('cartridge'),
                'titleshot': get_media_path('titleshot'),
                'video': get_media_path('video'),
                'screenshot': get_media_path('screenshot'),
                'wheel': get_media_path('wheel'),
                'mix': get_media_path('mix'),
            }
            
            # Set default display image (prefer thumbnail, then image)
            if game_data['thumbnail']:
                game_data['image'] = game_data['thumbnail']
            elif game_data['image']:
                pass  # Already set
            else:
                game_data['image'] = ''
            
            logger.info(f"Game data retrieved: {game_data['name']}")
            return game_data
        except Exception as e:
            logger.error(f"Failed to get game by ID: {e}")
            return None
    
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
        
        for system in systems:
            system_id = system['id']
            
            # Skip if system is not enabled
            if enabled_systems and system_id not in enabled_systems:
                logger.debug(f"Skipping disabled system in search index: {system_id}")
                continue
            
            if system_id not in self.gamelists:
                continue
            
            try:
                root = self.gamelists[system_id]
                
                for game in root.findall('.//game'):
                    # Skip hidden games
                    if _is_game_hidden(game):
                        continue
                    
                    game_name = game.findtext('name', '')
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
                    
                    # Get game data
                    thumbnail_path = game.findtext('thumbnail', '')
                    image_path = game.findtext('image', '')
                    display_image = thumbnail_path if thumbnail_path else image_path
                    display_image = display_image.lstrip('./')
                    
                    if display_image and not display_image.startswith(f"{system_id}/"):
                        display_image = f"{system_id}/{display_image}"
                    
                    game_data = {
                        'id': game.findtext('path', ''),
                        'name': game_name,
                        'description': game.findtext('desc', ''),
                        'image': display_image,
                        'system': system_id,
                        'systemName': self.get_system_name(system_id)
                    }
                    
                    # Add to index (normalized name -> list of games)
                    if normalized not in index[first_letter]:
                        index[first_letter][normalized] = []
                    
                    index[first_letter][normalized].append(game_data)
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
        self.gamelists = {}
        self.systems_list = []
        self.search_index = {}
        
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

