"""MCU with I2C bus pull-ups sized for bus capacitance, reset pull-up, decoupling and bus header."""
from __future__ import annotations

import random

from pcbenv.families._common import (BULK, DECOUPLING, E24, NRST_PULLUP, RESET_CAP, Bounds, Builder, golden, parts_summary,
                                     pick, series_values)
from pcbenv.golden import Golden
from pcbenv.parts_lib import I2C_K_RISE, I2C_RISE_LEVELS, I2C_SINK_MAX, I2C_VOL, MCU_PIN_C

FAMILY = "mcu_i2c"
K_RISE = I2C_K_RISE  # I2C rise time per UM10204: 30 -> 70 % of VDD = ln(0.7/0.3)·RC


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    while True:
        vdd = pick(rng, [1.8, 2.5, 3.3, 5.0])
        mode = pick(rng, ["standard", "fast"])
        tr_max = 1000e-9 if mode == "standard" else 300e-9
        cbus = pick(rng, [30e-12, 50e-12, 100e-12, 150e-12, 200e-12, 300e-12, 400e-12])
        ctot = cbus + MCU_PIN_C
        rmin = (vdd - I2C_VOL) / I2C_SINK_MAX
        rmax_tr = tr_max / (K_RISE * ctot)
        cands = [r for r in series_values(E24, 100.0, 100e3) if max(rmin * 1.05, 0.55 * rmax_tr) <= r <= 0.85 * rmax_tr]
        if cands:
            break
    rp = pick(rng, cands)
    b = Builder(f"MCU with I2C bus ({mode}-mode)", rng)
    b.add("J1", "CONN2")
    b.add("J2", "CONN4")
    b.add("U1", "MCU8")
    b.add("C1", "C", 100e-9)
    b.add("R1", "R", pick(rng, series_values(E24, 4.7e3, 47e3)))
    b.add("R2", "R", rp)
    b.add("R3", "R", rp)
    vnet = {1.8: "+1V8", 2.5: "+2V5", 3.3: "+3V3", 5.0: "+5V"}[vdd]
    b.net(vnet, "J1.1", "U1.VDD", "C1.1", "R1.1", "R2.1", "R3.1", "J2.1")
    b.net("GND", "J1.2", "U1.GND", "C1.2", "J2.2")
    b.net("NRST", "R1.2", "U1.NRST")
    b.net("SDA", "U1.SDA", "R2.2", "J2.3")
    b.net("SCL", "U1.SCL", "R3.2", "J2.4")
    bulk = rng.random() < 0.5
    if bulk:
        b.add("C2", "C", pick(rng, [1e-6, 4.7e-6, 10e-6]))
        b.net(vnet, "C2.1")
        b.net("GND", "C2.2")
    rst_cap = rng.random() < 0.5
    if rst_cap:
        b.add("C3", "C", 100e-9)
        b.net("NRST", "C3.1")
        b.net("GND", "C3.2")

    sup = {"pin": "J1.1", "volts": vdd}
    bus = [{"pin": "J2.3", "c": cbus}, {"pin": "J2.4", "c": cbus}]
    tstop = round(8 * tr_max, 12)
    assertions = [
        {"name": "vdd", "type": "dc_voltage", "net_pin": "U1.VDD", "ref_pin": "U1.GND", "min": round(vdd * 0.98, 4),
         "max": round(vdd * 1.02, 4), "supply": sup, "ground_pin": "J1.2"},
        {"name": "nrst_high", "type": "dc_voltage", "net_pin": "U1.NRST", "min": round(vdd * 0.9, 4),
         "max": round(vdd * 1.01, 4), "supply": sup, "ground_pin": "J1.2"},
    ]
    for line, pin, r in (("sda", "U1.SDA", "R2"), ("scl", "U1.SCL", "R3")):
        assertions.append({"name": f"{line}_rise_time", "type": "rise_time", "net_pin": pin, "min": 0.0,
                           "max": tr_max, "levels": list(I2C_RISE_LEVELS), "tstop": tstop, "supply": sup, "loads": bus,
                           "source": {"pin": pin, "kind": "release", "r_on": 10.0}, "ground_pin": "J1.2"})
        assertions.append({"name": f"{line}_sink_current", "type": "dc_current", "element": r, "min": 0.0,
                           "max": 3e-3, "supply": sup, "source": {"pin": pin, "dc": 0.4, "r": 1e-3},
                           "ground_pin": "J1.2"})
    tr_nom = K_RISE * rp * ctot
    intent = f"""
# MCU with I2C bus header

An MCU (U1, MCU8) running from {vdd:g} V (J1: pin 1 = +{vdd:g} V, pin 2 = GND) acts as I2C controller
for off-board devices on the 4-pin bus header J2 (pin 1 = VDD, pin 2 = GND, pin 3 = SDA, pin 4 = SCL).

- C1 decouples VDD at U1's VDD pin{"; C2 is an additional bulk capacitor on VDD" if bulk else ""}.
- NRST has no internal pull-up: R1 pulls it up to VDD{" and C3 to GND gives a power-on reset delay" if rst_cap else ""}.
- SDA (U1.SDA -> J2.3) and SCL (U1.SCL -> J2.4) are open-drain; R2 (SDA) and R3 (SCL) are the bus pull-ups
  to VDD.

Bus: {mode}-mode I2C with up to {cbus*1e12:.0f} pF of off-board bus capacitance per line (plus 5 pF
MCU pin capacitance). Spec: I2C rise time (30–70 % of VDD, as defined by UM10204) ≤ {tr_max*1e9:.0f} ns
on both lines (nominal {tr_nom*1e9:.0f} ns), pull-up current ≤ 3 mA with a line held at VOL = 0.4 V,
NRST ≥ 0.9·VDD.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ{"; bulk C2 1 µF–22 µF" if bulk else ""}{"; reset delay C3 10 nF–1 µF" if rst_cap else ""};
I2C pull-ups R2, R3 anywhere in the datasheet range (VDD-0.4 V)/3 mA .. tr/(0.8473·Cbus) that meets the spec.

{parts_summary([("supply connector", ["J1"]), ("MCU", ["U1"]), ("VDD decoupling", ["C1"] + (["C2"] if bulk else [])),
                ("reset pull-up" + (" and power-on delay" if rst_cap else ""), ["R1"] + (["C3"] if rst_cap else [])),
                ("I2C bus pull-ups", ["R2", "R3"]), ("I2C bus header", ["J2"])])}
"""
    params = {"vdd": vdd, "mode": mode, "cbus_pf": round(cbus * 1e12), "rpullup": rp,
              "tr_nominal_ns": round(tr_nom * 1e9, 1), "bulk_cap": bulk, "reset_cap": rst_cap}
    vb = Bounds(FAMILY, seed)
    vb.fixed("C1", *DECOUPLING)
    vb.fixed("R1", *NRST_PULLUP)
    # pull-ups pinned by rise-time (max R) and sink-current (min R) assertions; the bound always
    # contains the whole datasheet range (QA F1)
    vb.spec("R2", rp, ds_lo=rmin, ds_hi=rmax_tr)
    vb.spec("R3", rp, ds_lo=rmin, ds_hi=rmax_tr)
    if bulk:
        vb.fixed("C2", *BULK)
    if rst_cap:
        vb.fixed("C3", *RESET_CAP)  # MCU8 datasheet: optional 10 nF..1 uF (100 nF typical)
    return golden(FAMILY, seed, b, assertions, {vnet: 0.3, "GND": 0.3},
                  [{"cap": "C1", "ic_pin": "U1.VDD", "max_mm": 5.0}], intent, params, big=True, value_bounds=vb.out)
