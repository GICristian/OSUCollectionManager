# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: folder dist/OSC/ cu OSC.exe + resurse CustomTkinter."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

project_root = Path(SPECPATH)

datas, binaries, hiddenimports = collect_all("customtkinter")

hi = list(hiddenimports)
hi.append("osc_collector._build_stamp")

a = Analysis(
    [str(project_root / "osc_collector" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hi,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OSC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OSC",
)
