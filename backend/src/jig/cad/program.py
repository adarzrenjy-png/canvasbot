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
  part so far and returns the new part. The docstring's first line is `kind | label`;
  any further lines are a plain-English description of what the feature does.
* `SUPPRESSED = [...]` (optional) lists features that stay in the tree but are skipped
  when building, like suppressing a feature in a traditional CAD tool.

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
    description: str = ""
    enabled: bool = True


@dataclass
class Program:
    params: list[Param]
    features: list[Feature]
    analysis: dict | None = None

    def param(self, name: str) -> Param:
        for param in self.params:
            if param.name == name:
                return param
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "params": [asdict(p) for p in self.params],
            "features": [asdict(f) for f in self.features],
            "analysis": self.analysis,
        }

    def values(self) -> dict[str, float]:
        return {p.name: p.value for p in self.params}


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


def _param(node: ast.Assign, lines: list[str]) -> Param | None:
    """A top-level `UPPER_NAME = number  # unit | description | flags` line, or None."""
    target = node.targets[0]
    value = _number(node.value)
    if not isinstance(target, ast.Name) or value is None or not PARAM_NAME.match(target.id):
        return None
    info = _parse_comment(_trailing_comment(lines[node.lineno - 1], node.end_col_offset))
    return Param(
        name=target.id,
        value=float(value),
        is_int=isinstance(value, int),
        line=node.lineno,
        **info,  # type: ignore[arg-type]
    )


def parse_params(code: str) -> list[Param]:
    """Just the parameters of any Jig program (a part or a board)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ProgramError(f"Syntax error: {error.msg}", error.lineno) from error
    lines = code.splitlines()
    params = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            param = _param(node, lines)
            if param is not None:
                params.append(param)
    return params


def parse_program(code: str) -> Program:
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ProgramError(f"Syntax error: {error.msg}", error.lineno) from error
    lines = code.splitlines()

    params: list[Param] = []
    functions: dict[str, ast.FunctionDef] = {}
    feature_names: list[str] | None = None
    suppressed: list[str] = []
    analysis: dict | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == "ANALYSIS":
                try:
                    analysis = ast.literal_eval(node.value)
                except ValueError as error:
                    raise ProgramError(
                        "ANALYSIS must be plain data: numbers, strings, lists and dicts",
                        node.lineno,
                    ) from error
                if not isinstance(analysis, dict):
                    raise ProgramError("ANALYSIS must be a dict", node.lineno)
                continue
            if target.id in LIST_NAMES:
                names = _name_list(node, target.id)
                if target.id == "FEATURES":
                    feature_names = names
                else:
                    suppressed = names
                continue
            param = _param(node, lines)
            if param is not None:
                params.append(param)
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node

    if feature_names is None:
        raise ProgramError("The program must define FEATURES = [feature, ...]")
    if len(set(feature_names)) != len(feature_names):
        raise ProgramError("FEATURES lists the same feature more than once")
    stray = [name for name in suppressed if name not in feature_names]
    if stray:
        raise ProgramError(f"SUPPRESSED names features not in FEATURES: {', '.join(stray)}")

    param_names = {p.name for p in params}
    features: list[Feature] = []
    for name in feature_names:
        func = functions.get(name)
        if func is None:
            raise ProgramError(f"FEATURES lists {name!r} but no function by that name exists")
        kind, label = "other", name.replace("_", " ").capitalize()
        description = ""
        doc = ast.get_docstring(func)
        if doc:
            head, *body = doc.strip().splitlines()
            description = " ".join(line.strip() for line in body if line.strip())
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
                description=description,
                enabled=name not in suppressed,
            )
        )
        for param in params:
            if param.name in used:
                param.used_by.append(name)

    return Program(params=params, features=features, analysis=analysis)


LIST_NAMES = ("FEATURES", "SUPPRESSED")


def _name_list(node: ast.Assign, name: str) -> list[str]:
    if not isinstance(node.value, ast.List | ast.Tuple):
        raise ProgramError(f"{name} must be a list of feature functions", node.lineno)
    names = []
    for element in node.value.elts:
        if not isinstance(element, ast.Name):
            raise ProgramError(f"{name} may only list function names", node.lineno)
        names.append(element.id)
    return names


def _format_list(name: str, items: list[str], width: int = 100) -> str:
    one_line = f"{name} = [{', '.join(items)}]"
    if len(one_line) <= width:
        return one_line
    inner = "".join(f"    {item},\n" for item in items)
    return f"{name} = [\n{inner}]"


def _set_list(code: str, name: str, items: list[str]) -> str:
    """Rewrite (or add, right after FEATURES) the top-level `name = [...]` statement."""
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    text = _format_list(name, items)
    anchor = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                end = node.end_lineno or node.lineno
                newline = "\n" if lines[end - 1].endswith("\n") else ""
                lines[node.lineno - 1 : end] = [text + newline]
                return "".join(lines)
            if isinstance(target, ast.Name) and target.id == "FEATURES":
                anchor = node.end_lineno or node.lineno
    if anchor is None:
        raise ProgramError("The program must define FEATURES = [feature, ...]")
    lines.insert(anchor, text + "\n")
    return "".join(lines)


def set_feature_order(code: str, order: list[str]) -> str:
    """Reorder FEATURES. `order` must name exactly the features that are there now."""
    program = parse_program(code)
    current = [f.id for f in program.features]
    if sorted(order) != sorted(current):
        raise ProgramError("A new feature order must list every feature exactly once")
    return _set_list(code, "FEATURES", order)


def set_feature_enabled(code: str, feature_id: str, enabled: bool) -> str:
    """Suppress a feature (skip it when building) or bring it back."""
    program = parse_program(code)
    ids = [f.id for f in program.features]
    if feature_id not in ids:
        raise ProgramError(f"No feature named {feature_id!r}")
    off = [f.id for f in program.features if not f.enabled and f.id != feature_id]
    if not enabled:
        off.append(feature_id)
    return _set_list(code, "SUPPRESSED", [i for i in ids if i in off])


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
    known = {p.name: p for p in parse_params(code)}
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
    matches = [p for p in parse_params(code) if p.name == name]
    if not matches:
        raise KeyError(name)
    param = matches[0]
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
