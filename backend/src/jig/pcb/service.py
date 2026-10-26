"""Designs a board end to end: parse, route, check, draw, and write the fab files."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jig.pcb.checks import run_checks
from jig.pcb.fab import bom_rows, fab_files, fab_zip
from jig.pcb.geometry import ipc2221_current_a, ipc2221_width_mm
from jig.pcb.model import Board
from jig.pcb.model3d import board_part_program
from jig.pcb.program import parse_board
from jig.pcb.render import board_svg
from jig.pcb.router import Routing, route_board
from jig.pcb.schematic import schematic_svg


def _nets(board: Board, routing: Routing) -> list[dict[str, Any]]:
    out = []
    for net in board.nets.values():
        tracks = [t for t in routing.tracks if t.net == net.name]
        need = ipc2221_width_mm(net.current, board.rules.copper_oz, board.rules.temperature_rise_c)
        widest = max((t.width for t in tracks), default=None)
        busiest = max(tracks, key=lambda t: (t.current, t.width), default=None)
        out.append(
            {
                "name": net.name,
                "kind": net.kind,
                "voltage": net.voltage,
                "current": net.current,
                "pins": [f"{r}.{p}" for r, p in net.pins],
                "pour": net.pour,
                "ipc_width_mm": need,
                "widest_mm": widest,
                "widest_carries_a": ipc2221_current_a(
                    widest, board.rules.copper_oz, board.rules.temperature_rise_c
                )
                if widest
                else None,
                "busiest": None
                if busiest is None
                else {
                    "current": busiest.current,
                    "width": busiest.width,
                    "sized_by": busiest.sized_by,
                    "capacity": ipc2221_current_a(
                        busiest.width, board.rules.copper_oz, board.rules.temperature_rise_c
                    ),
                },
                "length_mm": round(sum(t.length for t in tracks), 1),
                "vias": sum(1 for v in routing.vias if v.net == net.name),
            }
        )
    return out


def _parts(board: Board) -> list[dict[str, Any]]:
    return [
        {
            "ref": ref,
            "part": p.part.id,
            "name": p.part.name,
            "value": p.value,
            "category": p.part.category,
            "x": p.x,
            "y": p.y,
            "rotation": p.rotation,
            "footprint": p.part.footprint.name,
            "footprint_source": p.part.footprint.source,
            "lcsc": p.part.lcsc,
            "source": p.part.source,
            "label": p.label,
        }
        for ref, p in board.parts.items()
    ]


class BoardService:
    def __init__(self, boards_dir: Path, keep: int = 30) -> None:
        self.dir = boards_dir.resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep = keep

    def design(self, code: str) -> dict[str, Any]:
        board = parse_board(code)
        routing = route_board(board)
        checks = run_checks(board, routing)
        board_id = uuid.uuid4().hex[:12]
        out = self.dir / board_id
        out.mkdir()
        name = "".join(c if c.isalnum() else "_" for c in board.name.lower()).strip("_") or "board"
        files = fab_files(board, routing, name)
        (out / "board.py").write_text(code, encoding="utf-8")
        (out / "fab.zip").write_bytes(fab_zip(files))
        track_len = sum(t.length for t in routing.tracks)
        payload = {
            "id": board_id,
            "code": code,
            "name": board.name,
            "description": board.description,
            "params": [asdict(p) for p in board.params],
            "board": {
                "width": board.width,
                "height": board.height,
                "thickness": board.thickness,
                "layers": 2,
                "copper_oz": board.rules.copper_oz,
            },
            "rules": asdict(board.rules),
            "parts": _parts(board),
            "nets": _nets(board, routing),
            "routing": {
                "tracks": len(routing.tracks),
                "vias": len(routing.vias),
                "length_mm": round(track_len, 1),
                "passes": routing.passes,
                "seconds": routing.seconds,
                "unrouted": routing.unrouted,
                "routed_nets": len(board.nets) - len({u["net"] for u in routing.unrouted}),
                "nets": len(board.nets),
            },
            "checks": checks,
            "svg": board_svg(board, routing),
            "schematic": schematic_svg(board),
            "bom": bom_rows(board),
            "fab_files": sorted(files),
            "model3d_code": board_part_program(board),
        }
        (out / "board.json").write_text(json.dumps(payload), encoding="utf-8")
        self._prune()
        return payload

    def load(self, board_id: str) -> dict[str, Any] | None:
        if not board_id.isalnum():
            return None
        path = self.dir / board_id / "board.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def path_for(self, board_id: str, filename: str) -> Path | None:
        if not board_id.isalnum():
            return None
        path = self.dir / board_id / filename
        return path if path.is_file() else None

    def _prune(self) -> None:
        dirs = sorted(
            (p for p in self.dir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime
        )
        for old in dirs[: max(0, len(dirs) - self.keep)]:
            shutil.rmtree(old, ignore_errors=True)
