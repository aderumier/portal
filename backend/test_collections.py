import sys
import os
import asyncio
import logging

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.game import GameService
from app.services.collection import CollectionService

logging.basicConfig(level=logging.INFO)

async def main():
    print("Loading services...")
    game_service = GameService()
    collection_service = CollectionService()
    
    # Preload to ensure data is there
    print("Preloading gamelists...")
    game_service.preload_all_gamelists()
    
    print("Testing collection...")
    games = collection_service.get_collection_games("custom-4players", game_service, catalog_type="releases")
    print(f"custom-4players (releases) found {len(games)} games")
    
    if len(games) == 0:
        # Check why it's empty
        print("Checking first few lines of custom-4players.cfg...")
        filepath = os.path.join(collection_service.collections_path, "custom-4players.cfg")
        with open(filepath, 'r') as f:
            lines = f.readlines()[:5]
            
        for line in lines:
            line = line.strip()
            print(f"Line: {line}")
            path = line
            if path.startswith('./'):
                path = path[2:]
            if path.startswith('roms/'):
                path = path[5:]
            parts = path.split('/', 1)
            if len(parts) == 2:
                system = parts[0]
                rompath = parts[1]
                print(f"  -> System: {system}, Rompath: {rompath}")
                
                game = game_service.get_game_by_id(rompath, system, "releases")
                print(f"  -> get_game_by_id(..., 'releases'): {'FOUND' if game else 'NOT FOUND'}")
                if not game:
                    # check if system exists in releases
                    sys_releases = game_service.catalog_releases.get(system)
                    if sys_releases is None:
                        print(f"     -> System {system} NOT IN releases catalog!")
                    else:
                        print(f"     -> System {system} has {len(sys_releases)} games in releases.")
                        # check if it exists in wip
                    
                    sys_wip = game_service.catalog_wip.get(system)
                    if sys_wip is None:
                        print(f"     -> System {system} NOT IN wip catalog!")
                    else:
                        print(f"     -> System {system} has {len(sys_wip)} games in wip.")
                        game_wip = game_service.get_game_by_id(rompath, system, "wip")
                        print(f"     -> get_game_by_id(..., 'wip'): {'FOUND' if game_wip else 'NOT FOUND'}")

if __name__ == "__main__":
    asyncio.run(main())
