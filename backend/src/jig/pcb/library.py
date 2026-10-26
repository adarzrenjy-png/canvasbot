"""Parts Jig can put on a board: pins with their electrical role, footprint, and ratings.

Pin types drive the electrical rules check (ERC):
    power_in   needs a supply on its net          power_out  is a supply
    ground     must sit on a ground net           input / output / bidirectional
    passive    resistors, capacitors, connectors  nc         must stay unconnected

Ratings are the part's absolute limits from its datasheet (voltage in V, current in
A, power in W). The checks compare them with the voltage and current each net
declares. LCSC numbers are suggestions for JLCPCB assembly: confirm stock and the
exact part on jlcpcb.com before ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jig.pcb import footprints as fp

PIN_TYPES = (
    "power_in",
    "power_out",
    "ground",
    "input",
    "output",
    "bidirectional",
    "passive",
    "nc",
)


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    type: str = "passive"


@dataclass(frozen=True)
class PartDef:
    id: str
    name: str
    category: str
    description: str
    pins: tuple[Pin, ...]
    footprint: fp.Footprint
    ratings: dict[str, float] = field(default_factory=dict)
    value: str = ""
    lcsc: str | None = None
    source: str = ""
    joined: tuple[tuple[str, ...], ...] = ()  # pins connected inside the part
    prefix: str = "U"

    def pin(self, number: str) -> Pin:
        for pin in self.pins:
            if pin.number == number or pin.name == number:
                return pin
        raise KeyError(f"{self.name} has no pin {number!r}")


def _two(a: str = "1", b: str = "2", ta: str = "passive", tb: str = "passive", na="1", nb="2"):
    return (Pin(a, na, ta), Pin(b, nb, tb))


def _resistor(size: str, watts: float, volts: float) -> PartDef:
    return PartDef(
        id=f"resistor_{size}",
        name=f"Resistor {size}",
        category="passive",
        description=f"Thick-film chip resistor, {size}, {watts} W, 1 %",
        pins=_two(),
        footprint=fp.chip(size),
        ratings={"power_w": watts, "voltage_v": volts},
        source="Generic thick-film chip resistor datasheet values",
        prefix="R",
    )


def _capacitor(size: str, value: str, volts: float, lcsc: str | None) -> PartDef:
    return PartDef(
        id=f"capacitor_{value.lower()}_{size}",
        name=f"Capacitor {value} {size}",
        category="passive",
        description=f"MLCC {value}, {volts:g} V, X5R/X7R, {size}",
        pins=_two(),
        footprint=fp.chip(size),
        ratings={"voltage_v": volts},
        value=value,
        lcsc=lcsc,
        source="Generic MLCC datasheet values; derate to half the rated voltage for X5R",
        prefix="C",
    )


def _header(pins: int) -> PartDef:
    return PartDef(
        id=f"header_1x{pins}",
        name=f"Pin header 1x{pins}",
        category="connector",
        description=f"2.54 mm single-row pin header, {pins} pins",
        pins=tuple(Pin(str(i + 1), str(i + 1)) for i in range(pins)),
        footprint=fp.header(pins),
        ratings={"current_a": 3.0},
        source="Generic 2.54 mm header, 3 A per pin",
        prefix="J",
    )


PICO_PINS = {
    1: "GP0",
    2: "GP1",
    3: "GND",
    4: "GP2",
    5: "GP3",
    6: "GP4",
    7: "GP5",
    8: "GND",
    9: "GP6",
    10: "GP7",
    11: "GP8",
    12: "GP9",
    13: "GND",
    14: "GP10",
    15: "GP11",
    16: "GP12",
    17: "GP13",
    18: "GND",
    19: "GP14",
    20: "GP15",
    21: "GP16",
    22: "GP17",
    23: "GND",
    24: "GP18",
    25: "GP19",
    26: "GP20",
    27: "GP21",
    28: "GND",
    29: "GP22",
    30: "RUN",
    31: "GP26",
    32: "GP27",
    33: "GND",
    34: "GP28",
    35: "ADC_VREF",
    36: "3V3",
    37: "3V3_EN",
    38: "GND",
    39: "VSYS",
    40: "VBUS",
}


def _pico_type(name: str) -> str:
    if name == "GND":
        return "ground"
    if name == "VSYS":
        return "power_in"
    if name == "3V3":
        return "power_out"
    if name in ("RUN", "3V3_EN"):
        return "input"
    if name in ("VBUS", "ADC_VREF"):
        return "passive"
    return "bidirectional"


PARTS: dict[str, PartDef] = {}


def _add(part: PartDef) -> None:
    PARTS[part.id] = part


for _size, _w, _v in (("0402", 0.0625, 50), ("0603", 0.1, 75), ("0805", 0.125, 150)):
    _add(_resistor(_size, _w, _v))
_add(_capacitor("0603", "100nF", 50, "C14663"))
_add(_capacitor("0603", "1uF", 25, None))
_add(_capacitor("0805", "10uF", 25, None))
_add(_capacitor("1206", "22uF", 25, None))
_add(
    PartDef(
        id="led_0603",
        name="LED 0603",
        category="indicator",
        description="Chip LED, 0603; pin 1 cathode, pin 2 anode",
        pins=(Pin("1", "K", "passive"), Pin("2", "A", "passive")),
        footprint=fp.chip("0603"),
        ratings={"current_a": 0.02, "voltage_v": 5.0},
        source="Generic 0603 LED, 20 mA max",
        prefix="D",
    )
)
_add(
    PartDef(
        id="schottky_ss34",
        name="SS34 Schottky diode",
        category="power",
        description="40 V, 3 A Schottky rectifier, SMA; pin 1 cathode",
        pins=(Pin("1", "K", "passive"), Pin("2", "A", "passive")),
        footprint=fp.sma(),
        ratings={"voltage_v": 40.0, "current_a": 3.0},
        lcsc="C8678",
        source="SS34 datasheet: VRRM 40 V, IF(AV) 3 A, VF about 0.5 V at 3 A",
        prefix="D",
    )
)
_add(
    PartDef(
        id="mosfet_ao3400a",
        name="AO3400A N-MOSFET",
        category="power",
        description="30 V, 5.7 A N-channel MOSFET, logic level, SOT-23",
        pins=(Pin("1", "G", "input"), Pin("2", "S", "passive"), Pin("3", "D", "passive")),
        footprint=fp.sot23(3),
        ratings={"voltage_v": 30.0, "current_a": 5.7},
        lcsc="C20917",
        source="AO3400A datasheet: VDS 30 V, ID 5.7 A, RDS(on) under 33 mOhm at 4.5 V",
        prefix="Q",
    )
)
_add(
    PartDef(
        id="ldo_ams1117_33",
        name="AMS1117-3.3 regulator",
        category="power",
        description="1 A, 3.3 V linear regulator, SOT-223; tab is the output",
        pins=(
            Pin("1", "GND", "ground"),
            Pin("2", "VOUT", "power_out"),
            Pin("3", "VIN", "power_in"),
            Pin("4", "TAB", "power_out"),
        ),
        footprint=fp.sot223(),
        joined=(("2", "4"),),
        ratings={"voltage_v": 15.0, "current_a": 1.0},
        lcsc="C6186",
        source="AMS1117 datasheet: VIN max 15 V, IOUT 1 A, dropout 1.3 V",
        prefix="U",
    )
)
_add(
    PartDef(
        id="ldo_ap2112k_33",
        name="AP2112K-3.3 regulator",
        category="power",
        description="600 mA, 3.3 V low-dropout regulator, SOT-23-5",
        pins=(
            Pin("1", "VIN", "power_in"),
            Pin("2", "GND", "ground"),
            Pin("3", "EN", "input"),
            Pin("4", "NC", "nc"),
            Pin("5", "VOUT", "power_out"),
        ),
        footprint=fp.sot23(5),
        ratings={"voltage_v": 6.0, "current_a": 0.6},
        lcsc="C51118",
        source="AP2112 datasheet: VIN max 6 V, IOUT 600 mA, dropout 250 mV",
        prefix="U",
    )
)
for _n in range(2, 11):
    _add(_header(_n))
_add(
    PartDef(
        id="servo_header",
        name="Servo header",
        category="connector",
        description="3-pin 2.54 mm header in hobby-servo order: signal, V+, ground",
        pins=(Pin("1", "SIG", "output"), Pin("2", "V+", "power_in"), Pin("3", "GND", "ground")),
        footprint=fp.header(3),
        ratings={"current_a": 3.0},
        source="Standard hobby servo pinout (signal, +, -)",
        prefix="J",
    )
)
_add(
    PartDef(
        id="jst_xh_2",
        name="JST XH 2-pin",
        category="connector",
        description="2.5 mm JST XH header (B2B-XH-A), common for battery leads",
        pins=(Pin("1", "1"), Pin("2", "2")),
        footprint=fp.jst("XH", 2),
        ratings={"current_a": 3.0, "voltage_v": 250.0},
        source="JST XH datasheet: 3 A, 250 V",
        prefix="J",
    )
)
_add(
    PartDef(
        id="terminal_2",
        name="Screw terminal 2-pin",
        category="connector",
        description="5.08 mm screw terminal block, 2 positions",
        pins=(Pin("1", "1"), Pin("2", "2")),
        footprint=fp.terminal(2),
        ratings={"current_a": 10.0, "voltage_v": 300.0},
        source="Typical 5.08 mm terminal block: 10 A, 300 V",
        prefix="J",
    )
)
_add(
    PartDef(
        id="tactile_switch",
        name="Tactile switch 6 mm",
        category="input",
        description="6 x 6 mm through-hole push button",
        pins=tuple(Pin(str(i), str(i)) for i in range(1, 5)),
        footprint=fp.tactile_6mm(),
        joined=(("1", "2"), ("3", "4")),
        ratings={"current_a": 0.05, "voltage_v": 12.0},
        source="Generic 6 mm tact switch: 50 mA, 12 V",
        prefix="SW",
    )
)
_add(
    PartDef(
        id="mount_hole_m3",
        name="M3 mounting hole",
        category="mechanical",
        description="Plated 3.2 mm hole for an M3 screw",
        pins=(Pin("1", "1"),),
        footprint=fp.mount_hole(),
        source="M3 clearance hole",
        prefix="H",
    )
)
_add(
    PartDef(
        id="raspberry_pi_pico",
        name="Raspberry Pi Pico",
        category="module",
        description="RP2040 microcontroller board on 2.54 mm headers; run it from VSYS (1.8-5.5 V)",
        pins=tuple(Pin(str(n), name, _pico_type(name)) for n, name in PICO_PINS.items()),
        footprint=fp.pico_module(),
        ratings={"voltage_v": 5.5},
        joined=(tuple(str(n) for n, name in PICO_PINS.items() if name == "GND"),),
        source="Raspberry Pi Pico datasheet (pinout and VSYS range)",
        prefix="U",
    )
)


def get_part(part_id: str) -> PartDef:
    try:
        return PARTS[part_id]
    except KeyError as error:
        raise KeyError(
            f"Unknown part {part_id!r}. Known parts: {', '.join(sorted(PARTS))}"
        ) from error
