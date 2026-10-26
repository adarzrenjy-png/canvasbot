"""What the agents are told about Jig's formats.

The format rules here mirror what the parsers enforce (jig.cad.program, jig.cad.sandbox,
jig.fea.spec, jig.pcb.program), and the board catalog is generated from the part
library itself, so the models are never told about a part or pin that does not exist.
"""

from __future__ import annotations

from jig.cad.program import FEATURE_KINDS
from jig.cad.samples import L_BRACKET
from jig.fea.materials import MATERIALS
from jig.pcb.library import PARTS
from jig.pcb.samples import PICO_SERVO

PART_FORMAT = f"""\
A Jig part program is one Python file of build123d code with a fixed layout. The parser
reads it into the feature tree and parameter panel, so the layout is not optional.

1. A module docstring: first line is the part's name, then a short paragraph on what it
   is for, what it carries, and how it is made.
2. `from build123d import *` and, if needed, `import math`. Nothing else may be
   imported. No file, network or process access, no eval/exec/open, no names that start
   with an underscore, no import_* or export_* calls (Jig exports the part itself).
3. Parameters between `# --- parameters ---` and `# --- end parameters ---`, one per line:
       NAME = 12.0  # unit | Plain description | min=1 max=50
   UPPER_CASE names, a plain number on the right (no expressions), units mm, N, deg, or
   count. Give every parameter a sensible min and max. Every dimension, count and load
   the user might want to change is a parameter; no magic numbers in the features.
4. One function per feature, `def name(part):`, taking the part so far (None for the
   first) and returning the new part. Its docstring's first line is `kind | Label`, where
   kind is one of: {", ".join(FEATURE_KINDS)}. Then a blank line and one to three
   sentences in plain English on what the feature adds and why, naming its parameters.
5. `FEATURES = [first, second, ...]` in build order, and `SUPPRESSED = []`.
6. If the part carries a load, an `ANALYSIS` dict (see below).
7. The standard `build()` function and `if __name__ == "__main__":` block, exactly as in
   the example.

Coordinates: Z is up. Put the part's mounting face on a principal plane and its
footprint near the origin.

build123d in algebra mode (use this style):
- Solids: Box(x, y, z, align=(Align.MIN, Align.CENTER, Align.MIN)), Cylinder(radius,
  height), Cone(r1, r2, h), Sphere(r), Torus(R, r). Default alignment is centred.
- Placement: Pos(x, y, z) * shape, Rot(rx, ry, rz) * shape (degrees), combine as
  Pos(...) * Rot(...) * shape. A Cylinder's axis is Z; Rot(0, 90, 0) turns it along X.
- Booleans: a + b (join), a - b (cut), a & b (intersect). `part -= Pos(...) * Cylinder(...)`
  for holes; make cutters longer than the material they cut so faces never coincide.
- 2D then extrude: extrude(Plane.XY * Rectangle(w, h), amount=t); RectangleRounded(w, h,
  r), Circle(r), Polygon((x, y), ...), SlotOverall(length, width); Plane.XZ, Plane.YZ,
  Plane.XY.offset(z) choose where. revolve(Plane.XZ * sketch, axis=Axis.Z).
- Edges and faces: part.edges().filter_by(Axis.Z), .filter_by_position(Axis.X, lo, hi),
  .sort_by(Axis.Z)[-1], .group_by(Axis.Z)[-1]; part.faces().sort_by(Axis.Z)[-1].
  fillet(edges, radius=r), chamfer(edges, length=d). Fillets fail when the radius is
  larger than the faces it joins allow; keep radii below half the thinner wall.
- Shell: offset(part, amount=-wall, openings=part.faces().sort_by(Axis.Z)[-1]).
- Mirror: part + mirror(part, about=Plane.YZ). Patterns: a for loop over positions.
- Keep the result one solid: every feature must touch what is already there.

ANALYSIS (the load case Jig's FEA runs; units mm, N, MPa):
    ANALYSIS = {{
        "material": "petg",
        "fixtures": [
            {{"name": "Wall bolts", "faces": {{"feature": "upright_holes", "type": "cylinder"}}}},
            {{"name": "Wall", "type": "support", "faces": {{"extreme": "-x"}}}},
        ],
        "loads": [{{"name": "Camera", "faces": {{"feature": "base_holes", "type": "cylinder"}},
                    "force": [0, 0, "-LOAD_N"]}}],
        "min_safety_factor": 2.0,
    }}
- material is one of: {", ".join(f"{m.id} ({m.name})" for m in MATERIALS.values())}.
- Fixtures are "fixed" (default; bolted bores, clamped faces) or "support" (a flat face
  resting on something: it cannot move along its normal but may slide).
- Faces are picked by what made them, never by number: {{"feature": "<function name>"}},
  optionally with "type": "cylinder" or "plane"; {{"extreme": "-z"}} for flat faces on the
  part's lowest Z plane (also +z, -x, +x, -y, +y); or {{"box": [[x0,y0,z0],[x1,y1,z1]]}}.
- A force is a total in newtons, spread over its faces by area. Write load magnitudes as
  parameters ("-LOAD_N") so they show in the panel. Include impact or vibration factors
  in the parameter and say so in its description.
- min_safety_factor: 2.0 unless the user asks otherwise. Never below 1.5.

A complete, correct example:

{L_BRACKET}"""


def board_catalog() -> str:
    """Every part in the board library, with its pins, in the form the board program uses."""
    lines = []
    for part in sorted(PARTS.values(), key=lambda p: (p.category, p.id)):
        bw, bh = part.footprint.body
        ratings = ", ".join(f"{k}={v:g}" for k, v in part.ratings.items())
        pins = " ".join(f"{p.number}:{p.name}:{p.type}" for p in part.pins)
        gpio = [p for p in part.pins if p.name.startswith("GP") and p.name[2:].isdigit()]
        if len(gpio) > 4:
            others = " ".join(f"{p.number}:{p.name}:{p.type}" for p in part.pins if p not in gpio)
            pins = (
                f"{others}; plus GPIO pins {gpio[0].name}..{gpio[-1].name} "
                f"({gpio[0].type}), written by name, e.g. U1.GP15"
            )
        lines.append(
            f"- {part.id} [{part.prefix}] {part.name}: {part.description.rstrip('.')}. "
            f"Body {bw:g} x {bh:g} mm.{f' Ratings: {ratings}.' if ratings else ''} "
            f"Pins (number:name:type): {pins}"
        )
    return "\n".join(lines)


BOARD_FORMAT = f"""\
A Jig board program describes a two-layer PCB as data. It is parsed, never executed:
values may only be numbers, strings, tuples, lists, dicts, and arithmetic on parameters.

1. A module docstring: the board's name on the first line, then what it is for.
2. Parameters, one per line: `NAME = 5.0  # unit | Description | min=.. max=..`.
3. BOARD = {{"width": .., "height": .., "thickness": 1.6, "corner_radius": 2}} in mm.
4. PARTS = {{"REF": {{"part": "<library id>", "at": (x, y), "rotate": 0|90|180|270,
   "value": "..." (optional), "current": amps through the part (optional),
   "label": "..." (optional)}}}}. Origin is the board's lower-left corner, y up, "at" is
   the part's centre. Keep every part's body plus 1 mm inside the board, and bodies at
   least 1 mm apart. Reference prefixes follow the library ([R], [C], [U] ...).
5. NETS = {{"NAME": {{"pins": ["REF.pin", ...], "kind": "power"|"ground"|"signal",
   "voltage": volts (power nets), "current": amps the net carries at its busiest,
   "pour": "bottom" (ground only)}}}}. Pins are written by number or by name.
   Every power input pin needs a supply: a net with a declared voltage or a power output.
   Unused pins are simply left out; never connect a pin of type nc.
6. RULES = {{"clearance": 0.2, "track": 0.25}} (optional; mm).
7. HOLES = [(x, y, diameter), ...] (optional) for unplated holes; prefer mount_hole_m3 parts.

Jig places nothing itself: it routes the nets you declare with tracks sized by IPC-2221
for each net's current, pours the ground net, and runs DRC and ERC. Put parts that
share busy nets near each other, connectors at board edges, and decoupling capacitors
next to the pins they serve.

The library (use only these part ids and pins):
{board_catalog()}

A complete, correct example:

{PICO_SERVO}"""
