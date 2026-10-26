"""The parameter <-> code round trip."""

from __future__ import annotations

import pytest

from jig.cad.program import ProgramError, parse_program, set_param_flags, set_params
from jig.cad.samples import L_BRACKET


def test_parses_parameters_with_units_descriptions_and_bounds() -> None:
    program = parse_program(L_BRACKET)
    names = [p.name for p in program.params]
    assert names[:3] == ["BASE_LENGTH", "WIDTH", "THICKNESS"]
    thickness = program.param("THICKNESS")
    assert thickness.value == 5.0
    assert thickness.unit == "mm"
    assert thickness.description == "Plate thickness"
    assert (thickness.min, thickness.max) == (1.0, 30.0)
    assert thickness.locked is False


def test_parses_features_in_order_with_kinds_and_param_usage() -> None:
    program = parse_program(L_BRACKET)
    assert [f.id for f in program.features] == [
        "base_flange",
        "upright_flange",
        "inside_fillet",
        "base_holes",
        "upright_holes",
    ]
    fillet = program.features[2]
    assert fillet.kind == "fillet"
    assert fillet.label == "Inside corner fillet"
    assert fillet.params == ["THICKNESS", "FILLET_RADIUS"]
    assert fillet.line_start < fillet.line_end
    assert "inside_fillet" in program.param("FILLET_RADIUS").used_by


def test_set_params_changes_only_the_literal() -> None:
    updated = set_params(L_BRACKET, {"THICKNESS": 6.5, "WIDTH": 42})
    assert "THICKNESS = 6.5  # mm | Plate thickness | min=1 max=30" in updated
    assert "WIDTH = 42.0  # mm | Width of the bracket" in updated
    before = L_BRACKET.splitlines()
    after = updated.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert len(changed) == 2


def test_round_trip_code_to_params_to_code() -> None:
    program = parse_program(L_BRACKET)
    values = {p.name: p.value for p in program.params}
    assert set_params(L_BRACKET, values) == L_BRACKET
    bumped = set_params(L_BRACKET, {"HOLE_DIAMETER": 6.6})
    assert parse_program(bumped).param("HOLE_DIAMETER").value == 6.6
    assert set_params(bumped, {"HOLE_DIAMETER": 5.5}) == L_BRACKET


def test_integer_parameters_stay_integers() -> None:
    code = "N = 4  # count | Number of holes\nFEATURES = []\n"
    assert set_params(code, {"N": 6}).startswith("N = 6  #")
    assert parse_program(code).param("N").is_int


def test_bounds_are_enforced() -> None:
    with pytest.raises(ProgramError, match="at least 1"):
        set_params(L_BRACKET, {"THICKNESS": 0.2})


def test_unknown_parameter_is_an_error() -> None:
    with pytest.raises(ProgramError, match="Unknown"):
        set_params(L_BRACKET, {"NOPE": 1})


def test_lock_flag_round_trips_through_the_comment() -> None:
    locked = set_param_flags(L_BRACKET, "WIDTH", locked=True)
    assert "WIDTH = 40.0  # mm | Width of the bracket | min=10 max=200 locked" in locked
    assert parse_program(locked).param("WIDTH").locked
    assert set_param_flags(locked, "WIDTH", locked=False) == L_BRACKET


def test_missing_features_list_is_reported() -> None:
    with pytest.raises(ProgramError, match="FEATURES"):
        parse_program("X = 1.0\n")


def test_feature_without_function_is_reported() -> None:
    with pytest.raises(ProgramError, match="ghost"):
        parse_program("FEATURES = [ghost]\n")
