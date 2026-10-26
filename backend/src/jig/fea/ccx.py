"""Finds the CalculiX solver (`ccx`). FEA features switch off cleanly without it."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

CANDIDATE_NAMES = ("ccx", "ccx_2.23", "ccx_2.22", "ccx_2.21", "ccx_2.20", "ccx_static", "ccx_MT")


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
        return "Install with Homebrew: brew install calculix-ccx (then restart Jig)."
    if system == "Windows":
        return (
            "Download the official CalculiX Windows build (bConverged/calculix.de), unzip it, "
            "and add the folder containing ccx.exe to PATH, or set JIG_CCX to its full path."
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


@lru_cache(maxsize=1)
def find_ccx(override: str | None = None) -> CcxStatus:
    override = override or os.environ.get("JIG_CCX")
    candidates = [override] if override else []
    candidates += [found for name in CANDIDATE_NAMES if (found := shutil.which(name))]
    for path in candidates:
        if path and shutil.which(path):
            version = _version(path)
            if version is not None:
                return CcxStatus(True, path, version, f"CalculiX {version} found")
    reason = (
        f"JIG_CCX points to {override}, which does not run"
        if override
        else "CalculiX (ccx) was not found on PATH"
    )
    return CcxStatus(False, None, None, f"{reason}. FEA checks are off until it is installed.")
