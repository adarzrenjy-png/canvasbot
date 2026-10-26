"""The Verifier's deterministic checks: code decides PASS or FAIL, never a model.

A model reviews the design too (does it match what was asked?), but its review only
feeds the Fixer. Every verdict the user sees comes from the checks in this module,
the FEA solver, and the board DRC/ERC, all of which measure the actual result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from jig.cad.program import Program, ProgramError, parse_params, set_params
from jig.fea.spec import SpecError, parse_analysis


@dataclass
class Check:
    id: str
    label: str
    status: str  # "pass" | "fail" | "warn" | "skip"
    message: str = ""
    line: int | None = None
    feature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enforce_locks(code: str, locked: dict[str, float]) -> tuple[str, list[str]]:
    """Put locked parameters back to their locked values. Returns the code and what moved."""
    try:
        current = {p.name: p.value for p in parse_params(code)}
    except ProgramError:
        return code, []
    restore = {
        name: value
        for name, value in locked.items()
        if name in current and not math.isclose(current[name], value, rel_tol=1e-9)
    }
    if not restore:
        return code, []
    moved = [f"{n} {current[n]:g} -> {v:g}" for n, v in restore.items()]
    return set_params(code, restore), moved


def requirement_values(program: Program) -> dict[str, Any] | None:
    """The parts of the load case a fix must not weaken: loads and the safety margin."""
    if program.analysis is None:
        return None
    values = program.values()
    loads = []
    for load in program.analysis.get("loads", []) or []:
        force = []
        for component in load.get("force", []) or []:
            if isinstance(component, str):
                sign = -1.0 if component.startswith("-") else 1.0
                component = sign * values.get(component.lstrip("-+"), math.nan)
            force.append(round(float(component), 6))
        loads.append((load.get("name"), tuple(force)))
    return {
        "loads": sorted(loads, key=lambda item: str(item[0])),
        "min_safety_factor": float(program.analysis.get("min_safety_factor", 2.0)),
    }


def _sorted_dims(values: list[float]) -> list[float]:
    return sorted(abs(v) for v in values)


def part_checks(
    code: str,
    program: Program | None,
    program_error: ProgramError | None,
    build: dict[str, Any] | None,
    *,
    plan: dict[str, Any] | None = None,
    locked: dict[str, float] | None = None,
    requirements: dict[str, Any] | None = None,
    fea: dict[str, Any] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    if program_error is not None or program is None:
        message = str(program_error) if program_error else "The program could not be read"
        line = program_error.line if program_error else None
        return [Check("program", "Program follows the Jig part format", "fail", message, line)]
    checks.append(
        Check(
            "program",
            "Program follows the Jig part format",
            "pass",
            f"{len(program.params)} parameters, {len(program.features)} features",
        )
    )

    undocumented = [f.id for f in program.features if not f.description.strip()]
    checks.append(
        Check(
            "documented",
            "Every feature explains what it does",
            "warn" if undocumented else "pass",
            f"No description: {', '.join(undocumented)}" if undocumented else "",
        )
    )

    out_of_range = [
        f"{p.name} = {p.value:g} is outside {p.min:g} to {p.max:g}"
        for p in program.params
        if (p.min is not None and p.value < p.min) or (p.max is not None and p.value > p.max)
    ]
    checks.append(
        Check(
            "ranges",
            "Parameters are inside their limits",
            "fail" if out_of_range else "pass",
            "; ".join(out_of_range),
        )
    )

    if locked:
        values = program.values()
        broken = [
            f"{name} must stay {value:g}" + ("" if name in values else " but was removed")
            for name, value in locked.items()
            if name not in values or not math.isclose(values[name], value, rel_tol=1e-9)
        ]
        checks.append(
            Check(
                "locked",
                "Locked parameters are untouched",
                "fail" if broken else "pass",
                "; ".join(broken) or f"{len(locked)} locked",
            )
        )

    if requirements is not None:
        now = requirement_values(program)
        weakened = now is None or (
            now["loads"] != requirements["loads"]
            or now["min_safety_factor"] < requirements["min_safety_factor"]
        )
        checks.append(
            Check(
                "requirements",
                "Loads and safety margin are as specified",
                "fail" if weakened else "pass",
                "A fix may change the part, never the test it must pass: restore the loads "
                "and min_safety_factor"
                if weakened
                else "",
            )
        )

    expects_load = bool(plan and plan.get("load_case", {}).get("applies"))
    if program.analysis is not None:
        try:
            parse_analysis(program.analysis, program.values())
        except SpecError as error:
            checks.append(Check("load_case", "Load case is complete", "fail", str(error)))
        else:
            checks.append(Check("load_case", "Load case is complete", "pass"))
    elif expects_load:
        checks.append(
            Check(
                "load_case",
                "Load case is complete",
                "fail",
                "The part carries a load but has no ANALYSIS block, so it cannot be checked",
            )
        )

    if build is None:
        return checks
    if not build.get("ok"):
        error = build.get("error") or {}
        checks.append(
            Check(
                "build",
                "Every feature builds",
                "fail",
                f"{error.get('stage', 'build')}: {error.get('message', 'failed')}",
                error.get("line"),
                error.get("feature"),
            )
        )
        return checks
    features = build.get("features", [])
    built = sum(1 for f in features if f.get("ok") and not f.get("skipped"))
    checks.append(Check("build", "Every feature builds", "pass", f"{built} features built"))

    stats = build.get("stats", {})
    solids = stats.get("solids", 0)
    valid = stats.get("valid", False) and solids == 1 and stats.get("volume_mm3", 0) > 0
    checks.append(
        Check(
            "solid",
            "Result is one valid solid",
            "pass" if valid else "fail",
            ""
            if valid
            else f"{solids} solids, valid={stats.get('valid')}: every feature must join "
            "the part and the shape must be closed",
        )
    )

    envelope = (plan or {}).get("envelope_mm") or []
    size = (stats.get("bbox") or {}).get("size")
    if size and len(envelope) == 3 and all(v > 0 for v in envelope):
        got, want = _sorted_dims(size), _sorted_dims(envelope)
        off = [
            f"{g:.0f} mm vs about {w:.0f} mm"
            for g, w in zip(got, want, strict=True)
            if not 0.5 <= g / w <= 2.0
        ]
        checks.append(
            Check(
                "envelope",
                "Overall size matches the plan",
                "warn" if off else "pass",
                "; ".join(off) or " x ".join(f"{v:.0f}" for v in size) + " mm",
            )
        )

    if fea is not None:
        checks.append(fea_check(fea))
    return checks


def fea_check(fea: dict[str, Any]) -> Check:
    label = "Survives its load case (FEA)"
    status = fea.get("status")
    if not fea.get("ok"):
        if status == "error":
            return Check("fea", label, "fail", fea.get("error", "The analysis failed"))
        return Check("fea", label, "skip", fea.get("error", "Not run"))
    sf = fea.get("safety_factor")
    peak = (fea.get("result") or {}).get("peak_von_mises_mpa")
    need = next(
        (c.get("limit") for c in fea.get("checks", []) if c.get("id") == "safety_factor"), None
    )
    detail = f"safety factor {sf:.2f}" + (f" (needs {need:g})" if need else "")
    if peak is not None:
        detail += f", peak stress {peak:.1f} MPa"
    if status == "pass":
        return Check("fea", label, "pass", detail)
    if status == "fail":
        return Check("fea", label, "fail", detail)
    return Check(
        "fea",
        label,
        "warn",
        f"{detail}; result not trusted ({status}): "
        + ("the mesh did not converge" if status == "unconverged" else "loads do not balance"),
    )


def verdict(checks: list[Check]) -> dict[str, Any]:
    """PASS only when nothing failed and, for a loaded part, FEA ran and passed."""
    errors = [c for c in checks if c.status == "fail"]
    warnings = [c for c in checks if c.status == "warn"]
    fea = next((c for c in checks if c.id == "fea"), None)
    loaded = any(c.id == "load_case" for c in checks)
    if errors:
        status = "fail"
    elif loaded and (fea is None or fea.status != "pass"):
        status = "unverified"  # built and sound, but its strength was not demonstrated
    else:
        status = "pass"
    return {
        "status": status,
        "errors": len(errors),
        "warnings": len(warnings),
        "checks": [c.to_dict() for c in checks],
    }


def nearest_feature(build: dict[str, Any], point: list[float] | None) -> str | None:
    """The feature whose face centre is closest to a point (where stress peaks)."""
    if not point:
        return None
    best, best_d = None, math.inf
    for face in build.get("face_info", []):
        centre = face.get("centre")
        if not centre or not face.get("feature"):
            continue
        d = math.dist(centre, point)
        if d < best_d:
            best, best_d = face["feature"], d
    return best


def code_from_reply(text: str) -> str:
    """Models sometimes wrap code in a fence inside the JSON string. Unwrap it."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip() + "\n"
