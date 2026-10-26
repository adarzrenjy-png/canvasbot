from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jig.fea import ccx


def make_exe(path: Path) -> None:
    path.write_text("#!/bin/sh\necho 'This is Version 2.99'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executables")
def test_scan_finds_versioned_names_newest_first(tmp_path: Path, monkeypatch) -> None:
    for name in ("ccx_2.21", "ccx_2.23", "ccxtool", "not_ccx"):
        make_exe(tmp_path / name)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ccx, "EXTRA_DIRS", ())
    found = [Path(p).name for p in ccx.scan_for_ccx()]
    assert found == ["ccx_2.23", "ccx_2.21"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX executables")
def test_find_reports_version_and_hint(tmp_path: Path, monkeypatch) -> None:
    make_exe(tmp_path / "ccx")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("JIG_CCX", raising=False)
    monkeypatch.setattr(ccx, "EXTRA_DIRS", ())
    ccx.find_ccx.cache_clear()
    status = ccx.find_ccx()
    ccx.find_ccx.cache_clear()
    assert status.available and status.version == "2.99"
    assert "Install" in ccx.install_hint() or "Get a Windows build" in ccx.install_hint()
