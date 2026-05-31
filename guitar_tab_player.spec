# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Guitar Tab Player (Windows)
#
# Usage (run on Windows):
#   pip install pyinstaller
#   pyinstaller guitar_tab_player.spec
#
# The resulting installer folder lives in dist/GuitarTabPlayer/

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# i18n .mo files
datas += [(str(ROOT / "tabplayer" / "locale"), "tabplayer/locale")]

# PySide6 translations & plugins (collected automatically by the hook,
# but add qt_plugins explicitly to be safe)
datas += collect_data_files("PySide6")

# FluidSynth DLL – the build script copies it next to the .spec first.
# If the file exists, bundle it; otherwise the user must have it installed.
_fs_dll = ROOT / "build_windows" / "fluidsynth.dll"
if _fs_dll.exists():
    datas += [(str(_fs_dll), ".")]

# Default SoundFont (optional – only bundled if present in build_windows/)
for sf_name in ("default.sf2", "FluidR3_GM.sf2", "GeneralUser GS.sf2", "TimGM6mb.sf2"):
    sf_path = ROOT / "build_windows" / sf_name
    if sf_path.exists():
        datas += [(str(sf_path), ".")]
        break

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = [
    "fluidsynth",
    "numpy",
    "tabplayer",
    "tabplayer.app",
    "tabplayer.player",
    "tabplayer.parser",
    "tabplayer.generator",
    "tabplayer.tuning",
    "tabplayer.examples",
    "tabplayer.i18n",
]
hiddenimports += collect_submodules("PySide6.QtWidgets")
hiddenimports += collect_submodules("PySide6.QtCore")
hiddenimports += collect_submodules("PySide6.QtGui")

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "tabplayer" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuitarTabPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # no console window
    icon=str(ROOT / "build_windows" / "icon.ico") if (ROOT / "build_windows" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GuitarTabPlayer",
)
