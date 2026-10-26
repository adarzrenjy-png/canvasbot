"""Built-in starter parts, written in the canonical part-program format."""

from __future__ import annotations

L_BRACKET = '''"""L-bracket

Holds a 2 kg camera about 50 mm out from a wall. The upright bolts to the wall with
two M5 screws and the camera hangs from two more in the base. Printed in PETG.
"""

# Made with Jig. Every dimension is a named parameter below: change a value and run
# this file again to regenerate the part. Needs only build123d (pip install build123d).

from build123d import *

# --- parameters ---
BASE_LENGTH = 60.0  # mm | Length of the base flange | min=20 max=300
WIDTH = 40.0  # mm | Width of the bracket | min=10 max=200
THICKNESS = 5.0  # mm | Plate thickness | min=1 max=30
UPRIGHT_HEIGHT = 45.0  # mm | Height of the upright flange | min=15 max=300
HOLE_DIAMETER = 5.5  # mm | Mounting hole diameter (M5 clearance) | min=1 max=30
HOLE_INSET = 10.0  # mm | Distance from hole centre to the flange edge | min=3 max=100
FILLET_RADIUS = 4.0  # mm | Inside corner fillet radius | min=0.5 max=30
LOAD_N = 60.0  # N | Load hung from the base holes (2 kg camera x 3 g bumps) | min=0 max=20000
# --- end parameters ---


def base_flange(part):
    """extrude | Base flange

    The flat plate the load sits on: a block BASE_LENGTH long, WIDTH wide and
    THICKNESS thick, lying on the XY plane with one end against the wall.
    """
    return Box(BASE_LENGTH, WIDTH, THICKNESS, align=(Align.MIN, Align.CENTER, Align.MIN))


def upright_flange(part):
    """extrude | Upright flange

    The plate that bolts to the wall: THICKNESS thick and UPRIGHT_HEIGHT tall,
    standing on the wall end of the base flange and joined to it.
    """
    upright = Box(THICKNESS, WIDTH, UPRIGHT_HEIGHT, align=(Align.MIN, Align.CENTER, Align.MIN))
    return part + upright


def inside_fillet(part):
    """fillet | Inside corner fillet

    Rounds the inside corner where the two flanges meet, with radius
    FILLET_RADIUS. This is where bending stress peaks, and a rounded corner spreads it.
    """
    corner = (
        part.edges()
        .filter_by(Axis.Y)
        .filter_by_position(Axis.X, THICKNESS - 0.01, THICKNESS + 0.01)
        .filter_by_position(Axis.Z, THICKNESS - 0.01, THICKNESS + 0.01)
    )
    return fillet(corner, radius=FILLET_RADIUS)


def base_holes(part):
    """hole | Base mounting holes

    Two through holes of HOLE_DIAMETER in the base flange, HOLE_INSET from its far
    end and from each side, for bolting on whatever the bracket carries.
    """
    x = BASE_LENGTH - HOLE_INSET
    for y in (-WIDTH / 2 + HOLE_INSET, WIDTH / 2 - HOLE_INSET):
        part -= Pos(x, y, THICKNESS / 2) * Cylinder(HOLE_DIAMETER / 2, THICKNESS * 2)
    return part


def upright_holes(part):
    """hole | Upright mounting holes

    Two through holes of HOLE_DIAMETER in the upright flange, HOLE_INSET from its
    top and from each side, for the bolts into the wall.
    """
    z = UPRIGHT_HEIGHT - HOLE_INSET
    for y in (-WIDTH / 2 + HOLE_INSET, WIDTH / 2 - HOLE_INSET):
        hole = Pos(THICKNESS / 2, y, z) * Rot(0, 90, 0) * Cylinder(HOLE_DIAMETER / 2, THICKNESS * 2)
        part -= hole
    return part


FEATURES = [base_flange, upright_flange, inside_fillet, base_holes, upright_holes]
SUPPRESSED = []

# The load case Jig's FEA runs. Faces are picked by the feature that made them, so
# the setup survives any change of dimensions. Forces are in newtons.
ANALYSIS = {
    "material": "petg",
    "fixtures": [
        {"name": "Wall bolts", "faces": {"feature": "upright_holes", "type": "cylinder"}},
        {"name": "Wall", "type": "support", "faces": {"extreme": "-x"}},
    ],
    "loads": [
        {
            "name": "Camera",
            "faces": {"feature": "base_holes", "type": "cylinder"},
            "force": [0, 0, "-LOAD_N"],
        },
    ],
    "min_safety_factor": 2.0,
}


def build():
    part = None
    for feature in FEATURES:
        if feature not in SUPPRESSED:
            part = feature(part)
    return part


if __name__ == "__main__":
    export_step(build(), "l_bracket.step")
    print("Wrote l_bracket.step")
'''

SAMPLES = {"l_bracket": L_BRACKET}
