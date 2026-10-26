"""JSON schemas the agents answer in. Every field is required so outputs are complete."""

from __future__ import annotations

from typing import Any

from jig.cad.program import FEATURE_KINDS
from jig.fea.materials import MATERIALS


def _obj(**props: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


STR = {"type": "string"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}


def _list(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


PART_PLAN = _obj(
    name=STR,
    summary=STR,
    approach=STR,
    material={"type": "string", "enum": sorted(MATERIALS)},
    envelope_mm=_list(NUM),
    features=_list(
        _obj(kind={"type": "string", "enum": list(FEATURE_KINDS)}, label=STR, description=STR)
    ),
    parameters=_list(_obj(name=STR, value=NUM, unit=STR, description=STR, min=NUM, max=NUM)),
    load_case=_obj(applies=BOOL, description=STR, fixtures=STR, loads=STR, force_n=NUM),
    assumptions=_list(STR),
)

BOARD_PLAN = _obj(
    name=STR,
    summary=STR,
    width_mm=NUM,
    height_mm=NUM,
    parts=_list(_obj(ref=STR, part=STR, value=STR, why=STR)),
    nets=_list(
        _obj(
            name=STR,
            kind={"type": "string", "enum": ["power", "ground", "signal"]},
            voltage_v=NUM,
            current_a=NUM,
            connects=_list(STR),
        )
    ),
    placement=STR,
    assumptions=_list(STR),
)

PROGRAM = _obj(code=STR, notes=STR)

FIX = _obj(diagnosis=STR, changes=_list(STR), code=STR)

REVIEW = _obj(
    matches_request=BOOL,
    summary=STR,
    issues=_list(
        _obj(
            severity={"type": "string", "enum": ["blocking", "minor"]},
            where=STR,
            message=STR,
        )
    ),
)
