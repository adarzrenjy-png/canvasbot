# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Cadence backend binary.

Produces a single self-contained executable that Electron ships inside
Cadence.app/Contents/Resources/backend/ and spawns on launch.

Build with:  pyinstaller packaging/cadence-backend.spec --noconfirm
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is injected by PyInstaller. Deriving the project root from it keeps
# the build independent of the directory pyinstaller happens to run from.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# The analyser imports these packages to walk them, so the project has to be
# importable while the spec is being evaluated.
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# uvicorn resolves its event loop, protocol, and lifespan implementations by
# string at runtime, so the analyser cannot see them. SQLModel/SQLAlchemy pull
# their SQLite dialect the same way.
hiddenimports = [
    *collect_submodules("uvicorn"),
    *collect_submodules("backend"),
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.sql.default_comparator",
]

a = Analysis(
    [os.path.join(SPECPATH, "backend_entry.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim development-only weight from the shipped binary.
    excludes=["tkinter", "pytest", "_pytest", "alembic", "IPython", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cadence-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
