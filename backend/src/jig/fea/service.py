"""Runs FEA for a finished build in its own process (gmsh and CalculiX stay out of the API)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from typing import Any

from jig.cad.builder import BuildResult
from jig.cad.program import Program
from jig.fea.ccx import CcxStatus
from jig.fea.spec import SpecError, parse_analysis


def unavailable(reason: str, status: str = "unavailable") -> dict[str, Any]:
    return {"ok": False, "status": status, "error": reason}


def analyze_build(
    build: BuildResult,
    program: Program,
    ccx: CcxStatus,
    *,
    timeout_s: float = 600,
    mesh_size_mm: float | None = None,
) -> dict[str, Any]:
    if not ccx.available:
        return unavailable(ccx.message)
    if not build.ok:
        return unavailable("The part did not build, so there is nothing to analyse", "error")
    if program.analysis is None:
        return unavailable(
            "This part has no ANALYSIS block yet (material, fixtures and loads)", "no_load_case"
        )
    try:
        parse_analysis(program.analysis, program.values())  # fail fast with a clear message
    except SpecError as error:
        return unavailable(str(error), "error")

    out_dir = build.out_dir / "fea"
    out_dir.mkdir(exist_ok=True)
    size = build.data["stats"]["bbox"]["size"]
    job = {
        "step": str(build.out_dir / "part.step"),
        "out_dir": str(out_dir),
        "face_info": build.data["face_info"],
        "diagonal": math.sqrt(sum(v * v for v in size)),
        "analysis": program.analysis,
        "params": program.values(),
        "ccx": ccx.path,
        "mesh_size_mm": mesh_size_mm,
        "timeout_s": timeout_s / 2,
    }
    job_path = out_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            [sys.executable, "-m", "jig.fea.solve", str(job_path)],
            cwd=out_dir,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return unavailable(f"FEA took longer than {timeout_s:g} s and was stopped", "error")
    result_path = out_dir / "fea.json"
    if not result_path.is_file():
        return unavailable("The FEA process exited without a result", "error")
    return json.loads(result_path.read_text(encoding="utf-8"))
