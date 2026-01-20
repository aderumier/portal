#!/usr/bin/env python3
"""Analyze catalog.pkl file to show dictionary sizes."""
import pickle
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

def get_size_mb(obj):
    """Get size of object in MB."""
    import sys
    return sys.getsizeof(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)) / (1024 * 1024)

def count_games(catalog):
    """Count total games in catalog."""
    total = 0
    for system_id, games in catalog.items():
        total += len(games)
    return total

def analyze_catalog_file(catalog_path):
    """Analyze catalog.pkl file and show dictionary sizes."""
    if not os.path.exists(catalog_path):
        print(f"Catalog file not found: {catalog_path}")
        return
    
    file_size_mb = os.path.getsize(catalog_path) / (1024 * 1024)
    print(f"\n{'='*60}")
    print(f"Catalog File: {catalog_path}")
    print(f"File Size: {file_size_mb:.2f} MB")
    print(f"{'='*60}\n")
    
    with open(catalog_path, 'rb') as f:
        catalog_data = pickle.load(f)
    
    print("Dictionary Sizes:\n")
    
    total_size = 0
    for key, value in catalog_data.items():
        size_mb = get_size_mb(value)
        total_size += size_mb
        
        if key in ('catalog_wip', 'catalog_releases'):
            game_count = count_games(value)
            system_count = len(value)
            print(f"  {key:30s}: {size_mb:8.2f} MB  ({system_count} systems, {game_count} games)")
        elif key in ('catalog_sorted_keys_wip', 'catalog_sorted_keys_releases'):
            total_keys = sum(len(v) for v in value.values()) if isinstance(value, dict) else 0
            print(f"  {key:30s}: {size_mb:8.2f} MB  ({len(value)} systems, {total_keys} total keys)")
        elif key == 'systems_list':
            print(f"  {key:30s}: {size_mb:8.2f} MB  ({len(value)} systems)")
        elif isinstance(value, dict):
            print(f"  {key:30s}: {size_mb:8.2f} MB  ({len(value)} entries)")
        else:
            print(f"  {key:30s}: {size_mb:8.2f} MB")
    
    print(f"\n  {'Total':30s}: {total_size:8.2f} MB")
    
    # Analyze catalog_wip structure in detail
    if 'catalog_wip' in catalog_data:
        print(f"\n{'='*60}")
        print("Detailed Analysis of catalog_wip:")
        print(f"{'='*60}\n")
        
        catalog_wip = catalog_data['catalog_wip']
        total_games = 0
        total_fields = 0
        field_counts = {}
        sample_game = None
        
        for system_id, games in list(catalog_wip.items())[:5]:  # Sample first 5 systems
            total_games += len(games)
            for rompath, game_data in list(games.items())[:10]:  # Sample first 10 games per system
                if sample_game is None:
                    sample_game = (system_id, rompath, game_data)
                total_fields += len(game_data)
                for field in game_data.keys():
                    field_counts[field] = field_counts.get(field, 0) + 1
        
        print(f"Sample: {total_games} games analyzed")
        print(f"\nFields found in games (frequency):")
        for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
            print(f"  {field:20s}: {count:6d} times")
        
        if sample_game:
            system_id, rompath, game_data = sample_game
            print(f"\nSample game from system '{system_id}':")
            print(f"  ROM path: {rompath}")
            print(f"  Fields ({len(game_data)}): {', '.join(sorted(game_data.keys()))}")
            print(f"  Field sizes:")
            for field, value in game_data.items():
                field_size = sys.getsizeof(str(value)) / 1024  # KB
                print(f"    {field:20s}: {field_size:6.2f} KB  (value: {str(value)[:50]}...)")

if __name__ == '__main__':
    # Try to find catalog.pkl file
    possible_paths = [
        '/opt/batocera-games-catalog/data/catalog.pkl',
        os.path.join(os.path.dirname(__file__), 'data', 'catalog.pkl'),
        os.path.join(os.path.dirname(__file__), 'backend', 'data', 'catalog.pkl'),
    ]
    
    catalog_path = None
    for path in possible_paths:
        if os.path.exists(path):
            catalog_path = path
            break
    
    if not catalog_path:
        # Try to determine from settings
        try:
            from app.config import settings
            from app.services.game import GameService
            game_service = GameService()
            catalog_path = game_service._get_catalog_file_path()
        except Exception as e:
            print(f"Could not determine catalog path: {e}")
            print("\nPlease provide the path to catalog.pkl:")
            catalog_path = input("Path: ").strip()
    
    if catalog_path and os.path.exists(catalog_path):
        analyze_catalog_file(catalog_path)
    else:
        print(f"Catalog file not found. Tried: {possible_paths}")
        print(f"Please provide the full path to catalog.pkl")
