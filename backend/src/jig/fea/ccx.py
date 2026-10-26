"""Finds the CalculiX solver (`ccx`). FEA features switch off cleanly without it."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# `ccx`, or a versioned build such as `ccx_2.23` (Homebrew) or `ccx_2.21_MT.exe`.
CCX_NAME = re.compile(r"^ccx(?:_(\d+(?:\.\d+)*))?(?:_[A-Za-z]+)?(?:\.exe)?$", re.IGNORECASE)
# Apps started from the Dock or Start menu may not inherit the shell's PATH.
EXTRA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


@dataclass(frozen=True)
class CcxStatus:
    available: bool
    path: str | None
    version: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "path": self.path,
            "version": self.version,
            "message": self.message,
            "install_hint": install_hint(),
        }


def install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        return (
            "Install with Homebrew: brew install costerwi/calculix/calculix-ccx "
            "(a community tap that builds CalculiX in a few minutes), then restart Jig."
        )
    if system == "Windows":
        return (
            "Get a Windows build of ccx.exe (for example the one bundled with PrePoMax, or the "
            "Windows links on calculix.de), then add its folder to PATH or set JIG_CCX in .env "
            "to the full path of ccx.exe."
        )
    return "Install with your package manager, e.g. sudo apt install calculix-ccx."


def _version(path: str) -> str | None:
    try:
        completed = subprocess.run(
            [path, "-v"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"[Vv]ersion\s+([\d.]+)", completed.stdout + completed.stderr)
    return match.group(1) if match else "unknown"


def _version_key(path: Path) -> tuple[int, ...]:
    match = CCX_NAME.match(path.name)
    if not match or not match.group(1):
        return (999,)  # a plain `ccx` is what the user chose to put on PATH: prefer it
    return tuple(int(part) for part in match.group(1).split("."))


def scan_for_ccx() -> list[str]:
    """Every ccx executable on PATH (plus Homebrew's folders), newest version first."""
    dirs = os.environ.get("PATH", "").split(os.pathsep) + list(EXTRA_DIRS)
    seen: set[Path] = set()
    found: list[Path] = []
    for raw in dirs:
        directory = Path(raw) if raw else None
        if directory is None or not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if CCX_NAME.match(entry.name) and entry.is_file() and os.access(entry, os.X_OK):
                resolved = entry.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(entry)
    found.sort(key=_version_key, reverse=True)
    return [str(p) for p in found]


@lru_cache(maxsize=1)
def find_ccx(override: str | None = None) -> CcxStatus:
    override = override or os.environ.get("JIG_CCX")
    candidates = [override] if override else []
    candidates += scan_for_ccx()
    for path in candidates:
        if path and (shutil.which(path) or Path(path).is_file()):
            version = _version(path)
            if version is not None:
                return CcxStatus(True, path, version, f"CalculiX {version} found")
    reason = (
        f"JIG_CCX points to {override}, which does not run"
        if override
        else "CalculiX (ccx) was not found on PATH"
    )
    return CcxStatus(False, None, None, f"{reason}. FEA checks are off until it is installed.")
