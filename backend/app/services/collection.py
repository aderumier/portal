"""Collection service for parsing custom collection .cfg files."""
import os
import logging
from typing import List, Dict, Optional
from app.config import settings
from app.services.game import GameService

logger = logging.getLogger(__name__)

class CollectionService:
    """Service for managing game collections."""
    
    def __init__(self, collections_path: Optional[str] = None):
        # Default to data/collections relative to project root
        self.collections_path = collections_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'data', 'collections'
        )
        
    def _parse_collection_name(self, filename: str) -> str:
        """Parse friendly name from filename (e.g. custom-3players.cfg -> 3players)."""
        name = filename
        if name.startswith('custom-'):
            name = name[7:]
        if name.endswith('.cfg'):
            name = name[:-4]
            
        # Capitalize and replace dashes with spaces
        return name.replace('-', ' ').title()

    def get_collections(self, game_service: GameService, catalog_type: str = 'releases') -> List[Dict]:
        """Get list of all available collections."""
        if not os.path.exists(self.collections_path):
            logger.warning(f"Collections path not found: {self.collections_path}")
            return []
            
        collections = []
        
        for filename in os.listdir(self.collections_path):
            if not filename.endswith('.cfg'):
                continue
                
            collection_id = filename[:-4] # Remove .cfg
            filepath = os.path.join(self.collections_path, filename)
            
            # Count games by reading lines
            game_count = 0
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            game_count += 1
            except Exception as e:
                logger.error(f"Error reading collection file {filepath}: {e}")
                continue
                
            collections.append({
                'id': collection_id,
                'name': self._parse_collection_name(filename),
                'gameCount': game_count
            })
            
        # Sort collections by name
        collections.sort(key=lambda x: x['name'])
        return collections

    def get_collection_games(
        self, 
        collection_id: str, 
        game_service: GameService,
        page: int = 1,
        limit: int = 12,
        search: Optional[str] = None,
        catalog_type: str = 'releases'
    ) -> List[Dict]:
        """Get paginated list of games in a specific collection."""
        filepath = os.path.join(self.collections_path, f"{collection_id}.cfg")
        
        if not os.path.exists(filepath):
            logger.warning(f"Collection file not found: {filepath}")
            return []
            
        # Read all rom paths from collection file
        rom_paths = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Line format is typically: ./roms/{system}/{game}
                        # Or just {system}/{game} depending on how it was generated
                        
                        path = line
                        if path.startswith('./'):
                            path = path[2:]
                        if path.startswith('roms/'):
                            path = path[5:]
                            
                        # Now path should be {system}/...
                        parts = path.split('/', 1)
                        if len(parts) == 2:
                            system = parts[0]
                            rompath = parts[1]
                            rom_paths.append((system, rompath))
        except Exception as e:
            logger.error(f"Error reading collection file {filepath}: {e}")
            return []
            
        # Resolve games using GameService
        # Note: We must fetch all of them to be able to sort & search properly across systems
        all_games = []
        for system, rompath in rom_paths:
            # Try to get the game in 'wip' catalog first
            game = game_service.get_game_by_id(rompath, system, 'wip')
            
            # If not found, fallback to 'releases'
            if not game:
                game = game_service.get_game_by_id(rompath, system, 'releases')
                
            if game:
                # Store system id since it's needed by frontend
                game['system'] = system
                all_games.append(game)
                
        # Filter by search if provided
        if search:
            search_lower = search.lower()
            all_games = [
                g for g in all_games 
                if search_lower in (g.get('name', '') or '').lower() or 
                   search_lower in (g.get('publisher', '') or '').lower()
            ]
            
        # Sort by name
        all_games.sort(key=lambda x: (x.get('name', '') or '').lower())
        
        # Apply pagination
        offset = (page - 1) * limit
        paginated_games = all_games[offset:offset + limit]
        
        return paginated_games

    def get_collection_game_count(self, collection_id: str, search: Optional[str] = None) -> int:
        """Get total count of games in a collection (used for pagination metadata if needed)."""
        # A bit expensive with search, but usually counts are small for collections
        filepath = os.path.join(self.collections_path, f"{collection_id}.cfg")
        if not os.path.exists(filepath):
            return 0
            
        count = 0
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        count += 1
        except Exception:
            pass
            
        return count
