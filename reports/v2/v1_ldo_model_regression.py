"""Root cause of the v1 LDO non-convergence, and the v2 fix, on ldo_reg first draws.

    PYTHONPATH=. python3 reports/v2/v1_ldo_model_regression.py [seeds=2000] [workers=4]

For every ldo_reg seed (first parameter draw, i.e. no redraw) and each of its DC conditions:
  v1 model, plain op  -> how often ngspice needed its transient-op fallback (v1 sim accepted that
                         point: e.g. seed 450 VOUT 36.9 V from 12 V)
  v1 model, v2 sim    -> assertions pass via the robust path? (rescues counted)
  v2 model, plain op  -> fallbacks (expected 0)
"""
from __future__ import annotations

import dataclasses
import random
import sys
from multiprocessing import get_context

V1_LDO = (".subckt PCB_LDO vin vss en fb vout\nRq vin vss 100k\nRen en vss 2Meg\nRdo vin vi 0.6\n"
          "Bena ena vss V=0.5*(1+tanh((v(en,vss)-1.2)/0.03))\nRena ena vss 1Meg\n"
          "Bpass vi vout I=0.5*v(ena,vss)*0.5*(1+tanh(4000*(0.8-v(fb,vss))))*tanh(max(v(vi,vout),0)/0.05)\n"
          "Rdis vout vss 1Meg\n.ends PCB_LDO")


def plain_fallbacks(g) -> int:
    from pcbenv import sim
    n = 0
    seen = set()
    for a in g.assertions:
        key = repr((a.get("supply"), a.get("loads")))
        if key in seen:
            continue
        seen.add(key)
        nl = sim.Netlist(g.design, a["ground_pin"])
        body = nl.lines() + sim._stimulus_lines(nl, a)
        _, log = sim._exec(sim._deck(body, ["op"]), [])
        n += sim._fell_back(log)
    return n


def chunk(rng_: tuple[int, int]):
    from pcbenv import sim
    from pcbenv.families import ldo_reg
    from pcbenv.parts import PARTS
    v2 = PARTS["LDO_ADJ"]
    out = {"v1_plain_fallback_seeds": [], "v1_robust_fail_seeds": [], "v2_plain_fallback_seeds": []}
    for s in range(*rng_):
        g = ldo_reg._generate(s, random.Random(s))
        PARTS["LDO_ADJ"] = dataclasses.replace(v2, models=V1_LDO)
        if plain_fallbacks(g):
            out["v1_plain_fallback_seeds"].append(s)
            if not all(r.passed for r in sim.run_assertions(g.design, g.assertions)):
                out["v1_robust_fail_seeds"].append(s)
        PARTS["LDO_ADJ"] = v2
        if plain_fallbacks(g):
            out["v2_plain_fallback_seeds"].append(s)
    out["rescued"] = sim.STATS["rescued"]
    return out


def main(n: int = 2000, workers: int = 4) -> int:
    step = max(1, n // (workers * 4))
    chunks = [(a, min(n, a + step)) for a in range(0, n, step)]
    with get_context("spawn").Pool(workers) as pool:
        res = pool.map(chunk, chunks)
    agg = {k: sorted(x for r in res for x in r[k]) for k in res[0] if k != "rescued"}
    print(f"ldo_reg first draws, seeds 0..{n - 1}:")
    print(f"  v1 model, plain op: transient-op fallback on {len(agg['v1_plain_fallback_seeds'])} seeds "
          f"{agg['v1_plain_fallback_seeds'][:40]}")
    print(f"  v1 model, v2 sim (robust path): assertions still failing on {len(agg['v1_robust_fail_seeds'])} of them "
          f"{agg['v1_robust_fail_seeds']}; rescues {sum(r['rescued'] for r in res)}")
    print(f"  v2 model, plain op: transient-op fallback on {len(agg['v2_plain_fallback_seeds'])} seeds")
    return 1 if agg["v2_plain_fallback_seeds"] or agg["v1_robust_fail_seeds"] else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:3])))
