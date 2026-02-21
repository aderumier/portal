import sys
import os
import asyncio
from app.services.game import GameService

async def main():
    service = GameService()
    service.preload_all_gamelists()
    
    # Try different formats
    game1 = service.get_game_by_id("88games.zip", "mame", "releases")
    print(f"88games.zip: {game1 is not None}")
    
    game2 = service.get_game_by_id("./88games.zip", "mame", "releases")
    print(f"./88games.zip: {game2 is not None}")
    
    # Let's see what keys are actually in mame catalog
    mame_catalog = service.catalog_releases.get("mame", {})
    keys = list(mame_catalog.keys())[:5]
    print(f"First 5 keys in mame releases catalog: {keys}")
    
if __name__ == "__main__":
    asyncio.run(main())
