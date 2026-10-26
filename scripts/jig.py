#!/usr/bin/env python3
"""Jig launcher. One command to set up and run Jig on macOS, Windows, and Linux.

    python scripts/jig.py setup     create .venv, install the backend and the UI
    python scripts/jig.py start     build the UI if needed, start Jig, open the browser
    python scripts/jig.py dev       backend with auto-reload plus the Vite dev server
    python scripts/jig.py test      run the backend tests and the UI type check
    python scripts/jig.py sample    build the sample part to STEP, STL, and .py
    python scripts/jig.py ping      make one real Meta Model API call
    python scripts/jig.py doctor    check Python, build123d, CalculiX, and API keys

Uses only the standard library, so it runs before anything is installed. On
Windows use `py scripts\\jig.py ...` if `python` is not on PATH.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = ROOT / ".venv"
HOST = "127.0.0.1"
PORT = int(os.environ.get("JIG_PORT", "8765"))
MIN_PY, MAX_PY = (3, 11), (3, 14)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def backend_python() -> str:
    """The interpreter that has Jig installed: JIG_PYTHON, then .venv, then this one."""
    override = os.environ.get("JIG_PYTHON")
    if override:
        return override
    if venv_python().is_file():
        return str(venv_python())
    return sys.executable


def npm() -> str | None:
    return shutil.which("npm")


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=cwd, check=False)
    if completed.returncode != 0:
        sys.exit(completed.returncode)


def ensure_env_file() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        shutil.copyfile(example, env)
        print("Created .env from .env.example. Add your MODEL_API_KEY there.")


def cmd_setup(_: argparse.Namespace) -> None:
    if not (MIN_PY <= sys.version_info[:2] <= MAX_PY):
        sys.exit(
            f"Jig needs Python {MIN_PY[0]}.{MIN_PY[1]} to {MAX_PY[0]}.{MAX_PY[1]}; "
            f"this is {sys.version.split()[0]}. Python 3.12 is the safest choice."
        )
    if not venv_python().is_file():
        run([sys.executable, "-m", "venv", str(VENV)])
    py = str(venv_python())
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-e", f"{BACKEND}[dev]"])
    if npm():
        run([npm(), "ci"], cwd=FRONTEND)
    else:
        print("Node.js (npm) was not found. Install Node 20.19 or newer for the UI.")
    ensure_env_file()
    run([py, "-m", "jig.cli", "doctor"])
    print("\nSetup done. Start Jig with: python scripts/jig.py start")


def build_ui(force: bool = False) -> None:
    if (FRONTEND / "dist" / "index.html").is_file() and not force:
        return
    if not npm():
        sys.exit("The UI is not built and npm was not found. Install Node.js, then run setup.")
    if not (FRONTEND / "node_modules").is_dir():
        run([npm(), "ci"], cwd=FRONTEND)
    run([npm(), "run", "build"], cwd=FRONTEND)


def wait_for_backend(timeout_s: float = 60) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def uvicorn_cmd(reload: bool) -> list[str]:
    cmd = [backend_python(), "-m", "uvicorn", "jig.app:get_app", "--factory"]
    cmd += ["--host", HOST, "--port", str(PORT)]
    if reload:
        cmd += ["--reload", "--reload-dir", str(BACKEND / "src")]
    return cmd


def supervise(procs: list[subprocess.Popen], url: str, open_browser: bool) -> None:
    try:
        if wait_for_backend() and open_browser:
            print(f"\nJig is running at {url}  (Ctrl+C to stop)\n", flush=True)
            webbrowser.open(url)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def cmd_start(args: argparse.Namespace) -> None:
    build_ui(force=args.rebuild_ui)
    ensure_env_file()
    backend = subprocess.Popen(uvicorn_cmd(reload=False), cwd=ROOT)
    supervise([backend], f"http://{HOST}:{PORT}", open_browser=not args.no_browser)


def cmd_dev(args: argparse.Namespace) -> None:
    if not npm():
        sys.exit("npm was not found. Install Node.js 20.19+ for the UI dev server.")
    if not (FRONTEND / "node_modules").is_dir():
        run([npm(), "ci"], cwd=FRONTEND)
    ensure_env_file()
    env = {**os.environ, "JIG_BACKEND_URL": f"http://{HOST}:{PORT}"}
    backend = subprocess.Popen(uvicorn_cmd(reload=True), cwd=ROOT)
    ui = subprocess.Popen([npm(), "run", "dev"], cwd=FRONTEND, env=env)
    supervise([backend, ui], "http://localhost:5173", open_browser=not args.no_browser)


def cmd_test(_: argparse.Namespace) -> None:
    run([backend_python(), "-m", "pytest", "-q"], cwd=BACKEND)
    if npm():
        run([npm(), "run", "typecheck"], cwd=FRONTEND)


def passthrough(command: str):
    def handler(args: argparse.Namespace) -> None:
        run([backend_python(), "-m", "jig.cli", command, *args.extra])

    return handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Jig launcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="install everything").set_defaults(func=cmd_setup)
    start = sub.add_parser("start", help="run Jig")
    start.add_argument("--no-browser", action="store_true")
    start.add_argument("--rebuild-ui", action="store_true")
    start.set_defaults(func=cmd_start)
    dev = sub.add_parser("dev", help="run with auto-reload")
    dev.add_argument("--no-browser", action="store_true")
    dev.set_defaults(func=cmd_dev)
    sub.add_parser("test", help="run the tests").set_defaults(func=cmd_test)
    for name, text in (
        ("sample", "build the sample part"),
        ("ping", "one Meta API call"),
        ("doctor", "check the setup"),
    ):
        sub.add_parser(name, help=text).set_defaults(func=passthrough(name), passthrough=True)
    # Options after sample/ping/doctor belong to the backend CLI, so pass them through.
    args, extra = parser.parse_known_args()
    if extra and not getattr(args, "passthrough", False):
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    args.extra = extra
    args.func(args)


if __name__ == "__main__":
    main()
