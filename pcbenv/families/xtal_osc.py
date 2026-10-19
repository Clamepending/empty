"""MCU crystal oscillator: crystal between XIN/XOUT with load capacitors sized for the crystal's CL."""
from __future__ import annotations

import random

from pcbenv.families._common import (DECOUPLING, E24, NRST_PULLUP, Bounds, Builder, golden, led_r_min, nearest, parts_summary,
                                     pick, series_values)
from pcbenv.golden import Golden
from pcbenv.parts import PARTS
from pcbenv.parts_lib import GPIO_IMAX

FAMILY = "xtal_osc"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    while True:
        xtal = pick(rng, ["XTAL", "XTAL_CL18"])
        cl = PARTS[xtal].extra["cl"]
        cstray = pick(rng, [2e-12, 2.5e-12, 3e-12, 4e-12, 5e-12])
        c = nearest(E24, 2 * (cl - cstray))
        if abs(c / 2 + cstray - cl) <= 0.05 * cl:
            break
    freq = pick(rng, ["8M", "12M", "16M", "20M", "24M", "25M"])
    vdd = pick(rng, [3.3, 5.0])
    b = Builder(f"MCU with {freq}Hz crystal", rng)
    b.add("J1", "CONN2")
    b.add("U1", "MCU8")
    b.add("Y1", xtal, freq)
    b.add("C1", "C", c, "Capacitor_SMD:C_0603_1608Metric")
    b.add("C2", "C", c, "Capacitor_SMD:C_0603_1608Metric")
    b.add("C3", "C", 100e-9)
    b.add("R1", "R", pick(rng, series_values(E24, 4.7e3, 47e3)))
    vnet = "+3V3" if vdd == 3.3 else "+5V"
    b.net(vnet, "J1.1", "U1.VDD", "C3.1", "R1.1")
    b.net("GND", "J1.2", "U1.GND", "C3.2", "C1.2", "C2.2")
    b.net("NRST", "R1.2", "U1.NRST")
    b.net("XIN", "U1.PA1", "Y1.1", "C1.1")
    b.net("XOUT", "U1.PA2", "Y1.2", "C2.1")
    led = rng.random() < 0.5
    if led:
        b.add("D1", pick(rng, ["LED_RED", "LED_GREEN"]))
        led_vf10 = 2.0 if b.components["D1"]["part"] == "LED_RED" else 2.2
        b.add("R2", "R", nearest(E24, (vdd - 2.1) / 0.004))
        b.net("LED", "U1.PA0", "R2.1")
        b.net("LED_A", "R2.2", "D1.A")
        b.net("GND", "D1.K")
    sup = {"pin": "J1.1", "volts": vdd}
    cl_eff = c / 2 + cstray
    assertions = [
        {"name": "xtal_load_capacitance", "type": "analytic", "check": "xtal_load", "xtal": "Y1",
         "cl": cl, "cstray": cstray, "tol": 0.10, "osc_pins": ["U1.PA1", "U1.PA2"], "ground_pin": "J1.2"},
        {"name": "vdd", "type": "dc_voltage", "net_pin": "U1.VDD", "ref_pin": "U1.GND", "min": round(vdd * 0.98, 4),
         "max": round(vdd * 1.02, 4), "supply": sup, "ground_pin": "J1.2"},
        {"name": "nrst_high", "type": "dc_voltage", "net_pin": "U1.NRST", "min": round(vdd * 0.9, 4),
         "max": round(vdd * 1.01, 4), "supply": sup, "ground_pin": "J1.2"},
    ]
    if led:
        assertions.append({"name": "led_current", "type": "dc_current", "element": "D1", "min": 0.002,
                           "max": 0.006, "supply": sup, "source": {"pin": "U1.PA0", "dc": vdd, "r": 50.0},
                           "ground_pin": "J1.2"})
    intent = f"""
# MCU with {freq}Hz crystal oscillator

An MCU (U1, MCU8) clocked from a {freq}Hz crystal Y1 ({xtal}, rated load capacitance {cl*1e12:.0f} pF),
powered from {vdd:g} V on J1 (pin 1 = +{vdd:g} V, pin 2 = GND).

- C3 decouples VDD at U1's VDD pin; R1 pulls NRST up to VDD (no internal pull-up).
- Y1 connects between XIN (PA1) and XOUT (PA2). Each crystal pin has its own load capacitor to GND:
  C1 on the XIN side, C2 on the XOUT side, both placed next to the crystal.
- Stray capacitance (MCU pin + PCB) is {cstray*1e12:g} pF per the layout estimate.
{"- PA0 drives a status LED D1 through R2 (about 4 mA)." if led else ""}

Spec: effective crystal load CL_eff = C1·C2/(C1+C2) + Cstray within ±10 % of {cl*1e12:.0f} pF
(golden: {cl_eff*1e12:.1f} pF); NRST ≥ 0.9·VDD.
Clock: Y1 must be a {freq}Hz crystal (value `{freq}`, ±0.1 %): the firmware's clock tree assumes exactly
this frequency, and MCU8 only supports 4–25 MHz crystals.
Component values: decoupling C3 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ.

{parts_summary([("supply connector", ["J1"]), ("MCU", ["U1"]), ("VDD decoupling", ["C3"]), ("reset pull-up", ["R1"]),
                ("crystal oscillator: crystal and load capacitors", ["Y1", "C1", "C2"])]
               + ([("status LED on PA0 with series resistor", ["D1", "R2"])] if led else []))}
"""
    params = {"xtal": xtal, "freq": freq, "cl_pf": cl * 1e12, "cstray_pf": cstray * 1e12, "c_load": c,
              "vdd": vdd, "status_led": led}
    vb = Bounds(FAMILY, seed)
    vb.exact("Y1", b.val("Y1"), 1e-3)  # frequency is a requirement (firmware clock); no assertion sees it
    vb.spec("C1", c)                   # load caps pinned by xtal_load; per-cap range stops C1/C2 imbalance
    vb.spec("C2", c)
    vb.fixed("C3", *DECOUPLING)
    vb.fixed("R1", *NRST_PULLUP)
    if led:
        # LED current pinned by led_current; datasheet floor = 8 mA GPIO limit
        vb.spec("R2", b.val("R2"), ds_lo=led_r_min(vdd, 1, led_vf10, i_max=GPIO_IMAX))
    return golden(FAMILY, seed, b, assertions, {vnet: 0.3, "GND": 0.3},
                  [{"cap": "C3", "ic_pin": "U1.VDD", "max_mm": 5.0}], intent, params, big=True, value_bounds=vb.out)
