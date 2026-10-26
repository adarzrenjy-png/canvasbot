"""SVG pictures of a board: copper layers, pads, vias, pour, outline, and part labels.

Every copper element carries `data-net`, and every layer is its own `<g>`, so the app
can highlight a net or hide a layer with CSS alone. The same SVG goes in the report.
"""

from __future__ import annotations

from html import escape

from shapely.geometry.base import BaseGeometry

from jig.pcb.geometry import outline, pad_shape
from jig.pcb.model import Board
from jig.pcb.router import Routing

COLORS = {
    "board": "#1d5c3a",
    "edge": "#e8e2c9",
    "bottom": "#62b0ff",
    "top": "#e8603f",
    "pad": "#d9b34a",
    "hole": "#101418",
    "silk": "#f2f2ee",
    "pour_bottom": "#1c4a85",
    "pour_top": "#8f3523",
}


def _path(geom: BaseGeometry, flip) -> str:
    out = []
    polygons = getattr(geom, "geoms", [geom])
    for poly in polygons:
        if poly.is_empty or not hasattr(poly, "exterior"):
            continue
        for ring in [poly.exterior, *poly.interiors]:
            pts = [flip(x, y) for x, y in ring.coords]
            out.append("M" + "L".join(f"{x:.3f} {y:.3f}" for x, y in pts) + "Z")
    return "".join(out)


def board_svg(
    board: Board, routing: Routing | None, *, scale: float = 10.0, margin: float = 3.0
) -> str:
    w, h = board.width, board.height
    width, height = (w + 2 * margin) * scale, (h + 2 * margin) * scale

    def flip(x: float, y: float) -> tuple[float, float]:
        return x + margin, h - y + margin  # SVG y grows downward; boards are y-up

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + 2 * margin:.2f} {h + 2 * margin:.2f}" '
        f'width="{width:.0f}" height="{height:.0f}" class="pcb" font-family="Inter, Arial, sans-serif">',
        f'<path class="board" d="{_path(outline(board), flip)}" fill="{COLORS["board"]}" '
        f'stroke="{COLORS["edge"]}" stroke-width="0.15"/>',
    ]

    def layer_group(layer: str) -> None:
        parts.append(f'<g class="layer layer-{layer}" data-layer="{layer}">')
        if routing:
            for zone in routing.zones:
                if zone.layer == layer:
                    parts.append(
                        f'<path class="zone" data-net="{escape(zone.net)}" fill-rule="evenodd" '
                        f'd="{_path(zone.polygon, flip)}" fill="{COLORS["pour_" + layer]}" opacity="0.55"/>'
                    )
            for t in routing.tracks:
                if t.layer == layer:
                    pts = " ".join(f"{flip(x, y)[0]:.3f},{flip(x, y)[1]:.3f}" for x, y in t.points)
                    parts.append(
                        f'<polyline class="track" data-net="{escape(t.net)}" points="{pts}" fill="none" '
                        f'stroke="{COLORS[layer]}" stroke-width="{t.width:.3f}" stroke-linecap="round" '
                        f'stroke-linejoin="round"/>'
                    )
        parts.append("</g>")

    layer_group("bottom")
    layer_group("top")

    parts.append('<g class="layer layer-pads">')
    for pad in board.pads():
        net = escape(pad.net or "")
        title = f"<title>{escape(pad.name)}{' · ' + net if net else ''}</title>"
        parts.append(
            f'<path class="pad" data-net="{net}" data-pad="{escape(pad.name)}" '
            f'd="{_path(pad_shape(pad), flip)}" fill="{COLORS["pad"]}">{title}</path>'
        )
        if pad.through_hole:
            cx, cy = flip(pad.x, pad.y)
            parts.append(
                f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{pad.pad.drill / 2:.3f}" fill="{COLORS["hole"]}"/>'
            )
    if routing:
        for v in routing.vias:
            cx, cy = flip(v.x, v.y)
            parts.append(
                f'<circle class="via" data-net="{escape(v.net)}" cx="{cx:.3f}" cy="{cy:.3f}" '
                f'r="{v.diameter / 2:.3f}" fill="{COLORS["pad"]}"/>'
                f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{v.drill / 2:.3f}" fill="{COLORS["hole"]}"/>'
            )
    for x, y, d in board.holes:
        cx, cy = flip(x, y)
        parts.append(
            f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{d / 2:.3f}" fill="{COLORS["hole"]}"/>'
        )
    parts.append("</g>")

    parts.append(
        f'<g class="layer layer-silk" fill="none" stroke="{COLORS["silk"]}" stroke-width="0.12">'
    )
    for ref, placed in board.parts.items():
        x0, y0, x1, y1 = placed.courtyard()
        (ax, ay), (bx, by) = flip(x0, y1), flip(x1, y0)
        parts.append(
            f'<rect class="courtyard" data-ref="{escape(ref)}" x="{ax:.3f}" y="{ay:.3f}" '
            f'width="{bx - ax:.3f}" height="{by - ay:.3f}" rx="0.2"/>'
        )
        tx, ty = flip(placed.x, y1 + 0.3)
        label = escape(
            ref + (f" {placed.value}" if placed.value and placed.part.category == "passive" else "")
        )
        parts.append(
            f'<text x="{tx:.3f}" y="{ty:.3f}" font-size="1.2" text-anchor="middle" '
            f'fill="{COLORS["silk"]}" stroke="none">{label}</text>'
        )
    parts.append("</g></svg>")
    return "".join(parts)
