# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file, windowed build of Caplift UI.

Build with:
    pyinstaller --clean --noconfirm main.spec

The result is dist/caplift-ui.exe, which bundles the Python runtime. Place it
next to lmstudio-caplift.exe and the UI will find the CLI automatically.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# CustomTkinter ships theme JSON assets that must travel with the binary.
datas = collect_data_files("customtkinter")
hiddenimports = collect_submodules("customtkinter")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim packages this app never imports; keep tkinter/PIL (CustomTkinter needs both).
    excludes=["pytest", "numpy", "pandas", "matplotlib"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="caplift-ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Windowed: no console window. Subprocess calls use CREATE_NO_WINDOW so the
    # CLI does not flash one either.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
