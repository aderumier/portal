# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for creating a standalone Linux executable.
Build via: bash build_linux_bin.sh
"""

block_cipher = None

a = Analysis(
    ['download_service.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'p2p_client',
        'upnp_helper',
        'natpmp_helper',
        'requests',
        'requests.adapters',
        'requests.packages',
        'requests.packages.urllib3',
        'requests.packages.urllib3.util',
        'requests.packages.urllib3.util.retry',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'websockets.legacy.server',
        'schedule',
        'miniupnpc',
        'internetspeedtest',
        'xml.etree.ElementTree',
        'logging.handlers',
        'asyncio',
        'pathlib',
        'socket',
        'threading',
        'subprocess',
        'configparser',
        'tarfile',
        'hashlib',
        'struct',
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
    strip=True,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    target_arch=None,
)
