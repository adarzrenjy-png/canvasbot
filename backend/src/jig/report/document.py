"""The engineering report: what the part is, how it was checked, and what was not.

Every number in it comes from the build (OpenCascade) or the FEA (CalculiX). The
wording is fixed templates filled with those numbers, so nothing in the report
can be invented. The layout follows a short engineering explainer: the result
first, then the test, the method in plain words with its equations, the
assumptions with their basis, and an explicit list of what was not checked.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from html import escape
from typing import Any

import numpy as np

from jig import __version__
from jig.cad.program import Program
from jig.report.render import (
    Camera,
    Picture,
    best_view,
    decode,
    face_colors,
    heat_colors,
    scale_bar,
)

FIX_BLUE = "#1f6feb"
LOAD_ORANGE = "#e8590c"
PART_GREY = "#c3ccd6"

STATUS_TEXT = {
    "pass": ("PASS", "Meets every requirement of its load case."),
    "fail": ("FAIL", "Does not meet its load case. Do not use it as is."),
    "unconverged": (
        "UNCONFIRMED",
        "Passes on paper, but the stress did not settle between meshes, so the result is not trusted.",
    ),
    "invalid": ("INVALID", "The solver's forces did not balance, so the result is not trusted."),
}


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def direction_words(force: list[float]) -> str:
    f = np.array(force, dtype=float)
    magnitude = float(np.linalg.norm(f))
    if magnitude == 0:
        return "0 N"
    axis = int(np.argmax(np.abs(f)))
    if abs(f[axis]) / magnitude > 0.999:
        name = "XYZ"[axis]
        sign = "+" if f[axis] > 0 else "−"
        plain = {
            "Z": ("straight up", "straight down"),
            "X": ("toward +X", "toward −X"),
            "Y": ("toward +Y", "toward −Y"),
        }[name][0 if f[axis] > 0 else 1]
        return f"{fmt(magnitude)} N {plain} ({sign}{name})"
    unit = f / magnitude
    return f"{fmt(magnitude)} N along ({unit[0]:.2f}, {unit[1]:.2f}, {unit[2]:.2f})"


def _part_title(code: str) -> tuple[str, str]:
    import ast

    doc = ast.get_docstring(ast.parse(code)) or "Untitled part"
    head, *rest = doc.strip().splitlines()
    body = " ".join(line.strip() for line in rest if line.strip())
    return head.strip(), body


def _mesh_arrays(mesh: dict) -> tuple[np.ndarray, np.ndarray]:
    return decode(mesh["positions"], "f"), decode(mesh["indices"], "I")


def part_picture(
    build: dict, highlight: dict[int, str] | None = None, *, width=560, height=380, view=None
) -> Picture:
    positions, indices = _mesh_arrays(build["mesh"])
    picture = Picture(width, height, Camera.iso(view) if view is not None else None)
    picture.add_mesh(
        positions, indices, face_colors(build["mesh"]["faces"], highlight or {}, PART_GREY)
    )
    return picture


def load_case_picture(build: dict, fea: dict) -> str:
    highlight: dict[int, str] = {}
    for fixture in fea["fixtures"]:
        for i in fixture["faces"]:
            highlight[i] = FIX_BLUE
    for load in fea["loads"]:
        for i in load["faces"]:
            highlight[i] = LOAD_ORANGE
    info = build["face_info"]
    picture = part_picture(build, highlight, view=best_view(info, list(highlight)))
    for load in fea["loads"]:
        faces = [info[i] for i in load["faces"]]
        weights = np.array([f["area"] for f in faces])
        tip = np.average(np.array([f["center"] for f in faces]), axis=0, weights=weights)
        magnitude = math.sqrt(sum(v * v for v in load["force_n"]))
        picture.add_arrow(
            tip, np.array(load["force_n"]), f"{load['name']}: {fmt(magnitude, 0)} N", LOAD_ORANGE
        )
    return picture.svg()


def heatmap_picture(fea: dict) -> str:
    field = fea.get("field_preview") or fea["field"]
    positions = decode(field["positions"], "f")
    indices = decode(field["indices"], "I")
    values = decode(field["von_mises"], "f")
    vmax = float(fea["result"]["peak_von_mises_mpa"])
    picture = Picture(560, 380)
    picture.add_mesh(positions, indices, heat_colors(indices, values, vmax))
    picture.add_marker(np.array(fea["result"]["peak_at"]), f"peak {fmt(vmax)} MPa", "#b42318")
    return picture.svg()


# ---------------------------------------------------------------- sections


def _summary(about: str, program: Program, build: dict, fea: dict | None) -> str:
    stats = build["stats"]
    size = " × ".join(fmt(v) for v in stats["bbox"]["size"])
    rows = []
    material = None
    if fea and fea.get("ok"):
        material = fea["material"]
        res = fea["result"]
        sf_check = next(c for c in fea["checks"] if c["id"] == "safety_factor")
        rows.append(
            (
                "Safety factor",
                f"{fmt(fea['safety_factor'], 2)}",
                f"≥ {fmt(sf_check['limit'], 1)} required",
            )
        )
        rows.append(
            (
                "Peak stress (von Mises)",
                f"{fmt(res['peak_von_mises_mpa'])} MPa",
                f"allowable {fmt(material['allowable_mpa'], 0)} MPa",
            )
        )
        disp = next((c for c in fea["checks"] if c["id"] == "displacement"), None)
        rows.append(
            (
                "Largest movement",
                f"{fmt(res['max_displacement_mm'], 2)} mm",
                f"≤ {fmt(disp['limit'], 2)} mm required" if disp else "no limit set",
            )
        )
    if material:
        mass = stats["volume_mm3"] / 1000 * material["density_g_cm3"]
        rows.append(("Mass", f"{fmt(mass)} g", f"{escape(material['name'])}, solid"))
    rows.append(("Size (X × Y × Z)", f"{size} mm", f"{fmt(stats['volume_mm3'] / 1000, 2)} cm³"))

    if fea and fea.get("ok"):
        label, sentence = STATUS_TEXT.get(fea["status"], ("?", ""))
        badge = f'<div class="badge is-{fea["status"]}"><strong>{label}</strong><span>{escape(sentence)}</span></div>'
    else:
        reason = (fea or {}).get("error", "No load case has been analysed yet.")
        badge = f'<div class="badge is-none"><strong>NOT ANALYSED</strong><span>{escape(reason)}</span></div>'

    table = "".join(f"<tr><th>{a}</th><td>{b}</td><td>{c}</td></tr>" for a, b, c in rows)
    about_html = f"<p>{escape(about)}</p>" if about else ""
    features = "".join(
        f"<li><strong>{escape(f.label)}</strong>{' (suppressed)' if not f.enabled else ''}"
        f"{': ' + escape(f.description) if f.description else ''}</li>"
        for f in program.features
    )
    return f"""
<section class="top">
  <div>
    <h2>What it is</h2>
    {about_html}
    <p>It is built from {len(program.features)} features, in this order:</p>
    <ol class="features">{features}</ol>
    {badge}
    <table class="metrics">{table}</table>
  </div>
  <figure>{part_picture(build).svg()}<figcaption>The part as built, drawn from its CAD model.</figcaption></figure>
</section>"""


def _fixture_words(fixture: dict) -> str:
    if fixture["type"] == "support":
        return (
            "held so it cannot move into or out of its plane, but free to slide along it "
            "(a flat face resting on something rigid)"
        )
    return "held completely still (as if clamped or bolted solid)"


def _load_case(build: dict, fea: dict) -> str:
    fixtures = "".join(
        f"<li><span class='swatch fix'></span><strong>{escape(f['name'])}</strong>: "
        f"{escape(f['selector'])}, {_fixture_words(f)}.</li>"
        for f in fea["fixtures"]
    )
    loads = "".join(
        f"<li><span class='swatch load'></span><strong>{escape(ld['name'])}</strong>: "
        f"{direction_words(ld['force_n'])}, spread over the {escape(ld['selector'])} by area.</li>"
        for ld in fea["loads"]
    )
    material = fea["material"]
    sf = next(c for c in fea["checks"] if c["id"] == "safety_factor")
    disp = next((c for c in fea["checks"] if c["id"] == "displacement"), None)
    disp_line = (
        f" and its largest movement must stay under {fmt(disp['limit'], 2)} mm" if disp else ""
    )
    return f"""
<section>
  <h2><span>1</span> The test: what the part has to survive</h2>
  <div class="split">
    <figure>{load_case_picture(build, fea)}<figcaption>Blue: faces held still. Orange: faces the load acts on.</figcaption></figure>
    <div>
      <p>This is the load case written into the part's own code (its <code>ANALYSIS</code> block), so
      anyone who opens the file runs the same test.</p>
      <ul class="plain">{fixtures}{loads}</ul>
      <p>Material: <strong>{escape(material["name"])}</strong>, E = {fmt(material["youngs_mpa"], 0)} MPa,
      ν = {material["poisson"]}. Allowable stress {fmt(material["allowable_mpa"])} MPa:
      {escape(material["allowable_basis"])}. Source: {escape(material["source"])}.</p>
    </div>
  </div>
  <div class="oneline">
    <span>Requirement</span>
    <p>Under these loads, the highest von Mises stress anywhere away from the clamps must stay below
    {fmt(material["allowable_mpa"])} MPa ÷ {fmt(sf["limit"], 1)} = <strong>{fmt(material["allowable_mpa"] / sf["limit"])} MPa</strong>
    (a safety factor of at least {fmt(sf["limit"], 1)}){disp_line}.</p>
  </div>
</section>"""


def _results(fea: dict) -> str:
    levels = fea["levels"]
    conv = fea["convergence"]
    rows = "".join(
        f"<tr><td>{'Coarse' if i == 0 else 'Fine'}</td><td>{fmt(lv['mesh_size_mm'], 2)} mm</td>"
        f"<td>{lv['nodes']:,}</td><td>{lv['elements']:,}</td><td>{fmt(lv['peak_von_mises_mpa'], 2)}</td>"
        f"<td>{fmt(lv['max_displacement_mm'], 3)}</td><td>{fmt(lv['solve_s'], 1)} s</td></tr>"
        for i, lv in enumerate(levels)
    )
    checks = "".join(
        f"<li class='{'ok' if c['pass'] else 'bad'}'><strong>{'Pass' if c['pass'] else 'Fail'}</strong> "
        f"{escape(c['label'])}: {fmt(c['value'], 2)} against {fmt(c['limit'], 2)} ({escape(c['detail'])})</li>"
        for c in fea["checks"]
    )
    res = fea["result"]
    peak = res["peak_at"]
    clamp_note = ""
    if res["raw_peak_von_mises_mpa"] > res["peak_von_mises_mpa"] * 1.01:
        clamp_note = (
            f" Right at the clamps the raw maximum is {fmt(res['raw_peak_von_mises_mpa'], 2)} MPa;"
            " section 3 explains why that number is not used."
        )
    return f"""
<section>
  <h2><span>2</span> The result</h2>
  <div class="split">
    <figure>{heatmap_picture(fea)}{scale_bar(res["peak_von_mises_mpa"])}
      <figcaption>Von Mises stress on the surface (finer mesh). The circle marks the peak.</figcaption></figure>
    <div>
      <ul class="checks">{checks}</ul>
      <p>The peak stress, {fmt(res["peak_von_mises_mpa"], 2)} MPa, sits at
      ({fmt(peak[0])}, {fmt(peak[1])}, {fmt(peak[2])}) mm.{clamp_note}</p>
      <p class="note">Between the two meshes the peak stress changed {fmt(conv["stress_change"] * 100)} %
      (limit {fmt(conv["stress_tolerance"] * 100, 0)} %) and the largest movement
      {fmt(conv["displacement_change"] * 100, 2)} % (limit {fmt(conv["displacement_tolerance"] * 100, 0)} %):
      <strong>{"converged" if conv["converged"] else "not converged"}</strong>. The reactions at the
      held faces balance the applied loads to {fea["equilibrium"]["error"] * 100:.4f} %.</p>
    </div>
  </div>
  <table class="data">
    <tr><th>Mesh</th><th>Element size</th><th>Nodes</th><th>Elements</th><th>Peak stress (MPa)</th><th>Largest movement (mm)</th><th>Solve time</th></tr>
    {rows}
  </table>
</section>"""


def _method(fea: dict) -> str:
    fine = fea["levels"][-1]
    return f"""
<section>
  <h2><span>3</span> How it was checked</h2>
  <p><strong>Finite element analysis.</strong> The CAD model is cut into small tetrahedra
  ({fine["elements"]:,} on the finer mesh). Each one has 10 nodes, one at each corner and one on
  each edge, so it can bend smoothly; simpler 4-node elements are far too stiff in bending and would
  make the part look stronger than it is. CalculiX solves the stiffness equations of all of them at
  once for how far every node moves:</p>
  <p class="eq">K u = f</p>
  <p>K is the part's stiffness (from its shape and the material's E and ν), f the applied forces and
  u the movement of every node. Stresses follow from how much each element is stretched and sheared.</p>
  <p><strong>Loads.</strong> Each load is a total force spread over its faces in proportion to area.
  On 10-node elements the exact equivalent nodal forces put each face triangle's share on its three
  edge nodes, a third each, and nothing on its corners, which is how they are applied.</p>
  <p><strong>Stress and safety factor.</strong> The six stress components at each point are combined
  into one number, the von Mises stress, which predicts when a ductile material starts to yield:</p>
  <p class="eq">σ<sub>vm</sub> = √( ½[(σ<sub>x</sub>−σ<sub>y</sub>)² + (σ<sub>y</sub>−σ<sub>z</sub>)² + (σ<sub>z</sub>−σ<sub>x</sub>)²] + 3(τ<sub>xy</sub>² + τ<sub>yz</sub>² + τ<sub>zx</sub>²) ),
  &nbsp;&nbsp; SF = σ<sub>allowable</sub> ÷ max σ<sub>vm</sub></p>
  <p><strong>Why the clamps are left out of the peak.</strong> A face held perfectly still is an
  idealisation: no real bolt or wall is infinitely stiff. At the edge of such a face the computed
  stress keeps rising every time the mesh is refined (a singularity), so it measures the model, not
  the part. The peak is therefore taken from nodes more than one element size
  ({fmt(fine["mesh_size_mm"], 2)} mm) away from fully held faces. Real stress near the bolts is checked
  by the bolt and bearing calculations, which are listed under "Not checked" until they exist.</p>
  <p><strong>Trusting the answer.</strong> The part is solved twice, the second time with elements
  1.6 times smaller. The result counts only if the peak stress moves by less than 10 % and the
  largest movement by less than 5 %, and if the reaction forces at the held faces balance the applied
  loads. The verdict above is computed from these numbers by code; no AI model decides it.</p>
  <p><strong>Is the solver right?</strong> Jig's test suite runs the same pipeline on a cantilever
  beam (100 mm aluminium, 10 × 10 mm, 100 N at the tip) and compares it with beam theory: the tip
  deflection must agree within 2 % and the bending stress within 3 % on every change to the code.</p>
</section>"""


def _parameters(program: Program) -> str:
    rows = "".join(
        f"<tr><td><code>{escape(p.name)}</code></td><td>{escape(p.description)}</td>"
        f"<td class='num'>{p.value:g} {escape(p.unit)}</td>"
        f"<td>{'' if p.min is None else f'{p.min:g}'}–{'' if p.max is None else f'{p.max:g}'}</td>"
        f"<td>{'locked' if p.locked else ''}</td></tr>"
        for p in program.params
    )
    return f"""
<section>
  <h2><span>4</span> Design parameters</h2>
  <p>Every dimension is a named parameter in the part's code. Locked values are ones the design
  agents are not allowed to change.</p>
  <table class="data"><tr><th>Name</th><th>Meaning</th><th>Value</th><th>Allowed</th><th></th></tr>{rows}</table>
</section>"""


def _geometry(build: dict) -> str:
    s = build["stats"]
    items = [
        (s["valid"], "OpenCascade reports a valid, closed solid."),
        (
            s["solids"] == 1,
            f"The part is one piece ({s['solids']} solid{'s' if s['solids'] != 1 else ''}).",
        ),
        (
            True,
            f"{s['faces']} faces and {s['edges']} edges; surface area {fmt(s['area_mm2'], 0)} mm².",
        ),
    ]
    rows = "".join(
        f"<li class='{'ok' if ok else 'bad'}'><strong>{'Pass' if ok else 'Fail'}</strong> {escape(t)}</li>"
        for ok, t in items
    )
    return f"""
<section>
  <h2><span>5</span> Geometry checks</h2>
  <ul class="checks">{rows}</ul>
</section>"""


def _assumptions(fea: dict | None) -> str:
    items = [
        "The material is linear elastic and the same in every direction, and deflections are small "
        "compared with the part, so the stiffness does not change as it bends.",
        "Loads are static: applied slowly and held. Shock, vibration and impact are represented only "
        "as far as the load values already include them.",
    ]
    if fea and fea.get("ok"):
        material = fea["material"]
        if material["process"] == "printed":
            items.append(
                "3D-printed plastic is weaker between layers than along them. The allowable stress "
                f"uses a 0.6 knockdown on the datasheet strength ({escape(material['allowable_basis'])}); "
                "it assumes solid infill and normal print quality."
            )
        if any(f["type"] == "fixed" for f in fea["fixtures"]):
            items.append(
                "Bolted or clamped faces are held perfectly rigid. Real bolts allow a little slip and "
                "the holes can stretch, which moves load around near them."
            )
        if any(f["type"] == "support" for f in fea["fixtures"]):
            items.append(
                "Supported faces cannot lift off what they rest on. Where the part would really "
                "separate, the model holds it down, which can make it look stiffer than it is there."
            )
    return f"""
<section>
  <h2><span>6</span> Assumptions</h2>
  <ul class="plain">{"".join(f"<li>{t}</li>" for t in items)}</ul>
</section>"""


def _not_checked() -> str:
    items = [
        "Fatigue: loads that repeat many times can crack a part well below its static strength.",
        "Buckling of thin walls or slender sections under compression.",
        "Bolts, screws and inserts: their strength, thread pull-out, and bearing on the hole edge.",
        "Creep: plastics slowly deform under a load held for days or months.",
        "Temperature: heat lowers the strength and stiffness of plastics sharply.",
        "Print orientation, layer adhesion and defects beyond the knockdown above.",
        "Manufacturing tolerances and how the part fits the parts around it.",
    ]
    return f"""
<section>
  <h2><span>7</span> Not checked</h2>
  <p>These can still break a part that passes the test above. Check the ones that apply to how
  this part will be used.</p>
  <ul class="plain">{"".join(f"<li>{t}</li>" for t in items)}</ul>
</section>"""


def _reproduce(code: str, build: dict, fea: dict | None) -> str:
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
    versions = (fea or {}).get("versions") or {}
    solver = ", ".join(f"{k} {v}" for k, v in versions.items()) or "not run"
    return f"""
<section>
  <h2><span>8</span> Reproduce it</h2>
  <p>The exact source is in Appendix A (fingerprint <code>{digest}</code>). Saved as
  <code>part.py</code>, it rebuilds this part with <code>python part.py</code> and nothing but
  build123d installed. Jig {escape(__version__)} built it (build <code>{escape(build.get("id", ""))}</code>);
  FEA solvers: {escape(solver)}.</p>
</section>
<section class="appendix">
  <h2>Appendix A. The part's source code</h2>
  <pre>{escape(code)}</pre>
</section>"""


STYLE = """
@page { size: A4; margin: 14mm 14mm 16mm; }
* { box-sizing: border-box; }
body { margin: 0; font: 10.5pt/1.45 Inter, "Helvetica Neue", Arial, sans-serif; color: #17222b; background: #fff; }
main { max-width: 190mm; margin: 0 auto; padding: 10mm 0; }
header h1 { font-size: 24pt; margin: 0; letter-spacing: -0.02em; }
header .sub { color: #5b6b78; margin: 2px 0 0; }
header .meta { color: #8796a3; font-size: 8.5pt; border-bottom: 1.5px solid #0a66e8; padding-bottom: 6px; margin-bottom: 10px; }
h2 { font-size: 13pt; color: #0a66e8; margin: 14px 0 6px; }
h2 span { display: inline-block; min-width: 18px; }
p { margin: 4px 0 6px; }
code { font: 9pt ui-monospace, Menlo, Consolas, monospace; background: #f2f5f8; padding: 0 3px; border-radius: 3px; }
figure { margin: 0; text-align: center; }
figure svg { max-width: 100%; height: auto; }
figcaption { color: #5b6b78; font-size: 8.5pt; }
.top { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
.split { display: grid; grid-template-columns: 1.05fr 1fr; gap: 14px; align-items: start; }
.features { margin: 2px 0 8px; padding-left: 18px; font-size: 9.5pt; }
.badge { display: flex; gap: 10px; align-items: center; border-radius: 10px; padding: 8px 12px; margin: 8px 0; }
.badge strong { font-size: 16pt; letter-spacing: 0.04em; }
.badge span { font-size: 9.5pt; }
.badge.is-pass { background: #e3f5ea; color: #157a40; }
.badge.is-fail, .badge.is-invalid { background: #fde7e7; color: #b42318; }
.badge.is-unconverged, .badge.is-none { background: #fdf1dc; color: #9a6100; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; }
.metrics th { text-align: left; font-weight: 600; padding: 3px 6px 3px 0; }
.metrics td { padding: 3px 6px; border-top: 1px solid #e5eaf0; }
.metrics tr:first-child td, .metrics tr:first-child th { border-top: 0; }
.data th { text-align: left; border-bottom: 1.5px solid #17222b; padding: 3px 6px 3px 0; font-weight: 600; }
.data td { border-bottom: 1px solid #e5eaf0; padding: 3px 6px 3px 0; }
.data td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
ul.plain, ul.checks { padding-left: 16px; margin: 4px 0; }
ul.checks { list-style: none; padding-left: 0; }
ul.checks li { margin: 3px 0; }
ul.checks li strong { display: inline-block; min-width: 38px; }
ul.checks li.ok strong { color: #157a40; }
ul.checks li.bad strong { color: #b42318; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.swatch.fix { background: #1f6feb; } .swatch.load { background: #e8590c; }
.oneline { display: grid; grid-template-columns: 110px 1fr; gap: 10px; border: 1px solid #b9d3f8; background: #f3f8fe;
  border-radius: 8px; padding: 8px 12px; margin-top: 8px; }
.oneline span { font-weight: 700; color: #0a66e8; }
.eq { text-align: center; font-family: "Times New Roman", serif; font-size: 12pt; margin: 6px 0; }
.note { font-size: 9pt; color: #3c4a56; }
pre { font: 7.5pt/1.35 ui-monospace, Menlo, Consolas, monospace; background: #f6f8fa; border-radius: 6px;
  padding: 8px; white-space: pre-wrap; }
.appendix { break-before: page; }
section { break-inside: avoid-page; }
footer { color: #8796a3; font-size: 8pt; border-top: 1px solid #e5eaf0; margin-top: 14px; padding-top: 6px; }
@media screen { body { background: #eef1f4; } main { background: #fff; padding: 14mm; margin: 16px auto;
  box-shadow: 0 4px 20px rgb(16 32 48 / 0.1); border-radius: 6px; } }
"""


def build_report(
    code: str,
    program: Program,
    build: dict[str, Any],
    fea: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str:
    title, about = _part_title(code)
    when = (now or datetime.now(UTC)).strftime("%d %B %Y, %H:%M UTC")
    analysed = bool(fea and fea.get("ok"))
    body = [_summary(about, program, build, fea)]
    if analysed:
        body += [_load_case(build, fea), _results(fea), _method(fea)]
    body += [
        _parameters(program),
        _geometry(build),
        _assumptions(fea),
        _not_checked(),
        _reproduce(code, build, fea),
    ]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}: engineering report</title><style>{STYLE}</style></head>
<body><main>
<header><h1>{escape(title)}</h1>
<p class="sub">Engineering report: what the part is, how it was checked, and what was not checked</p>
<p class="meta">Generated by Jig {escape(__version__)} on {when}. Numbers come from OpenCascade (geometry) and CalculiX (FEA); none are written by an AI model.</p></header>
{"".join(body)}
<footer>FEA results are simulation estimates, not certification. Verify critical parts with physical testing.</footer>
</main></body></html>"""
