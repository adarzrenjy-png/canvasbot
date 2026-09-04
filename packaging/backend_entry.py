"""Entry point for the standalone Cadence backend binary.

PyInstaller freezes this module together with the FastAPI application so the
packaged macOS app does not need Python, a virtualenv, or pip on the user's
machine. Electron spawns the resulting binary and talks to it over loopback.

Configuration is read from the environment because the packaged app has no
writable project directory to hold a .env file:

    CADENCE_API_HOST   interface to bind (default 127.0.0.1)
    CADENCE_API_PORT   port to bind (default 8000)
    DATABASE_URL       SQLite URL, pointed at Electron's userData directory
"""

from __future__ import annotations

import os
import sys

# Python puts this file's directory (packaging/) on sys.path, not the project
# root, so "import backend" would fail when the script is run directly. A frozen
# build carries its own import table and needs no help.
if not getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)


def main() -> int:
    # Imported lazily so PyInstaller's dependency graph stays rooted here and
    # any import failure is reported with a usable traceback.
    import uvicorn

    from backend.app.main import app

    host = os.environ.get("CADENCE_API_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("CADENCE_API_PORT", "8000"))
    except ValueError:
        print("CADENCE_API_PORT must be an integer", file=sys.stderr)
        return 2

    # Refuse to expose the planner beyond the local machine. The API has no
    # authentication; it is reachable only by the desktop app that spawned it.
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"refusing to bind {host}: the local API is loopback-only", file=sys.stderr)
        return 2

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
