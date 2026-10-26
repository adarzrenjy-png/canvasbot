"""The canonical Jig part program, and the two-way map between it and the UI.

A part is plain build123d Python, and that source is the single source of truth:

    PLATE_WIDTH = 40.0  # mm | Width of the bracket | min=10 max=200

    def base_flange(part):
        \"\"\"extrude | Base flange\"\"\"
        return Box(...)

    FEATURES = [base_flange, ...]

* Parameters are top-level UPPER_CASE names bound to a number. The trailing comment
  holds `unit | description | flags`, every field optional. Flags: `min=`, `max=`,
  `locked`.
* Features are the functions listed in `FEATURES`, applied in order. Each takes the
  part so far and returns the new part. The docstring's first line is `kind | label`.

Editing a parameter in the UI rewrites only that literal, so comments and layout
survive; editing the code re-parses it into the tree. Both directions go through
this module.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field

PARAM_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
FEATURE_KINDS = (
    "sketch",
    "extrude",
    "revolve",
    "loft",
    "sweep",
    "fillet",
    "chamfer",
    "hole",
    "shell",
    "pattern",
    "mirror",
    "boolean",
    "rib",
    "other",
)


class ProgramError(ValueError):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


@dataclass
class Param:
    name: str
    value: float
    unit: str = ""
    description: str = ""
    min: float | None = None
    max: float | None = None
    locked: bool = False
    is_int: bool = False
    line: int = 0
    used_by: list[str] = field(default_factory=list)


@dataclass
class Feature:
    id: str
    kind: str
    label: str
    line_start: int
    line_end: int
    params: list[str] = field(default_factory=list)


@dataclass
class Program:
    params: list[Param]
    features: list[Feature]

    def param(self, name: str) -> Param:
        for param in self.params:
            if param.name == name:
                return param
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "params": [asdict(p) for p in self.params],
            "features": [asdict(f) for f in self.features],
        }


def _number(node: ast.expr) -> float | int | None:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in (int, float)
    ):
        return -node.operand.value
    return None


def _parse_comment(comment: str) -> dict[str, object]:
    parts = [part.strip() for part in comment.split("|")]
    info: dict[str, object] = {"unit": parts[0] if parts else ""}
    if len(parts) > 1:
        info["description"] = parts[1]
    if len(parts) > 2:
        for token in parts[2].split():
            if token == "locked":
                info["locked"] = True
            elif "=" in token:
                key, _, raw = token.partition("=")
                if key in ("min", "max"):
                    try:
                        info[key] = float(raw)
                    except ValueError:
                        pass
    return info


def _trailing_comment(line: str, end_col: int) -> str:
    rest = line[end_col:]
    hash_at = rest.find("#")
    return rest[hash_at + 1 :].strip() if hash_at >= 0 else ""


def parse_program(code: str) -> Program:
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ProgramError(f"Syntax error: {error.msg}", error.lineno) from error
    lines = code.splitlines()

    params: list[Param] = []
    functions: dict[str, ast.FunctionDef] = {}
    feature_names: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == "FEATURES":
                if not isinstance(node.value, ast.List | ast.Tuple):
                    raise ProgramError("FEATURES must be a list of feature functions", node.lineno)
                feature_names = []
                for element in node.value.elts:
                    if not isinstance(element, ast.Name):
                        raise ProgramError("FEATURES may only list function names", node.lineno)
                    feature_names.append(element.id)
                continue
            value = _number(node.value)
            if value is None or not PARAM_NAME.match(target.id):
                continue
            info = _parse_comment(_trailing_comment(lines[node.lineno - 1], node.end_col_offset))
            params.append(
                Param(
                    name=target.id,
                    value=float(value),
                    is_int=isinstance(value, int),
                    line=node.lineno,
                    **info,  # type: ignore[arg-type]
                )
            )
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node

    if feature_names is None:
        raise ProgramError("The program must define FEATURES = [feature, ...]")

    param_names = {p.name for p in params}
    features: list[Feature] = []
    for name in feature_names:
        func = functions.get(name)
        if func is None:
            raise ProgramError(f"FEATURES lists {name!r} but no function by that name exists")
        kind, label = "other", name.replace("_", " ").capitalize()
        doc = ast.get_docstring(func)
        if doc:
            head = doc.strip().splitlines()[0]
            if "|" in head:
                raw_kind, _, raw_label = head.partition("|")
                kind = raw_kind.strip().lower() or kind
                label = raw_label.strip() or label
            else:
                label = head.strip() or label
        if kind not in FEATURE_KINDS:
            kind = "other"
        used = sorted(
            {n.id for n in ast.walk(func) if isinstance(n, ast.Name) and n.id in param_names},
            key=[p.name for p in params].index,
        )
        start = func.decorator_list[0].lineno if func.decorator_list else func.lineno
        features.append(
            Feature(
                id=name,
                kind=kind,
                label=label,
                line_start=start,
                line_end=func.end_lineno or func.lineno,
                params=used,
            )
        )
        for param in params:
            if param.name in used:
                param.used_by.append(name)

    return Program(params=params, features=features)


def format_number(value: float, is_int: bool) -> str:
    if is_int:
        return str(int(round(value)))
    text = repr(round(float(value), 6))
    return text


def set_params(code: str, updates: dict[str, float]) -> str:
    """Rewrite parameter literals in place, keeping every comment and blank line."""
    if not updates:
        return code
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    program = parse_program(code)
    known = {p.name: p for p in program.params}
    unknown = sorted(set(updates) - set(known))
    if unknown:
        raise ProgramError(f"Unknown parameter(s): {', '.join(unknown)}")

    edits: list[tuple[int, int, int, str]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in updates
        ):
            param = known[node.targets[0].id]
            value = float(updates[param.name])
            if param.min is not None and value < param.min:
                raise ProgramError(f"{param.name} must be at least {param.min:g}")
            if param.max is not None and value > param.max:
                raise ProgramError(f"{param.name} must be at most {param.max:g}")
            if node.value.lineno != node.value.end_lineno:
                raise ProgramError(f"{param.name} must be written on one line", node.lineno)
            edits.append(
                (
                    node.value.lineno - 1,
                    node.value.col_offset,
                    node.value.end_col_offset or node.value.col_offset,
                    format_number(value, param.is_int),
                )
            )
    # Apply right-to-left so earlier offsets stay valid. ast offsets are UTF-8 byte
    # offsets, so edit each line as bytes.
    for line_index, start, end, text in sorted(edits, reverse=True):
        raw = lines[line_index].encode("utf-8")
        lines[line_index] = (raw[:start] + text.encode("utf-8") + raw[end:]).decode("utf-8")
    return "".join(lines)


def set_param_flags(code: str, name: str, *, locked: bool) -> str:
    """Add or remove the `locked` flag in a parameter's trailing comment."""
    program = parse_program(code)
    param = program.param(name)
    lines = code.splitlines(keepends=True)
    line = lines[param.line - 1]
    newline = "\n" if line.endswith("\n") else ""
    body = line.rstrip("\r\n")
    hash_at = body.find("#", body.find("=") + 1)
    head = body[:hash_at].rstrip() if hash_at >= 0 else body.rstrip()
    flags = []
    if param.min is not None:
        flags.append(f"min={param.min:g}")
    if param.max is not None:
        flags.append(f"max={param.max:g}")
    if locked:
        flags.append("locked")
    fields = [param.unit, param.description, " ".join(flags)]
    while fields and not fields[-1]:
        fields.pop()
    comment = " | ".join(fields)
    lines[param.line - 1] = f"{head}  # {comment}{newline}" if comment else f"{head}{newline}"
    return "".join(lines)
