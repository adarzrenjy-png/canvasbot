"""In-memory API key store.

Provider keys are held by the desktop app in the OS-backed vault and pushed to
this process at runtime. They are deliberately never written to SQLite, so this
store lives only for the lifetime of the backend process: restarting the app
re-pushes them from the vault.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_keys: dict[str, str] = {}


def set_key(provider: str, api_key: str) -> None:
    with _lock:
        if api_key:
            _keys[provider] = api_key
        else:
            _keys.pop(provider, None)


def get_key(provider: str) -> str | None:
    with _lock:
        return _keys.get(provider)


def has_key(provider: str) -> bool:
    return get_key(provider) is not None


def configured_providers() -> list[str]:
    with _lock:
        return sorted(_keys)


def clear() -> None:
    with _lock:
        _keys.clear()
