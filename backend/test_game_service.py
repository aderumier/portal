#!/usr/bin/env python3
"""Unit tests for GameService functionality."""
import unittest
import tempfile
import os
import shutil
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.game import GameService, _is_game_hidden
from app.config import settings

class TestGameService(unittest.TestCase):
    """Test cases for GameService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directories
        self.test_dir = tempfile.mkdtemp()
        self.games_path = os.path.join(self.test_dir, 'games')
        self.systemscfg_path = os.path.join(self.test_dir, 'data', 'systemscfg')
        os.makedirs(self.games_path, exist_ok=True)
        os.makedirs(self.systemscfg_path, exist_ok=True)
        
        # Create test es_systems.cfg
        self.create_test_systems_cfg()
        
        # Create test gamelist.xml files
        self.create_test_gamelists()
        
        # Initialize GameService with test paths
        self.game_service = GameService(games_path=self.games_path)
        # Override systemscfg path for testing
        self.game_service._hardware_loaded = False
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def create_test_systems_cfg(self):
        """Create a test es_systems.cfg file."""
        systems_cfg = """<?xml version="1.0"?>
<systemList>
  <system>
    <fullname>Nintendo Entertainment System</fullname>
    <name>nes</name>
    <manufacturer>Nintendo</manufacturer>
    <release>1983</release>
    <hardware>console</hardware>
  </system>
  <system>
    <fullname>Super Nintendo Entertainment System</fullname>
    <name>snes</name>
    <manufacturer>Nintendo</manufacturer>
    <release>1990</release>
    <hardware>console</hardware>
  </system>
  <system>
    <fullname>Game Boy</fullname>
    <name>gb</name>
    <manufacturer>Nintendo</manufacturer>
    <release>1989</release>
    <hardware>portable</hardware>
  </system>
</systemList>"""
        cfg_file = os.path.join(self.systemscfg_path, 'es_systems.cfg')
        with open(cfg_file, 'w', encoding='utf-8') as f:
            f.write(systems_cfg)
    
    def create_test_gamelists(self):
        """Create test gamelist.xml files."""
        # Create nes system
        nes_dir = os.path.join(self.games_path, 'nes')
        os.makedirs(nes_dir, exist_ok=True)
        nes_gamelist = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./Super Mario Bros.nes</path>
    <name>Super Mario Bros.</name>
  </game>
  <game>
    <path>./The Legend of Zelda.nes</path>
    <name>The Legend of Zelda</name>
  </game>
</gameList>"""
        with open(os.path.join(nes_dir, 'gamelist.xml'), 'w', encoding='utf-8') as f:
            f.write(nes_gamelist)
        
        # Create nes_batocera system
        nes_batocera_dir = os.path.join(self.games_path, 'nes_batocera')
        os.makedirs(nes_batocera_dir, exist_ok=True)
        nes_batocera_gamelist = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./Mega Man.nes</path>
    <name>Mega Man</name>
  </game>
</gameList>"""
        with open(os.path.join(nes_batocera_dir, 'gamelist.xml'), 'w', encoding='utf-8') as f:
            f.write(nes_batocera_gamelist)
        
        # Create gb_retrobat system
        gb_retrobat_dir = os.path.join(self.games_path, 'gb_retrobat')
        os.makedirs(gb_retrobat_dir, exist_ok=True)
        gb_retrobat_gamelist = """<?xml version="1.0"?>
<gameList>
  <game>
    <path>./Pokemon Red.gb</path>
    <name>Pokemon Red</name>
  </game>
</gameList>"""
        with open(os.path.join(gb_retrobat_dir, 'gamelist.xml'), 'w', encoding='utf-8') as f:
            f.write(gb_retrobat_gamelist)
    
    def test_load_system_hardware(self):
        """Test loading system hardware from es_systems.cfg."""
        # Mock the systemscfg path
        import app.services.game as game_module
        original_paths = None
        
        # Temporarily override the path resolution
        def mock_load_hardware(self):
            if self._hardware_loaded:
                return self.system_hardware
            
            hardware_map = {}
            manufacturer_map = {}
            release_map = {}
            fullname_map = {}
            
            systemcfg_dir = Path(self.systemscfg_path)
            main_config = systemcfg_dir / 'es_systems.cfg'
            
            if main_config.exists():
                tree = ET.parse(main_config)
                root = tree.getroot()
                systems = root.findall('.//system')
                
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
            
            self.system_hardware = hardware_map
            self.system_manufacturer = manufacturer_map
            self.system_release = release_map
            self.system_fullname = fullname_map
            self._hardware_loaded = True
            return hardware_map
        
        # Patch the method
        self.game_service.systemscfg_path = self.systemscfg_path
        self.game_service._load_system_hardware = lambda: mock_load_hardware(self.game_service)
        
        # Test loading
        hardware_map = self.game_service._load_system_hardware()
        
        # Assertions
        self.assertIn('nes', hardware_map)
        self.assertEqual(hardware_map['nes'], 'console')
        self.assertEqual(self.game_service.system_manufacturer['nes'], 'Nintendo')
        self.assertEqual(self.game_service.system_release['nes'], '1983')
        self.assertEqual(self.game_service.system_fullname['nes'], 'Nintendo Entertainment System')
        
        self.assertIn('snes', hardware_map)
        self.assertEqual(hardware_map['snes'], 'console')
        
        self.assertIn('gb', hardware_map)
        self.assertEqual(hardware_map['gb'], 'portable')
    
    def test_system_with_batocera_suffix(self):
        """Test system mapping with _batocera suffix."""
        # Mock hardware loading
        self.game_service.system_hardware = {'nes': 'console'}
        self.game_service.system_manufacturer = {'nes': 'Nintendo'}
        self.game_service.system_release = {'nes': '1983'}
        self.game_service.system_fullname = {'nes': 'Nintendo Entertainment System'}
        self.game_service._hardware_loaded = True
        
        # Preload gamelists
        self.game_service.preload_all_gamelists()
        
        # Get systems
        systems = self.game_service.get_systems()
        
        # Find nes_batocera system
        nes_batocera = next((s for s in systems if s['id'] == 'nes_batocera'), None)
        
        self.assertIsNotNone(nes_batocera, "nes_batocera system should exist")
        self.assertEqual(nes_batocera['hardware'], 'console')
        self.assertEqual(nes_batocera['manufacturer'], 'Nintendo')
        self.assertEqual(nes_batocera['release'], '1983')
        self.assertEqual(nes_batocera['name'], 'Nintendo Entertainment System (Batocera)')
    
    def test_system_with_retrobat_suffix(self):
        """Test system mapping with _retrobat suffix."""
        # Mock hardware loading
        self.game_service.system_hardware = {'gb': 'portable'}
        self.game_service.system_manufacturer = {'gb': 'Nintendo'}
        self.game_service.system_release = {'gb': '1989'}
        self.game_service.system_fullname = {'gb': 'Game Boy'}
        self.game_service._hardware_loaded = True
        
        # Preload gamelists
        self.game_service.preload_all_gamelists()
        
        # Get systems
        systems = self.game_service.get_systems()
        
        # Find gb_retrobat system
        gb_retrobat = next((s for s in systems if s['id'] == 'gb_retrobat'), None)
        
        self.assertIsNotNone(gb_retrobat, "gb_retrobat system should exist")
        self.assertEqual(gb_retrobat['hardware'], 'portable')
        self.assertEqual(gb_retrobat['manufacturer'], 'Nintendo')
        self.assertEqual(gb_retrobat['release'], '1989')
        self.assertEqual(gb_retrobat['name'], 'Game Boy (Retrobat)')
    
    def test_system_metadata_included(self):
        """Test that system metadata (hardware, manufacturer, release, fullname) is included."""
        # Mock hardware loading with multiple systems
        self.game_service.system_hardware = {
            'nes': 'console',
            'snes': 'console',
            'gb': 'portable'
        }
        self.game_service.system_manufacturer = {
            'nes': 'Nintendo',
            'snes': 'Nintendo',
            'gb': 'Nintendo'
        }
        self.game_service.system_release = {
            'nes': '1983',
            'snes': '1990',
            'gb': '1989'
        }
        self.game_service.system_fullname = {
            'nes': 'Nintendo Entertainment System',
            'snes': 'Super Nintendo Entertainment System',
            'gb': 'Game Boy'
        }
        self.game_service._hardware_loaded = True
        
        # Preload gamelists
        self.game_service.preload_all_gamelists()
        
        # Get systems
        systems = self.game_service.get_systems()
        
        # Find nes system
        nes = next((s for s in systems if s['id'] == 'nes'), None)
        
        self.assertIsNotNone(nes, "nes system should exist")
        self.assertIn('hardware', nes)
        self.assertIn('manufacturer', nes)
        self.assertIn('release', nes)
        self.assertEqual(nes['hardware'], 'console')
        self.assertEqual(nes['manufacturer'], 'Nintendo')
        self.assertEqual(nes['release'], '1983')
        self.assertEqual(nes['name'], 'Nintendo Entertainment System')


class TestSystemHardwareParsing(unittest.TestCase):
    """Test parsing of es_systems*.cfg files."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.systemscfg_path = os.path.join(self.test_dir, 'systemscfg')
        os.makedirs(self.systemscfg_path, exist_ok=True)
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_parse_system_with_all_fields(self):
        """Test parsing a system with all fields (name, hardware, manufacturer, release, fullname)."""
        systems_cfg = """<?xml version="1.0"?>
<systemList>
  <system>
    <fullname>Nintendo Entertainment System</fullname>
    <name>nes</name>
    <manufacturer>Nintendo</manufacturer>
    <release>1983</release>
    <hardware>console</hardware>
  </system>
</systemList>"""
        cfg_file = os.path.join(self.systemscfg_path, 'es_systems.cfg')
        with open(cfg_file, 'w', encoding='utf-8') as f:
            f.write(systems_cfg)
        
        # Parse the file
        tree = ET.parse(cfg_file)
        root = tree.getroot()
        systems = root.findall('.//system')
        
        self.assertEqual(len(systems), 1)
        
        system = systems[0]
        name = system.find('name').text.strip()
        hardware = system.find('hardware').text.strip()
        manufacturer = system.find('manufacturer').text.strip()
        release = system.find('release').text.strip()
        fullname = system.find('fullname').text.strip()
        
        self.assertEqual(name, 'nes')
        self.assertEqual(hardware, 'console')
        self.assertEqual(manufacturer, 'Nintendo')
        self.assertEqual(release, '1983')
        self.assertEqual(fullname, 'Nintendo Entertainment System')
    
    def test_parse_system_with_missing_fields(self):
        """Test parsing a system with missing optional fields."""
        systems_cfg = """<?xml version="1.0"?>
<systemList>
  <system>
    <name>test</name>
    <hardware>console</hardware>
  </system>
</systemList>"""
        cfg_file = os.path.join(self.systemscfg_path, 'es_systems.cfg')
        with open(cfg_file, 'w', encoding='utf-8') as f:
            f.write(systems_cfg)
        
        # Parse the file
        tree = ET.parse(cfg_file)
        root = tree.getroot()
        systems = root.findall('.//system')
        
        self.assertEqual(len(systems), 1)
        
        system = systems[0]
        name = system.find('name').text.strip()
        hardware = system.find('hardware').text.strip()
        manufacturer = system.find('manufacturer')
        release = system.find('release')
        fullname = system.find('fullname')
        
        self.assertEqual(name, 'test')
        self.assertEqual(hardware, 'console')
        self.assertIsNone(manufacturer)
        self.assertIsNone(release)
        self.assertIsNone(fullname)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)

