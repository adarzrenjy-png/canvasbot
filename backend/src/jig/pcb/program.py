"""The board program: a PCB written as data, the same way a part is written as code.

    \"\"\"Pico servo board

    What the board is for, in a sentence or two.
    \"\"\"

    BOARD_W = 60.0  # mm | Board width | min=30 max=200
    SERVO_A = 1.5  # A | Peak current per servo

    BOARD = {"width": BOARD_W, "height": 45, "thickness": 1.6, "corner_radius": 2}
    PARTS = {
        "U1": {"part": "raspberry_pi_pico", "at": (16, 22.5), "rotate": 0},
        "R1": {"part": "resistor_0603", "value": "330", "at": (36, 30), "rotate": 90},
    }
    NETS = {
        "VIN": {"pins": ["J1.1", "D1.2"], "kind": "power", "voltage": 5.0, "current": 2 * SERVO_A},
        "GND": {"pins": ["J1.2", "U1.3"], "kind": "ground", "pour": "bottom"},
    }
    RULES = {"clearance": 0.2, "track": 0.25}

Values may be arithmetic on parameters (`BOARD_W / 2`), nothing more: the program is
evaluated as data, never executed, so it needs no sandbox. Parameters use the same
`unit | description | flags` comments as parts, so the parameter panel, locks and
two-way editing work unchanged.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import fields
from typing import Any

from jig.cad.program import ProgramError, parse_params
from jig.pcb.library import get_part
from jig.pcb.model import NET_KINDS, Board, Net, PlacedPart, Rules

SECTIONS = ("BOARD", "PARTS", "NETS", "RULES", "HOLES")
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def safe_eval(node: ast.AST, names: dict[str, float]) -> Any:
    """Evaluate literals and arithmetic over parameter names. Anything else is an error."""
    if isinstance(node, ast.Constant) and isinstance(
        node.value, int | float | str | bool | type(None)
    ):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise ProgramError(f"Unknown name {node.id!r} (only parameters can be used)", node.lineno)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = safe_eval(node.operand, names)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        try:
            return _OPS[type(node.op)](safe_eval(node.left, names), safe_eval(node.right, names))
        except (TypeError, ZeroDivisionError) as error:
            raise ProgramError(f"Cannot compute this value: {error}", node.lineno) from error
    if isinstance(node, ast.Tuple | ast.List):
        return [safe_eval(e, names) for e in node.elts]
    if isinstance(node, ast.Dict):
        out = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise ProgramError("'**' is not allowed here", node.lineno)
            out[safe_eval(key, names)] = safe_eval(value, names)
        return out
    raise ProgramError(
        f"Only numbers, text, lists, dicts and arithmetic on parameters are allowed here "
        f"(found {type(node).__name__})",
        getattr(node, "lineno", None),
    )


def _sections(code: str) -> tuple[dict[str, Any], dict[str, int], str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ProgramError(f"Syntax error: {error.msg}", error.lineno) from error
    names = {p.name: p.value for p in parse_params(code)}
    found: dict[str, Any] = {}
    lines: dict[str, int] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in SECTIONS
        ):
            name = node.targets[0].id
            found[name] = safe_eval(node.value, names)
            lines[name] = node.lineno
        elif isinstance(node, ast.Import | ast.ImportFrom | ast.FunctionDef | ast.ClassDef):
            raise ProgramError("A board program is data only: no imports or functions", node.lineno)
    return found, lines, ast.get_docstring(tree) or ""


def _number(value: Any, where: str, line: int | None, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ProgramError(f"{where} must be a number", line)
    if positive and value <= 0:
        raise ProgramError(f"{where} must be greater than zero", line)
    return float(value)


def parse_board(code: str) -> Board:
    data, lines, doc = _sections(code)
    for required in ("BOARD", "PARTS", "NETS"):
        if required not in data:
            raise ProgramError(f"The board program must define {required} = {{...}}")
    head, *rest = (doc.strip() or "Untitled board").splitlines()
    description = " ".join(line.strip() for line in rest if line.strip())

    raw_board = data["BOARD"]
    bl = lines["BOARD"]
    if not isinstance(raw_board, dict):
        raise ProgramError("BOARD must be a dict", bl)

    rules_raw = data.get("RULES", {})
    known_rules = {f.name for f in fields(Rules)}
    unknown = set(rules_raw) - known_rules
    if unknown:
        raise ProgramError(f"Unknown rule(s): {', '.join(sorted(unknown))}", lines.get("RULES"))
    rules = Rules(
        **{k: _number(v, f"RULES[{k!r}]", lines.get("RULES"), True) for k, v in rules_raw.items()}
    )

    parts: dict[str, PlacedPart] = {}
    pl = lines["PARTS"]
    if not isinstance(data["PARTS"], dict):
        raise ProgramError("PARTS must be a dict of reference -> part", pl)
    for ref, spec in data["PARTS"].items():
        if not isinstance(ref, str) or not ref or not ref[0].isalpha():
            raise ProgramError(f"Part reference {ref!r} must start with a letter, like R1", pl)
        if not isinstance(spec, dict) or "part" not in spec:
            raise ProgramError(f"{ref}: needs at least {{'part': ..., 'at': (x, y)}}", pl)
        try:
            part = get_part(spec["part"])
        except KeyError as error:
            raise ProgramError(f"{ref}: {error.args[0]}", pl) from error
        at = spec.get("at")
        if not isinstance(at, list) or len(at) != 2:
            raise ProgramError(f"{ref}: 'at' must be (x, y) in mm", pl)
        rotation = int(_number(spec.get("rotate", 0), f"{ref} rotate", pl))
        if rotation % 90:
            raise ProgramError(f"{ref}: rotate must be a multiple of 90 degrees", pl)
        if spec.get("side", "top") != "top":
            raise ProgramError(f"{ref}: only top-side parts are supported for now", pl)
        ratings = {k: _number(v, f"{ref} {k}", pl) for k, v in spec.get("ratings", {}).items()}
        parts[ref] = PlacedPart(
            ref=ref,
            part=part,
            x=_number(at[0], f"{ref} x", pl),
            y=_number(at[1], f"{ref} y", pl),
            rotation=rotation,
            value=str(spec.get("value", part.value)),
            label=str(spec.get("label", "")),
            ratings=ratings,
            current=None
            if spec.get("current") is None
            else _number(spec["current"], f"{ref} current", pl, True),
        )

    nets: dict[str, Net] = {}
    nl = lines["NETS"]
    used: dict[tuple[str, str], str] = {}
    if not isinstance(data["NETS"], dict):
        raise ProgramError("NETS must be a dict of net name -> {'pins': [...]}", nl)
    for name, spec in data["NETS"].items():
        if isinstance(spec, list):
            spec = {"pins": spec}
        if not isinstance(spec, dict) or not isinstance(spec.get("pins"), list):
            raise ProgramError(f"Net {name}: needs 'pins': ['R1.1', 'U1.VSYS', ...]", nl)
        kind = spec.get("kind", "ground" if name.upper() in ("GND", "GROUND") else "signal")
        if kind not in NET_KINDS:
            raise ProgramError(f"Net {name}: kind must be one of {', '.join(NET_KINDS)}", nl)
        pins = []
        for ref_pin in spec["pins"]:
            if not isinstance(ref_pin, str) or "." not in ref_pin:
                raise ProgramError(f"Net {name}: pins look like 'R1.1' or 'U1.VSYS'", nl)
            ref, pin_name = ref_pin.split(".", 1)
            if ref not in parts:
                raise ProgramError(f"Net {name}: no part {ref!r} in PARTS", nl)
            matches = [p for p in parts[ref].part.pins if p.number == pin_name]
            if not matches:
                matches = [p for p in parts[ref].part.pins if p.name == pin_name]
            if not matches:
                raise ProgramError(
                    f"Net {name}: {parts[ref].part.name} has no pin {pin_name!r}", nl
                )
            if len(matches) > 1:
                numbers = ", ".join(p.number for p in matches)
                raise ProgramError(
                    f"Net {name}: {ref}.{pin_name} is ambiguous; use a pin number ({numbers})", nl
                )
            key = (ref, matches[0].number)
            if key in used:
                raise ProgramError(f"{ref}.{pin_name} is in both {used[key]} and {name}", nl)
            used[key] = name
            pins.append(key)
        voltage = spec.get("voltage")
        pour = spec.get("pour")
        if pour not in (None, "top", "bottom"):
            raise ProgramError(f"Net {name}: pour must be 'top' or 'bottom'", nl)
        nets[name] = Net(
            name=name,
            pins=pins,
            kind=kind,
            voltage=None if voltage is None else _number(voltage, f"{name} voltage", nl),
            current=_number(spec.get("current", 0.1), f"{name} current", nl, True),
            pour=pour,
        )

    holes = []
    for hole in data.get("HOLES", []):
        if not isinstance(hole, list) or len(hole) != 3:
            raise ProgramError("HOLES entries are (x, y, drill)", lines.get("HOLES"))
        holes.append(
            tuple(_number(v, "hole", lines.get("HOLES"), i == 2) for i, v in enumerate(hole))
        )

    return Board(
        name=head.strip(),
        description=description,
        width=_number(raw_board.get("width"), "BOARD width", bl, True),
        height=_number(raw_board.get("height"), "BOARD height", bl, True),
        thickness=_number(raw_board.get("thickness", 1.6), "BOARD thickness", bl, True),
        corner_radius=_number(raw_board.get("corner_radius", 0), "BOARD corner_radius", bl),
        parts=parts,
        nets=nets,
        rules=rules,
        params=parse_params(code),
        holes=holes,
    )
