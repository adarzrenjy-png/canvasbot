"""Footprints (land patterns) generated from package dimensions.

Pad sizes follow IPC-7351 nominal-density practice for each package family; the
numbers are standard package geometry, written here from the formulas and common
values, not copied from any footprint library. Coordinates are millimetres in the
part's own frame: +x right, +y up, origin at the package centre. Pin 1 is marked.

Every generator records where its dimensions come from, and the board report
repeats that, so anyone can check a footprint against the datasheet before ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pad:
    number: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "rect"  # rect | circle | oval
    drill: float | None = None  # set for through-hole pads (plated)
    plated: bool = True

    @property
    def through_hole(self) -> bool:
        return self.drill is not None


@dataclass(frozen=True)
class Footprint:
    name: str
    pads: tuple[Pad, ...]
    body: tuple[float, float]  # package outline width (x) and height (y)
    height: float  # how tall the part stands off the board, for 3D and enclosures
    source: str
    courtyard_margin: float = 0.25
    pin1: tuple[float, float] | None = None  # silkscreen marker position
    keepout: tuple[tuple[float, float, float, float], ...] = field(default_factory=tuple)

    @property
    def courtyard(self) -> tuple[float, float, float, float]:
        """(x0, y0, x1, y1) around body and pads, plus the margin."""
        xs = [p.x - p.w / 2 for p in self.pads] + [p.x + p.w / 2 for p in self.pads]
        ys = [p.y - p.h / 2 for p in self.pads] + [p.y + p.h / 2 for p in self.pads]
        bw, bh = self.body
        m = self.courtyard_margin
        return (
            min(xs + [-bw / 2]) - m,
            min(ys + [-bh / 2]) - m,
            max(xs + [bw / 2]) + m,
            max(ys + [bh / 2]) + m,
        )

    def pad(self, number: str) -> Pad:
        for pad in self.pads:
            if pad.number == number:
                return pad
        raise KeyError(f"{self.name} has no pad {number!r}")


IPC = "IPC-7351 nominal land pattern for the package"

# Two-terminal chip packages: (pad width x, pad height y, pad centre x, body w, body h, height)
CHIP = {
    "0402": (0.6, 0.65, 0.5, 1.0, 0.5, 0.35),
    "0603": (0.9, 0.95, 0.8, 1.6, 0.8, 0.45),
    "0805": (1.0, 1.45, 0.95, 2.0, 1.25, 0.6),
    "1206": (1.15, 1.8, 1.45, 3.2, 1.6, 0.6),
}


def chip(size: str) -> Footprint:
    w, h, x, bw, bh, height = CHIP[size]
    return Footprint(
        name=f"chip_{size}",
        pads=(Pad("1", -x, 0, w, h), Pad("2", x, 0, w, h)),
        body=(bw, bh),
        height=height,
        source=f"{IPC}: {size} (imperial) chip",
        pin1=(-x - w / 2 - 0.3, 0),
    )


def sot23(pins: int = 3) -> Footprint:
    w, h, x = 1.3, 0.6, 1.1 if pins == 3 else 1.2
    if pins == 3:
        pads = (Pad("1", -x, 0.95, w, h), Pad("2", -x, -0.95, w, h), Pad("3", x, 0, w, h))
    elif pins == 5:
        pads = (
            Pad("1", -x, 0.95, w, h),
            Pad("2", -x, 0, w, h),
            Pad("3", -x, -0.95, w, h),
            Pad("4", x, -0.95, w, h),
            Pad("5", x, 0.95, w, h),
        )
    else:
        raise ValueError("SOT-23 comes with 3 or 5 pins here")
    return Footprint(
        name=f"sot23_{pins}",
        pads=pads,
        body=(1.6, 2.9),
        height=1.1,
        source=f"{IPC}: SOT-23-{pins}, 0.95 mm pitch",
        pin1=(-x - 0.9, 0.95),
    )


def sot223() -> Footprint:
    small = [Pad(str(i + 1), -2.3 + 2.3 * i, -3.15, 1.0, 2.0) for i in range(3)]
    return Footprint(
        name="sot223",
        pads=(*small, Pad("4", 0, 3.15, 3.6, 2.0)),
        body=(6.5, 3.5),
        height=1.8,
        source=f"{IPC}: SOT-223, 2.3 mm pitch, tab pad 4",
        pin1=(-2.3, -4.5),
    )


def soic(pins: int) -> Footprint:
    if pins % 2:
        raise ValueError("SOIC has an even pin count")
    per_side = pins // 2
    top = (per_side - 1) * 1.27 / 2
    pads = [Pad(str(i + 1), -2.7, top - i * 1.27, 1.95, 0.6) for i in range(per_side)]
    pads += [Pad(str(per_side + i + 1), 2.7, -top + i * 1.27, 1.95, 0.6) for i in range(per_side)]
    return Footprint(
        name=f"soic{pins}",
        pads=tuple(pads),
        body=(3.9, per_side * 1.27 + 0.4),
        height=1.75,
        source=f"{IPC}: SOIC-{pins}, 1.27 mm pitch, 3.9 mm body",
        pin1=(-3.9, top + 0.6),
    )


def sma() -> Footprint:
    return Footprint(
        name="sma",
        pads=(Pad("1", -2.0, 0, 2.5, 1.7), Pad("2", 2.0, 0, 2.5, 1.7)),
        body=(4.3, 2.6),
        height=2.3,
        source=f"{IPC}: DO-214AC (SMA); pad 1 is the cathode",
        pin1=(-3.6, 0),
    )


def header(pins: int, pitch: float = 2.54, drill: float = 1.0, pad: float = 1.7) -> Footprint:
    """Single row, pin 1 at the top, running down (-y)."""
    top = (pins - 1) * pitch / 2
    pads = tuple(
        Pad(str(i + 1), 0, top - i * pitch, pad, pad, "rect" if i == 0 else "circle", drill)
        for i in range(pins)
    )
    return Footprint(
        name=f"header_1x{pins}_{pitch:g}",
        pads=pads,
        body=(pitch, pins * pitch),
        height=8.5,
        source=f"Through-hole pin header, {pitch} mm pitch, {drill} mm drill",
        pin1=(-1.6, top),
    )


def jst(series: str, pins: int) -> Footprint:
    pitch, drill, pw, ph, depth, height = {
        "XH": (2.5, 0.95, 1.7, 2.0, 5.75, 7.0),
        "PH": (2.0, 0.75, 1.2, 1.75, 4.5, 6.0),
    }[series]
    left = -(pins - 1) * pitch / 2
    pads = tuple(
        Pad(str(i + 1), left + i * pitch, 0, pw, ph, "rect" if i == 0 else "oval", drill)
        for i in range(pins)
    )
    return Footprint(
        name=f"jst_{series.lower()}_{pins}",
        pads=pads,
        body=(pins * pitch + 2.4, depth),
        height=height,
        source=f"JST {series} series top-entry header, {pitch} mm pitch (JST datasheet)",
        pin1=(left, -depth / 2 - 0.6),
    )


def terminal(pins: int, pitch: float = 5.08) -> Footprint:
    left = -(pins - 1) * pitch / 2
    pads = tuple(
        Pad(str(i + 1), left + i * pitch, 0, 2.6, 2.6, "rect" if i == 0 else "circle", 1.3)
        for i in range(pins)
    )
    return Footprint(
        name=f"terminal_{pins}_{pitch:g}",
        pads=pads,
        body=(pins * pitch, 8.0),
        height=10.0,
        source=f"Screw terminal block, {pitch} mm pitch, 1.3 mm drill",
        pin1=(left, -4.6),
    )


def tactile_6mm() -> Footprint:
    pads = (
        Pad("1", -3.25, 2.25, 2.0, 2.0, "circle", 1.0),
        Pad("2", 3.25, 2.25, 2.0, 2.0, "circle", 1.0),
        Pad("3", -3.25, -2.25, 2.0, 2.0, "circle", 1.0),
        Pad("4", 3.25, -2.25, 2.0, 2.0, "circle", 1.0),
    )
    return Footprint(
        name="tactile_6mm",
        pads=pads,
        body=(6.0, 6.0),
        height=5.0,
        source="6 x 6 mm through-hole tactile switch; pins 1-2 and 3-4 are joined inside",
    )


def mount_hole(drill: float = 3.2, pad: float = 5.6) -> Footprint:
    return Footprint(
        name=f"mount_hole_{drill:g}",
        pads=(Pad("1", 0, 0, pad, pad, "circle", drill),),
        body=(pad, pad),
        height=0.0,
        source=f"Plated mounting hole, {drill} mm (M3 clearance)",
    )


def pico_module() -> Footprint:
    """Raspberry Pi Pico soldered on 2.54 mm headers: two rows of 20, 17.78 mm apart."""
    top = 19 * 2.54 / 2
    pads = []
    for i in range(20):
        y = top - i * 2.54
        pads.append(Pad(str(i + 1), -8.89, y, 1.7, 1.7, "rect" if i == 0 else "circle", 1.0))
    for i in range(20):
        y = -top + i * 2.54
        pads.append(Pad(str(21 + i), 8.89, y, 1.7, 1.7, "circle", 1.0))
    return Footprint(
        name="raspberry_pi_pico",
        pads=tuple(pads),
        body=(21.0, 51.0),
        height=12.0,
        source="Raspberry Pi Pico datasheet: 21 x 51 mm board, 2.54 mm pins, rows 17.78 mm apart",
        pin1=(-10.4, top),
    )
