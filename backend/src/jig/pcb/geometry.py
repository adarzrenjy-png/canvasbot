"""Copper and outline geometry (shapely), and IPC-2221 trace sizing."""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

from jig.pcb.model import Board, PlacedPad

# IPC-2221: I = k * dT^0.44 * A^0.725, with A in square mils. k is 0.048 for outer
# layers and 0.024 for inner ones. 1 oz/ft^2 copper is 1.378 mil (35 um) thick.
IPC_K_EXTERNAL = 0.048
MIL_PER_OZ = 1.378
MM_PER_MIL = 0.0254


def ipc2221_width_mm(current_a: float, copper_oz: float = 1.0, rise_c: float = 10.0) -> float:
    """Minimum outer-layer trace width to carry `current_a` with a `rise_c` temperature rise."""
    if current_a <= 0:
        return 0.0
    area_mil2 = (current_a / (IPC_K_EXTERNAL * rise_c**0.44)) ** (1 / 0.725)
    return area_mil2 / (copper_oz * MIL_PER_OZ) * MM_PER_MIL


def ipc2221_current_a(width_mm: float, copper_oz: float = 1.0, rise_c: float = 10.0) -> float:
    """The inverse: how much current a trace of this width carries for the same rise."""
    area_mil2 = width_mm / MM_PER_MIL * copper_oz * MIL_PER_OZ
    return IPC_K_EXTERNAL * rise_c**0.44 * area_mil2**0.725


def outline(board: Board) -> Polygon:
    shape = box(0, 0, board.width, board.height)
    r = min(board.corner_radius, board.width / 2, board.height / 2)
    if r > 0:
        shape = shape.buffer(-r, join_style="mitre").buffer(r, quad_segs=8)
    return shape


def pad_shape(pad: PlacedPad) -> BaseGeometry:
    shape = pad.pad.shape
    if shape == "circle":
        return Point(pad.x, pad.y).buffer(max(pad.w, pad.h) / 2, quad_segs=8)
    if shape == "oval":
        r = min(pad.w, pad.h) / 2
        dx, dy = max(0.0, pad.w / 2 - r), max(0.0, pad.h / 2 - r)
        return LineString([(pad.x - dx, pad.y - dy), (pad.x + dx, pad.y + dy)]).buffer(
            r, quad_segs=8
        )
    return box(pad.x - pad.w / 2, pad.y - pad.h / 2, pad.x + pad.w / 2, pad.y + pad.h / 2)


def track_shape(points: list[tuple[float, float]], width: float) -> BaseGeometry:
    if len(points) == 1:
        return Point(points[0]).buffer(width / 2, quad_segs=8)
    return LineString(points).buffer(width / 2, quad_segs=8)


def via_shape(x: float, y: float, diameter: float) -> BaseGeometry:
    return Point(x, y).buffer(diameter / 2, quad_segs=8)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
