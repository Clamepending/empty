"""LDO model vs analytic: random E24/E96 feedback dividers that meet the spec analytically.

    PYTHONPATH=. python3 reports/v2/ldo_analytic_agreement.py [N] [seed]

For N random (vout target, vin, load, Rbot, Rtop) with Rbot in the datasheet range and Rtop the
nearest E24/E96 value such that 0.8*(1+Rtop/Rbot) is within ±3 % of the target, simulate the
ldo_reg circuit (at vin and at the minimum vin = vout + 0.6 V) and compare with the analytic
VOUT = 0.8*(1 + Rtop/Rbot). Prints the worst relative deviation; exit 1 if any > 1 % or any
simulation does not converge.
"""
from __future__ import annotations

import random
import sys

from pcbenv import sim
from pcbenv.families._common import E24, E96, nearest, series_values, vstr


def case(rng: random.Random) -> tuple[dict, list[dict], float]:
    vout_t = rng.choice([1.2, 1.5, 1.8, 2.5, 2.8, 3.0, 3.3, 5.0]) * rng.uniform(0.9, 1.1)
    series = rng.choice([E24, E96])
    while True:
        rbot = rng.choice(series_values(series, 3.3e3, 150e3))
        rtop = nearest(series, rbot * (vout_t / 0.8 - 1))
        va = 0.8 * (1 + rtop / rbot)
        if abs(va / vout_t - 1) <= 0.03:
            break
    vin = rng.choice([v for v in (3.3, 5.0, 9.0, 12.0, 16.0) if v >= va + 0.6] or [16.0])
    iload = rng.choice([0.001, 0.01, 0.05, 0.1, 0.2, 0.25, 0.3])
    while (vin - va) * iload > 0.5 and iload > 0.001:
        iload /= 2
    design = {"schema": "pcbenv/design@1", "title": "ldo", "components": {
        "J1": {"part": "CONN2", "value": "", "footprint": ""}, "J2": {"part": "CONN2", "value": "", "footprint": ""},
        "U1": {"part": "LDO_ADJ", "value": "", "footprint": ""},
        "C1": {"part": "C", "value": "1u", "footprint": ""}, "C2": {"part": "C", "value": "1u", "footprint": ""},
        "R1": {"part": "R", "value": vstr(rtop), "footprint": ""}, "R2": {"part": "R", "value": vstr(rbot), "footprint": ""}},
        "nets": {"VIN": ["J1.1", "U1.VIN", "U1.EN", "C1.1"], "GND": ["J1.2", "U1.GND", "C1.2", "C2.2", "R2.2", "J2.2"],
                 "VOUT": ["U1.VOUT", "C2.1", "R1.1", "J2.1"], "FB": ["R1.2", "R2.1", "U1.FB"]}}
    rl = round(va / iload, 4)
    asserts = [{"name": f"vout_{tag}", "type": "dc_voltage", "net_pin": "J2.1", "ground_pin": "J1.2",
                "supply": {"pin": "J1.1", "volts": v}, "loads": [{"pin": "J2.1", "r": rl}]}
               for tag, v in (("vin", vin), ("vin_min", round(va + 0.6, 3)))]
    return design, asserts, va


def main(n: int = 500, seed: int = 2026) -> int:
    rng = random.Random(seed)
    worst, bad = 0.0, 0
    for k in range(n):
        d, asserts, va = case(rng)
        for r in sim.run_assertions(d, asserts):
            if r.measured is None:
                bad += 1
                print(f"case {k}: {r.name} {r.detail}")
                continue
            dev = abs(r.measured / va - 1)
            worst = max(worst, dev)
            if dev > 0.01:
                bad += 1
                print(f"case {k}: {r.name} sim {r.measured:.5g} analytic {va:.5g} ({dev*100:.2f} %)")
    print(f"{n} dividers x 2 input voltages: worst |sim/analytic - 1| = {worst*100:.3f} %, "
          f"{bad} outside 1 % or not converged; sim stats {sim.STATS}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:3])))
