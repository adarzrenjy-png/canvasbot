"""Built-in starter boards, written in the board-program format."""

from __future__ import annotations

PICO_SERVO = '''"""Pico servo board

Drives two hobby servos from a 5 V supply with a Raspberry Pi Pico. The servos take
power straight from the input; the Pico is fed through a Schottky diode on VSYS, as
its datasheet recommends, so USB and the supply can both be plugged in.
"""

# --- parameters ---
BOARD_W = 72.0  # mm | Board width | min=60 max=200
BOARD_H = 45.0  # mm | Board height | min=40 max=200
SUPPLY_V = 5.0  # V | Supply voltage | min=4.5 max=5.5
SERVO_A = 1.5  # A | Peak current per servo | min=0.1 max=3
# --- end parameters ---

BOARD = {"width": BOARD_W, "height": BOARD_H, "thickness": 1.6, "corner_radius": 2.0}

PARTS = {
    "U1": {"part": "raspberry_pi_pico", "at": (35, 28), "rotate": 90},
    "J1": {"part": "terminal_2", "at": (BOARD_W - 6, 8), "rotate": 90, "label": "5 V in",
           "current": 2 * SERVO_A + 0.3},
    "D1": {"part": "schottky_ss34", "at": (22, 41.5), "current": 0.3},
    "C1": {"part": "capacitor_10uf_0805", "at": (BOARD_W - 4.5, 21), "rotate": 90},
    "C2": {"part": "capacitor_22uf_1206", "at": (BOARD_W - 8.5, 21), "rotate": 90},
    "J2": {"part": "servo_header", "at": (12, 6), "rotate": 90, "label": "Servo 1",
           "current": SERVO_A},
    "J3": {"part": "servo_header", "at": (24, 6), "rotate": 90, "label": "Servo 2",
           "current": SERVO_A},
    "R1": {"part": "resistor_0603", "value": "330", "at": (17, 12.5)},
    "R2": {"part": "resistor_0603", "value": "330", "at": (29, 12.5)},
    "R3": {"part": "resistor_0603", "value": "1k", "at": (50, 12.5)},
    "D2": {"part": "led_0603", "value": "green", "at": (55, 12.5), "rotate": 180},
    "H1": {"part": "mount_hole_m3", "at": (4, 4)},
    "H2": {"part": "mount_hole_m3", "at": (4, BOARD_H - 4)},
    "H3": {"part": "mount_hole_m3", "at": (BOARD_W - 4, BOARD_H - 4)},
    "H4": {"part": "mount_hole_m3", "at": (42, 4)},
}

NETS = {
    "VIN": {"pins": ["J1.1", "D1.A", "C1.1", "C2.1", "J2.V+", "J3.V+"], "kind": "power",
            "voltage": SUPPLY_V, "current": 2 * SERVO_A + 0.3},
    "VSYS": {"pins": ["D1.K", "U1.VSYS"], "kind": "power", "voltage": SUPPLY_V - 0.4,
             "current": 0.3},
    "GND": {"pins": ["J1.2", "C1.2", "C2.2", "J2.GND", "J3.GND", "D2.K", "U1.3", "U1.38"],
            "kind": "ground", "pour": "bottom", "current": 2 * SERVO_A + 0.3},
    "GP2": {"pins": ["U1.GP2", "R1.1"]},
    "GP3": {"pins": ["U1.GP3", "R2.1"]},
    "SERVO1": {"pins": ["R1.2", "J2.SIG"]},
    "SERVO2": {"pins": ["R2.2", "J3.SIG"]},
    "GP15": {"pins": ["U1.GP15", "R3.1"]},
    "LED": {"pins": ["R3.2", "D2.A"]},
}

RULES = {"clearance": 0.2, "track": 0.25, "via_drill": 0.4, "via_diameter": 0.8}
'''

SAMPLES = {"pico_servo": PICO_SERVO}
