"""Logic-controlled N-MOSFET low-side switch for an off-board resistive or inductive load."""
from __future__ import annotations

import random

from pcbenv.families._common import BULK, E6, E24, Bounds, Builder, band, golden, parts_summary, pick, series_values
from pcbenv.golden import Golden

FAMILY = "nmos_switch"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vload = pick(rng, [5.0, 9.0, 12.0, 24.0])
    iload = pick(rng, [0.2, 0.3, 0.5, 0.75, 1.0])
    vctrl = pick(rng, [3.3, 5.0])
    kind = pick(rng, ["inductive", "inductive", "resistive"])
    rload = round(vload / iload, 3)
    b = Builder(f"{vload:g} V low-side MOSFET switch", rng)
    b.add("J1", "CONN3")
    b.add("J2", "CONN2")
    b.add("Q1", "NMOS")
    b.add("R1", "R", pick(rng, series_values(E24, 10.0, 100.0)))
    b.add("R2", "R", pick(rng, series_values(E24, 10e3, 100e3)))
    b.add("C1", "C", pick(rng, series_values(E6, 1e-6, 10e-6)), "Capacitor_SMD:C_1206_3216Metric")
    vnet = f"+{vload:g}V"
    b.net(vnet, "J1.1", "J2.1", "C1.1")
    b.net("GND", "J1.2", "Q1.S", "R2.2", "C1.2")
    b.net("CTRL", "J1.3", "R1.1")
    b.net("GATE", "R1.2", "Q1.G", "R2.1")
    b.net("SW", "J2.2", "Q1.D")
    if kind == "inductive":
        b.add("D1", "D_SCHOTTKY", footprint="Diode_SMD:D_SMA" if iload > 0.5 else None)
        b.net(vnet, "D1.K")
        b.net("SW", "D1.A")
    load = {"pin": "J2.1", "to": "J2.2", "r": rload}
    if kind == "inductive":
        load["l"] = 0.005
    sup = {"pin": "J1.1", "volts": vload}
    on = {"supply": sup, "source": {"pin": "J1.3", "dc": vctrl, "r": 50.0}, "loads": [load], "ground_pin": "J1.2"}
    off = {"supply": sup, "loads": [load, {"pin": "Q1.G", "to": "J1.1", "r": 10e6}], "ground_pin": "J1.2"}
    vds_max = round(max(0.1, iload * 0.4), 3)
    assertions = [
        {"name": "load_on_current", "type": "dc_current", "element": "J2.2", **band(iload, 0.05), **on},
        {"name": "vds_on", "type": "dc_voltage", "net_pin": "Q1.D", "min": 0.0, "max": vds_max, **on},
        {"name": "load_off_current", "type": "dc_current", "element": "J2.2", "min": 0.0, "max": 1e-4, **off},
        {"name": "ctrl_current_on", "type": "dc_current", "element": "R1", "min": 0.0, "max": 1e-3, **on},
    ]
    load_txt = (f"an inductive load (solenoid/motor, ~{rload:g} Ω) with Schottky D1 as flyback clamp across J2: "
                "cathode to the supply pin, anode to the switched pin" if kind == "inductive"
                else f"a resistive load (heater, ~{rload:g} Ω); no flyback diode is needed")
    intent = f"""
# {vload:g} V low-side MOSFET switch

A {vctrl:g} V logic signal switches a {iload:g} A load from a {vload:g} V supply.
J1 is the input header: pin 1 = +{vload:g} V, pin 2 = GND, pin 3 = CTRL (logic input).
J2 connects the off-board load: pin 1 = +{vload:g} V, pin 2 = switched return to the MOSFET drain.
The load is {load_txt}.

- Q1 (logic-level NMOS) has its source on GND and drain on the switched node (J2 pin 2).
- CTRL drives the gate through series resistor R1; R2 pulls the gate to GND so the load is off
  when CTRL is floating.
- C1 is a bulk capacitor across the load supply at the input header.

Spec: CTRL = {vctrl:g} V -> load current {iload:g} A ±5 % with VDS ≤ {vds_max:g} V; CTRL floating ->
load off (< 0.1 mA) even with 10 MΩ of leakage from the supply to the gate. Load-current
traces (supply, switched node, GND) at least 0.5 mm wide.
Component values: gate series R1 4.7 Ω–220 Ω (datasheet: 10–100 Ω); gate pull-down R2 4.7 kΩ–220 kΩ
(datasheet: 10k–100k); bulk C1 1 µF–22 µF.

{parts_summary([("input header", ["J1"]), ("load connector", ["J2"]), ("low-side MOSFET", ["Q1"]),
                ("gate series resistor and gate pull-down", ["R1", "R2"]), ("supply bulk capacitor", ["C1"])]
               + ([("flyback clamp diode", ["D1"])] if kind == "inductive" else []))}
"""
    params = {"vload": vload, "iload": iload, "vctrl": vctrl, "kind": kind, "rload": rload}
    power_nets = {vnet: 0.5, "SW": 0.5, "GND": 0.5}
    vb = Bounds(FAMILY, seed)
    vb.fixed("R1", 4.7, 220.0)    # NMOS datasheet: gate series 10-100 ohm; >220 ohm slows the ~300 pF gate
    vb.fixed("R2", 4.7e3, 220e3)  # NMOS datasheet: gate pull-down 10k-100k (x2 slack)
    vb.fixed("C1", *BULK)         # bulk across the load supply: 1-22 uF ceramic (1206)
    return golden(FAMILY, seed, b, assertions, power_nets, [], intent, params, value_bounds=vb.out)
