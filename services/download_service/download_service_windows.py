"""
Windows-compatible wrapper for download_service.py
Handles Windows-specific paths and ensures standalone execution
"""
import os
import sys
import platform
import configparser
from pathlib import Path

# Ensure we're running on Windows
if platform.system() != 'Windows':
    print("This script is designed for Windows only.")
    sys.exit(1)

# Get executable directory (works for both .py and .exe)
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    EXE_DIR = Path(sys.executable).parent
    # Add EXE_DIR to Python path so we can import download_service
    if str(EXE_DIR) not in sys.path:
        sys.path.insert(0, str(EXE_DIR))
else:
    # Running as script
    EXE_DIR = Path(__file__).parent

def read_config_ini(config_path):
    """Read config.ini file and return a dictionary of settings."""
    config = {}
    if config_path.exists():
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding='utf-8')
            if 'Service' in parser:
                for key, value in parser['Service'].items():
                    config[key.upper()] = value
        except Exception as e:
            print(f"Warning: Failed to read config.ini at {config_path}: {e}", file=sys.stderr)
    return config

# Path handling (ROMS_PATH, LOG_DIR, LOG_FILE) is done in download_service.py
# No need to duplicate it here

# Import download_service module
# When frozen, download_service.py should be in the same directory as the exe
try:
    import download_service
except ImportError:
    # Try loading from file if import fails
    import importlib.util
    service_file = EXE_DIR / "download_service.py"
    if not service_file.exists():
        service_file = Path(__file__).parent / "download_service.py"
    
    if not service_file.exists():
        print(f"ERROR: download_service.py not found in {EXE_DIR}")
        sys.exit(1)
    
    spec = importlib.util.spec_from_file_location("download_service", service_file)
    download_service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(download_service)

# Patch API_TOKEN path to look in executable directory
if hasattr(download_service, 'api_token_path'):
    download_service.api_token_path = EXE_DIR / 'API_TOKEN.txt'
elif hasattr(download_service, 'SERVICE_DIR'):
    # Update SERVICE_DIR if it exists
    download_service.SERVICE_DIR = EXE_DIR
    download_service.api_token_path = EXE_DIR / 'API_TOKEN.txt'

# Logging is configured in download_service.py - no need to reconfigure here

# Verify API_TOKEN can be loaded
if hasattr(download_service, 'API_TOKEN'):
    if not download_service.API_TOKEN:
        api_token_file = EXE_DIR / 'API_TOKEN.txt'
        if api_token_file.exists():
            try:
                with open(api_token_file, 'r', encoding='utf-8') as f:
                    download_service.API_TOKEN = f.read().strip()
                if download_service.API_TOKEN and hasattr(download_service, 'logger'):
                    download_service.logger.info(f"API_TOKEN loaded from {api_token_file}")
            except Exception as e:
                if hasattr(download_service, 'logger'):
                    download_service.logger.error(f"Failed to read API_TOKEN: {e}")

# Now run the main function
if __name__ == "__main__":
    try:
        download_service.main()
    except KeyboardInterrupt:
        print("Service stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
