"""DC operating-point audit: does the PLAIN Newton solve (no rescue) converge for every golden?

    PYTHONPATH=. python3 reports/v2/op_convergence_audit.py [seeds=30] [workers=4]

For every family x seed: every DC scenario the golden's assertions use (as the hard-tier design
rules simulate them: AC dropped, released open-drain lines without a source), both with plain
nodes and with every non-connector pin current-sensed (the rules' netlist). Counts runs where
ngspice needed its transient-op fallback (or timed out). Also runs the assertions and reports
the sim.STATS rescue counters. Exit 1 if any plain solve failed.
"""
from __future__ import annotations

import sys
from multiprocessing import get_context


def one(args):
    fam, seed = args
    from pcbenv import rules, sim
    from pcbenv.families import FAMILIES
    g = FAMILIES[fam].generate(seed)
    fails = []
    for i, sc in enumerate(rules.rules_context(g)["scenarios"]):
        for sensed in (False, True):
            nl = sim.Netlist(g.design, sc.get("ground_pin") or "J1.2", rules._sense_pins(g.design) if sensed else [])
            body = nl.lines() + sim._stimulus_lines(nl, {k: sc.get(k) for k in ("supply", "source", "loads")})
            try:
                _, log = sim._exec(sim._deck(body, ["op"]), [])
                if sim._fell_back(log):
                    fails.append(f"scenario {i} sensed={sensed}: transient-op fallback")
            except sim.SimError as e:
                fails.append(f"scenario {i} sensed={sensed}: {e}")
    res = sim.run_assertions(g.design, g.assertions)
    bad = [r.name for r in res if not r.passed]
    return fam, seed, fails, bad, dict(sim.STATS)


def main(n: int = 30, workers: int = 4) -> int:
    from pcbenv.families import FAMILIES
    jobs = [(f, s) for f in sorted(FAMILIES) for s in range(n)]
    with get_context("spawn").Pool(workers) as pool:
        out = pool.map(one, jobs, chunksize=4)
    nfail = 0
    rescued = 0
    for fam, seed, fails, bad, st in out:
        rescued += st["rescued"]
        for f in fails:
            nfail += 1
            print(f"PLAIN-OP FAIL {fam} {seed}: {f}")
        if bad:
            print(f"ASSERTION FAIL {fam} {seed}: {bad}")
            nfail += 1
    print(f"{len(jobs)} goldens ({len(FAMILIES)} families x {n} seeds): {nfail} plain-op failures / assertion "
          f"failures; robust-path rescues during assertions: {rescued}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:3])))
