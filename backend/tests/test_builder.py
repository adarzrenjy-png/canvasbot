"""End-to-end builds through the sandboxed runner process."""

from __future__ import annotations

import base64
import math
from array import array

from jig.cad.builder import Builder
from jig.cad.program import set_params
from jig.cad.samples import L_BRACKET


def expected_bracket_volume(length=60.0, width=40.0, t=5.0, height=45.0, d=5.5, r=4.0) -> float:
    plates = length * width * t + t * width * (height - t)
    fillet = (r * r - math.pi * r * r / 4) * width
    holes = 4 * math.pi * (d / 2) ** 2 * t
    return plates + fillet - holes


def test_sample_builds_a_valid_solid_with_exports(builder: Builder) -> None:
    result = builder.build(L_BRACKET)
    assert result.ok, result.data.get("error")
    stats = result.data["stats"]
    assert stats["valid"] and stats["solids"] == 1
    assert math.isclose(stats["volume_mm3"], expected_bracket_volume(), rel_tol=1e-3)
    assert [round(v, 3) for v in stats["bbox"]["size"]] == [60.0, 40.0, 45.0]
    assert (result.out_dir / "part.step").stat().st_size > 1000
    assert (result.out_dir / "part.stl").stat().st_size > 1000
    assert [f["ok"] for f in result.data["features"]] == [True] * 5


def test_mesh_payload_decodes_and_credits_faces_to_features(builder: Builder) -> None:
    mesh = builder.build(L_BRACKET).data["mesh"]
    positions = array("f", base64.b64decode(mesh["positions"]))
    indices = array("I", base64.b64decode(mesh["indices"]))
    assert len(indices) == mesh["triangles"] * 3
    assert max(indices) < len(positions) // 3
    owners = {face["feature"] for face in mesh["faces"]}
    assert {"base_flange", "inside_fillet", "base_holes", "upright_holes"} <= owners
    assert sum(face["count"] for face in mesh["faces"]) == len(indices)


def test_parameter_edit_changes_the_geometry(builder: Builder) -> None:
    thicker = set_params(L_BRACKET, {"THICKNESS": 6.0})
    stats = builder.build(thicker).data["stats"]
    assert math.isclose(stats["volume_mm3"], expected_bracket_volume(t=6.0), rel_tol=1e-3)


def test_failing_feature_is_named_with_its_line(builder: Builder) -> None:
    broken = L_BRACKET.replace("radius=FILLET_RADIUS", "radius=FILLET_RADIUS * 100")
    result = builder.build(broken)
    assert not result.ok
    error = result.data["error"]
    assert error["feature"] == "inside_fillet"
    assert error["line"] is not None
    assert [f["ok"] for f in result.data["features"]] == [True, True, False]


def test_validation_failure_never_runs_the_code(builder: Builder) -> None:
    result = builder.build("import os\nos.remove('x')\nFEATURES = []\n")
    assert not result.ok
    assert result.data["error"]["stage"] == "validate"


def test_runtime_import_guard_blocks_private_submodules(builder: Builder) -> None:
    code = "from build123d import topology\nFEATURES = []\n"
    result = builder.build(code)
    assert not result.ok
    assert "not a public name" in result.data["error"]["message"]


def test_runaway_code_is_stopped_by_the_timeout(tmp_path) -> None:
    quick = Builder(tmp_path, timeout_s=3)
    try:
        result = quick.build("while True:\n    pass\nFEATURES = []\n")
    finally:
        quick.close()
    assert not result.ok
    assert result.data["error"]["stage"] in {"timeout", "crash"}


def test_print_output_is_captured(builder: Builder) -> None:
    code = set_params(L_BRACKET, {}).replace(
        "def build():", 'print("hello from the part")\n\n\ndef build():'
    )
    result = builder.build(code)
    assert result.ok
    assert "hello from the part" in result.data["log"]


def test_suppressed_features_are_skipped_but_listed(builder: Builder) -> None:
    from jig.cad.program import set_feature_enabled

    result = builder.build(set_feature_enabled(L_BRACKET, "base_holes", False))
    assert result.ok
    skipped = [f["id"] for f in result.data["features"] if f.get("skipped")]
    assert skipped == ["base_holes"]
    assert result.data["stats"]["faces"] == 11  # two hole bores fewer


def test_each_step_has_a_light_mesh_marking_its_new_faces(builder: Builder) -> None:
    steps = builder.build(L_BRACKET).data["steps"]
    assert [s["id"] for s in steps] == [
        "base_flange",
        "upright_flange",
        "inside_fillet",
        "base_holes",
        "upright_holes",
    ]
    holes = steps[3]["mesh"]
    new = [f for f in holes["faces"] if f["feature"] == "base_holes"]
    assert 2 <= len(new) < len(holes["faces"])


def test_face_info_describes_every_final_face(builder: Builder) -> None:
    data = builder.build(L_BRACKET).data
    info = data["face_info"]
    assert len(info) == data["stats"]["faces"]
    bores = [f for f in info if f["feature"] == "base_holes" and f["type"] == "cylinder"]
    assert len(bores) == 2
    assert all(f["normal"] is not None for f in info if f["type"] == "plane")
