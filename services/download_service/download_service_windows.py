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

# Read config.ini if it exists
config_ini_path = EXE_DIR / 'config.ini'
config = read_config_ini(config_ini_path)

# Set Windows-specific defaults before importing download_service
def get_windows_paths():
    """Get Windows-appropriate paths."""
    # Use ProgramData for ROMS (accessible to all users)
    roms_base = os.getenv('PROGRAMDATA', 'C:\\ProgramData')
    roms_path = os.path.join(roms_base, 'RGS', 'roms')
    
    # Use AppData for logs (user-specific)
    appdata = os.getenv('APPDATA', os.path.expanduser('~'))
    log_dir = os.path.join(appdata, 'RGS', 'logs')
    log_file = os.path.join(log_dir, 'rgs_download.log')
    
    return roms_path, log_file

# Set environment variables if not already set
if 'ROMS_PATH' not in os.environ:
    roms_path = config.get('ROMS_PATH') or get_windows_paths()[0]
    os.environ['ROMS_PATH'] = roms_path

# Determine log file path - priority: LOG_FILE env > LOG_DIR from config.ini/env > default
if os.getenv('LOG_FILE'):
    log_file_path = os.path.abspath(os.getenv('LOG_FILE'))
elif config.get('LOG_DIR'):
    log_dir = config.get('LOG_DIR')
    log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
elif os.getenv('LOG_DIR'):
    log_dir = os.getenv('LOG_DIR')
    log_file_path = os.path.abspath(os.path.join(log_dir, 'rgs_download.log'))
else:
    _, log_file_path = get_windows_paths()
    log_file_path = os.path.abspath(log_file_path)

# Set LOG_FILE environment variable so download_service.py can use it
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
os.environ['LOG_FILE'] = log_file_path

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

# Patch paths after module load
if hasattr(download_service, 'log_file_path'):
    download_service.log_file_path = log_file_path

# Patch API_TOKEN path to look in executable directory
if hasattr(download_service, 'api_token_path'):
    download_service.api_token_path = EXE_DIR / 'API_TOKEN.txt'
elif hasattr(download_service, 'SERVICE_DIR'):
    # Update SERVICE_DIR if it exists
    download_service.SERVICE_DIR = EXE_DIR
    download_service.api_token_path = EXE_DIR / 'API_TOKEN.txt'

# Reconfigure logging with Windows path (in case module already configured it)
import logging
from logging.handlers import RotatingFileHandler

# Remove existing handlers
root_logger = logging.getLogger()
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Add new handler with Windows path
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=500 * 1024 * 1024,  # 500 MB
    backupCount=10
)
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
file_handler.setLevel(getattr(logging, log_level, logging.INFO))
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
root_logger.addHandler(file_handler)
root_logger.setLevel(getattr(logging, log_level, logging.INFO))

# Update the module's logger
if hasattr(download_service, 'logger'):
    download_service.logger = logging.getLogger('download_service')
    download_service.logger.info(f"Windows wrapper initialized. Log file: {log_file_path}")
else:
    logger = logging.getLogger('download_service')
    logger.info(f"Windows wrapper initialized. Log file: {log_file_path}")

# Patch ROMS_PATH in the module
if hasattr(download_service, 'ROMS_PATH'):
    download_service.ROMS_PATH = os.environ.get('ROMS_PATH', get_windows_paths()[0])

# Verify API_TOKEN can be loaded
if hasattr(download_service, 'API_TOKEN'):
    if not download_service.API_TOKEN:
        api_token_file = EXE_DIR / 'API_TOKEN.txt'
        if api_token_file.exists():
            try:
                with open(api_token_file, 'r', encoding='utf-8') as f:
                    download_service.API_TOKEN = f.read().strip()
                if download_service.API_TOKEN:
                    logging.getLogger('download_service').info(f"API_TOKEN loaded from {api_token_file}")
            except Exception as e:
                logging.getLogger('download_service').error(f"Failed to read API_TOKEN: {e}")

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
