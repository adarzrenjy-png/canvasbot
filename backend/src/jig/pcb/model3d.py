"""The board in 3D, written as an ordinary Jig part program.

The board blank, its holes and a block for every part (its body size and height from
the footprint) become a build123d program, which goes through the same sandboxed
builder as any part: so the board shows in the viewport, exports to STEP, and an
enclosure can be designed around it. Part blocks are envelopes for fit and
clearance, not detailed models.
"""

from __future__ import annotations

from jig.pcb.model import Board


def _r(value: float) -> str:
    return repr(round(value, 4))


def board_part_program(board: Board) -> str:
    holes = [(p.x, p.y, p.pad.drill) for p in board.pads() if p.through_hole]
    holes += list(board.holes)
    blocks = []
    for ref, placed in board.parts.items():
        fp = placed.part.footprint
        if fp.height <= 0:
            continue
        w, h = placed.size(*fp.body)
        blocks.append((ref, placed.x, placed.y, w, h, fp.height))
    hole_list = ",\n    ".join(f"({_r(x)}, {_r(y)}, {_r(d)})" for x, y, d in holes)
    block_list = ",\n    ".join(
        f"({ref!r}, {_r(x)}, {_r(y)}, {_r(w)}, {_r(h)}, {_r(z)})" for ref, x, y, w, h, z in blocks
    )
    return f'''"""{board.name} (3D envelope)

The circuit board as a solid: the blank, its drilled holes, and a block for each part
at its body size and height. Made by Jig from the board program; use it to check fit
and design an enclosure.
"""

from build123d import *

# --- parameters ---
BOARD_W = {_r(board.width)}  # mm | Board width
BOARD_H = {_r(board.height)}  # mm | Board height
THICKNESS = {_r(board.thickness)}  # mm | Board thickness | min=0.4 max=3.2
CORNER_RADIUS = {_r(max(board.corner_radius, 0.0))}  # mm | Board corner radius
# --- end parameters ---

HOLES = [
    {hole_list}
]

PARTS = [
    {block_list}
]


def blank(part):
    """extrude | Board blank

    The bare board: BOARD_W by BOARD_H, THICKNESS thick, with corners rounded to
    CORNER_RADIUS, lying on the XY plane with its lower-left corner at the origin.
    """
    plate = Box(BOARD_W, BOARD_H, THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN))
    if CORNER_RADIUS > 0:
        plate = fillet(plate.edges().filter_by(Axis.Z), radius=CORNER_RADIUS)
    return plate


def drilled_holes(part):
    """hole | Drilled holes

    Every plated and mounting hole, at its finished drill size.
    """
    drills = [Pos(x, y, THICKNESS / 2) * Cylinder(d / 2, THICKNESS * 2) for x, y, d in HOLES]
    return part - Compound(children=drills)  # one cut for all holes is much faster


def components(part):
    """extrude | Component envelopes

    One block per part on top of the board, as wide, deep and tall as its body.
    """
    bodies = [
        Pos(x, y, THICKNESS) * Box(w, h, z, align=(Align.CENTER, Align.CENTER, Align.MIN))
        for ref, x, y, w, h, z in PARTS
    ]
    return part + Compound(children=bodies)


FEATURES = [blank, drilled_holes, components]
SUPPRESSED = []


def build():
    part = None
    for feature in FEATURES:
        if feature not in SUPPRESSED:
            part = feature(part)
    return part


if __name__ == "__main__":
    export_step(build(), "board.step")
'''
