"""The board report: what the board is, how it was designed and checked, what was not.

Same rules as the part report: every number comes from the board program, the router
or the checks, and the words are fixed templates around them.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from html import escape
from typing import Any

from jig import __version__
from jig.report.document import STYLE, fmt

EXTRA_STYLE = """
.boardpic svg { width: 100%; height: auto; border-radius: 6px; }
.schem svg { width: 100%; height: auto; border: 1px solid #e5eaf0; border-radius: 6px; }
.findings { font-size: 8.5pt; color: #3c4a56; margin: 2px 0 0 18px; padding: 0; }
.kind-power { color: #c0362c; font-weight: 600; } .kind-ground { color: #1f7a3d; font-weight: 600; }
.kind-signal { color: #1f5fbf; font-weight: 600; }
td.st-pass { color: #157a40; font-weight: 700; } td.st-fail { color: #b42318; font-weight: 700; }
td.st-warn { color: #9a6100; font-weight: 700; }
.layers { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.layers .view-bottom .layer-top, .layers .view-top .layer-bottom { display: none; }
"""


def _summary(p: dict[str, Any]) -> str:
    checks = p["checks"]
    r = p["routing"]
    b = p["board"]
    passed = checks["status"] == "pass"
    errors, warnings = checks["errors"], checks["warnings"]
    if passed:
        sentence = "Every design and electrical rule check passes."
    else:
        sentence = f"{errors} rule violation(s): see section 4. Do not order it as is."
    if warnings:
        sentence += f" {warnings} warning(s) to review."
    tone = "pass" if passed else "fail"
    badge = (
        f'<div class="badge is-{tone}"><strong>{tone.upper()}</strong><span>{sentence}</span></div>'
    )
    rows = [
        (
            "Board",
            f"{fmt(b['width'])} × {fmt(b['height'])} mm, {fmt(b['thickness'], 1)} mm thick",
            f"2 layers, {fmt(b['copper_oz'], 0)} oz copper",
        ),
        ("Parts", str(len(p["parts"])), f"{len(p['bom'])} different line items"),
        (
            "Nets",
            f"{r['routed_nets']} of {r['nets']} routed",
            f"{r['tracks']} tracks, {r['vias']} vias, {fmt(r['length_mm'], 0)} mm of track",
        ),
        (
            "Checks",
            f"{sum(1 for c in checks['checks'] if c['status'] == 'pass')} of {len(checks['checks'])} clean",
            f"{checks['errors']} errors, {checks['warnings']} warnings",
        ),
    ]
    table = "".join(f"<tr><th>{a}</th><td>{b_}</td><td>{c}</td></tr>" for a, b_, c in rows)
    return f"""
<section class="top">
  <div>
    <h2>What it is</h2>
    <p>{escape(p["description"])}</p>
    {badge}
    <table class="metrics">{table}</table>
  </div>
  <figure class="boardpic">{p["svg"]}<figcaption>The routed board from above. Red: top copper. Blue: bottom copper and ground pour. Gold: pads and vias.</figcaption></figure>
</section>"""


def _schematic(p: dict[str, Any]) -> str:
    return f"""
<section>
  <h2><span>1</span> The circuit</h2>
  <p>Every part with every pin labelled by the net it belongs to: pins with the same label are
  connected. Power nets are red, ground green, signals blue.</p>
  <figure class="schem">{p["schematic"]}</figure>
</section>"""


def _layout(p: dict[str, Any]) -> str:
    rules = p["rules"]
    r = p["routing"]
    return f"""
<section>
  <h2><span>2</span> The layout and how it was routed</h2>
  <div class="layers">
    <figure class="view-top boardpic">{p["svg"]}<figcaption>Top copper</figcaption></figure>
    <figure class="view-bottom boardpic">{p["svg"]}<figcaption>Bottom copper and ground pour</figcaption></figure>
  </div>
  <p><strong>Routing.</strong> The board is laid on a {fmt(rules["grid"], 2)} mm grid on both copper layers.
  Nets are routed one at a time, wide power nets first. For each net, every other net's copper is
  grown by the clearance ({fmt(rules["clearance"], 2)} mm) plus half the track width, so the
  track's centre line can only use cells where the whole track fits. An A* search then joins the pads,
  stepping in eight directions and changing layer through a via
  ({fmt(rules["via_drill"], 2)} mm drill, {fmt(rules["via_diameter"], 2)} mm pad) when that is shorter
  overall. Pads that carry a net's full current are joined first as its trunk; every other pad gets
  its own branch, sized for its own current and joined to the trunk only. Ground floods the bottom
  layer; top-side ground pads drop a via into it. This board routed in {r["passes"]} pass{"es" if r["passes"] > 1 else ""}
  ({fmt(r["seconds"], 1)} s).</p>
</section>"""


def _busiest(n: dict[str, Any]) -> str:
    if n["pour"]:
        return "pour (plane)"
    if not n.get("busiest"):
        return ""
    b = n["busiest"]
    return (
        f"{fmt(b['current'], 2)} A in {fmt(b['width'], 2)} mm (good for {fmt(b['capacity'], 2)} A)"
    )


def _current(p: dict[str, Any]) -> str:
    rules = p["rules"]
    rows = "".join(
        f"<tr><td class='kind-{n['kind']}'>{escape(n['name'])}</td><td>{n['kind']}</td>"
        f"<td>{'' if n['voltage'] is None else fmt(n['voltage'], 2) + ' V'}</td><td>{fmt(n['current'], 2)} A</td>"
        f"<td>{fmt(n['ipc_width_mm'], 2)} mm</td>"
        f"<td>{_busiest(n)}</td>"
        f"<td>{fmt(n['length_mm'], 0)} mm</td><td>{len(n['pins'])}</td></tr>"
        for n in p["nets"]
    )
    return f"""
<section>
  <h2><span>3</span> Power: are the tracks wide enough?</h2>
  <p>A track heats up when it carries current. IPC-2221 relates the current I a track can carry to its
  copper cross-section A (in square mils) and the temperature rise ΔT it is allowed:</p>
  <p class="eq">I = k · ΔT<sup>0.44</sup> · A<sup>0.725</sup>,&nbsp;&nbsp; k = 0.048 (outer layers),&nbsp;&nbsp;
  width = A ÷ (1.378 mil × copper oz)</p>
  <p>Jig allows a {fmt(rules["temperature_rise_c"], 0)} °C rise on {fmt(rules["copper_oz"], 0)} oz copper. Each net
  declares the current it carries; every track is sized for its own share (a branch to a single
  servo carries one servo's current, not the whole supply's), and the check in section 4 confirms each
  track's width against the current it was sized for.</p>
  <table class="data"><tr><th>Net</th><th>Kind</th><th>Voltage</th><th>Net current</th><th>Width for all of it</th>
  <th>Busiest single track</th><th>Track length</th><th>Pins</th></tr>{rows}</table>
</section>"""


def _checks(p: dict[str, Any]) -> str:
    rows = []
    for c in p["checks"]["checks"]:
        findings = "".join(f"<li>{escape(f['message'])}</li>" for f in c["findings"])
        rows.append(
            f"<tr><td>{'DRC' if c['kind'] == 'drc' else 'ERC'}</td><td>{escape(c['label'])}"
            f"{f'<ul class=findings>{findings}</ul>' if findings else ''}</td>"
            f"<td>{c['looked_at']}</td><td class='st-{c['status']}'>{c['status'].upper()}</td></tr>"
        )
    return f"""
<section>
  <h2><span>4</span> Checks</h2>
  <p>The design rule check (DRC) measures the copper the router produced, independently of the router:
  it does not trust that clearances came out right. The electrical rule check (ERC) reads the circuit:
  supplies, ground, drivers, and every part's voltage and current ratings. Only these checks decide
  PASS; no AI model does.</p>
  <table class="data"><tr><th></th><th>Check</th><th>Items</th><th>Result</th></tr>{"".join(rows)}</table>
</section>"""


def _bom(p: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{escape(str(r['Designator']))}</td><td>{escape(str(r['Comment']))}</td>"
        f"<td>{escape(r['Footprint'])}</td><td>{escape(r['LCSC Part #']) or '—'}</td><td>{r['Quantity']}</td></tr>"
        for r in p["bom"]
    )
    sources = sorted({(x["footprint"], x["footprint_source"]) for x in p["parts"]})
    src = "".join(f"<li><code>{escape(a)}</code>: {escape(b)}</li>" for a, b in sources)
    return f"""
<section>
  <h2><span>5</span> Parts</h2>
  <table class="data"><tr><th>Refs</th><th>Value</th><th>Footprint</th><th>LCSC</th><th>Qty</th></tr>{rows}</table>
  <p class="note">Where each footprint's dimensions come from:</p><ul class="plain note">{src}</ul>
</section>"""


def _fab(p: dict[str, Any]) -> str:
    rules = p["rules"]
    files = "".join(f"<li><code>{escape(f)}</code></li>" for f in p["fab_files"])
    return f"""
<section>
  <h2><span>6</span> Making it</h2>
  <p>The fabrication zip holds Gerber RS-274X copper, solder mask, paste, silkscreen and outline
  layers, Excellon drill files, and a JLCPCB-format BOM and pick-and-place file. Smallest features:
  {fmt(rules["track"], 2)} mm track, {fmt(rules["clearance"], 2)} mm gap, {fmt(rules["via_drill"], 2)} mm drill:
  inside the standard 2-layer process of common fabs.</p>
  <ul class="plain">{files}</ul>
</section>"""


def _assumptions_and_gaps() -> str:
    assumptions = [
        "Footprints are generated from standard package dimensions (IPC-7351 nominal). Compare each one "
        "with the exact part's datasheet before ordering; manufacturers' recommended pads differ slightly.",
        "A branch that feeds a resistor, capacitor, LED or button carries at most that part's rated or "
        "declared current (0.5 A if it has none). Trunks carry the net's full declared current.",
        "The ground pour connects solidly to its pads, with no thermal relief spokes. Through-hole ground "
        "pins need a little more heat to hand-solder.",
        "All parts sit on the top side. Vias are tented (covered by solder mask).",
    ]
    gaps = [
        "Signal integrity and impedance: no high-speed or controlled-impedance rules.",
        "EMC and noise: loop areas, decoupling placement and return paths are not analysed.",
        "Heat in parts: a regulator or MOSFET can overheat even when its tracks are fine.",
        "High voltage: creepage and clearance for mains or above 50 V.",
        "Part stock and lifecycle: LCSC numbers are suggestions; check stock and exact specs.",
        "Assembly rotations: check every part's orientation in the fab's assembly preview.",
        "Firmware, and whether the circuit does what you intend beyond these electrical rules.",
    ]
    return f"""
<section>
  <h2><span>7</span> Assumptions</h2>
  <ul class="plain">{"".join(f"<li>{a}</li>" for a in assumptions)}</ul>
</section>
<section>
  <h2><span>8</span> Not checked</h2>
  <ul class="plain">{"".join(f"<li>{g}</li>" for g in gaps)}</ul>
</section>"""


def build_board_report(payload: dict[str, Any], *, now: datetime | None = None) -> str:
    when = (now or datetime.now(UTC)).strftime("%d %B %Y, %H:%M UTC")
    digest = hashlib.sha256(payload["code"].encode("utf-8")).hexdigest()[:16]
    body = [
        _summary(payload),
        _schematic(payload),
        _layout(payload),
        _current(payload),
        _checks(payload),
        _bom(payload),
        _fab(payload),
        _assumptions_and_gaps(),
        f"""<section><h2><span>9</span> Reproduce it</h2><p>The board program below (fingerprint
        <code>{digest}</code>) regenerates this exact board in Jig {escape(__version__)}.</p></section>
        <section class="appendix"><h2>Appendix A. The board program</h2><pre>{escape(payload["code"])}</pre></section>""",
    ]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(payload["name"])}: board report</title><style>{STYLE}{EXTRA_STYLE}</style></head>
<body><main>
<header><h1>{escape(payload["name"])}</h1>
<p class="sub">Board report: what it is, how it was designed and checked, and what was not checked</p>
<p class="meta">Generated by Jig {escape(__version__)} on {when}. Numbers come from the board program, the
router and the rule checks; none are written by an AI model.</p></header>
{"".join(body)}
<footer>Rule checks catch layout and wiring mistakes, not every design error. Build and test a first board before relying on it.</footer>
</main></body></html>"""
