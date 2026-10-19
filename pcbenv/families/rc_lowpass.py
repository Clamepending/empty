"""Passive low-pass filters: 1st-order RC, 2nd-order RC-RC, and damped LC."""
from __future__ import annotations

import math
import random

from pcbenv.families._common import E6, E12, E24, Bounds, Builder, cutoff_of, gain_at, golden, nearest, parts_summary, pick, series_values
from pcbenv.golden import Golden

FAMILY = "rc_lowpass"
# QA F7: no golden capacitor below ~100 pF (an ADC input or a probe would move the corner) and no
# resistor above 220 kOhm; the bounds keep the R draw inside these.
C_MIN = 105e-12
R_MAX = 220e3


def transfer(topo: str, v: dict):
    def h(s: complex) -> complex:
        if topo == "rc1":
            return 1 / (1 + s * v["R1"] * v["C1"])
        if topo == "rc2":
            r1, c1, r2, c2 = v["R1"], v["C1"], v["R2"], v["C2"]
            return 1 / (1 + s * (r1 * c1 + r2 * c2 + r1 * c2) + s * s * r1 * c1 * r2 * c2)
        r, l, c = v["R1"] + 0.05, v["L1"], v["C1"]
        return 1 / (1 + s * r * c + s * s * l * c)
    return h


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    topo = pick(rng, ["rc1", "rc2", "rlc"])
    if topo == "rlc":
        fc_t = 10 ** rng.uniform(4.0, 5.3)
    else:
        fc_t = 10 ** rng.uniform(1.5, 5.0)
    b = Builder({"rc1": "1st-order RC", "rc2": "2nd-order RC", "rlc": "2nd-order LC"}[topo] + " low-pass filter", rng)
    b.add("J1", "CONN2")
    b.add("J2", "CONN2")
    b.net("GND", "J1.2", "J2.2")
    if topo == "rc1":
        r = pick(rng, [x for x in series_values(E24, 1e3, 100e3) if 1 / (2 * math.pi * x * fc_t) >= C_MIN]
                   or [1e3])
        b.add("R1", "R", r)
        b.add("C1", "C", nearest(E12, 1 / (2 * math.pi * r * fc_t)))
        b.net("IN", "J1.1", "R1.1")
        b.net("OUT", "R1.2", "C1.1", "J2.1")
        b.net("GND", "C1.2")
    elif topo == "rc2":
        r = pick(rng, [x for x in series_values(E24, 1e3, 22e3) if 1 / (2 * math.pi * x * fc_t) / 15 >= C_MIN]
                   or [1e3])
        b.add("R1", "R", r)
        b.add("R2", "R", nearest(E24, 10 * r))
        c = 1 / (2 * math.pi * r * fc_t) / 1.5   # rough: lightly-loaded 2-pole sections
        b.add("C1", "C", nearest(E12, c))
        b.add("C2", "C", nearest(E12, c / 10))
        b.net("IN", "J1.1", "R1.1")
        b.net("MID", "R1.2", "C1.1", "R2.1")
        b.net("OUT", "R2.2", "C2.1", "J2.1")
        b.net("GND", "C1.2", "C2.2")
    else:
        lv = pick(rng, series_values(E6, 10e-6, 1e-3))
        c = 1 / ((2 * math.pi * fc_t) ** 2 * lv)
        b.add("L1", "L", lv)
        b.add("C1", "C", nearest(E12, c))
        cv = b.val("C1")
        b.add("R1", "R", nearest(E24, math.sqrt(lv / cv) / 0.707))
        b.net("IN", "J1.1", "R1.1")
        b.net("RL", "R1.2", "L1.1")
        b.net("OUT", "L1.2", "C1.1", "J2.1")
        b.net("GND", "C1.2")
    vals = {k: b.val(k) for k in b.components if not k.startswith("J")}
    h = transfer(topo, vals)
    fc = cutoff_of(h, "high")
    g_pass = gain_at(h, fc / 20)
    g_stop = gain_at(h, fc * 10)
    st = {"source": {"pin": "J1.1", "ac": 1.0}, "ground_pin": "J1.2"}
    assertions = [
        {"name": "cutoff", "type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "edge": "high",
         "min": round(fc * 0.9, 4), "max": round(fc * 1.1, 4), **st},
        {"name": "passband_gain", "type": "ac_gain", "in_pin": "J1.1", "out_pin": "J2.1", "freq": round(fc / 20, 4),
         "min": round(g_pass * 0.97, 5), "max": round(g_pass * 1.03, 5), **st},
        {"name": "stopband_gain", "type": "ac_gain", "in_pin": "J1.1", "out_pin": "J2.1", "freq": round(fc * 10, 4),
         "min": round(g_stop * 0.75, 6), "max": round(g_stop * 1.25, 6), **st},
    ]
    order = 1 if topo == "rc1" else 2
    desc = {
        "rc1": "R1 in series from the input to the output node, C1 from the output node to GND.",
        "rc2": "two cascaded RC sections: R1 from the input to MID with C1 from MID to GND, then R2 (≈10x R1, "
               "to limit loading) from MID to the output with C2 from the output to GND.",
        "rlc": "series damping resistor R1 then inductor L1 from the input to the output node, with C1 from the "
               "output node to GND (damped for a near-maximally-flat response, Q ≈ 0.7).",
    }[topo]
    intent = f"""
# {b.title}

Removes high-frequency content from the signal entering on J1 (pin 1 = input, pin 2 = GND) and
delivers the filtered signal on J2 (pin 1 = output, pin 2 = GND). Grounds of J1 and J2 are common.

Topology: {desc}

Spec: order {order}; -3 dB corner {fc:.4g} Hz ±10 %; passband gain ≈ {g_pass:.3f} at fc/20;
attenuation at 10·fc: gain {g_stop:.3g} ±25 %.

{parts_summary([("input connector", ["J1"]), ("filter network", sorted(vals)), ("output connector", ["J2"])])}
"""
    params = {"topology": topo, "fc_hz": round(fc, 3), "order": order}
    vb = Bounds(FAMILY, seed)
    for ref, val in sorted(vals.items()):
        vb.spec(ref, val)  # every R/L/C sets fc / passband / stopband: sanity range only (bounds R-vs-C scaling)
    return golden(FAMILY, seed, b, assertions, {"GND": 0.3}, [], intent, params, value_bounds=vb.out)
