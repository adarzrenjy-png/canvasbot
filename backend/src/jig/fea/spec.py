"""The load case of a part: material, fixtures, loads, and pass criteria.

It lives in the part program as a plain dict, so an exported .py carries its own
test definition:

    ANALYSIS = {
        "material": "petg",
        "fixtures": [{"name": "Wall bolts",
                      "faces": {"feature": "upright_holes", "type": "cylinder"}}],
        "loads": [{"name": "Camera", "faces": {"feature": "base_holes", "type": "cylinder"},
                   "force": [0, 0, "-LOAD_N"]}],
        "min_safety_factor": 2.0,
    }

Numbers may be written as a parameter name ("LOAD_N", or "-LOAD_N"), so a load
can be a parameter like any dimension. Forces are totals in newtons, spread over
the selected faces by area. Units are mm, N, MPa.

Fixtures are "fixed" (the faces cannot move at all, e.g. bolted bores) or
"support" (the faces cannot move along their normal but may slide, e.g. a flange
resting on a wall). A support face must be flat and face along X, Y or Z. Contact
that can separate is not modelled: a support also stops the face lifting off.

Face selectors match on what the build reports for every final face (see
runner.face_info), never on face numbers, so they survive parameter changes:

    {"feature": "base_holes"}                   faces that feature created
    {"feature": "base_holes", "type": "cylinder"}   ...that are cylinders
    {"extreme": "-z"}                           flat faces on the part's lowest Z plane
    {"box": [[x0, y0, z0], [x1, y1, z1]]}        faces whose centre is inside the box
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jig.fea.materials import Material, get_material

FACE_TYPES = ("plane", "cylinder", "cone", "sphere", "torus", "bspline", "bezier", "other")
AXES = {"x": 0, "y": 1, "z": 2}


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class FaceSelector:
    feature: str | None = None
    type: str | None = None
    extreme: str | None = None
    box: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None

    def describe(self) -> str:
        parts = []
        if self.type:
            parts.append(f"{self.type} faces")
        else:
            parts.append("faces")
        if self.feature:
            parts.append(f"made by '{self.feature}'")
        if self.extreme:
            parts.append(f"on the {self.extreme} side of the part")
        if self.box:
            parts.append("inside the given box")
        return " ".join(parts)


FIXTURE_TYPES = ("fixed", "support")


@dataclass(frozen=True)
class Fixture:
    name: str
    faces: FaceSelector
    type: str = "fixed"


@dataclass(frozen=True)
class Load:
    name: str
    faces: FaceSelector
    force: tuple[float, float, float]

    @property
    def magnitude(self) -> float:
        return math.sqrt(sum(f * f for f in self.force))


@dataclass(frozen=True)
class AnalysisSpec:
    material: Material
    fixtures: list[Fixture]
    loads: list[Load]
    min_safety_factor: float = 2.0
    max_displacement_mm: float | None = None
    notes: list[str] = field(default_factory=list)


def _number(value: Any, params: dict[str, float], where: str) -> float:
    if isinstance(value, bool):
        raise SpecError(f"{where}: expected a number")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        sign = -1.0 if value.strip().startswith("-") else 1.0
        name = value.strip().lstrip("+-").strip()
        if name in params:
            return sign * params[name]
        raise SpecError(f"{where}: '{value}' is not a number or a parameter name")
    raise SpecError(f"{where}: expected a number")


def _selector(raw: Any, where: str) -> FaceSelector:
    if not isinstance(raw, dict) or not raw:
        raise SpecError(f"{where}: 'faces' must be a selector like {{'feature': 'base_holes'}}")
    unknown = set(raw) - {"feature", "type", "extreme", "box"}
    if unknown:
        raise SpecError(f"{where}: unknown selector keys {sorted(unknown)}")
    face_type = raw.get("type")
    if face_type is not None and face_type not in FACE_TYPES:
        raise SpecError(f"{where}: face type must be one of {', '.join(FACE_TYPES)}")
    extreme = raw.get("extreme")
    if extreme is not None and (
        len(extreme) != 2 or extreme[0] not in "+-" or extreme[1] not in AXES
    ):
        raise SpecError(f"{where}: 'extreme' must be like '+z' or '-x'")
    box = raw.get("box")
    if box is not None:
        try:
            lo, hi = (tuple(float(v) for v in corner) for corner in box)
            assert len(lo) == 3 and len(hi) == 3
        except (TypeError, ValueError, AssertionError) as error:
            raise SpecError(f"{where}: 'box' must be [[x0, y0, z0], [x1, y1, z1]]") from error
        box = (lo, hi)
    return FaceSelector(feature=raw.get("feature"), type=face_type, extreme=extreme, box=box)


def parse_analysis(raw: Any, params: dict[str, float]) -> AnalysisSpec:
    if not isinstance(raw, dict):
        raise SpecError("ANALYSIS must be a dict")
    try:
        material = get_material(str(raw.get("material", "")))
    except KeyError as error:
        raise SpecError(str(error.args[0])) from error
    fixtures = []
    for i, item in enumerate(raw.get("fixtures") or []):
        where = f"fixture {i + 1}"
        kind = item.get("type", "fixed")
        if kind not in FIXTURE_TYPES:
            raise SpecError(f"{where}: type must be one of {', '.join(FIXTURE_TYPES)}")
        fixtures.append(
            Fixture(str(item.get("name", where)), _selector(item.get("faces"), where), kind)
        )
    loads = []
    for i, item in enumerate(raw.get("loads") or []):
        where = f"load {i + 1}"
        force = item.get("force")
        if not isinstance(force, list | tuple) or len(force) != 3:
            raise SpecError(f"{where}: 'force' must be [Fx, Fy, Fz] in newtons")
        vector = tuple(_number(v, params, where) for v in force)
        loads.append(
            Load(str(item.get("name", where)), _selector(item.get("faces"), where), vector)
        )
    if not fixtures:
        raise SpecError("ANALYSIS needs at least one fixture (faces held still)")
    if not loads:
        raise SpecError("ANALYSIS needs at least one load")
    min_sf = _number(raw.get("min_safety_factor", 2.0), params, "min_safety_factor")
    max_disp = raw.get("max_displacement_mm")
    return AnalysisSpec(
        material=material,
        fixtures=fixtures,
        loads=loads,
        min_safety_factor=min_sf,
        max_displacement_mm=None if max_disp is None else _number(max_disp, params, "max disp"),
        notes=[str(n) for n in raw.get("notes", [])],
    )


def select_faces(face_info: list[dict], selector: FaceSelector, tol: float = 1e-3) -> list[int]:
    """Indices of the final faces a selector picks."""
    chosen = []
    extreme_value = None
    if selector.extreme:
        axis = AXES[selector.extreme[1]]
        values = [f["bbox"][0][axis] for f in face_info] + [f["bbox"][1][axis] for f in face_info]
        extreme_value = min(values) if selector.extreme[0] == "-" else max(values)
    for face in face_info:
        if selector.feature is not None and face["feature"] != selector.feature:
            continue
        if selector.type is not None and face["type"] != selector.type:
            continue
        if selector.extreme:
            axis = AXES[selector.extreme[1]]
            sign = 1.0 if selector.extreme[0] == "+" else -1.0
            normal = face.get("normal")
            if normal is None or normal[axis] * sign < 0.99:
                continue
            if abs(face["center"][axis] - extreme_value) > tol * 10:
                continue
        if selector.box:
            lo, hi = selector.box
            if not all(lo[i] - tol <= face["center"][i] <= hi[i] + tol for i in range(3)):
                continue
        chosen.append(face["index"])
    return chosen
