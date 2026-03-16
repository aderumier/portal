#!/usr/bin/env python3
"""Unit tests for GameService regrouping fallback."""
import unittest
import tempfile
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.game import GameService
from app.database import SessionLocal, System, Base, engine

class TestGameGroupingFallback(unittest.TestCase):
    """Test cases for GameService regrouping fallback."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.games_path = os.path.join(self.test_dir, 'games')
        os.makedirs(self.games_path, exist_ok=True)
        
        # Initialize database for testing
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        
        # Clean up System table
        self.db.query(System).delete()
        self.db.commit()
        
        # Initialize GameService
        self.game_service = GameService(games_path=self.games_path)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_merge_by_name_fallback(self):
        """Test that games are merged by name if rompath_without_extension doesn't match."""
        system_id = 'test_system'
        system_dir = os.path.join(self.games_path, system_id)
        os.makedirs(system_dir, exist_ok=True)
        
        # Create gamelist.xml with two games having same name but different paths/extensions
        # game1: path="./game_v1.zip", name="Test Game"
        # game2: path="./game_alt.n64", name="Test Game"
        gamelist_content = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./game_v1.zip</path>
    <name>Test Game</name>
  </game>
  <game>
    <path>./game_alt.n64</path>
    <name>Test Game</name>
  </game>
</gameList>"""
        with open(os.path.join(system_dir, 'gamelist.xml'), 'w', encoding='utf-8') as f:
            f.write(gamelist_content)
            
        # Add system to DB with dual extensions
        test_system = System(
            id=system_id,
            name='Test System',
            enabled=True,
            batocera_extension='.zip',
            retrobat_extension='.n64'
        )
        self.db.add(test_system)
        self.db.commit()
        
        # Load catalog
        self.game_service.preload_all_gamelists(force_reload=True)
        
        # Verify merging
        catalog = self.game_service.catalog_wip
        self.assertIn(system_id, catalog)
        
        # Should have only ONE game entry with unified key
        # Unified key for batocera (.zip) and retrobat (.n64)
        unified_key = "game_v1.(zip|n64)"
        
        self.assertEqual(len(catalog[system_id]), 1, f"Expected 1 merged game, found {len(catalog[system_id])}: {list(catalog[system_id].keys())}")
        self.assertIn(unified_key, catalog[system_id])
        
        game_data = catalog[system_id][unified_key]
        self.assertEqual(game_data.get('name'), 'Test Game')
        self.assertEqual(game_data.get('_original_batocera_path'), 'game_v1.zip')
        self.assertEqual(game_data.get('_original_retrobat_path'), 'game_alt.n64')

if __name__ == '__main__':
    unittest.main()
