"""Two-layer autorouter and copper pour.

How it works:
1. The board becomes a grid (rules.grid, 0.25 mm by default) on two layers.
2. Nets are routed one at a time: wide power nets first, then signal nets from the
   shortest up. A pour net (ground) is routed last, as short drops to its pour.
3. For each net, every other net's copper is grown by the clearance plus half this
   net's track width, so any grid cell left free is a legal place for the track's
   centre line; the same is done with the via size for places a via may go.
4. Pads are joined one at a time (like growing a minimum spanning tree): an A*
   search runs from everything already connected to the nearest pad not yet
   connected, moving in 8 directions, changing layer through a via at a cost.
5. Paths become straight track segments (collinear steps merged) that start and end
   on pad centres. Nets that fail are routed first on the next pass (three passes).
6. Finally each pour net floods its layer, keeping clear of other copper, and any
   island of pour that touches none of its pads is removed.

The design rule check (checks.py) then measures the result independently; the router
is never trusted to have got clearances right.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from jig.pcb.geometry import ipc2221_width_mm, outline, pad_shape, track_shape, via_shape
from jig.pcb.model import Board, Net, PlacedPad

LAYERS = ("top", "bottom")
SQRT2 = math.sqrt(2)
MOVES = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, SQRT2),
    (1, -1, SQRT2),
    (-1, 1, SQRT2),
    (-1, -1, SQRT2),
]


@dataclass
class Track:
    net: str
    layer: str
    points: list[tuple[float, float]]
    width: float
    current: float = 0.0  # the current this track was sized for (IPC-2221)
    sized_by: str = ""  # why that current: the net's current, or the part it feeds

    def shape(self) -> BaseGeometry:
        return track_shape(self.points, self.width)

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:], strict=False))


@dataclass
class Via:
    net: str
    x: float
    y: float
    drill: float
    diameter: float

    def shape(self) -> BaseGeometry:
        return via_shape(self.x, self.y, self.diameter)


@dataclass
class Zone:
    net: str
    layer: str
    polygon: BaseGeometry


@dataclass
class Routing:
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    unrouted: list[dict] = field(default_factory=list)
    widths: dict[str, float] = field(default_factory=dict)
    passes: int = 0
    seconds: float = 0.0


def width_for(board: Board, current: float) -> float:
    """Wide enough for the rules and for `current` (IPC-2221), on a 0.05 mm step."""
    need = ipc2221_width_mm(current, board.rules.copper_oz, board.rules.temperature_rise_c)
    return max(board.rules.track, math.ceil(need / 0.05 - 1e-9) * 0.05)


def track_width(board: Board, net: Net) -> float:
    return width_for(board, net.current)


# A branch that ends at one of these parts never carries more than the part allows.
SMALL_SIGNAL = ("passive", "indicator", "input")


def branch_current(board: Board, pad: PlacedPad, net: Net) -> tuple[float, str]:
    """The current a connection to `pad` has to carry, and why.

    The trunk of a net carries the net's full current. A branch that only feeds a
    small-signal part (a resistor, LED, capacitor, button) is sized for that part:
    its declared current, else its rated current. Connections between anything else
    stay at the full net current, which is conservative."""
    placed = board.parts[pad.ref]
    if placed.current is not None:
        return min(net.current, placed.current), f"{pad.ref} draws {placed.current:g} A"
    rated = placed.rating("current_a")
    if placed.part.category in SMALL_SIGNAL:
        if rated is not None:
            return min(net.current, rated), f"{pad.ref} is rated {rated:g} A"
        return min(net.current, 0.5), f"{pad.ref} is a small-signal part (0.5 A assumed)"
    return net.current, f"net {net.name} carries {net.current:g} A"


class _Grid:
    def __init__(self, board: Board) -> None:
        self.g = board.rules.grid
        self.nx = int(board.width / self.g) + 1
        self.ny = int(board.height / self.g) + 1
        xs = np.arange(self.nx) * self.g
        ys = np.arange(self.ny) * self.g
        self.X, self.Y = np.meshgrid(xs, ys)  # shape (ny, nx)

    def mask(self, geom: BaseGeometry | None) -> np.ndarray:
        if geom is None or geom.is_empty:
            return np.zeros((self.ny, self.nx), dtype=bool)
        shapely.prepare(geom)
        return shapely.contains_xy(geom, self.X, self.Y)

    def xy(self, ix: int, iy: int) -> tuple[float, float]:
        return round(ix * self.g, 4), round(iy * self.g, 4)


class Router:
    def __init__(self, board: Board) -> None:
        self.board = board
        self.rules = board.rules
        self.grid = _Grid(board)
        self.outline = outline(board)
        self.pads = board.pads()
        self.pad_geom = {p.name: pad_shape(p) for p in self.pads}
        self.holes = [Point(x, y).buffer(d / 2) for x, y, d in board.holes]
        self.pour_nets = {n.name: n.pour for n in board.nets.values() if n.pour}

    # ---------------------------------------------------------------- copper

    def _copper(self, routing: Routing, layer: str, exclude: str | None) -> list[BaseGeometry]:
        shapes = [
            self.pad_geom[p.name] for p in self.pads if layer in p.layers and p.net != exclude
        ]
        shapes += [t.shape() for t in routing.tracks if t.layer == layer and t.net != exclude]
        shapes += [v.shape() for v in routing.vias if v.net != exclude]
        return shapes

    def _blocked(
        self, routing: Routing, net: str, width: float
    ) -> tuple[list[np.ndarray], np.ndarray]:
        r = self.rules
        margin = self.grid.g * 0.15  # covers diagonal steps between free cell centres
        grow = r.clearance + width / 2 + margin
        inside = self.outline.buffer(-(r.edge_clearance + width / 2 + margin))
        holes = unary_union(self.holes).buffer(r.clearance + width / 2) if self.holes else None
        outside = ~self.grid.mask(inside)
        hole_mask = self.grid.mask(holes)
        layers = []
        for layer in LAYERS:
            other = unary_union(self._copper(routing, layer, net)).buffer(grow, quad_segs=4)
            layers.append(self.grid.mask(other) | outside | hole_mask)
        vgrow = r.clearance + r.via_diameter / 2 + margin
        via_inside = self.outline.buffer(-(r.edge_clearance + r.via_diameter / 2 + margin))
        via_block = ~self.grid.mask(via_inside) | hole_mask
        for layer in LAYERS:
            other = unary_union(self._copper(routing, layer, net)).buffer(vgrow, quad_segs=4)
            via_block |= self.grid.mask(other)
        return layers, via_block

    # ---------------------------------------------------------------- search

    def _pad_cells(self, pad: PlacedPad) -> list[tuple[int, int, int]]:
        g = self.grid
        geom = self.pad_geom[pad.name]
        x0, y0, x1, y1 = geom.bounds
        cells = []
        for iy in range(max(0, int(y0 / g.g)), min(g.ny, int(y1 / g.g) + 2)):
            for ix in range(max(0, int(x0 / g.g)), min(g.nx, int(x1 / g.g) + 2)):
                if geom.contains(Point(ix * g.g, iy * g.g)):
                    for layer in pad.layers:
                        cells.append((LAYERS.index(layer), ix, iy))
        if not cells:  # a pad smaller than a grid cell: use the nearest cell
            ix, iy = round(pad.x / g.g), round(pad.y / g.g)
            cells = [(LAYERS.index(layer), ix, iy) for layer in pad.layers]
        return cells

    def _search(
        self,
        sources: set[tuple[int, int, int]],
        targets: dict[tuple[int, int, int], str] | None,
        blocked: list[np.ndarray],
        via_block: np.ndarray,
        layer_cost: tuple[float, float],
        goal_layer: int | None = None,
    ) -> list[tuple[int, int, int]] | None:
        """A* from any source cell to any target cell (or, with goal_layer, to any free
        cell on that layer). Blocked cells are passable when they are sources or targets."""
        g = self.grid
        nx, ny = g.nx, g.ny
        free = [b.ravel().tolist() for b in blocked]
        via_ok = (~via_block).ravel().tolist()
        allowed = set(sources) | set(targets or ())
        goals = list({(ix, iy) for _, ix, iy in targets}) if targets else []
        via_cost = 6.0 + 2.0 * self.rules.via_diameter / g.g

        def heuristic(ix: int, iy: int) -> float:
            if not goals:
                return 0.0
            best = math.inf
            for gx, gy in goals:
                dx, dy = abs(ix - gx), abs(iy - gy)
                best = min(best, max(dx, dy) + (SQRT2 - 1) * min(dx, dy))
            return best * min(layer_cost)

        open_heap: list[tuple[float, float, tuple[int, int, int]]] = []
        cost: dict[tuple[int, int, int], float] = {}
        came: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
        for s in sources:
            cost[s] = 0.0
            came[s] = None
            heapq.heappush(open_heap, (heuristic(s[1], s[2]), 0.0, s))
        budget = 600_000
        while open_heap and budget:
            budget -= 1
            _, c, state = heapq.heappop(open_heap)
            if c > cost.get(state, math.inf):
                continue
            layer, ix, iy = state
            reached = (targets is not None and state in targets and state not in sources) or (
                goal_layer is not None and layer == goal_layer and state not in sources
            )
            if reached:
                path = [state]
                while came[path[-1]] is not None:
                    path.append(came[path[-1]])
                return path[::-1]
            step = layer_cost[layer]
            for dx, dy, length in MOVES:
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < nx and 0 <= jy < ny):
                    continue
                nxt = (layer, jx, jy)
                if free[layer][jy * nx + jx] and nxt not in allowed:
                    continue
                if dx and dy:  # no corner cutting past an obstacle
                    if free[layer][iy * nx + jx] and free[layer][jy * nx + ix]:
                        continue
                nc = c + length * step
                if nc < cost.get(nxt, math.inf):
                    cost[nxt] = nc
                    came[nxt] = state
                    heapq.heappush(open_heap, (nc + heuristic(jx, jy), nc, nxt))
            other = 1 - layer
            nxt = (other, ix, iy)
            if via_ok[iy * nx + ix] and (not free[other][iy * nx + ix] or nxt in allowed):
                nc = c + via_cost
                if nc < cost.get(nxt, math.inf):
                    cost[nxt] = nc
                    came[nxt] = state
                    heapq.heappush(open_heap, (nc + heuristic(ix, iy), nc, nxt))
        return None

    # ---------------------------------------------------------------- geometry out

    def _emit(
        self,
        routing: Routing,
        net: str,
        width: float,
        path: list[tuple[int, int, int]],
        pad_of_cell: dict[tuple[int, int, int], PlacedPad],
        current: float = 0.0,
        sized_by: str = "",
    ) -> None:
        g = self.grid
        runs: list[tuple[int, list[tuple[int, int]]]] = []
        for layer, ix, iy in path:
            if runs and runs[-1][0] == layer:
                runs[-1][1].append((ix, iy))
            else:
                if runs:
                    x, y = g.xy(ix, iy)
                    routing.vias.append(
                        Via(net, x, y, self.rules.via_drill, self.rules.via_diameter)
                    )
                runs.append((layer, [(ix, iy)]))
        for i, (layer, cells) in enumerate(runs):
            points = [g.xy(ix, iy) for ix, iy in _simplify(cells)]
            start = pad_of_cell.get((layer, *cells[0])) if i == 0 else None
            end = pad_of_cell.get((layer, *cells[-1])) if i == len(runs) - 1 else None
            if start is not None:
                points.insert(0, (start.x, start.y))
            if end is not None:
                points.append((end.x, end.y))
            points = _dedupe(points)
            routing.tracks.append(Track(net, LAYERS[layer], points, width, current, sized_by))

    # ---------------------------------------------------------------- nets

    def _connection(self, net: Net, pads: list[PlacedPad]) -> tuple[float, float, str]:
        """Width, design current and reason for a connection touching these pads: the
        smallest branch current among them, capped by the smallest pad (a track can't be
        wider than the pad it lands on; the current check then catches a pad too small)."""
        current, why = min((branch_current(self.board, p, net) for p in pads), key=lambda c: c[0])
        width = width_for(self.board, current)
        narrowest = min(min(p.w, p.h) for p in pads)
        if width > narrowest:
            width = max(self.rules.track, math.floor(narrowest / 0.05) * 0.05)
            why += f"; narrowed to the {narrowest:g} mm pad"
        return width, current, why

    def _route_net(self, routing: Routing, net: Net) -> None:
        width = track_width(self.board, net)
        routing.widths[net.name] = width
        pads = [p for p in self.pads if p.net == net.name]
        pour_layer = self.pour_nets.get(net.name)
        if pour_layer:
            # Pads already on the pour layer join through the pour; the rest drop a via.
            pads = [p for p in pads if pour_layer not in p.layers]
        if not pads or (len(pads) < 2 and not pour_layer):
            return
        blocked, via_block = self._blocked(routing, net.name, width)
        bottom_pour = any(layer == "bottom" for layer in self.pour_nets.values())
        layer_cost = (1.0, 2.0 if bottom_pour and net.name not in self.pour_nets else 1.15)
        cells = {p.name: self._pad_cells(p) for p in pads}
        pad_of_cell = {cell: p for p in pads for cell in cells[p.name]}

        if pour_layer:
            goal = LAYERS.index(pour_layer)
            for pad in pads:
                w, current, why = self._connection(net, [pad])
                blocked, via_block = self._blocked(routing, net.name, w)
                path = self._search(
                    set(cells[pad.name]), None, blocked, via_block, layer_cost, goal
                )
                if path is None:
                    routing.unrouted.append(
                        {"net": net.name, "from": pad.name, "to": f"{pour_layer} pour"}
                    )
                else:
                    self._emit(routing, net.name, w, path, pad_of_cell, current, why)
            return

        # Trunk first: the pads that carry the net's full current, joined at full width.
        # Then every other pad gets its own branch, sized for its own current, joined to
        # the trunk only (never to another branch, which would then carry both currents).
        heavy = [p for p in pads if branch_current(self.board, p, net)[0] >= net.current - 1e-9]
        if not heavy:
            heavy = [max(pads, key=lambda p: branch_current(self.board, p, net)[0])]
        light = [p for p in pads if p not in heavy]
        heavy.sort(key=lambda p: (p.x, p.y))
        connected = {heavy[0].name}
        trunk = set(cells[heavy[0].name])
        by_name = {p.name: p for p in pads}
        why = f"net {net.name} carries {net.current:g} A"
        while len(connected) < len(heavy):
            targets = {c: p.name for p in heavy if p.name not in connected for c in cells[p.name]}
            path = self._search(trunk, targets, blocked, via_block, layer_cost)
            if path is None:
                for p in heavy:
                    if p.name not in connected:
                        routing.unrouted.append(
                            {"net": net.name, "from": heavy[0].name, "to": p.name}
                        )
                break
            reached = by_name[targets[path[-1]]]
            w = min(
                width, max(self.rules.track, math.floor(min(reached.w, reached.h) / 0.05) * 0.05)
            )
            note = (
                why
                if w == width
                else f"{why}; narrowed to the {min(reached.w, reached.h):g} mm pad"
            )
            self._emit(routing, net.name, w, path, pad_of_cell, net.current, note)
            connected.add(reached.name)
            trunk |= set(path) | set(cells[reached.name])

        masks: dict[float, tuple] = {width: (blocked, via_block)}
        for pad in sorted(light, key=lambda p: -branch_current(self.board, p, net)[0]):
            w, current, note = self._connection(net, [pad])
            if w not in masks:
                masks[w] = self._blocked(routing, net.name, w)
            b, v = masks[w]
            path = self._search(set(cells[pad.name]), {c: "trunk" for c in trunk}, b, v, layer_cost)
            if path is None:
                routing.unrouted.append(
                    {"net": net.name, "from": pad.name, "to": f"{net.name} trunk"}
                )
                continue
            self._emit(routing, net.name, w, path, pad_of_cell, current, note)

    def _order(self, first: list[str]) -> list[Net]:
        def key(net: Net) -> tuple:
            pads = [p for p in self.pads if p.net == net.name]
            xs = [p.x for p in pads] or [0]
            ys = [p.y for p in pads] or [0]
            span = (max(xs) - min(xs)) + (max(ys) - min(ys))
            return (
                net.name not in first,
                net.name in self.pour_nets,
                -track_width(self.board, net),
                span,
            )

        return sorted(self.board.nets.values(), key=key)

    def _pour(self, routing: Routing) -> None:
        r = self.rules
        for net_name, layer in self.pour_nets.items():
            area = self.outline.buffer(-r.edge_clearance)
            others = unary_union(self._copper(routing, layer, net_name))
            if not others.is_empty:
                area = area.difference(others.buffer(r.clearance, quad_segs=6))
            if self.holes:
                area = area.difference(unary_union(self.holes).buffer(r.clearance))
            # Remove slivers narrower than a track: they etch badly.
            area = area.buffer(-r.track / 2).buffer(r.track / 2)
            mine = [
                self.pad_geom[p.name] for p in self.pads if p.net == net_name and layer in p.layers
            ]
            mine += [v.shape() for v in routing.vias if v.net == net_name]
            mine += [t.shape() for t in routing.tracks if t.net == net_name and t.layer == layer]
            anchor = unary_union(mine) if mine else None
            parts = list(getattr(area, "geoms", [area]))
            keep = [p for p in parts if anchor is not None and p.intersects(anchor)]
            if keep:
                routing.zones.append(Zone(net_name, layer, unary_union(keep)))

    def route(self) -> Routing:
        started = time.monotonic()
        best: Routing | None = None
        first: list[str] = []
        for attempt in range(3):
            routing = Routing(passes=attempt + 1)
            for net in self._order(first):
                self._route_net(routing, net)
            if best is None or len(routing.unrouted) < len(best.unrouted):
                best = routing
            if not routing.unrouted:
                break
            failed = list(dict.fromkeys(u["net"] for u in routing.unrouted))
            first = failed + [n for n in first if n not in failed]
        assert best is not None
        self._pour(best)
        best.seconds = round(time.monotonic() - started, 2)
        return best


def _simplify(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(cells) <= 2:
        return cells
    out = [cells[0]]
    for prev, cur, nxt in zip(cells, cells[1:], cells[2:], strict=False):
        if (cur[0] - prev[0], cur[1] - prev[1]) != (nxt[0] - cur[0], nxt[1] - cur[1]):
            out.append(cur)
    out.append(cells[-1])
    return out


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in points:
        if not out or math.dist(out[-1], p) > 1e-6:
            out.append(p)
    return out


def route_board(board: Board) -> Routing:
    return Router(board).route()
