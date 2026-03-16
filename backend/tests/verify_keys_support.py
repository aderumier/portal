
import os
import sys
import logging
from typing import Optional, Dict

# Setup minimal logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_detect_keys():
    # Import the function after making sure we can reach it
    sys.path.append(os.path.abspath('backend'))
    from app.services.download import detect_and_parse_special_file
    
    import tempfile
    import shutil
    
    test_dir = tempfile.mkdtemp()
    try:
        # Test 1: .wsquashfs with game.wsquashfs.keys
        rom1 = os.path.join(test_dir, "game1.wsquashfs")
        key1 = os.path.join(test_dir, "game1.wsquashfs.keys")
        with open(rom1, 'w') as f: f.write("dummy rom")
        with open(key1, 'w') as f: f.write("dummy keys")
        
        result = detect_and_parse_special_file(rom1)
        print(f"Test 1 (.wsquashfs + .wsquashfs.keys): {result}")
        assert result is not None
        assert "game1.wsquashfs.keys" in result['files']
        
        # Test 2: ensure .zip does NOT have .keys support (as per requirement)
        rom2 = os.path.join(test_dir, "game2.zip")
        key2 = os.path.join(test_dir, "game2.zip.keys")
        with open(rom2, 'w') as f: f.write("dummy rom")
        with open(key2, 'w') as f: f.write("dummy keys")
        
        result = detect_and_parse_special_file(rom2)
        print(f"Test 2 (.zip + .zip.keys - should be None or not include .keys): {result}")
        assert result is None
        
        print("\nAll tests passed successfully!")
        
    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_detect_keys()
