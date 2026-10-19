"""QA F1 audit: how often the v1 sanity-only value bound was tighter than a datasheet limit.

    PYTHONPATH=. python3 reports/v2/bounds_audit.py [seeds=200]

For every family x seed and every bound a family widened to a datasheet-derived limit
(params["datasheet_limits"]), recompute the v1 sanity range (golden / 2.5..4 .. golden x 2.5..4,
same per-ref RNG as `Bounds.spec`) and count where it excluded part of the datasheet range
(v1 would reject a datasheet-valid value on `values` alone). v2 bounds contain every such limit
(asserted here and in tests/test_bounds_policy.py).
"""
from __future__ import annotations

import random
import sys
from collections import Counter


def sanity(family: str, seed: int, ref: str, v: float) -> tuple[float, float]:
    r = random.Random(f"value_bounds/{family}/{seed}/{ref}")
    lo, hi = 2.5 + 1.5 * r.random(), 2.5 + 1.5 * r.random()
    return float(f"{v / lo:.2g}"), float(f"{v * hi:.2g}")


def kind(g, ref: str) -> str:
    roles = g.params.get("roles") or {}
    for k, refs in roles.items():
        if ref in refs:
            return k
    return {"mcu_i2c": "pull", "npn_switch": "base/led", "led_driver": "led_res", "xtal_osc": "led_res",
            "ldo_reg": "led_res"}.get(g.family, "?")


def main(n: int = 200) -> int:
    from pcbenv.families import FAMILIES
    from pcbenv.parts import parse_value
    tot, tight_lo, tight_hi, bad = Counter(), Counter(), Counter(), 0
    for fam in sorted(FAMILIES):
        for s in range(n):
            g = FAMILIES[fam].generate(s)
            for ref, (dlo, dhi) in (g.params.get("datasheet_limits") or {}).items():
                key = (fam, kind(g, ref))
                tot[key] += 1
                v = parse_value(g.design["components"][ref]["value"])
                slo, shi = sanity(fam, s, ref, v)
                if dlo is not None and slo > dlo:
                    tight_lo[key] += 1
                if dhi is not None and shi < dhi:
                    tight_hi[key] += 1
                lo, hi = g.value_bounds[ref]
                if (dlo is not None and lo > dlo * (1 + 1e-9)) or (dhi is not None and hi < dhi * (1 - 1e-9)):
                    bad += 1
                    print(f"STILL TIGHT {fam} {s} {ref}: bound {lo}-{hi}, datasheet {dlo}-{dhi}")
    print(f"{'family':22s} {'role':10s} {'bounds':>7s} {'v1 min > datasheet min':>24s} {'v1 max < datasheet max':>24s}")
    for key in sorted(tot):
        print(f"{key[0]:22s} {key[1]:10s} {tot[key]:7d} {tight_lo[key]:24d} {tight_hi[key]:24d}")
    print(f"total {sum(tot.values())} datasheet-limited bounds over {n} seeds/family; v1-style sanity range too tight "
          f"in {sum(tight_lo.values())} (min) + {sum(tight_hi.values())} (max) cases; v2 bounds still tight: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:2])))
