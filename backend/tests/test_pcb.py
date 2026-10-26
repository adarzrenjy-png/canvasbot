"""PCB: parsing, footprints, routing, and that the checks catch real faults."""

from __future__ import annotations

import pytest

from jig.cad.program import ProgramError, set_params
from jig.pcb import footprints as fp
from jig.pcb.checks import run_checks
from jig.pcb.geometry import ipc2221_current_a, ipc2221_width_mm
from jig.pcb.program import parse_board
from jig.pcb.router import Track, route_board
from jig.pcb.samples import PICO_SERVO


@pytest.fixture(scope="module")
def routed():
    board = parse_board(PICO_SERVO)
    return board, route_board(board)


def statuses(result: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in result["checks"]}


# ---------------------------------------------------------------- basics


def test_ipc2221_matches_published_calculators() -> None:
    # 1 A, 10 °C rise, 1 oz outer layer: about 0.30 mm (11.8 mil) in standard calculators.
    assert ipc2221_width_mm(1.0) == pytest.approx(0.30, abs=0.01)
    assert ipc2221_current_a(ipc2221_width_mm(2.5)) == pytest.approx(2.5, rel=1e-6)
    assert ipc2221_width_mm(3.0, copper_oz=2.0) < ipc2221_width_mm(3.0)


def test_footprints_follow_package_geometry() -> None:
    soic8 = fp.soic(8)
    assert [p.number for p in soic8.pads] == [str(i) for i in range(1, 9)]
    assert soic8.pad("1").x < 0 and soic8.pad("8").x > 0  # pin 1 top-left, 8 top-right
    assert soic8.pad("1").y == pytest.approx(soic8.pad("8").y)
    pico = fp.pico_module()
    assert pico.pad("1").x == pytest.approx(-8.89) and pico.pad("40").x == pytest.approx(8.89)
    assert pico.pad("1").y == pytest.approx(pico.pad("40").y)  # pin 40 faces pin 1


def test_board_program_parses_parts_nets_and_parameters() -> None:
    board = parse_board(PICO_SERVO)
    assert board.name == "Pico servo board"
    assert board.width == 72 and len(board.parts) == 15
    assert board.nets["VIN"].current == pytest.approx(3.3)
    assert board.nets["GND"].pour == "bottom"
    pads = {p.name: p for p in board.pads()}
    assert pads["U1.8"].net == "GND"  # joined inside the Pico, not listed in NETS
    assert pads["U1.39"].net == "VSYS"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('"U1.VSYS"', '"U1.NOPE"'), "no pin 'NOPE'"),
        (('"U1.3", "U1.38"', '"U1.GND"'), "ambiguous"),
        (('"part": "schottky_ss34"', '"part": "flux_capacitor"'), "Unknown part"),
        (('"rotate": 90}', '"rotate": 45}'), "multiple of 90"),
        (("BOARD = {", "import os\nBOARD = {"), "data only"),
        (('"at": (35, 28)', '"at": (open("x"), 28)'), "Only numbers"),
    ],
)
def test_bad_board_programs_explain_themselves(change: tuple[str, str], message: str) -> None:
    with pytest.raises(ProgramError, match=message):
        parse_board(PICO_SERVO.replace(*change, 1))


def test_parameters_drive_the_board() -> None:
    wide = parse_board(set_params(PICO_SERVO, {"BOARD_W": 80, "SERVO_A": 2.0}))
    assert wide.width == 80
    assert wide.parts["J1"].x == 74
    assert wide.nets["VIN"].current == pytest.approx(4.3)


# ---------------------------------------------------------------- routing


def test_sample_routes_completely_and_passes_every_check(routed) -> None:
    board, routing = routed
    assert routing.unrouted == []
    result = run_checks(board, routing)
    assert result["status"] == "pass", [
        f for c in result["checks"] for f in c["findings"] if f["severity"] == "error"
    ]
    assert result["errors"] == 0
    assert any(z.net == "GND" and z.layer == "bottom" for z in routing.zones)


def test_power_tracks_are_sized_for_the_current_they_carry(routed) -> None:
    board, routing = routed
    vin = [t for t in routing.tracks if t.net == "VIN"]
    assert vin and all(ipc2221_current_a(t.width) >= t.current - 1e-9 for t in vin)
    # Each servo gets its own branch sized for one servo, straight back to the supply
    # terminal, so no branch ever carries both servos' current.
    servo = [t for t in vin if "J2" in t.sized_by or "J3" in t.sized_by]
    need = ipc2221_width_mm(1.5)
    assert servo and all(t.current == pytest.approx(1.5) and t.width >= need for t in servo)


# ---------------------------------------------------------------- checks catch faults


def test_clearance_violation_is_caught(routed) -> None:
    board, routing = routed
    pads = {p.name: p for p in board.pads()}
    a, b = pads["U1.4"], pads["U1.5"]  # GP2 and GP3, neighbours
    bad = Track("GP2", "top", [(a.x, a.y), (b.x, b.y)], 0.25, 0.1, "test")
    routing.tracks.append(bad)
    try:
        result = run_checks(board, routing)
    finally:
        routing.tracks.remove(bad)
    clearance = next(c for c in result["checks"] if c["id"] == "clearance")
    assert clearance["status"] == "fail"
    assert any("U1.5" in f["message"] for f in clearance["findings"])


def test_undersized_power_track_is_caught(routed) -> None:
    board, routing = routed
    trunk = next(t for t in routing.tracks if t.net == "VIN" and t.current >= 1.5)
    original = trunk.width
    trunk.width = 0.3
    try:
        result = run_checks(board, routing)
    finally:
        trunk.width = original
    assert statuses(result)["current"] == "fail"


def test_cut_connection_is_caught(routed) -> None:
    board, routing = routed
    servo = next(t for t in routing.tracks if t.net == "SERVO1")
    routing.tracks.remove(servo)
    try:
        result = run_checks(board, routing)
    finally:
        routing.tracks.append(servo)
    connectivity = next(c for c in result["checks"] if c["id"] == "connectivity")
    assert connectivity["status"] == "fail"
    assert any("SERVO1" in f["message"] for f in connectivity["findings"])


def test_unpowered_input_and_overvoltage_are_caught() -> None:
    no_supply = PICO_SERVO.replace('"voltage": SUPPLY_V - 0.4,', "")
    board = parse_board(no_supply)
    result = run_checks(board, route_board(board))
    assert statuses(result)["supply"] == "fail"

    hot = parse_board(PICO_SERVO.replace('"voltage": SUPPLY_V - 0.4,', '"voltage": 12,'))
    erc = run_checks(hot, route_board(hot))
    voltage = next(c for c in erc["checks"] if c["id"] == "voltage")
    assert voltage["status"] == "fail"
    assert any("U1" in f["message"] and "5.5 V" in f["message"] for f in voltage["findings"])


def test_overlapping_parts_are_caught() -> None:
    board = parse_board(
        PICO_SERVO.replace(
            '"R2": {"part": "resistor_0603", "value": "330", "at": (29, 12.5)}',
            '"R2": {"part": "resistor_0603", "value": "330", "at": (17.5, 12.5)}',
        )
    )
    result = run_checks(board, route_board(board))
    placement = next(c for c in result["checks"] if c["id"] == "placement")
    assert any("R1" in f["message"] and "R2" in f["message"] for f in placement["findings"])


# ---------------------------------------------------------------- outputs


def test_gerbers_parse_in_an_independent_reader_and_match_the_board(routed) -> None:
    from pygerber.gerberx3.api.v2 import GerberFile

    from jig.pcb.fab import fab_files

    board, routing = routed
    files = fab_files(board, routing, "pico")
    gerbers = [
        n for n in files if n.endswith((".gtl", ".gbl", ".gts", ".gbs", ".gtp", ".gto", ".gm1"))
    ]
    assert len(gerbers) == 7
    for name in gerbers:
        info = GerberFile.from_str(files[name]).parse().get_info()
        assert float(info.min_x_mm) >= -0.1 and float(info.max_x_mm) <= board.width + 0.1, name
        assert float(info.min_y_mm) >= -0.1 and float(info.max_y_mm) <= board.height + 0.1, name
    edge = GerberFile.from_str(files["pico-Edge_Cuts.gm1"]).parse().get_info()
    assert float(edge.width_mm) == pytest.approx(board.width + 0.1, abs=0.01)  # 0.1 mm pen
    assert float(edge.height_mm) == pytest.approx(board.height + 0.1, abs=0.01)


def test_drill_files_hold_every_hole(routed) -> None:
    from jig.pcb.fab import fab_files

    board, routing = routed
    drill = fab_files(board, routing, "pico")["pico-PTH.drl"]
    hits = [line for line in drill.splitlines() if line.startswith("X")]
    tht = [p for p in board.pads() if p.through_hole]
    assert len(hits) == len(tht) + len(routing.vias)
    assert "METRIC" in drill and drill.rstrip().endswith("M30")


def test_bom_groups_parts_and_skips_mechanical(routed) -> None:
    from jig.pcb.fab import bom_rows

    board, _ = routed
    rows = {r["Designator"]: r for r in bom_rows(board)}
    assert rows["R1,R2"]["Quantity"] == 2 and rows["R1,R2"]["Comment"] == "330"
    assert rows["D1"]["LCSC Part #"] == "C8678"
    assert not any(d.startswith("H") for d in rows)  # mounting holes are not assembled


def test_schematic_labels_every_connected_pin(routed) -> None:
    from jig.pcb.schematic import schematic_svg

    board, _ = routed
    svg = schematic_svg(board)
    for net in board.nets:
        assert f'data-net="{net}"' in svg
    assert "34 unused pins not shown" in svg  # the Pico shows only what is used


def test_board_3d_builds_as_a_part(builder) -> None:
    from jig.pcb.model3d import board_part_program

    board = parse_board(PICO_SERVO)
    result = builder.build(board_part_program(board))
    assert result.ok, result.data.get("error")
    size = result.data["stats"]["bbox"]["size"]
    assert size[0] == pytest.approx(72) and size[1] == pytest.approx(45)
    assert size[2] == pytest.approx(1.6 + 12.0)  # the Pico on headers is the tallest part


def test_board_service_and_report(tmp_path) -> None:
    from jig.pcb.service import BoardService
    from jig.report.board_document import build_board_report

    service = BoardService(tmp_path)
    payload = service.design(PICO_SERVO)
    assert payload["checks"]["status"] == "pass"
    assert service.path_for(payload["id"], "fab.zip") is not None
    assert service.load(payload["id"])["name"] == "Pico servo board"
    html = build_board_report(payload)
    assert ">PASS<" in html and "IPC-2221" in html and "Not checked" in html
    assert "1.50 A in 0.55 mm" in html  # the busiest VIN branch, explained
