# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for creating standalone Windows executable
This creates a single .exe file with embedded Python interpreter
"""

import os
from pathlib import Path

block_cipher = None

# Get the directory where this spec file is located
spec_dir = Path(SPECPATH).parent

a = Analysis(
    ['download_service_windows.py'],
    pathex=[str(spec_dir)],
    binaries=[],
    datas=[
        # Include download_service.py as data (it will be imported)
        (str(spec_dir / 'download_service.py'), '.'),
    ],
    hiddenimports=[
        'requests',
        'requests.adapters',
        'requests.packages',
        'requests.packages.urllib3',
        'requests.packages.urllib3.util',
        'requests.packages.urllib3.util.retry',
        'schedule',
        'xml.etree.ElementTree',
        'logging.handlers',
        'pathlib',
        'socket',
        'threading',
        'subprocess',
        'importlib',
        'importlib.util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'PyQt5',
        'PyQt6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='rgs_download_service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress executable (smaller file size)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Show console for debugging (set to False for service)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)
