"""Single-supply AC-coupled inverting op-amp stage with a mid-supply bias divider."""
from __future__ import annotations

import math
import random

from pcbenv.families._common import (DECOUPLING, E6, E24, E96, Bounds, Builder, band, cutoff_of, gain_at, golden, nearest,
                                     parts_summary, pick, series_values)
from pcbenv.golden import Golden
from pcbenv.parts_lib import OPAMP_A0, OPAMP_GBW

FAMILY = "opamp_inv"


def transfer(rin: float, cin: float, rf: float):
    def h(s: complex) -> complex:
        a = OPAMP_A0 / (1 + s / (2 * math.pi * OPAMP_GBW / OPAMP_A0))
        zin = rin + 1 / (s * cin)
        beta = zin / (zin + rf)          # feedback fraction OUT -> IN-
        alpha = rf / (zin + rf)          # input fraction IN -> IN-
        return -a * alpha / (1 + a * beta)
    return h


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vcc = pick(rng, [3.3, 5.0])
    gain = pick(rng, [1.0, 2.0, 3.3, 4.7, 5.0, 10.0, 15.0, 22.0])
    f_hp = pick(rng, [10.0, 20.0, 50.0, 100.0])
    b = Builder(f"inverting x{gain:g} AC amplifier", rng)
    for j in ("J1", "J2", "J3"):
        b.add(j, "CONN2")
    b.add("U1", "OPAMP")
    b.add("C1", "C", 100e-9)
    rin = pick(rng, series_values(E96, 2e3, 20e3))
    b.add("R1", "R", rin)
    b.add("R2", "R", nearest(E96, rin * gain))
    rb = pick(rng, series_values(E24, 10e3, 100e3))
    b.add("R3", "R", rb)
    b.add("R4", "R", rb)
    b.add("C3", "C", pick(rng, [1e-6, 4.7e-6, 10e-6]))
    b.add("C2", "C", nearest(E6, 1 / (2 * math.pi * rin * f_hp)))
    b.net("VCC", "J1.1", "U1.V+", "C1.1", "R3.1")
    b.net("GND", "J1.2", "U1.V-", "C1.2", "R4.2", "C3.2", "J2.2", "J3.2")
    b.net("VMID", "R3.2", "R4.1", "C3.1", "U1.IN+")
    b.net("IN", "J2.1", "C2.1")
    b.net("IN_AC", "C2.2", "R1.1")
    b.net("SUM", "R1.2", "R2.1", "U1.IN-")
    b.net("OUT", "U1.OUT", "R2.2", "J3.1")

    rin_v, rf_v, cin_v = b.val("R1"), b.val("R2"), b.val("C2")
    h = transfer(rin_v, cin_v, rf_v)
    f_mid = 1000.0
    g_mid = gain_at(h, f_mid)
    fc_low = cutoff_of(h, "low")
    st = {"supply": {"pin": "J1.1", "volts": vcc}, "source": {"pin": "J2.1", "dc": 0.0, "ac": 1.0},
          "ground_pin": "J1.2"}
    assertions = [
        {"name": "dc_bias_out", "type": "dc_voltage", "net_pin": "J3.1", **band(vcc / 2, 0.03), **st},
        {"name": "midband_gain", "type": "ac_gain", "in_pin": "J2.1", "out_pin": "J3.1", "freq": f_mid,
         **band(g_mid, 0.03), **st},
        {"name": "low_cutoff", "type": "cutoff", "in_pin": "J2.1", "out_pin": "J3.1", "edge": "low",
         **band(fc_low, 0.15), **st},
    ]
    intent = f"""
# Inverting x{gain:g} AC amplifier (single supply)

Amplifies an AC signal on J2 (pin 1 = input, pin 2 = GND) with a gain of -{gain:g} and outputs it on
J3 (pin 1 = output, pin 2 = GND), centred at mid-supply. Single {vcc:g} V supply on J1
(pin 1 = VCC, pin 2 = GND).

- U1 (OPAMP): V+ on VCC (decoupled by C1 at the pin), V- on GND.
- Mid-supply reference: equal resistors R3 (VCC to VMID) and R4 (VMID to GND), bypassed by C3 to GND;
  VMID drives the non-inverting input.
- The input is AC-coupled: J2 pin 1 -> C2 -> R1 -> IN-. R2 is the feedback resistor from OUT to IN-.
  Gain = -R2/R1; the coupling capacitor sets the low cut-off 1/(2π·R1·C2) ≈ {f_hp:g} Hz.

Spec: output DC level VCC/2 ±3 %; |gain| {g_mid:.3g} ±3 % at 1 kHz; low -3 dB corner {fc_low:.3g} Hz ±15 %.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); bias divider R3, R4 4.7 kΩ–470 kΩ each;
VMID bypass C3 470 nF–47 µF.

{parts_summary([("supply connector", ["J1"]), ("op-amp with supply decoupling", ["U1", "C1"]),
                ("mid-supply bias divider and bypass", ["R3", "R4", "C3"]), ("input coupling capacitor", ["C2"]),
                ("gain-setting input and feedback resistors", ["R1", "R2"]), ("input connector", ["J2"]),
                ("output connector", ["J3"])])}
"""
    params = {"vcc": vcc, "gain": gain, "f_hp": f_hp, "fc_low_hz": round(fc_low, 3)}
    vb = Bounds(FAMILY, seed)
    vb.fixed("C1", *DECOUPLING)
    vb.spec("R1", rin_v)            # gain and low cut-off pinned by assertions
    vb.spec("R2", rf_v)
    vb.spec("C2", cin_v)
    vb.fixed("R3", 4.7e3, 470e3)    # mid-supply divider: ratio pinned by dc_bias_out, scale is not;
    vb.fixed("R4", 4.7e3, 470e3)    # 4.7k..470k = 0.35..5 mA at 5 V down to stiff-enough-for-IN+
    vb.fixed("C3", 470e-9, 47e-6)   # VMID bypass: corner with R3||R4 well below the signal band
    return golden(FAMILY, seed, b, assertions, {"VCC": 0.3, "GND": 0.3},
                  [{"cap": "C1", "ic_pin": "U1.V+", "max_mm": 5.0}], intent, params, big=True, value_bounds=vb.out)
