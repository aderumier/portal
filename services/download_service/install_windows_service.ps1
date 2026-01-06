# PowerShell script to install RGS Download Service on Windows
# Requires: Administrator privileges

param(
    [string]$ServiceName = "RGSDownloadService",
    [string]$DisplayName = "RGS Download Service",
    [string]$Description = "Downloads games for Retro Games Saviours",
    [string]$ServicePath = "",
    [string]$NSSMPath = ""
)

# Check for administrator privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires Administrator privileges." -ForegroundColor Red
    Write-Host "Please run PowerShell as Administrator and try again." -ForegroundColor Yellow
    exit 1
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Determine service path
if ([string]::IsNullOrEmpty($ServicePath)) {
    $ServicePath = Join-Path $ScriptDir "rgs_download_service.exe"
}

if (-not (Test-Path $ServicePath)) {
    Write-Host "ERROR: Service executable not found at: $ServicePath" -ForegroundColor Red
    exit 1
}

# Check for NSSM
if ([string]::IsNullOrEmpty($NSSMPath)) {
    # Try common locations
    $NSSMPaths = @(
        "C:\nssm\win64\nssm.exe",
        "C:\nssm\win32\nssm.exe",
        "C:\Program Files\nssm\nssm.exe",
        "C:\Program Files (x86)\nssm\nssm.exe",
        "$ScriptDir\nssm.exe"
    )
    
    $NSSMPath = $null
    foreach ($path in $NSSMPaths) {
        if (Test-Path $path) {
            $NSSMPath = $path
            break
        }
    }
}

if ([string]::IsNullOrEmpty($NSSMPath) -or -not (Test-Path $NSSMPath)) {
    Write-Host "NSSM not found. Downloading NSSM..." -ForegroundColor Yellow
    $NSSMDir = Join-Path $ScriptDir "nssm"
    New-Item -ItemType Directory -Force -Path $NSSMDir | Out-Null
    
    $NSSMUrl = "https://nssm.cc/release/nssm-2.24.zip"
    $NSSMZip = Join-Path $env:TEMP "nssm.zip"
    
    try {
        Invoke-WebRequest -Uri $NSSMUrl -OutFile $NSSMZip
        Expand-Archive -Path $NSSMZip -DestinationPath $NSSMDir -Force
        Remove-Item $NSSMZip
        
        # Find nssm.exe
        $NSSMPath = Get-ChildItem -Path $NSSMDir -Filter "nssm.exe" -Recurse | Select-Object -First 1 -ExpandProperty FullName
        
        if ([string]::IsNullOrEmpty($NSSMPath)) {
            Write-Host "ERROR: Failed to extract NSSM" -ForegroundColor Red
            exit 1
        }
        
        Write-Host "NSSM downloaded and extracted to: $NSSMPath" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to download NSSM: $_" -ForegroundColor Red
        Write-Host "Please download NSSM manually from https://nssm.cc/download" -ForegroundColor Yellow
        exit 1
    }
}

# Check if service already exists
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Service '$ServiceName' already exists." -ForegroundColor Yellow
    $response = Read-Host "Do you want to remove it and reinstall? (Y/N)"
    if ($response -eq "Y" -or $response -eq "y") {
        Write-Host "Removing existing service..." -ForegroundColor Yellow
        Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
        & $NSSMPath remove $ServiceName confirm
        Start-Sleep -Seconds 2
    } else {
        Write-Host "Installation cancelled." -ForegroundColor Yellow
        exit 0
    }
}

# Install service
Write-Host "Installing service..." -ForegroundColor Green
$ServiceDir = Split-Path -Parent $ServicePath

& $NSSMPath install $ServiceName `"$ServicePath`"
& $NSSMPath set $ServiceName AppDirectory `"$ServiceDir`"
& $NSSMPath set $ServiceName DisplayName `"$DisplayName`"
& $NSSMPath set $ServiceName Description `"$Description`"
& $NSSMPath set $ServiceName Start SERVICE_AUTO_START
& $NSSMPath set $ServiceName AppStdout `"$ServiceDir\service_stdout.log`"
& $NSSMPath set $ServiceName AppStderr `"$ServiceDir\service_stderr.log`"

# Set environment variables if config.ini exists
$ConfigFile = Join-Path $ServiceDir "config.ini"
if (Test-Path $ConfigFile) {
    Write-Host "Reading configuration from config.ini..." -ForegroundColor Green
    $config = Get-Content $ConfigFile | ConvertFrom-StringData
    
    $envVars = @()
    if ($config.API_URL) { $envVars += "API_URL=$($config.API_URL)" }
    if ($config.ROMS_PATH) { $envVars += "ROMS_PATH=$($config.ROMS_PATH)" }
    if ($config.SERVICE_ID) { $envVars += "SERVICE_ID=$($config.SERVICE_ID)" }
    if ($config.LOG_LEVEL) { $envVars += "LOG_LEVEL=$($config.LOG_LEVEL)" }
    if ($config.BANDWIDTH_UPDATE_INTERVAL) { $envVars += "BANDWIDTH_UPDATE_INTERVAL=$($config.BANDWIDTH_UPDATE_INTERVAL)" }
    
    if ($envVars.Count -gt 0) {
        $envString = $envVars -join "&"
        & $NSSMPath set $ServiceName AppEnvironmentExtra $envString
        Write-Host "Environment variables set from config.ini" -ForegroundColor Green
    }
}

# Verify API_TOKEN.txt exists
$TokenFile = Join-Path $ServiceDir "API_TOKEN.txt"
if (-not (Test-Path $TokenFile)) {
    Write-Host "WARNING: API_TOKEN.txt not found in service directory!" -ForegroundColor Yellow
    Write-Host "Please create API_TOKEN.txt with your API token before starting the service." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Service installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Ensure API_TOKEN.txt exists in: $ServiceDir" -ForegroundColor White
Write-Host "2. Start the service: Start-Service -Name $ServiceName" -ForegroundColor White
Write-Host "3. Check service status: Get-Service -Name $ServiceName" -ForegroundColor White
Write-Host "4. View logs: Get-Content '$env:APPDATA\RGS\logs\rgs_download.log' -Tail 50" -ForegroundColor White
Write-Host ""
Write-Host "To uninstall: & '$NSSMPath' remove $ServiceName confirm" -ForegroundColor Yellow

