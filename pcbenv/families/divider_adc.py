"""Voltage-sense divider with anti-alias RC feeding an ADC header."""
from __future__ import annotations

import math
import random

from pcbenv.families._common import E12, E96, Builder, band, cutoff_of, golden, nearest, pick, series_values
from pcbenv.golden import Golden

FAMILY = "divider_adc"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vmax = pick(rng, [5.0, 9.0, 12.0, 15.0, 24.0, 30.0])
    vfs = pick(rng, [1.8, 2.5, 3.0, 3.3])
    f_aa = pick(rng, [10.0, 50.0, 100.0, 500.0, 1000.0])
    series_r = rng.random() < 0.5
    ratio_t = 0.9 * vfs / vmax
    b = Builder(f"0-{vmax:g} V sense divider for a {vfs:g} V ADC", rng)
    b.add("J1", "CONN2")
    b.add("J2", "CONN2")
    rbot = pick(rng, series_values(E96, 10e3, 100e3))
    b.add("R2", "R", rbot)
    b.add("R1", "R", nearest(E96, rbot * (1 / ratio_t - 1)))
    r1, r2 = b.val("R1"), b.val("R2")
    rth = r1 * r2 / (r1 + r2)
    b.add("C1", "C", nearest(E12, 1 / (2 * math.pi * rth * f_aa)))
    c1 = b.val("C1")
    b.net("VSENSE", "J1.1", "R1.1")
    b.net("GND", "J1.2", "R2.2", "C1.2", "J2.2")
    if series_r:
        b.add("R3", "R", pick(rng, [100.0, 220.0, 470.0, 1000.0]))
        b.net("DIV", "R1.2", "R2.1", "C1.1", "R3.1")
        b.net("ADC", "R3.2", "J2.1")
    else:
        b.net("DIV", "R1.2", "R2.1", "C1.1", "J2.1")
    ratio = r2 / (r1 + r2)

    def h(s: complex) -> complex:
        return (r2 / (r1 + r2)) / (1 + s * rth * c1)

    fc = cutoff_of(h, "high")
    assertions = [
        {"name": "full_scale", "type": "dc_voltage", "net_pin": "J2.1", **band(ratio_t * vmax, 0.02),
         "supply": {"pin": "J1.1", "volts": vmax}, "ground_pin": "J1.2"},
        {"name": "half_scale", "type": "dc_voltage", "net_pin": "J2.1", **band(ratio_t * vmax / 2, 0.02),
         "supply": {"pin": "J1.1", "volts": vmax / 2}, "ground_pin": "J1.2"},
        {"name": "anti_alias_corner", "type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "edge": "high",
         **band(fc, 0.10), "source": {"pin": "J1.1", "ac": 1.0}, "ground_pin": "J1.2"},
    ]
    intent = f"""
# Voltage-sense divider for an ADC

Scales a 0–{vmax:g} V signal on J1 (pin 1 = sensed voltage, pin 2 = GND) down so that {vmax:g} V reads as
{ratio_t*vmax:.3g} V (90 % of a {vfs:g} V ADC full scale) on the ADC header J2 (pin 1 = ADC input, pin 2 = GND).

- Divider: R1 from the sensed input to the divider node, R2 from the divider node to GND
  (ratio R2/(R1+R2)).
- Anti-alias filter: C1 from the divider node to GND, corner 1/(2π·(R1||R2)·C1) ≈ {f_aa:g} Hz.
{"- R3 is a small series resistor from the divider node to the ADC pin (protection/isolation)." if series_r else "- The divider node goes directly to J2 pin 1."}

Spec: ADC voltage = {ratio_t:.4f} × input ±2 %; anti-alias -3 dB corner {fc:.4g} Hz ±10 %.
"""
    params = {"vmax": vmax, "vfs": vfs, "ratio": round(ratio, 6), "f_aa": f_aa, "fc_hz": round(fc, 3),
              "series_r": series_r}
    return golden(FAMILY, seed, b, assertions, {"GND": 0.3}, [], intent, params)
