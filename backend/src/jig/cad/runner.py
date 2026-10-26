"""Sandboxed part builder. Runs as its own process: `python -I -m jig.cad.runner`.

The parent starts this process ahead of time so build123d is already imported,
then writes one line to stdin: the path of a job.json inside the build's output
folder. The runner validates the code again, executes it with a restricted set of
builtins and an import guard, applies FEATURES in order, and writes result.json
plus the STEP and STL exports into that same folder. One process runs exactly one
job, so nothing a part does can leak into the next build.
"""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import io
import json
import math
import sys
import time
import traceback
from array import array
from pathlib import Path
from typing import Any

import build123d as bd

from jig.cad.sandbox import ALLOWED_MODULES, PLAIN_IMPORTS, strip_main_guard, validate

PART_FILENAME = "<part>"
MAX_LOG_CHARS = 20_000

_SAFE_BUILTIN_NAMES = (
    "abs all any bool dict divmod enumerate filter float frozenset int isinstance "
    "issubclass iter len list map max min next pow print range repr reversed round set "
    "slice sorted str sum tuple zip ArithmeticError AssertionError Exception "
    "IndexError KeyError NotImplementedError RuntimeError StopIteration TypeError "
    "ValueError ZeroDivisionError True False None"
).split()


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    allowed = name in PLAIN_IMPORTS or (name in ALLOWED_MODULES and fromlist)
    if level or not allowed:
        raise ImportError(f"import of '{name}' is not allowed in part code")
    module = builtins.__import__(name, globals, locals, fromlist, level)
    public = set(getattr(module, "__all__", ()))
    for item in fromlist or ():
        if item != "*" and public and item not in public:
            raise ImportError(f"'{item}' is not a public name of {name}")
    return module


def _safe_builtins() -> dict[str, Any]:
    safe = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
    safe["__import__"] = _guarded_import
    safe["__build_class__"] = builtins.__build_class__
    return safe


def _block_network() -> None:
    import socket

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("network access is disabled while building parts")

    socket.socket = refuse  # type: ignore[assignment,misc]
    socket.create_connection = refuse  # type: ignore[assignment]


def _limit_cpu(seconds: float) -> None:
    try:
        import resource
    except ImportError:  # Windows: the parent's timeout is the only limit
        return
    limit = max(1, int(math.ceil(seconds)))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 1))


def _part_line(tb: Any) -> int | None:
    line = None
    for frame, lineno in traceback.walk_tb(tb):
        if frame.f_code.co_filename == PART_FILENAME:
            line = lineno
    return line


def _signature(face: bd.Face) -> tuple:
    center = face.center()
    return (
        str(face.geom_type),
        round(face.area, 3),
        round(center.X, 3),
        round(center.Y, 3),
        round(center.Z, 3),
    )


def _b64(values: array) -> str:
    if sys.byteorder != "little":
        values.byteswap()
    return base64.b64encode(values.tobytes()).decode("ascii")


def _edge_points(edge: bd.Edge) -> list[bd.Vector]:
    if edge.geom_type == bd.GeomType.LINE:
        return [edge.position_at(0), edge.position_at(1)]
    count = min(96, max(8, int(edge.length / 1.5)))
    return [edge.position_at(i / count) for i in range(count + 1)]


def tessellate(part: bd.Shape, owners: list[str | None], tol: float, ang: float) -> dict:
    positions = array("f")
    indices = array("I")
    faces = []
    for face, owner in zip(part.faces(), owners, strict=True):
        verts, tris = face.tessellate(tol, ang)
        base = len(positions) // 3
        start = len(indices)
        for v in verts:
            positions.extend((v.X, v.Y, v.Z))
        for a, b, c in tris:
            indices.extend((base + a, base + b, base + c))
        faces.append({"start": start, "count": len(indices) - start, "feature": owner})
    edges = array("f")
    for edge in part.edges():
        points = _edge_points(edge)
        for p, q in zip(points, points[1:], strict=False):
            edges.extend((p.X, p.Y, p.Z, q.X, q.Y, q.Z))
    return {
        "positions": _b64(positions),
        "indices": _b64(indices),
        "edges": _b64(edges),
        "faces": faces,
        "triangles": len(indices) // 3,
    }


def _owners(final_sigs: list[tuple], history: list[tuple[str, set[tuple]]]) -> list[str | None]:
    """Credit each final face to the feature that created it in its final form."""
    owners: list[str | None] = []
    for sig in final_sigs:
        owner = None
        for name, sigs in reversed(history):
            if sig not in sigs:
                break
            owner = name
        owners.append(owner)
    return owners


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    out_dir = Path(job["out_dir"])
    code: str = job["code"]
    result: dict[str, Any] = {"ok": False, "features": [], "log": ""}

    violations = validate(code)
    if violations:
        result["error"] = {
            "stage": "validate",
            "message": "; ".join(str(v) for v in violations[:10]),
            "line": violations[0].line,
            "feature": None,
        }
        return result

    namespace: dict[str, Any] = {"__builtins__": _safe_builtins(), "__name__": "jig_part"}
    log = io.StringIO()
    history: list[tuple[str, set[tuple]]] = []
    part: Any = None
    with contextlib.redirect_stdout(log):
        try:
            tree = strip_main_guard(ast.parse(code, filename=PART_FILENAME))
            exec(compile(tree, PART_FILENAME, "exec"), namespace)  # noqa: S102
        except Exception as error:
            result["error"] = {
                "stage": "load",
                "message": f"{type(error).__name__}: {error}",
                "line": _part_line(error.__traceback__),
                "feature": None,
            }
        features = namespace.get("FEATURES")
        if "error" not in result and not isinstance(features, list | tuple):
            result["error"] = {
                "stage": "load",
                "message": "FEATURES must be a list of functions",
                "line": None,
                "feature": None,
            }
        for func in features if "error" not in result else []:
            name = getattr(func, "__name__", "feature")
            started = time.perf_counter()
            try:
                part = func(part)
                if not isinstance(part, bd.Shape):
                    raise TypeError(f"returned {type(part).__name__}, expected a build123d part")
                if not part.faces():
                    raise ValueError("returned an empty shape")
            except Exception as error:
                result["error"] = {
                    "stage": "feature",
                    "message": f"{type(error).__name__}: {error}",
                    "line": _part_line(error.__traceback__),
                    "feature": name,
                }
                result["features"].append({"id": name, "ok": False, "ms": _ms(started)})
                break
            history.append((name, {_signature(f) for f in part.faces()}))
            result["features"].append({"id": name, "ok": True, "ms": _ms(started)})
    result["log"] = log.getvalue()[-MAX_LOG_CHARS:]
    if "error" in result:
        return result

    faces = part.faces()
    owners = _owners([_signature(f) for f in faces], history)
    tol = float(job.get("tolerance", 0.05))
    ang = float(job.get("angular_tolerance", 0.2))
    box = part.bounding_box()
    result.update(
        ok=True,
        stats={
            "valid": bool(part.is_valid),
            "solids": len(part.solids()),
            "faces": len(faces),
            "edges": len(part.edges()),
            "volume_mm3": part.volume,
            "area_mm2": part.area,
            "bbox": {
                "min": [box.min.X, box.min.Y, box.min.Z],
                "max": [box.max.X, box.max.Y, box.max.Z],
                "size": [box.size.X, box.size.Y, box.size.Z],
            },
        },
        mesh=tessellate(part, owners, tol, ang),
    )
    exports = {}
    if "step" in job.get("exports", ["step", "stl"]):
        bd.export_step(part, out_dir / "part.step")
        exports["step"] = "part.step"
    if "stl" in job.get("exports", ["step", "stl"]):
        bd.export_stl(part, out_dir / "part.stl", tolerance=tol, angular_tolerance=ang)
        exports["stl"] = "part.stl"
    result["exports"] = exports
    return result


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def main() -> int:
    _block_network()
    sys.stdin.reconfigure(encoding="utf-8")  # job paths may be non-ASCII on Windows
    line = sys.stdin.readline().strip()
    if not line:
        return 2
    job_path = Path(line)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    _limit_cpu(float(job.get("timeout_s", 60)) + 5)
    try:
        result = run_job(job)
    except Exception as error:  # a bug in the runner, not in the part
        result = {
            "ok": False,
            "error": {
                "stage": "runner",
                "message": f"{type(error).__name__}: {error}",
                "line": None,
                "feature": None,
            },
            "traceback": traceback.format_exc()[-4000:],
        }
    out = Path(job["out_dir"]) / "result.json"
    out.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
