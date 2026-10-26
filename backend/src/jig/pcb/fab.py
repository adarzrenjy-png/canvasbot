"""Fabrication outputs: Gerber (RS-274X), Excellon drill, BOM and pick-and-place.

What a board house needs to make and assemble the board, in the formats JLCPCB and
most other fabs accept:

    <name>-F_Cu.gtl  <name>-B_Cu.gbl        copper, top and bottom
    <name>-F_Mask.gts <name>-B_Mask.gbs     solder mask openings
    <name>-F_Paste.gtp                      stencil openings for top SMD pads
    <name>-F_Silkscreen.gto                 part outlines, pin 1 marks, references
    <name>-Edge_Cuts.gm1                    board outline
    <name>-PTH.drl  <name>-NPTH.drl         plated and unplated holes (Excellon)
    <name>-BOM.csv  <name>-CPL.csv          JLCPCB assembly files

Coordinates are millimetres, 4.6 format, absolute, origin at the board's lower-left.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import UTC, datetime

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from jig import __version__
from jig.pcb.font import text_strokes
from jig.pcb.geometry import outline, pad_shape
from jig.pcb.model import Board, PlacedPad
from jig.pcb.router import Routing

MASK_EXPANSION = 0.05
SILK_WIDTH = 0.15
SILK_PAD_GAP = 0.15


def _n(mm: float) -> str:
    return str(round(mm * 1_000_000))


class Gerber:
    def __init__(self, function: str, polarity: str = "Positive") -> None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        self.lines = [
            f"%TF.GenerationSoftware,Jig,Jig,{__version__}*%",
            f"%TF.CreationDate,{stamp}*%",
            f"%TF.FileFunction,{function}*%",
            f"%TF.FilePolarity,{polarity}*%",
            "%FSLAX46Y46*%",
            "%MOMM*%",
            "%LPD*%",
            "G01*",
        ]
        self.apertures: dict[tuple, int] = {}
        self.body: list[str] = []
        self.current: int | None = None

    def _aperture(self, kind: str, *dims: float) -> int:
        key = (kind, *(round(d, 4) for d in dims))
        if key not in self.apertures:
            code = 10 + len(self.apertures)
            self.apertures[key] = code
            sizes = "X".join(f"{d:.4f}" for d in dims)
            self.lines.append(f"%ADD{code}{kind},{sizes}*%")
        return self.apertures[key]

    def _use(self, code: int) -> None:
        if code != self.current:
            self.body.append(f"D{code}*")
            self.current = code

    def flash_pad(self, pad: PlacedPad, grow: float = 0.0) -> None:
        w, h = pad.w + 2 * grow, pad.h + 2 * grow
        if pad.pad.shape == "circle":
            code = self._aperture("C", max(w, h))
        elif pad.pad.shape == "oval":
            code = self._aperture("O", w, h)
        else:
            code = self._aperture("R", w, h)
        self._use(code)
        self.body.append(f"X{_n(pad.x)}Y{_n(pad.y)}D03*")

    def flash_circle(self, x: float, y: float, diameter: float) -> None:
        self._use(self._aperture("C", diameter))
        self.body.append(f"X{_n(x)}Y{_n(y)}D03*")

    def draw(self, points: list[tuple[float, float]], width: float) -> None:
        if len(points) < 2:
            if points:
                self.flash_circle(*points[0], width)
            return
        self._use(self._aperture("C", width))
        x, y = points[0]
        self.body.append(f"X{_n(x)}Y{_n(y)}D02*")
        for x, y in points[1:]:
            self.body.append(f"X{_n(x)}Y{_n(y)}D01*")

    def region(self, polygon: Polygon) -> None:
        """A filled polygon; its holes are cut with clear polarity."""
        self._ring(list(polygon.exterior.coords))
        if polygon.interiors:
            self.body.append("%LPC*%")
            for ring in polygon.interiors:
                self._ring(list(ring.coords))
            self.body.append("%LPD*%")

    def _ring(self, coords: list[tuple[float, float]]) -> None:
        self.body.append("G36*")
        x, y = coords[0]
        self.body.append(f"X{_n(x)}Y{_n(y)}D02*")
        for x, y in coords[1:]:
            self.body.append(f"X{_n(x)}Y{_n(y)}D01*")
        self.body.append("G37*")

    def text(self) -> str:
        return "\n".join(self.lines + self.body + ["M02*", ""])


def _copper(board: Board, routing: Routing, layer: str, function: str) -> str:
    g = Gerber(function)
    for zone in routing.zones:  # pours first: their clearance holes are cut before pads land
        if zone.layer == layer:
            for poly in getattr(zone.polygon, "geoms", [zone.polygon]):
                g.region(poly)
    for track in routing.tracks:
        if track.layer == layer:
            g.draw(track.points, track.width)
    for pad in board.pads():
        if layer in pad.layers:
            g.flash_pad(pad)
    for via in routing.vias:
        g.flash_circle(via.x, via.y, via.diameter)
    return g.text()


def _mask(board: Board, layer: str, function: str) -> str:
    g = Gerber(function, "Negative")  # openings; vias stay tented under the mask
    for pad in board.pads():
        if layer in pad.layers:
            g.flash_pad(pad, MASK_EXPANSION)
    return g.text()


def _paste(board: Board) -> str:
    g = Gerber("Paste,Top")
    for pad in board.pads():
        if not pad.through_hole:
            g.flash_pad(pad)
    return g.text()


def _silk(board: Board) -> str:
    g = Gerber("Legend,Top")
    keep_out = unary_union(
        [pad_shape(p).buffer(SILK_PAD_GAP + SILK_WIDTH / 2) for p in board.pads()]
    )
    inside = outline(board).buffer(-0.2)

    def clipped(line: LineString) -> None:
        visible = line.difference(keep_out).intersection(inside)
        for piece in getattr(visible, "geoms", [visible]):
            if not piece.is_empty and piece.geom_type == "LineString":
                g.draw(list(piece.coords), SILK_WIDTH)

    for ref, placed in board.parts.items():
        if placed.part.category == "mechanical":
            continue
        fp = placed.part.footprint
        bw, bh = fp.body
        corners = [(-bw / 2, -bh / 2), (bw / 2, -bh / 2), (bw / 2, bh / 2), (-bw / 2, bh / 2)]
        world = [placed.place(*c) for c in corners]
        clipped(LineString(world + [world[0]]))
        if fp.pin1 is not None:
            x, y = placed.place(*fp.pin1)
            if not keep_out.contains(LineString([(x, y), (x + 0.01, y)])):
                g.flash_circle(x, y, 0.5)
        x0, y0, x1, y1 = placed.courtyard()
        for stroke in text_strokes(ref, (x0 + x1) / 2, y1 + 0.35, 1.0):
            clipped(LineString(stroke) if len(stroke) > 1 else LineString([stroke[0], stroke[0]]))
    return g.text()


def _edge(board: Board) -> str:
    g = Gerber("Profile,NP")
    g.draw(list(outline(board).exterior.coords), 0.1)
    return g.text()


def _drill(holes: list[tuple[float, float, float]], plated: bool) -> str:
    by_size: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for x, y, d in holes:
        by_size[round(d, 3)].append((x, y))
    lines = [
        "M48",
        f"; DRILL file {{Jig {__version__}}} {'plated' if plated else 'non-plated'} holes",
        "; FORMAT={-:-/ absolute / metric / decimal}",
        f"; #@! TF.FileFunction,{'Plated' if plated else 'NonPlated'},1,2,"
        f"{'PTH' if plated else 'NPTH'}",
        "FMAT,2",
        "METRIC",
    ]
    tools = sorted(by_size)
    for i, d in enumerate(tools, start=1):
        lines.append(f"T{i}C{d:.3f}")
    lines += ["%", "G90", "G05"]
    for i, d in enumerate(tools, start=1):
        lines.append(f"T{i}")
        lines += [f"X{x:.3f}Y{y:.3f}" for x, y in by_size[d]]
    lines += ["M30", ""]
    return "\n".join(lines)


def _natural(ref: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref))


def bom_rows(board: Board) -> list[dict]:
    groups: dict[tuple, list[str]] = defaultdict(list)
    for ref, placed in board.parts.items():
        if placed.part.category == "mechanical":
            continue
        groups[(placed.part.id, placed.value or placed.part.value)].append(ref)
    rows = []
    for (_part_id, value), refs in sorted(
        groups.items(), key=lambda kv: _natural(sorted(kv[1], key=_natural)[0])
    ):
        part = board.parts[refs[0]].part
        rows.append(
            {
                "Comment": value or part.name,
                "Designator": ",".join(sorted(refs, key=_natural)),
                "Footprint": part.footprint.name,
                "LCSC Part #": part.lcsc or "",
                "Quantity": len(refs),
                "Description": part.description,
            }
        )
    return rows


def _csv(rows: list[dict], fields: list[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def fab_files(board: Board, routing: Routing, name: str = "board") -> dict[str, str]:
    pads = board.pads()
    pth = [(p.x, p.y, p.pad.drill) for p in pads if p.through_hole and p.pad.plated]
    pth += [(v.x, v.y, v.drill) for v in routing.vias]
    npth = [(p.x, p.y, p.pad.drill) for p in pads if p.through_hole and not p.pad.plated]
    npth += list(board.holes)
    cpl = [
        {
            "Designator": ref,
            "Mid X": f"{p.x:.3f}mm",
            "Mid Y": f"{p.y:.3f}mm",
            "Layer": "Top",
            "Rotation": p.rotation % 360,
        }
        for ref, p in sorted(board.parts.items(), key=lambda kv: _natural(kv[0]))
        if p.part.category != "mechanical"
    ]
    files = {
        f"{name}-F_Cu.gtl": _copper(board, routing, "top", "Copper,L1,Top"),
        f"{name}-B_Cu.gbl": _copper(board, routing, "bottom", "Copper,L2,Bot"),
        f"{name}-F_Mask.gts": _mask(board, "top", "Soldermask,Top"),
        f"{name}-B_Mask.gbs": _mask(board, "bottom", "Soldermask,Bot"),
        f"{name}-F_Paste.gtp": _paste(board),
        f"{name}-F_Silkscreen.gto": _silk(board),
        f"{name}-Edge_Cuts.gm1": _edge(board),
        f"{name}-PTH.drl": _drill(pth, True),
        f"{name}-NPTH.drl": _drill(npth, False),
        f"{name}-BOM.csv": _csv(
            bom_rows(board),
            ["Comment", "Designator", "Footprint", "LCSC Part #", "Quantity", "Description"],
        ),
        f"{name}-CPL.csv": _csv(cpl, ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]),
    }
    files["README.txt"] = (
        f"{board.name}: fabrication files made by Jig {__version__}\n\n"
        f"Board {board.width:g} x {board.height:g} mm, {board.thickness:g} mm thick, 2 layers, "
        f"{board.rules.copper_oz:g} oz copper.\n"
        "Units mm; Gerber RS-274X 4.6 format; drill files Excellon, metric, decimal.\n"
        "Assembly (JLCPCB): upload the BOM and CPL. LCSC numbers are suggestions; check stock\n"
        "and part details, and check every part's rotation in the assembly preview.\n"
    )
    return files


def fab_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()
