"""Design and electrical rule checks: the only thing that can pass a board.

DRC (design rules) measures the copper the router produced, independently of the
router: clearances between different nets, track widths against the current each
track must carry (IPC-2221), via and hole sizes, distance to the board edge, part
overlap, and that every net is really connected through copper.

ERC (electrical rules) reads the schematic: every power input has a supply, ground
pins sit on ground, no two outputs fight, IC power pins are not left open, and no
part sees more voltage or current than its datasheet allows.

Each check reports what it looked at, so a pass means something.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field

import shapely
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from jig.pcb.geometry import ipc2221_current_a, outline, pad_shape
from jig.pcb.model import Board
from jig.pcb.router import LAYERS, Routing

TOLERANCE = 0.005  # mm; below fab resolution


@dataclass
class Finding:
    check: str
    severity: str  # "error" | "warning"
    message: str
    at: tuple[float, float] | None = None
    nets: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    id: str
    label: str
    kind: str  # "drc" | "erc"
    looked_at: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(f.severity == "error" for f in self.findings):
            return "fail"
        return "warn" if self.findings else "pass"


@dataclass
class _Item:
    kind: str  # pad | track | via | zone
    name: str
    net: str | None
    layer: str
    geom: BaseGeometry


def _items(board: Board, routing: Routing) -> list[_Item]:
    items = []
    for pad in board.pads():
        for layer in pad.layers:
            items.append(_Item("pad", pad.name, pad.net, layer, pad_shape(pad)))
    for i, t in enumerate(routing.tracks):
        items.append(_Item("track", f"track {i + 1} ({t.net})", t.net, t.layer, t.shape()))
    for i, v in enumerate(routing.vias):
        for layer in LAYERS:
            items.append(_Item("via", f"via {i + 1} ({v.net})", v.net, layer, v.shape()))
    for z in routing.zones:
        items.append(_Item("zone", f"{z.net} pour ({z.layer})", z.net, z.layer, z.polygon))
    return items


def _point(geom_a: BaseGeometry, geom_b: BaseGeometry) -> tuple[float, float]:
    a, b = nearest_points(geom_a, geom_b)
    return round((a.x + b.x) / 2, 3), round((a.y + b.y) / 2, 3)


def check_clearance(board: Board, items: list[_Item]) -> CheckResult:
    gap = board.rules.clearance
    result = CheckResult("clearance", f"Copper clearance ≥ {gap:g} mm between nets", "drc", 0)
    seen = set()
    for layer in LAYERS:
        layer_items = [it for it in items if it.layer == layer]
        tree = STRtree([it.geom for it in layer_items])
        for i, a in enumerate(layer_items):
            for j in tree.query(a.geom, predicate="dwithin", distance=gap - TOLERANCE):
                if j <= i:
                    continue
                b = layer_items[j]
                same_net = a.net is not None and a.net == b.net
                if same_net or (a.kind == "via" and b.kind == "via" and a.name == b.name):
                    continue
                result.looked_at += 1
                d = a.geom.distance(b.geom)
                if d < gap - TOLERANCE:
                    key = tuple(sorted((a.name, b.name))) + (layer,)
                    if key in seen:
                        continue
                    seen.add(key)
                    what = "overlap" if d == 0 else f"are {d:.3f} mm apart"
                    result.findings.append(
                        Finding(
                            "clearance",
                            "error",
                            f"{a.name} and {b.name} on {layer} {what} (need {gap:g} mm)",
                            _point(a.geom, b.geom),
                            [n for n in (a.net, b.net) if n],
                        )
                    )
    result.looked_at = max(result.looked_at, len(items))
    return result


def check_edge(board: Board, items: list[_Item]) -> CheckResult:
    need = board.rules.edge_clearance
    edge = outline(board).exterior
    shape = outline(board)
    result = CheckResult("edge", f"Copper ≥ {need:g} mm from the board edge", "drc", len(items))
    for it in items:
        if it.kind == "zone":
            continue
        if not shape.contains(it.geom.centroid):
            result.findings.append(
                Finding("edge", "error", f"{it.name} is off the board", None, [])
            )
            continue
        d = it.geom.distance(edge)
        # Mounting holes may sit on the edge clearance line: allow pads of parts with no net.
        if d < need - TOLERANCE and not (it.kind == "pad" and it.net is None):
            result.findings.append(
                Finding(
                    "edge",
                    "error",
                    f"{it.name} is {d:.2f} mm from the edge (need {need:g} mm)",
                    _point(it.geom, edge),
                    [it.net] if it.net else [],
                )
            )
    return result


def check_tracks(board: Board, routing: Routing) -> list[CheckResult]:
    r = board.rules
    width = CheckResult("track_width", f"Tracks ≥ {r.track:g} mm wide", "drc", len(routing.tracks))
    current = CheckResult(
        "current",
        f"Tracks wide enough for their current (IPC-2221, {r.temperature_rise_c:g} °C rise, "
        f"{r.copper_oz:g} oz)",
        "drc",
        len(routing.tracks),
    )
    for i, t in enumerate(routing.tracks):
        if t.width < r.track - TOLERANCE:
            width.findings.append(
                Finding(
                    "track_width",
                    "error",
                    f"Track {i + 1} ({t.net}) is {t.width:.2f} mm",
                    t.points[0],
                    [t.net],
                )
            )
        capacity = ipc2221_current_a(t.width, r.copper_oz, r.temperature_rise_c)
        if capacity < t.current - 1e-6:
            current.findings.append(
                Finding(
                    "current",
                    "error",
                    f"Track {i + 1} ({t.net}) is {t.width:.2f} mm wide and carries "
                    f"{t.current:g} A, but that width carries only {capacity:.2f} A "
                    f"({t.sized_by})",
                    t.points[0],
                    [t.net],
                )
            )
    return [width, current]


def check_holes(board: Board, routing: Routing) -> CheckResult:
    r = board.rules
    holes = [(f"via {i + 1}", v.drill, v.diameter, (v.x, v.y)) for i, v in enumerate(routing.vias)]
    holes += [
        (p.name, p.pad.drill, min(p.w, p.h), (p.x, p.y)) for p in board.pads() if p.through_hole
    ]
    result = CheckResult(
        "holes",
        f"Drills ≥ {r.min_drill:g} mm, annular ring ≥ {r.min_annular_ring:g} mm",
        "drc",
        len(holes),
    )
    for name, drill, diameter, at in holes:
        if drill < r.min_drill - TOLERANCE:
            result.findings.append(
                Finding("holes", "error", f"{name} drill {drill:g} mm is too small", at)
            )
        ring = (diameter - drill) / 2
        if ring < r.min_annular_ring - TOLERANCE:
            result.findings.append(
                Finding("holes", "error", f"{name} annular ring {ring:.2f} mm is too thin", at)
            )
    return result


def check_placement(board: Board) -> CheckResult:
    shape = outline(board)
    boxes = {ref: shapely.box(*p.courtyard()) for ref, p in board.parts.items()}
    result = CheckResult("placement", "Parts on the board and not overlapping", "drc", len(boxes))
    refs = list(boxes)
    for i, a in enumerate(refs):
        if not shape.buffer(1e-6).contains(boxes[a]):
            result.findings.append(
                Finding(
                    "placement",
                    "error",
                    f"{a} hangs over the board edge",
                    (board.parts[a].x, board.parts[a].y),
                )
            )
        for b in refs[i + 1 :]:
            overlap = boxes[a].intersection(boxes[b]).area
            if overlap > 0.01:
                c = boxes[a].intersection(boxes[b]).centroid
                result.findings.append(
                    Finding(
                        "placement",
                        "error",
                        f"{a} and {b} overlap ({overlap:.1f} mm²)",
                        (round(c.x, 2), round(c.y, 2)),
                    )
                )
    return result


def check_connectivity(board: Board, routing: Routing, items: list[_Item]) -> CheckResult:
    """Union-find over copper: same-net items that touch on a layer, vias and through-hole
    pads joining layers, and pins joined inside a part. Every pad of a net must end up in
    one group."""
    result = CheckResult(
        "connectivity", "Every net fully connected through copper", "drc", len(board.nets)
    )
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for layer in LAYERS:
        layer_items = [it for it in items if it.layer == layer and it.net is not None]
        tree = STRtree([it.geom for it in layer_items])
        for i, a in enumerate(layer_items):
            for j in tree.query(a.geom, predicate="intersects"):
                b = layer_items[j]
                if j != i and a.net == b.net:
                    union(a.name, b.name)
    for ref, placed in board.parts.items():
        for group in placed.part.joined:
            for pin in group[1:]:
                union(f"{ref}.{group[0]}", f"{ref}.{pin}")
    for net in board.nets.values():
        names = [f"{ref}.{pin}" for ref, pin in net.pins]
        groups = defaultdict(list)
        for name in names:
            groups[find(name)].append(name)
        if len(groups) > 1:
            biggest = max(groups.values(), key=len)
            missing = sorted(n for g in groups.values() if g is not biggest for n in g)
            result.findings.append(
                Finding(
                    "connectivity",
                    "error",
                    f"{net.name}: {', '.join(missing)} not connected to {', '.join(biggest[:3])}"
                    f"{'…' if len(biggest) > 3 else ''}",
                    None,
                    [net.name],
                )
            )
        if len(names) == 1:
            result.findings.append(
                Finding(
                    "connectivity",
                    "warning",
                    f"{net.name} has only one pin ({names[0]})",
                    None,
                    [net.name],
                )
            )
    return result


# ---------------------------------------------------------------- ERC


def run_erc(board: Board) -> list[CheckResult]:
    net_of = {(ref, pin): net for net in board.nets.values() for ref, pin in net.pins}
    for ref, placed in board.parts.items():  # joined pins share their partner's net
        for group in placed.part.joined:
            net = next((net_of[(ref, p)] for p in group if (ref, p) in net_of), None)
            if net is not None:
                for p in group:
                    net_of.setdefault((ref, p), net)

    pad_at = {(pad.ref, pad.pad.number): (round(pad.x, 3), round(pad.y, 3)) for pad in board.pads()}
    centre = {ref: (round(placed.x, 3), round(placed.y, 3)) for ref, placed in board.parts.items()}

    supply = CheckResult("supply", "Every power input has a supply", "erc", 0)
    ground = CheckResult("ground", "Ground pins are on a ground net", "erc", 0)
    drivers = CheckResult("drivers", "No two outputs drive the same net", "erc", len(board.nets))
    open_pins = CheckResult("open_pins", "IC power and ground pins are connected", "erc", 0)
    nc = CheckResult("nc", "No-connect pins are left unconnected", "erc", 0)
    voltage = CheckResult("voltage", "No part sees more voltage than it is rated for", "erc", 0)
    current = CheckResult(
        "part_current", "No part carries more current than it is rated for", "erc", 0
    )

    outputs: dict[str, list[str]] = defaultdict(list)
    for ref, placed in board.parts.items():
        nets_here = []
        for pin in placed.part.pins:
            net = net_of.get((ref, pin.number))
            label = f"{ref}.{pin.name}"
            at = pad_at.get((ref, pin.number))
            if pin.type == "power_in":
                supply.looked_at += 1
                if net is None:
                    open_pins.findings.append(
                        Finding("open_pins", "error", f"{label} (power input) is not connected", at)
                    )
                elif net.voltage is None and not any(
                    board.parts[r].part.pin(p).type == "power_out" for r, p in net.pins
                ):
                    supply.findings.append(
                        Finding(
                            "supply",
                            "error",
                            f"{label} is on {net.name}, which has no supply: no power "
                            "output pin and no declared voltage",
                            at,
                            [net.name],
                        )
                    )
            if pin.type == "ground":
                ground.looked_at += 1
                open_pins.looked_at += 1
                if net is None:
                    open_pins.findings.append(
                        Finding("open_pins", "error", f"{label} (ground) is not connected", at)
                    )
                elif net.kind != "ground":
                    ground.findings.append(
                        Finding(
                            "ground",
                            "error",
                            f"{label} is a ground pin on {net.name}, which is not ground",
                            at,
                            [net.name],
                        )
                    )
            if pin.type == "power_out":
                open_pins.looked_at += 1
                if net is None and not any(pin.number in g for g in placed.part.joined):
                    open_pins.findings.append(
                        Finding("open_pins", "warning", f"{label} (power output) is unused", at)
                    )
            if pin.type in ("output", "power_out") and net is not None:
                outputs[net.name].append(label)
            if pin.type == "nc":
                nc.looked_at += 1
                if net is not None:
                    nc.findings.append(
                        Finding(
                            "nc",
                            "error",
                            f"{label} must not be connected (it is on {net.name})",
                            at,
                            [net.name],
                        )
                    )
            if net is not None:
                nets_here.append(net)

        rated_v = placed.rating("voltage_v")
        declared = [n.voltage for n in nets_here if n.voltage is not None]
        if rated_v is not None and declared:
            voltage.looked_at += 1
            worst = max(declared)
            if worst > rated_v:
                voltage.findings.append(
                    Finding(
                        "voltage",
                        "error",
                        f"{ref} ({placed.part.name}) sees {worst:g} V but is rated {rated_v:g} V",
                        centre[ref],
                    )
                )
            elif (
                placed.part.category == "passive"
                and placed.part.prefix == "C"
                and worst > rated_v / 2
            ):
                voltage.findings.append(
                    Finding(
                        "voltage",
                        "warning",
                        f"{ref} runs at {worst:g} V, over half its {rated_v:g} V rating; "
                        "ceramic capacitors lose capacitance there",
                        centre[ref],
                    )
                )
        rated_a = placed.rating("current_a")
        if placed.current is not None and rated_a is not None:
            current.looked_at += 1
            if placed.current > rated_a:
                current.findings.append(
                    Finding(
                        "part_current",
                        "error",
                        f"{ref} carries {placed.current:g} A but is rated {rated_a:g} A",
                        centre[ref],
                    )
                )

    for net, labels in outputs.items():
        if len(labels) > 1:
            pins = [lab for lab in labels]
            # Joined pins of one part (a regulator's VOUT and tab) are one output.
            refs = {lab.split(".")[0] for lab in pins}
            if len(refs) > 1:
                drivers.findings.append(
                    Finding(
                        "drivers", "error", f"{net} is driven by {', '.join(pins)}", None, [net]
                    )
                )
    return [supply, ground, drivers, open_pins, nc, voltage, current]


def run_checks(board: Board, routing: Routing) -> dict:
    items = _items(board, routing)
    drc = [
        check_clearance(board, items),
        check_edge(board, items),
        *check_tracks(board, routing),
        check_holes(board, routing),
        check_placement(board),
        check_connectivity(board, routing, items),
    ]
    erc = run_erc(board)
    results = drc + erc
    errors = sum(1 for r in results for f in r.findings if f.severity == "error")
    warnings = sum(1 for r in results for f in r.findings if f.severity == "warning")
    return {
        "status": "pass" if errors == 0 else "fail",
        "errors": errors,
        "warnings": warnings,
        "checks": [
            {
                "id": r.id,
                "label": r.label,
                "kind": r.kind,
                "status": r.status,
                "looked_at": r.looked_at,
                "findings": [asdict(f) for f in r.findings],
            }
            for r in results
        ],
    }
