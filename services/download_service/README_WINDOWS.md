# RGS Download Service - Windows Installation Guide

This guide explains how to install and run the RGS Download Service on Windows as a standalone executable or Windows service.

## Prerequisites

- Windows 7 or later
- No Python installation required (Python is embedded in the executable)
- Administrator privileges (for service installation)

## Quick Start

### Option 1: Run as Standalone Application

1. Download the latest release from GitHub
2. Extract `rgs_download_service.exe` and `API_TOKEN.txt` to a folder
3. Edit `API_TOKEN.txt` and add your API token
4. Double-click `rgs_download_service.exe` to run

### Option 2: Install as Windows Service (Recommended)

#### Using PowerShell Script (Easiest)

1. Download the latest release
2. Extract all files to a folder (e.g., `C:\RGS\DownloadService`)
3. Edit `API_TOKEN.txt` and add your API token
4. Right-click `install_windows_service.ps1` → "Run with PowerShell"
5. The script will:
   - Download NSSM automatically if needed
   - Install the service
   - Configure it to start automatically

#### Using Batch Script

1. Download the latest release
2. Extract all files to a folder
3. Download NSSM from https://nssm.cc/download
4. Extract NSSM to `C:\nssm\win64\` or place `nssm.exe` in the service folder
5. Edit `API_TOKEN.txt` and add your API token
6. Right-click `install_windows_service.bat` → "Run as administrator"
7. Follow the prompts

#### Manual Installation with NSSM

1. Download NSSM from https://nssm.cc/download
2. Extract to `C:\nssm\win64\`
3. Open Command Prompt as Administrator
4. Navigate to the service directory
5. Run:
   ```batch
   C:\nssm\win64\nssm.exe install RGSDownloadService "C:\path\to\rgs_download_service.exe"
   C:\nssm\win64\nssm.exe set RGSDownloadService AppDirectory "C:\path\to\service\folder"
   C:\nssm\win64\nssm.exe set RGSDownloadService DisplayName "RGS Download Service"
   C:\nssm\win64\nssm.exe set RGSDownloadService Description "Downloads games for Retro Games Saviours"
   C:\nssm\win64\nssm.exe set RGSDownloadService Start SERVICE_AUTO_START
   ```

## Configuration

### Environment Variables

Set these via NSSM GUI or command line:

- `API_URL`: Backend API URL (default: `https://rgs-retro.ddns.net`)
- `ROMS_PATH`: Path to ROMs directory (default: `C:\ProgramData\RGS\roms`)
- `SERVICE_ID`: Service identifier (default: hostname)
- `LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)
- `BANDWIDTH_UPDATE_INTERVAL`: Progress update interval in seconds (default: 5)

### Using NSSM GUI to Set Environment Variables

1. Run: `C:\nssm\win64\nssm.exe edit RGSDownloadService`
2. Go to "Environment" tab
3. Add variables in format: `VARIABLE_NAME=value`
4. Click "Install service" or "Edit service"

### Using Command Line

```batch
C:\nssm\win64\nssm.exe set RGSDownloadService AppEnvironmentExtra "API_URL=https://your-api.com^&ROMS_PATH=C:\Games\ROMs^&SERVICE_ID=my-service-1"
```

Note: Use `^&` to separate multiple variables in batch files.

## Service Management

### Start Service
```batch
net start RGSDownloadService
```
Or via Services GUI: `services.msc` → Find "RGS Download Service" → Start

### Stop Service
```batch
net stop RGSDownloadService
```

### Check Status
```batch
sc query RGSDownloadService
```

### View Logs
Logs are written to: `%APPDATA%\RGS\logs\rgs_download.log`

View recent logs:
```batch
powershell Get-Content "$env:APPDATA\RGS\logs\rgs_download.log" -Tail 50
```

### Uninstall Service
```batch
C:\nssm\win64\nssm.exe remove RGSDownloadService confirm
```

## File Structure

```
RGS_Download_Service/
├── rgs_download_service.exe    # Main executable (standalone, no Python needed)
├── API_TOKEN.txt               # Your API token (REQUIRED)
├── config.ini                  # Configuration template (optional)
├── README.txt                  # This file
├── install_windows_service.ps1 # PowerShell installation script
└── install_windows_service.bat # Batch installation script
```

## Troubleshooting

### Service Won't Start

1. Check that `API_TOKEN.txt` exists and contains a valid token
2. Check service logs: `%SERVICE_DIR%\service_stdout.log` and `service_stderr.log`
3. Check application logs: `%APPDATA%\RGS\logs\rgs_download.log`
4. Verify executable path in NSSM: `nssm.exe edit RGSDownloadService`

### "API_TOKEN is required" Error

- Ensure `API_TOKEN.txt` is in the same directory as `rgs_download_service.exe`
- Check that the file contains only the token (no extra whitespace)
- Verify file encoding is UTF-8

### Downloads Not Working

1. Check API_URL is correct
2. Verify ROMS_PATH exists and is writable
3. Check network connectivity to API_URL
4. Review logs for specific error messages

### Large Executable Size

The executable is ~20-50MB because it includes:
- Python interpreter
- All Python dependencies (requests, etc.)
- All required libraries

This is normal for a standalone executable. No Python installation is needed on target machines.

## Building from Source

If you want to build the executable yourself:

1. Install Python 3.11+ on Windows
2. Install dependencies: `pip install -r requirements.txt pyinstaller`
3. Run: `pyinstaller download_service.spec --clean`
4. Executable will be in `dist\rgs_download_service.exe`

Or use GitHub Actions to build automatically (see `.github/workflows/build-windows.yml`).

## Support

For issues or questions:
- Check logs: `%APPDATA%\RGS\logs\rgs_download.log`
- Review GitHub Issues: https://github.com/aderumier/portal/issues

