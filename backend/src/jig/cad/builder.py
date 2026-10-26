"""Runs part builds in sandboxed runner processes and keeps one warmed up.

Importing build123d takes a few seconds, which would make every parameter edit
feel sluggish. So the builder keeps one spare runner process that has already
imported it and is waiting for a job. Each process still runs exactly one job,
then exits, and a fresh spare starts in the background.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUNNER_ARGS = ["-I", "-m", "jig.cad.runner"]


@dataclass
class BuildResult:
    build_id: str
    out_dir: Path
    data: dict[str, Any]
    elapsed_ms: int

    @property
    def ok(self) -> bool:
        return bool(self.data.get("ok"))


class Builder:
    def __init__(self, builds_dir: Path, *, timeout_s: float = 60.0, keep: int = 40) -> None:
        self.builds_dir = builds_dir
        self.builds_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.keep = keep
        self._lock = threading.Lock()
        self._spare: subprocess.Popen[str] | None = None

    def _spawn(self) -> subprocess.Popen[str]:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            [sys.executable, *RUNNER_ARGS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=self.builds_dir,
            creationflags=flags,
        )

    def warm(self) -> None:
        with self._lock:
            if self._spare is None or self._spare.poll() is not None:
                self._spare = self._spawn()

    def _take(self) -> subprocess.Popen[str]:
        with self._lock:
            proc = self._spare
            self._spare = None
        if proc is None or proc.poll() is not None:
            proc = self._spawn()
        threading.Thread(target=self.warm, daemon=True).start()
        return proc

    def build(self, code: str, *, exports: tuple[str, ...] = ("step", "stl")) -> BuildResult:
        build_id = uuid.uuid4().hex[:12]
        out_dir = self.builds_dir / build_id
        out_dir.mkdir(parents=True)
        (out_dir / "part.py").write_text(code, encoding="utf-8")
        job = {
            "code": code,
            "out_dir": str(out_dir),
            "exports": list(exports),
            "timeout_s": self.timeout_s,
            "tolerance": 0.05,
            "angular_tolerance": 0.2,
        }
        job_path = out_dir / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")

        started = time.monotonic()
        proc = self._take()
        try:
            _, stderr = proc.communicate(f"{job_path}\n", timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            data = _failure(
                "timeout", f"Build took longer than {self.timeout_s:g} s and was stopped"
            )
        else:
            result_path = out_dir / "result.json"
            if result_path.is_file():
                data = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                tail = (stderr or "").strip().splitlines()[-3:]
                data = _failure("crash", "Build process exited unexpectedly: " + " ".join(tail))
        elapsed = int((time.monotonic() - started) * 1000)
        self._prune()
        return BuildResult(build_id=build_id, out_dir=out_dir, data=data, elapsed_ms=elapsed)

    def path_for(self, build_id: str, filename: str) -> Path | None:
        if not build_id.isalnum():
            return None
        path = self.builds_dir / build_id / filename
        return path if path.is_file() else None

    def _prune(self) -> None:
        dirs = sorted(
            (p for p in self.builds_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
        )
        for old in dirs[: max(0, len(dirs) - self.keep)]:
            shutil.rmtree(old, ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            proc, self._spare = self._spare, None
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()


def _failure(stage: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "features": [],
        "error": {"stage": stage, "message": message, "line": None, "feature": None},
    }
