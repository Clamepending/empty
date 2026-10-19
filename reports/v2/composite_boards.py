"""Composite (hard-tier) families: golden task build (board placed, routed, DRC-checked) + verify.

    PYTHONPATH=. python3 reports/v2/composite_boards.py [seeds=20] [workers=3] [verify_seeds=10]

For every hard family x seed: `taskio.make_golden_task` (build_board + task files), DRC / board
partition / power widths / decoupling via the verifier; for the first `verify_seeds` seeds the
full verifier (`pcbenv.verify.verify`) must return reward 1.0. Prints per-family part counts,
assertion counts, board size and build-time median/max. Exit 1 on any failure.
"""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from multiprocessing import get_context


def one(args):
    fam, seed, do_verify = args
    import os
    from pcbenv import boardnet, design as D
    from pcbenv.drc import run_drc
    from pcbenv.families import FAMILIES
    from pcbenv.taskio import make_golden_task
    g = FAMILIES[fam].generate(seed)
    with tempfile.TemporaryDirectory(prefix="hardb_") as td:
        t = time.monotonic()
        try:
            task = make_golden_task(g, os.path.join(td, "t"), 0, task_id=f"{fam}-{seed}")
        except Exception as e:  # noqa: BLE001
            return fam, seed, len(g.design["components"]), len(g.assertions), (g.board_w_mm, g.board_h_mm), None, \
                f"build: {e}"[:300], None
        dt = time.monotonic() - t
        bp = os.path.join(task, "public", "board.kicad_pcb")
        err = None
        r = run_drc(bp, bp)
        if r.errors or r.unconnected:
            err = f"DRC {len(r.errors)} errors, {r.unconnected} unconnected"
        elif boardnet.board_info(bp, g.design).partition != D.partition(g.design):
            err = "board partition != design partition"
        reward = None
        if do_verify and err is None:
            from pcbenv.verify import verify_isolated
            v = verify_isolated(os.path.join(task, "public"), task)
            reward = v.reward
            if v.reward != 1.0:
                err = f"verify reward {v.reward}: {v.detail}"[:400]
    return fam, seed, len(g.design["components"]), len(g.assertions), (g.board_w_mm, g.board_h_mm), dt, err, reward


def main(n: int = 20, workers: int = 3, nv: int = 10) -> int:
    from pcbenv.families import HARD_FAMILIES
    jobs = [(f, s, s < nv) for s in range(n) for f in HARD_FAMILIES]
    with get_context("spawn").Pool(workers, maxtasksperchild=4) as pool:
        out = pool.map(one, jobs, chunksize=1)
    bad = 0
    for fam in HARD_FAMILIES:
        rows = [o for o in out if o[0] == fam]
        times = [o[5] for o in rows if o[5] is not None]
        parts = [o[2] for o in rows]
        nas = [o[3] for o in rows]
        sizes = sorted({o[4] for o in rows})
        ok_v = sum(1 for o in rows if o[7] == 1.0)
        fails = [o for o in rows if o[6]]
        bad += len(fails)
        print(f"{fam}: {len(rows) - len(fails)}/{len(rows)} boards DRC-clean, verify 1.0 on {ok_v}/{sum(1 for o in rows if o[1] < nv)}; "
              f"parts {min(parts)}-{max(parts)}, assertions {min(nas)}-{max(nas)}, boards "
              f"{sizes[0][0]:g}x{sizes[0][1]:g}..{sizes[-1][0]:g}x{sizes[-1][1]:g} mm; build median "
              f"{statistics.median(times):.1f} s max {max(times):.1f} s")
        for o in fails:
            print(f"  FAIL {fam} seed {o[1]}: {o[6]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:4])))
