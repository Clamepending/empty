"""Broad self-consistency sweep of the family generators.

    python3 -m pcbenv.families.sweep --seeds 0:2000 [--families ldo_reg,led_driver] [--workers 8]

For every (family, seed): generate the golden, `design.validate` it, run all its own assertions
(all must pass) and check every valued component lies inside its `value_bounds` (and every
valued component has a bound). Exit status 1 if any (family, seed) fails; failures are printed.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from multiprocessing import get_context


def check(args: tuple[str, int]) -> tuple[str, int, str | None]:
    """(family, seed, None) if the golden is self-consistent, else (family, seed, reason)."""
    family, seed = args
    try:
        from pcbenv.design import validate
        from pcbenv.families import FAMILIES
        from pcbenv.families._common import check_bounds
        from pcbenv.sim import run_assertions

        g = FAMILIES[family].generate(seed)
        if g.family != family or g.seed != seed:
            return family, seed, "family/seed mismatch"
        validate(g.design)
        check_bounds(g.design, g.value_bounds)
        res = run_assertions(g.design, g.assertions)
        if len(res) != len(g.assertions):
            return family, seed, f"{len(res)} results for {len(g.assertions)} assertions"
        bad = [f"{r.name}: measured {r.measured} expected {r.expected} {r.detail}".strip()
               for r in res if not r.passed]
        if bad:
            return family, seed, "; ".join(bad)
    except Exception as e:  # noqa: BLE001
        return family, seed, f"exception {type(e).__name__}: {e} {traceback.format_exc()[-400:]}"
    return family, seed, None


def sweep(families: list[str], seeds: list[int], workers: int = 0) -> list[tuple[str, int, str]]:
    """All failures, sorted by (family, seed)."""
    jobs = [(f, s) for f in families for s in seeds]
    workers = workers or os.cpu_count() or 1
    if workers <= 1:
        results = map(check, jobs)
        fails = [r for r in results if r[2] is not None]
    else:
        with get_context("spawn").Pool(workers) as pool:
            fails = [r for r in pool.imap_unordered(check, jobs, chunksize=8) if r[2] is not None]
    return sorted(fails)


def _parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            out.extend(range(int(a), int(b)))
        else:
            out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    from pcbenv.families import FAMILIES

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", default="0:2000", help="start:stop (half-open) or comma list")
    ap.add_argument("--families", default="", help="comma list (default: all)")
    ap.add_argument("--workers", type=int, default=0, help="worker processes (default: cpu count)")
    a = ap.parse_args(argv)
    fams = [f for f in a.families.split(",") if f] or sorted(FAMILIES)
    seeds = _parse_seeds(a.seeds)
    fails = sweep(fams, seeds, a.workers)
    for f, s, why in fails:
        print(f"FAIL {f} seed {s}: {why}")
    per = {f: sum(1 for x in fails if x[0] == f) for f in fams}
    for f in fams:
        print(f"{f:14s} {len(seeds) - per[f]}/{len(seeds)} ok")
    print(f"total: {len(fams) * len(seeds) - len(fails)}/{len(fams) * len(seeds)} ok, {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
