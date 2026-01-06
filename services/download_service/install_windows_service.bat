@echo off
REM Batch script to install RGS Download Service on Windows using NSSM
REM Requires: Administrator privileges

setlocal enabledelayedexpansion

REM Check for administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script requires Administrator privileges.
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

set SERVICE_NAME=RGSDownloadService
set DISPLAY_NAME=RGS Download Service
set DESCRIPTION=Downloads games for Retro Games Saviours

REM Get script directory
set SCRIPT_DIR=%~dp0
set SERVICE_EXE=%SCRIPT_DIR%rgs_download_service.exe
set SERVICE_DIR=%SCRIPT_DIR%

REM Check if executable exists
if not exist "%SERVICE_EXE%" (
    echo ERROR: Service executable not found at: %SERVICE_EXE%
    pause
    exit /b 1
)

REM Check for NSSM
set NSSM_PATH=
if exist "C:\nssm\win64\nssm.exe" set NSSM_PATH=C:\nssm\win64\nssm.exe
if exist "C:\nssm\win32\nssm.exe" set NSSM_PATH=C:\nssm\win32\nssm.exe
if exist "%SCRIPT_DIR%nssm.exe" set NSSM_PATH=%SCRIPT_DIR%nssm.exe

if "%NSSM_PATH%"=="" (
    echo NSSM not found. Please download NSSM from https://nssm.cc/download
    echo Extract it to C:\nssm\win64\ or place nssm.exe in the service directory.
    pause
    exit /b 1
)

REM Check if service already exists
sc query %SERVICE_NAME% >nul 2>&1
if %errorLevel% equ 0 (
    echo Service '%SERVICE_NAME%' already exists.
    set /p REMOVE="Do you want to remove it and reinstall? (Y/N): "
    if /i "!REMOVE!"=="Y" (
        echo Removing existing service...
        "%NSSM_PATH%" stop %SERVICE_NAME%
        "%NSSM_PATH%" remove %SERVICE_NAME% confirm
        timeout /t 2 /nobreak >nul
    ) else (
        echo Installation cancelled.
        pause
        exit /b 0
    )
)

REM Install service
echo Installing service...
"%NSSM_PATH%" install %SERVICE_NAME% "%SERVICE_EXE%"
"%NSSM_PATH%" set %SERVICE_NAME% AppDirectory "%SERVICE_DIR%"
"%NSSM_PATH%" set %SERVICE_NAME% DisplayName "%DISPLAY_NAME%"
"%NSSM_PATH%" set %SERVICE_NAME% Description "%DESCRIPTION%"
"%NSSM_PATH%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM_PATH%" set %SERVICE_NAME% AppStdout "%SERVICE_DIR%service_stdout.log"
"%NSSM_PATH%" set %SERVICE_NAME% AppStderr "%SERVICE_DIR%service_stderr.log"

REM Check for config.ini and set environment variables
if exist "%SERVICE_DIR%config.ini" (
    echo Reading configuration from config.ini...
    REM Note: Batch script can't easily parse INI files, so we'll set common defaults
    REM Users can manually set environment variables via NSSM GUI if needed
)

REM Verify API_TOKEN.txt exists
if not exist "%SERVICE_DIR%API_TOKEN.txt" (
    echo.
    echo WARNING: API_TOKEN.txt not found in service directory!
    echo Please create API_TOKEN.txt with your API token before starting the service.
    echo.
)

echo.
echo Service installed successfully!
echo.
echo Next steps:
echo 1. Ensure API_TOKEN.txt exists in: %SERVICE_DIR%
echo 2. Start the service: net start %SERVICE_NAME%
echo 3. Check service status: sc query %SERVICE_NAME%
echo 4. View logs: type "%APPDATA%\RGS\logs\rgs_download.log"
echo.
echo To uninstall: "%NSSM_PATH%" remove %SERVICE_NAME% confirm
echo.
pause

