from __future__ import annotations

from pathlib import Path

import pytest

from jig.cad.builder import Builder


@pytest.fixture(scope="session")
def builder(tmp_path_factory: pytest.TempPathFactory) -> Builder:
    instance = Builder(tmp_path_factory.mktemp("builds"), timeout_s=90)
    instance.warm()
    yield instance
    instance.close()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JIG_DATA_DIR", str(tmp_path))
    return tmp_path
