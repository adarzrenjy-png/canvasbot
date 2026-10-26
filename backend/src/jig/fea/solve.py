"""Runs one FEA load case end to end: `python -m jig.fea.solve job.json`.

1. Pick the fixture and load faces with the spec's selectors.
2. Mesh the STEP part with quadratic tetrahedra at two sizes (coarse, then finer).
3. Solve each mesh with CalculiX.
4. Check the answer before trusting it:
   * equilibrium: the reactions at the fixtures must balance the applied loads;
   * convergence: peak stress and displacement must settle between the two meshes.
5. Score the finer mesh: safety factor = allowable stress / peak von Mises.

Peak stress is taken away from the fixtures. A fully fixed face is an idealised
clamp, and the stress right at its edge grows without limit as the mesh is refined
(a singularity), so it says nothing about the real part. The raw peak, including
those nodes, is reported alongside so nothing is hidden.

The verdict is computed here, from numbers. A model never gets to call a part safe.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from array import array
from pathlib import Path
from typing import Any

import numpy as np

from jig.fea.deck import BoundarySet, ForceSet, surface_nodes, write_deck
from jig.fea.frd import nodal_results, read_blocks, von_mises
from jig.fea.mesh import Mesh, match_surfaces, mesh_step
from jig.fea.spec import AnalysisSpec, parse_analysis, select_faces

STRESS_TOLERANCE = 0.10  # max change in peak stress between meshes to call it converged
DISP_TOLERANCE = 0.05
EQUILIBRIUM_TOLERANCE = 0.01


class AnalysisError(RuntimeError):
    pass


def _b64(values: array) -> str:
    if sys.byteorder != "little":
        values.byteswap()
    return base64.b64encode(values.tobytes()).decode("ascii")


def run_ccx(ccx: str, deck: str, work: Path, timeout_s: float) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    (work / "job.inp").write_text(deck, encoding="ascii")
    env = {**os.environ, "OMP_NUM_THREADS": str(os.cpu_count() or 1)}
    env["CCX_NPROC_EQUATION_SOLVER"] = env["OMP_NUM_THREADS"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(
            [ccx, "-i", "job"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            creationflags=flags,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AnalysisError(f"CalculiX took longer than {timeout_s:g} s") from error
    (work / "ccx.log").write_text(done.stdout + done.stderr, encoding="utf-8")
    errors = [line.strip() for line in done.stdout.splitlines() if "*ERROR" in line]
    frd = work / "job.frd"
    if done.returncode != 0 or errors or not frd.is_file():
        detail = errors[0] if errors else (done.stdout + done.stderr).strip()[-300:]
        raise AnalysisError(f"CalculiX failed: {detail}")
    return frd


def _fixture_dofs(fixture, faces: list[dict]) -> tuple[int, ...]:
    if fixture.type == "fixed":
        return (1, 2, 3)
    axes = set()
    for face in faces:
        normal = face.get("normal")
        axis = None if normal is None else max(range(3), key=lambda k: abs(normal[k]))
        if axis is None or abs(normal[axis]) < 0.999:
            raise AnalysisError(f"Support '{fixture.name}' needs flat faces facing along X, Y or Z")
        axes.add(axis + 1)
    return tuple(sorted(axes))


def _groups(spec: AnalysisSpec, face_info: list[dict]) -> tuple[list, list]:
    fixtures, loads = [], []
    for fixture in spec.fixtures:
        faces = select_faces(face_info, fixture.faces)
        if not faces:
            raise AnalysisError(
                f"Fixture '{fixture.name}' matched no faces ({fixture.faces.describe()})"
            )
        fixtures.append((fixture, faces, _fixture_dofs(fixture, [face_info[i] for i in faces])))
    for load in spec.loads:
        faces = select_faces(face_info, load.faces)
        if not faces:
            raise AnalysisError(f"Load '{load.name}' matched no faces ({load.faces.describe()})")
        loads.append((load, faces))
    return fixtures, loads


def solve_level(
    mesh: Mesh,
    spec: AnalysisSpec,
    fixtures: list,
    loads: list,
    face_to_surface: dict[int, int],
    ccx: str,
    work: Path,
    timeout_s: float,
) -> dict[str, Any]:
    boundary = [
        BoundarySet(f.name, [face_to_surface[i] for i in faces], dofs)
        for f, faces, dofs in fixtures
    ]
    forces = [
        ForceSet(load.name, [face_to_surface[i] for i in faces], load.force)
        for load, faces in loads
    ]
    deck = write_deck(mesh, spec.material, boundary, forces).replace(
        "*NODE FILE\nU", "*NODE FILE\nU, RF"
    )
    started = time.monotonic()
    frd = run_ccx(ccx, deck, work, timeout_s)
    solve_s = time.monotonic() - started

    ids, u, s = nodal_results(frd)
    vm = von_mises(s)
    index = {int(n): i for i, n in enumerate(ids)}
    xyz = mesh.coord_lookup()

    # Reactions come from every held face; the stress exclusion zone only from fully
    # fixed ones, whose edges are the idealised clamps that make singularities.
    held = surface_nodes(mesh, [t for b in boundary for t in b.surface_tags])
    fixed = surface_nodes(mesh, [t for b in boundary if len(b.dofs) == 3 for t in b.surface_tags])
    if len(fixed) == 0:
        fixed = held
    fixed_xyz = np.array([xyz[int(n)] for n in fixed])
    node_xyz = np.array([xyz[int(n)] for n in ids])
    # Distance from every node to the nearest fixed node, in chunks to bound memory.
    near = np.zeros(len(ids), dtype=bool)
    radius = mesh.size
    for start in range(0, len(ids), 4096):
        block = node_xyz[start : start + 4096]
        d = np.min(np.linalg.norm(block[:, None, :] - fixed_xyz[None, :, :], axis=2), axis=1)
        near[start : start + 4096] = d <= radius

    disp = np.linalg.norm(u, axis=1)
    i_disp = int(np.argmax(disp))
    i_raw = int(np.argmax(vm))
    away = np.where(~near)[0]
    i_away = int(away[np.argmax(vm[away])]) if len(away) else i_raw

    # Equilibrium: reactions at the fixtures should cancel the applied loads.
    reactions = read_blocks(frd).get("FORC", {})
    reaction = np.sum([reactions[n][:3] for n in held.tolist() if n in reactions], axis=0)
    applied = np.sum([np.array(load.force) for load, _ in loads], axis=0)
    imbalance = float(np.linalg.norm(reaction + applied) / max(np.linalg.norm(applied), 1e-12))

    return {
        "mesh_size_mm": mesh.size,
        "nodes": int(len(mesh.node_ids)),
        "elements": int(len(mesh.tets)),
        "solve_s": round(solve_s, 2),
        "max_displacement_mm": float(disp[i_disp]),
        "max_displacement_at": node_xyz[i_disp].tolist(),
        "peak_von_mises_mpa": float(vm[i_away]),
        "peak_von_mises_at": node_xyz[i_away].tolist(),
        "raw_peak_von_mises_mpa": float(vm[i_raw]),
        "raw_peak_at": node_xyz[i_raw].tolist(),
        "reaction_n": reaction.tolist(),
        "applied_n": applied.tolist(),
        "equilibrium_error": imbalance,
        "_field": (ids, index, u, vm),
    }


def surface_field(
    mesh: Mesh, ids_index: dict[int, int], u: np.ndarray, vm: np.ndarray, split: bool = True
) -> dict:
    """The outer surface as linear triangles with nodal results. Each 6-node triangle is
    split in four (all its nodes carry results); `split=False` keeps only its corners,
    a quarter of the size, for pictures."""
    xyz = mesh.coord_lookup()
    used: dict[int, int] = {}
    positions, values, moves = array("f"), array("f"), array("f")
    indices = array("I")

    def vertex(node: int) -> int:
        if node not in used:
            used[node] = len(used)
            positions.extend(float(c) for c in xyz[node])
            i = ids_index.get(node)
            values.append(float(vm[i]) if i is not None else 0.0)
            moves.extend(float(c) for c in (u[i] if i is not None else (0.0, 0.0, 0.0)))
        return used[node]

    for surface in mesh.surfaces.values():
        for a, b, c, ab, bc, ca in surface.tris.tolist():
            parts = ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)) if split else ((a, b, c),)
            for tri in parts:
                indices.extend(vertex(n) for n in tri)
    return {
        "positions": _b64(positions),
        "indices": _b64(indices),
        "von_mises": _b64(values),
        "displacement": _b64(moves),
        "triangles": len(indices) // 3,
    }


def analyze(job: dict[str, Any]) -> dict[str, Any]:
    out_dir = Path(job["out_dir"])
    spec = parse_analysis(job["analysis"], job.get("params", {}))
    face_info = job["face_info"]
    diagonal = float(job["diagonal"])
    fixtures, loads = _groups(spec, face_info)
    base = float(job.get("mesh_size_mm") or diagonal / 25)
    sizes = [base, base / 1.6]
    levels = []
    for n, size in enumerate(sizes):
        mesh = mesh_step(Path(job["step"]), size)
        needed = [face_info[i] for group in fixtures + loads for i in group[1]]
        mapping = match_surfaces(mesh, needed, diagonal)
        level = solve_level(
            mesh,
            spec,
            fixtures,
            loads,
            mapping,
            job["ccx"],
            out_dir / f"mesh{n + 1}",
            float(job.get("timeout_s", 300)),
        )
        levels.append((mesh, level))

    fine_mesh, fine = levels[-1]
    coarse = levels[0][1]
    ids, index, u, vm = fine.pop("_field")
    _, c_index, c_u, c_vm = coarse.pop("_field")
    preview = surface_field(levels[0][0], c_index, c_u, c_vm, split=False)  # for report pictures

    def change(key: str) -> float:
        return abs(fine[key] - coarse[key]) / max(abs(fine[key]), 1e-12)

    stress_change = change("peak_von_mises_mpa")
    disp_change = change("max_displacement_mm")
    converged = stress_change <= STRESS_TOLERANCE and disp_change <= DISP_TOLERANCE
    balanced = fine["equilibrium_error"] <= EQUILIBRIUM_TOLERANCE

    allowable = spec.material.allowable_mpa
    safety_factor = allowable / max(fine["peak_von_mises_mpa"], 1e-12)
    checks = [
        {
            "id": "safety_factor",
            "label": "Safety factor",
            "value": safety_factor,
            "limit": spec.min_safety_factor,
            "pass": safety_factor >= spec.min_safety_factor,
            "detail": f"{allowable:g} MPa allowable / {fine['peak_von_mises_mpa']:.1f} MPa peak",
        }
    ]
    if spec.max_displacement_mm is not None:
        checks.append(
            {
                "id": "displacement",
                "label": "Max displacement",
                "value": fine["max_displacement_mm"],
                "limit": spec.max_displacement_mm,
                "pass": fine["max_displacement_mm"] <= spec.max_displacement_mm,
                "detail": "mm, largest movement of any point",
            }
        )
    failed = [c for c in checks if not c["pass"]]
    if failed:
        status = "fail"  # failing on the finer mesh is never overturned by refinement doubts
    elif not balanced:
        status = "invalid"
    elif not converged:
        status = "unconverged"
    else:
        status = "pass"

    return {
        "ok": True,
        "status": status,
        "safety_factor": safety_factor,
        "checks": checks,
        "material": spec.material.to_dict(),
        "fixtures": [
            {"name": f.name, "type": f.type, "faces": faces, "selector": f.faces.describe()}
            for f, faces, _ in fixtures
        ],
        "loads": [
            {
                "name": ld.name,
                "faces": faces,
                "selector": ld.faces.describe(),
                "force_n": list(ld.force),
            }
            for ld, faces in loads
        ],
        "levels": [level for _, level in levels],
        "convergence": {
            "stress_change": stress_change,
            "displacement_change": disp_change,
            "converged": converged,
            "stress_tolerance": STRESS_TOLERANCE,
            "displacement_tolerance": DISP_TOLERANCE,
        },
        "equilibrium": {"error": fine["equilibrium_error"], "ok": balanced},
        "result": {
            "peak_von_mises_mpa": fine["peak_von_mises_mpa"],
            "peak_at": fine["peak_von_mises_at"],
            "raw_peak_von_mises_mpa": fine["raw_peak_von_mises_mpa"],
            "max_displacement_mm": fine["max_displacement_mm"],
            "max_displacement_at": fine["max_displacement_at"],
        },
        "field": surface_field(fine_mesh, index, u, vm),
        "field_preview": preview,
        "versions": _versions(job["ccx"]),
    }


def _versions(ccx: str) -> dict[str, str]:
    import gmsh

    try:
        out = subprocess.run([ccx, "-v"], capture_output=True, text=True, timeout=10).stdout
        ccx_version = next((w for w in out.split() if w[:1].isdigit()), "unknown")
    except (OSError, subprocess.SubprocessError):
        ccx_version = "unknown"
    return {"gmsh": gmsh.__version__, "calculix": ccx_version}


def find_ccx_or_fail(path: str | None) -> str:
    resolved = shutil.which(path) if path else None
    if not resolved:
        raise AnalysisError("CalculiX (ccx) is not available")
    return resolved


def main() -> int:
    job_path = Path(sys.argv[1])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    out = Path(job["out_dir"]) / "fea.json"
    try:
        job["ccx"] = find_ccx_or_fail(job.get("ccx"))
        result = analyze(job)
    except Exception as error:  # report every failure as data, never crash silently
        result = {
            "ok": False,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc()[-3000:],
        }
    out.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
