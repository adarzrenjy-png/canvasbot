"""A net-label schematic: every part as a symbol, every pin labelled with its net.

Pins on the same net are connected because they carry the same label, the way many
professional schematics are drawn, so no wires need laying out. Power nets are red,
ground green, signals blue. Big parts (modules) show only the pins in use.
"""

from __future__ import annotations

from html import escape

from jig.pcb.model import Board, PlacedPart

PIN_PITCH = 16
STUB = 18
COLORS = {"power": "#c0362c", "ground": "#1f7a3d", "signal": "#1f5fbf", "box": "#17222b"}
CATEGORY_ORDER = {"connector": 0, "power": 1, "module": 2, "input": 3, "passive": 4, "indicator": 5}
LEFT_TYPES = ("power_in", "input", "ground", "nc")


def _pins(placed: PlacedPart, net_of: dict) -> tuple[list, list, int]:
    pins = [(p, net_of.get((placed.ref, p.number))) for p in placed.part.pins]
    hidden = 0
    if len(pins) > 12:
        hidden = sum(1 for _, n in pins if n is None)
        pins = [(p, n) for p, n in pins if n is not None]
    if placed.part.category == "connector":
        return pins, [], hidden
    if len(placed.part.pins) == 2:
        return [pins[0]], [pins[1]], hidden
    left = [(p, n) for p, n in pins if p.type in LEFT_TYPES]
    right = [(p, n) for p, n in pins if p.type not in LEFT_TYPES]
    while len(right) > len(left) + 1:  # keep the symbol roughly balanced
        left.append(right.pop())
    return left, right, hidden


def _symbol(
    placed: PlacedPart, net_of: dict, kinds: dict, x: float, y: float
) -> tuple[str, float, float]:
    left, right, hidden = _pins(placed, net_of)
    two_pin = len(placed.part.pins) == 2 and placed.part.category != "connector"
    rows = max(len(left), len(right), 1)
    short = placed.value or placed.part.name.split()[0]
    w = max(64, len(short) * 6 + 16) if two_pin else 120
    h = 26 if two_pin else rows * PIN_PITCH + 28
    out = [
        f'<g class="symbol" data-ref="{escape(placed.ref)}">',
        f'<rect x="{x + STUB + 40:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="4" fill="#fff" '
        f'stroke="{COLORS["box"]}" stroke-width="1.4"/>',
        f'<text x="{x + STUB + 40 + w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" font-size="11" '
        f'font-weight="700">{escape(placed.ref)}</text>',
    ]
    title = short if two_pin else (placed.label or placed.part.name)
    out.append(
        f'<text x="{x + STUB + 40 + w / 2:.1f}" y="{y + (17 if two_pin else h - 8):.1f}" '
        f'text-anchor="middle" font-size="{9 if two_pin else 9.5}" fill="#5b6b78">{escape(title)}</text>'
    )
    box_left = x + STUB + 40
    box_right = box_left + w
    for side, pins in (("left", left), ("right", right)):
        for i, (pin, net) in enumerate(pins):
            py = y + (13 if two_pin else 20 + i * PIN_PITCH)
            if side == "left":
                x0, x1 = box_left - STUB, box_left
                label_x, anchor = x0 - 3, "end"
                name_x, name_anchor = box_left + 4, "start"
            else:
                x0, x1 = box_right, box_right + STUB
                label_x, anchor = x1 + 3, "start"
                name_x, name_anchor = box_right - 4, "end"
            out.append(
                f'<line x1="{x0:.1f}" y1="{py:.1f}" x2="{x1:.1f}" y2="{py:.1f}" stroke="{COLORS["box"]}" stroke-width="1.2"/>'
            )
            if not two_pin:
                out.append(
                    f'<text x="{name_x:.1f}" y="{py + 3:.1f}" text-anchor="{name_anchor}" font-size="8.5">{escape(pin.name)}</text>'
                )
            if net is not None:
                color = COLORS[kinds.get(net, "signal")]
                out.append(
                    f'<text class="net" data-net="{escape(net)}" x="{label_x:.1f}" y="{py + 3:.1f}" '
                    f'text-anchor="{anchor}" font-size="9" font-weight="700" fill="{color}">{escape(net)}</text>'
                )
            else:
                out.append(
                    f'<text x="{(x0 + x1) / 2:.1f}" y="{py + 3:.1f}" text-anchor="middle" font-size="10" fill="#8796a3">×</text>'
                )
    if hidden:
        out.append(
            f'<text x="{box_left + w / 2:.1f}" y="{y + h + 12:.1f}" text-anchor="middle" font-size="8" '
            f'fill="#8796a3">{hidden} unused pins not shown</text>'
        )
    out.append("</g>")
    total_w = w + 2 * STUB + 80
    return "".join(out), total_w, h + (24 if hidden else 12)


def schematic_svg(board: Board, width: float = 900) -> str:
    net_of = {(ref, pin): net.name for net in board.nets.values() for ref, pin in net.pins}
    kinds = {net.name: net.kind for net in board.nets.values()}
    parts = sorted(
        (p for p in board.parts.values() if p.part.category != "mechanical"),
        key=lambda p: (CATEGORY_ORDER.get(p.part.category, 9), p.ref),
    )
    x, y, row_h = 20.0, 34.0, 0.0
    body = []
    for placed in parts:
        svg, w, h = _symbol(placed, net_of, kinds, x, y)
        if x + w > width and x > 20:
            x, y = 20.0, y + row_h + 26
            row_h = 0.0
            svg, w, h = _symbol(placed, net_of, kinds, x, y)
        body.append(svg)
        x += w
        row_h = max(row_h, h)
    height = y + row_h + 50
    title = (
        f'<g font-size="10" fill="#5b6b78"><text x="{width - 16}" y="{height - 26}" text-anchor="end" '
        f'font-weight="700" fill="#17222b">{escape(board.name)}</text>'
        f'<text x="{width - 16}" y="{height - 12}" text-anchor="end">Schematic drawn by Jig from the board '
        f"program. Same label = same net.</text></g>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" width="{width}" '
        f'height="{height:.0f}" font-family="Inter, Arial, sans-serif" class="schematic">'
        f'<rect width="{width}" height="{height:.0f}" fill="#fbfcfd"/>{"".join(body)}{title}</svg>'
    )
