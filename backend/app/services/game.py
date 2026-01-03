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
    
    def preload_all_gamelists(self) -> None:
        """Preload all gamelist.xml files into memory at startup."""
        if self._gamelists_loaded:
            logger.info("Gamelists already loaded")
            return
        
        logger.info("Preloading all gamelist.xml files into memory...")
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
            
            dir_path = os.path.join(self.games_path, dir_name)
            if not os.path.isdir(dir_path) or not os.access(dir_path, os.R_OK):
                logger.warning(f"Directory not readable: {dir_path}")
                continue
            
            gamelist_path = os.path.join(dir_path, 'gamelist.xml')
            if not os.path.isfile(gamelist_path) or not os.access(gamelist_path, os.R_OK):
                logger.warning(f"No gamelist.xml found for system: {dir_name}")
                continue
            
            # Parse and store XML in memory
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                self.gamelists[dir_name] = root
                
                # Count games (excluding hidden ones)
                game_count = 0
                for game in root.findall('.//game'):
                    hidden = game.get('hidden', 'false')
                    if hidden.lower() not in ['true', '1']:
                        game_count += 1
                
                system = {
                    'id': dir_name,
                    'name': self.get_system_name(dir_name),
                    'gameCount': game_count
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
                hidden = game.get('hidden', 'false')
                if hidden.lower() not in ['true', '1']:
                    visible_games.append(game)
            
            total_games = len(visible_games)
            logger.info(f"Total visible games found: {total_games}")
            
            # Apply pagination
            offset = (page - 1) * limit
            paginated_games = visible_games[offset:offset + limit]
            logger.info(f"Games after pagination: {len(paginated_games)}")
            
            for game in paginated_games:
                thumbnail_path = game.findtext('thumbnail', '')
                image_path = game.findtext('image', '')
                
                # Prefer thumbnail, fallback to image
                display_image = thumbnail_path if thumbnail_path else image_path
                
                # Clean up image path
                display_image = display_image.lstrip('./')
                
                # If path doesn't start with system, prefix it
                if display_image and not display_image.startswith(f"{system}/"):
                    display_image = f"{system}/{display_image}"
                
                game_data = {
                    'id': game.findtext('path', ''),
                    'name': game.findtext('name', ''),
                    'description': game.findtext('desc', ''),
                    'image': display_image,
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
                hidden = game.get('hidden', 'false')
                if hidden.lower() not in ['true', '1']:
                    visible_games += 1
            
            return visible_games > (page * limit)
        except Exception as e:
            logger.error(f"Error checking for more games: {e}")
            return False
    
    def search_games(self, query: str, page: int = 1, limit: int = 12) -> List[Dict]:
        """Search games across all systems."""
        if not query:
            return []
        
        cache_key = f"search_{query}_{page}_{limit}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        systems = self.get_systems()
        results = []
        
        for system in systems:
            system_id = system['id']
            gamelist_path = os.path.join(self.games_path, system_id, 'gamelist.xml')
            
            if not os.path.isfile(gamelist_path) or not os.access(gamelist_path, os.R_OK):
                continue
            
            try:
                tree = ET.parse(gamelist_path)
                root = tree.getroot()
                
                for game in root.findall('.//game'):
                    # Skip hidden games
                    hidden = game.get('hidden', 'false')
                    if hidden.lower() in ['true', '1']:
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
        """Get a specific game by its ID (path)."""
        logger.info(f"Getting game by ID: {game_id}")
        
        # Clean up the game ID
        clean_game_id = game_id.lstrip('./')
        logger.info(f"Cleaned game ID: {clean_game_id}")
        
        # Extract system ID from game path
        parts = clean_game_id.split('/')
        if not parts:
            logger.warning(f"Invalid game ID format: {game_id}")
            return None
        
        system_id = parts[0]
        logger.info(f"System ID extracted: {system_id}")
        
        # Check if system exists
        if not self.get_system(system_id):
            logger.warning(f"System not found for ID: {system_id}")
            return None
        
        # Ensure gamelists are loaded
        if not self._gamelists_loaded:
            self.preload_all_gamelists()
        
        if system_id not in self.gamelists:
            logger.warning(f"Gamelist not found in memory for system: {system_id}")
            return None
        
        try:
            root = self.gamelists[system_id]
            
            # Get the path portion without the system ID
            path_without_system = '/'.join(parts[1:]) if len(parts) > 1 else clean_game_id
            logger.info(f"Looking for game with path: {path_without_system}")
            
            # Search for the game by path
            found = None
            for game in root.findall('.//game'):
                game_path = game.findtext('path', '')
                clean_game_path = game_path.lstrip('./')
                
                # Check if game is hidden
                hidden = game.get('hidden', 'false')
                if hidden.lower() in ['true', '1']:
                    continue
                
                # Try multiple possible matches
                if (clean_game_path == path_without_system or
                    clean_game_path == clean_game_id or
                    game_path == f'./{path_without_system}' or
                    game_path == path_without_system):
                    found = game
                    logger.info(f"Game found with path: {game_path}")
                    break
            
            if not found:
                logger.warning(f"Game not found with ID: {game_id}")
                return None
            
            # Get all media types
            def get_media_path(media_type):
                path = found.findtext(media_type, '')
                if path:
                    path = path.lstrip('./')
                    if not path.startswith(f"{system_id}/"):
                        path = f"{system_id}/{path}"
                return path
            
            # Get all game information
            game_data = {
                'id': found.findtext('path', ''),
                'name': found.findtext('name', ''),
                'description': found.findtext('desc', ''),
                'system': system_id,
                'systemName': self.get_system_name(system_id),
                
                # Metadata
                'developer': found.findtext('developer', ''),
                'publisher': found.findtext('publisher', ''),
                'genre': found.findtext('genre', ''),
                'releaseDate': found.findtext('releasedate', ''),
                'players': found.findtext('players', ''),
                'rating': found.findtext('rating', ''),
                'region': found.findtext('region', ''),
                'lang': found.findtext('lang', ''),
                
                # Media types
                'thumbnail': get_media_path('thumbnail'),
                'image': get_media_path('image'),
                'boxart': get_media_path('boxart'),
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
    
    def build_search_index(self) -> Dict:
        """Build a global partitioned search index with normalized game names."""
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
        
        systems = self.get_systems()
        total_games = 0
        
        for system in systems:
            system_id = system['id']
            
            if system_id not in self.gamelists:
                continue
            
            try:
                root = self.gamelists[system_id]
                
                for game in root.findall('.//game'):
                    # Skip hidden games
                    hidden = game.get('hidden', 'false')
                    if hidden.lower() in ['true', '1']:
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
    
    def search_indexed_games(self, query: str, limit: int = 50) -> List[Dict]:
        """Search games using the partitioned index."""
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
        
        results = []
        query_lower = normalized_query.lower()
        
        # Search in all partitions
        for first_letter, games_dict in self.search_index.items():
            for normalized_name, games in games_dict.items():
                # Check if normalized query matches normalized name
                if query_lower in normalized_name.lower() or normalized_name.lower().startswith(query_lower):
                    # Add all games with this normalized name
                    results.extend(games)
        
        # Remove duplicates (same game might appear multiple times if indexed multiple ways)
        seen = set()
        unique_results = []
        for game in results:
            game_key = (game['system'], game['id'])
            if game_key not in seen:
                seen.add(game_key)
                unique_results.append(game)
        
        # Sort results: exact matches first, then by name
        unique_results.sort(key=lambda x: (
            0 if normalized_query.lower() == normalize_game_name(x['name'], remove_paranthesis=True, remove_articles=True).lower() else 1,
            x['name'].lower()
        ))
        
        # Limit results
        return unique_results[:limit]

