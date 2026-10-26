"""A board: outline, placed parts, nets, and the design rules they must meet."""

from __future__ import annotations

from dataclasses import dataclass, field

from jig.cad.program import Param
from jig.pcb.footprints import Pad
from jig.pcb.library import PartDef

NET_KINDS = ("signal", "power", "ground")


@dataclass(frozen=True)
class Rules:
    """Design rules. Defaults sit inside the standard 2-layer capability of common fabs
    (JLCPCB: 0.127 mm track/space, 0.3 mm drill), with margin for hobby boards."""

    clearance: float = 0.2
    track: float = 0.25
    via_drill: float = 0.4
    via_diameter: float = 0.8
    edge_clearance: float = 0.5
    min_drill: float = 0.3
    min_annular_ring: float = 0.13
    copper_oz: float = 1.0
    temperature_rise_c: float = 10.0
    grid: float = 0.25


@dataclass(frozen=True)
class PlacedPad:
    """A pad in board coordinates, after the part's position and rotation."""

    ref: str
    pad: Pad
    x: float
    y: float
    w: float
    h: float
    net: str | None

    @property
    def through_hole(self) -> bool:
        return self.pad.drill is not None

    @property
    def layers(self) -> tuple[str, ...]:
        return ("top", "bottom") if self.through_hole else ("top",)

    @property
    def name(self) -> str:
        return f"{self.ref}.{self.pad.number}"


@dataclass
class PlacedPart:
    ref: str
    part: PartDef
    x: float
    y: float
    rotation: int = 0  # degrees, a multiple of 90
    value: str = ""
    label: str = ""
    ratings: dict[str, float] = field(default_factory=dict)  # overrides the library's
    current: float | None = None  # amps the part carries, checked against its rating

    def place(self, lx: float, ly: float) -> tuple[float, float]:
        r = self.rotation % 360
        x, y = {0: (lx, ly), 90: (-ly, lx), 180: (-lx, -ly), 270: (ly, -lx)}[r]
        return self.x + x, self.y + y

    def size(self, w: float, h: float) -> tuple[float, float]:
        return (h, w) if self.rotation % 180 == 90 else (w, h)

    def courtyard(self) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.part.footprint.courtyard
        (ax, ay), (bx, by) = self.place(x0, y0), self.place(x1, y1)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    def rating(self, key: str) -> float | None:
        return self.ratings.get(key, self.part.ratings.get(key))


@dataclass
class Net:
    name: str
    pins: list[tuple[str, str]]  # (ref, pad number)
    kind: str = "signal"
    voltage: float | None = None
    current: float = 0.1  # amps the net must carry continuously
    pour: str | None = None  # layer to flood with this net ("bottom" for ground, usually)


@dataclass
class Board:
    name: str
    description: str
    width: float
    height: float
    thickness: float
    corner_radius: float
    parts: dict[str, PlacedPart]
    nets: dict[str, Net]
    rules: Rules
    params: list[Param] = field(default_factory=list)
    holes: list[tuple[float, float, float]] = field(default_factory=list)  # x, y, drill (NPTH)

    def pads(self) -> list[PlacedPad]:
        net_of = {(ref, pin): net.name for net in self.nets.values() for ref, pin in net.pins}
        out = []
        for ref, placed in self.parts.items():
            for pad in placed.part.footprint.pads:
                x, y = placed.place(pad.x, pad.y)
                w, h = placed.size(pad.w, pad.h)
                net = net_of.get((ref, pad.number))
                if net is None:  # a pin joined inside the part follows its partner's net
                    for group in placed.part.joined:
                        if pad.number in group:
                            net = next(
                                (net_of[(ref, p)] for p in group if (ref, p) in net_of), None
                            )
                out.append(PlacedPad(ref, pad, x, y, w, h, net))
        return out
