"""FEA: load-case parsing, mesh ordering, result reading, and solver accuracy.

The accuracy tests compare CalculiX through Jig's whole pipeline with textbook
beam theory, the same way a fast model is checked against a trusted one before
anyone believes it. They need gmsh and ccx, and skip without them.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from jig.cad.builder import Builder
from jig.cad.program import parse_program, set_params
from jig.cad.samples import L_BRACKET
from jig.fea.frd import read_blocks, von_mises
from jig.fea.materials import MATERIALS, get_material
from jig.fea.spec import FaceSelector, SpecError, parse_analysis, select_faces

try:
    import gmsh  # noqa: F401

    HAVE_GMSH = True
except (ImportError, OSError):
    HAVE_GMSH = False

CCX = shutil.which("ccx")
needs_solver = pytest.mark.skipif(not (HAVE_GMSH and CCX), reason="needs gmsh and CalculiX")

CANTILEVER = '''from build123d import *
LENGTH = 100.0  # mm
WIDTH = 10.0  # mm
HEIGHT = 10.0  # mm
LOAD_N = 100.0  # N

def beam(part):
    """extrude | Beam"""
    return Box(LENGTH, WIDTH, HEIGHT, align=(Align.MIN, Align.CENTER, Align.CENTER))

FEATURES = [beam]
ANALYSIS = {
    "material": "al6061_t6",
    "fixtures": [{"name": "Wall", "faces": {"extreme": "-x"}}],
    "loads": [{"name": "Tip", "faces": {"extreme": "+x"}, "force": [0, 0, "-LOAD_N"]}],
}
'''


# ---------- load case parsing ----------


def test_every_material_has_a_sourced_allowable() -> None:
    for material in MATERIALS.values():
        assert material.allowable_mpa > 0 and material.allowable_basis and material.source
    assert get_material("petg").process == "printed"


def test_analysis_resolves_parameter_names_in_forces() -> None:
    program = parse_program(L_BRACKET)
    spec = parse_analysis(program.analysis, program.values())
    assert spec.material.id == "petg"
    assert spec.loads[0].force == (0.0, 0.0, -60.0)
    assert [f.type for f in spec.fixtures] == ["fixed", "support"]
    assert spec.min_safety_factor == 2.0


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"material": "unobtainium"}, "Unknown material"),
        (
            {"material": "petg", "loads": [{"faces": {"extreme": "+x"}, "force": [0, 0, 1]}]},
            "fixture",
        ),
        (
            {
                "material": "petg",
                "fixtures": [{"faces": {"extreme": "-x"}}],
                "loads": [{"faces": {"extreme": "+x"}, "force": [0, 0, "NOPE"]}],
            },
            "not a number or a parameter",
        ),
        (
            {
                "material": "petg",
                "fixtures": [{"faces": {"extreme": "sideways"}}],
                "loads": [{"faces": {"extreme": "+x"}, "force": [0, 0, 1]}],
            },
            "extreme",
        ),
    ],
)
def test_bad_load_cases_explain_themselves(raw: dict, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        parse_analysis(raw, {})


def test_selectors_match_on_feature_type_and_extremes() -> None:
    faces = [
        {
            "index": 0,
            "type": "plane",
            "feature": "base",
            "center": [0, 0, 0],
            "normal": [0, 0, -1],
            "bbox": [[-5, -5, 0], [5, 5, 0]],
        },
        {
            "index": 1,
            "type": "plane",
            "feature": "base",
            "center": [0, 0, 5],
            "normal": [0, 0, 1],
            "bbox": [[-5, -5, 5], [5, 5, 5]],
        },
        {
            "index": 2,
            "type": "cylinder",
            "feature": "holes",
            "center": [1, 1, 2.5],
            "normal": None,
            "bbox": [[0, 0, 0], [2, 2, 5]],
        },
    ]
    assert select_faces(faces, FaceSelector(extreme="-z")) == [0]
    assert select_faces(faces, FaceSelector(extreme="+z")) == [1]
    assert select_faces(faces, FaceSelector(feature="holes", type="cylinder")) == [2]
    assert select_faces(faces, FaceSelector(feature="base", type="cylinder")) == []
    assert select_faces(faces, FaceSelector(box=((0.5, 0.5, 1), (2, 2, 3)))) == [2]


# ---------- result reading ----------


def test_frd_reader_handles_fields_that_run_together(tmp_path: Path) -> None:
    frd = tmp_path / "job.frd"
    frd.write_text(
        "    1C\n"
        " -4  DISP        4    1\n"
        " -5  D1          1    2    1    0\n"
        " -1         1 1.00000E+00-2.00000E+00 3.00000E-01\n"
        " -3\n"
        " -4  STRESS      6    1\n"
        " -1         1 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00\n"
        " -3\n",
        encoding="ascii",
    )
    blocks = read_blocks(frd)
    assert blocks["DISP"][1] == [1.0, -2.0, 0.3]
    assert von_mises(np.array([blocks["STRESS"][1]]))[0] == pytest.approx(100.0)


def test_von_mises_of_pure_shear_is_root3_tau() -> None:
    assert von_mises(np.array([[0, 0, 0, 10.0, 0, 0]]))[0] == pytest.approx(10 * math.sqrt(3))


# ---------- meshing ----------


@pytest.mark.skipif(not HAVE_GMSH, reason="needs gmsh")
def test_tet10_nodes_are_in_calculix_order(builder: Builder) -> None:
    from jig.fea.mesh import mesh_step

    result = builder.build(CANTILEVER)
    mesh = mesh_step(result.out_dir / "part.step", size=5.0)
    xyz = mesh.coord_lookup()
    # C3D10: nodes 5-10 sit on edges 1-2, 2-3, 3-1, 1-4, 2-4, 3-4 (1-based).
    edges = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
    for tet in mesh.tets[:50]:
        p = [xyz[int(n)] for n in tet]
        for k, (a, b) in enumerate(edges, start=4):
            assert np.allclose(p[k], (p[a] + p[b]) / 2, atol=1e-6)


# ---------- accuracy against theory ----------


@needs_solver
def test_cantilever_matches_beam_theory(builder: Builder, tmp_path: Path) -> None:
    from jig.fea.solve import analyze

    result = builder.build(CANTILEVER)
    program = parse_program(CANTILEVER)
    job = {
        "step": str(result.out_dir / "part.step"),
        "out_dir": str(tmp_path),
        "face_info": result.data["face_info"],
        "diagonal": math.dist((0, 0, 0), result.data["stats"]["bbox"]["size"]),
        "analysis": program.analysis,
        "params": program.values(),
        "ccx": CCX,
    }
    out = analyze(job)

    E, nu, P, L, b, h = 68900.0, 0.33, 100.0, 100.0, 10.0, 10.0
    inertia = b * h**3 / 12
    G = E / (2 * (1 + nu))
    theory = P * L**3 / (3 * E * inertia) + P * L / (5 / 6 * G * b * h)  # bending + shear
    assert out["result"]["max_displacement_mm"] == pytest.approx(theory, rel=0.02)

    # Bending stress next to the clamp, where the peak (outside the clamp zone) sits.
    x = out["result"]["peak_at"][0]
    sigma = P * (L - x) * (h / 2) / inertia
    assert out["result"]["peak_von_mises_mpa"] == pytest.approx(sigma, rel=0.03)

    assert out["equilibrium"]["ok"] and out["equilibrium"]["error"] < 1e-4
    assert out["convergence"]["converged"]
    assert out["status"] == "pass"


@needs_solver
def test_bracket_fails_then_a_thicker_one_passes(builder: Builder, tmp_path: Path) -> None:
    """The starter bracket is deliberately under-designed for its load."""
    from jig.fea.solve import analyze

    def run(code: str, sub: str) -> dict:
        result = builder.build(code)
        program = parse_program(code)
        return analyze(
            {
                "step": str(result.out_dir / "part.step"),
                "out_dir": str(tmp_path / sub),
                "face_info": result.data["face_info"],
                "diagonal": math.dist((0, 0, 0), result.data["stats"]["bbox"]["size"]),
                "analysis": program.analysis,
                "params": program.values(),
                "ccx": CCX,
                "mesh_size_mm": 3.0,
            }
        )

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    weak = run(L_BRACKET, "a")
    assert weak["status"] == "fail"
    assert 1.4 < weak["safety_factor"] < 2.0
    strong = run(set_params(L_BRACKET, {"THICKNESS": 7.0}), "b")
    assert strong["safety_factor"] > weak["safety_factor"] * 1.5
    assert strong["status"] == "pass"
