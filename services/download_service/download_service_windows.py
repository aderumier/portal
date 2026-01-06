"""
Windows-compatible wrapper for download_service.py
Handles Windows-specific paths and ensures standalone execution
"""
import os
import sys
import platform
from pathlib import Path

# Ensure we're running on Windows
if platform.system() != 'Windows':
    print("This script is designed for Windows only.")
    sys.exit(1)

# Get executable directory (works for both .py and .exe)
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    EXE_DIR = Path(sys.executable).parent
else:
    # Running as script
    EXE_DIR = Path(__file__).parent

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
    roms_path, _ = get_windows_paths()
    os.environ['ROMS_PATH'] = roms_path

# Import download_service module
# We need to modify paths before the module initializes logging
import importlib.util

# Load download_service as a module
service_file = EXE_DIR / "download_service.py"
if not service_file.exists():
    # Try relative to current file
    service_file = Path(__file__).parent / "download_service.py"

spec = importlib.util.spec_from_file_location("download_service", service_file)
download_service = importlib.util.module_from_spec(spec)

# Patch environment before module execution
_, log_file_path = get_windows_paths()
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
os.environ['LOG_FILE'] = log_file_path

# Execute the module
spec.loader.exec_module(download_service)

# Patch paths after module load
if hasattr(download_service, 'log_file_path'):
    download_service.log_file_path = log_file_path

# Patch API_TOKEN path
if hasattr(download_service, 'api_token_path'):
    download_service.api_token_path = EXE_DIR / 'API_TOKEN.txt'

# Reconfigure logging with Windows path
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
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
root_logger.addHandler(file_handler)
root_logger.setLevel(logging.INFO)

# Update the module's logger
download_service.logger = logging.getLogger(__name__)
download_service.logger.info(f"Windows wrapper initialized. Log file: {log_file_path}")

# Patch ROMS_PATH in the module
if hasattr(download_service, 'ROMS_PATH'):
    download_service.ROMS_PATH = os.environ.get('ROMS_PATH', get_windows_paths()[0])

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
