"""Runtime settings, read from the environment and an optional `.env` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _find_dotenv() -> Path | None:
    """Look for `.env` in the working directory and its parents, then the repo root."""
    candidates = [Path.cwd(), *Path.cwd().parents]
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root)
    for directory in candidates:
        path = directory / ".env"
        if path.is_file():
            return path
    return None


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    budget_usd: float
    build_timeout_s: float
    ccx_path: str | None

    @property
    def builds_dir(self) -> Path:
        return self.data_dir / "builds"

    @staticmethod
    def api_key(env_name: str) -> str | None:
        value = os.environ.get(env_name, "").strip()
        return value or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    dotenv = _find_dotenv()
    if dotenv is not None:
        load_dotenv(dotenv, override=False)
    data_dir = Path(os.environ.get("JIG_DATA_DIR") or Path.home() / ".jig").expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        budget_usd=_float_env("JIG_BUDGET_USD", 20.0),
        build_timeout_s=_float_env("JIG_BUILD_TIMEOUT_S", 60.0),
        ccx_path=os.environ.get("JIG_CCX") or None,
    )
