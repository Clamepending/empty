"""Fault injection on the composite (hard-tier) families: every v1 fault type, applied to
composite goldens, must give a valid task that the verifier scores 0 (faulted) / 1 (oracle =
golden restored), and a pcbtool repair (tests/test_faults.realistic_repair) must score 1.

    PYTHONPATH=. python3 reports/v2/composite_faults.py [seeds=3] [workers=3]
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from multiprocessing import get_context
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PCBTOOL = str(ROOT / "bin" / "pcbtool")


def one(args):
    fam, seed = args
    from pcbenv.board import build_board
    from pcbenv.faults import FAULT_TYPES, apply_fault
    from pcbenv.families import FAMILIES
    from pcbenv.taskio import write_task
    from pcbenv.verify import verify
    from tests.test_faults import realistic_repair
    g = FAMILIES[fam].generate(seed)
    out = []
    with tempfile.TemporaryDirectory(prefix="hardf_") as root:
        gboard = os.path.join(root, "golden.kicad_pcb")
        build_board(g, gboard, 0)
        for name in sorted(FAULT_TYPES):
            design = json.loads(json.dumps(g.design))
            base = os.path.join(root, name)
            os.makedirs(base)
            board = os.path.join(base, "faulted.kicad_pcb")
            shutil.copyfile(gboard, board)
            try:
                rec = apply_fault(name, g, design, board, random.Random(f"hard:{fam}:{seed}:{name}"), salt="h")
            except Exception as e:  # noqa: BLE001
                out.append((fam, seed, name, "invalid", str(e)[:200]))
                continue
            if rec is None:
                out.append((fam, seed, name, "n/a", ""))
                continue
            td = os.path.join(base, "task")
            write_task(td, g, gboard, public_design=design, public_board=board, faults=[rec.to_dict()])
            faulted = verify(os.path.join(td, "public"), td).reward
            oracle = os.path.join(base, "oracle")
            shutil.copytree(os.path.join(td, "public"), oracle)
            shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(oracle, "design.json"))
            shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(oracle, "board.kicad_pcb"))
            orc = verify(oracle, td).reward
            wd = os.path.join(base, "agent")
            shutil.copytree(os.path.join(td, "public"), wd)
            for cmd in realistic_repair(rec.to_dict(), wd):
                subprocess.run([PCBTOOL, *cmd], cwd=wd, capture_output=True, text=True, timeout=300)
            rep = verify(wd, td).reward
            status = "ok" if (faulted == 0.0 and orc == 1.0) else "BAD"
            out.append((fam, seed, name, status, f"faulted={faulted} oracle={orc} repair={rep} {rec.detail}"[:240]))
    return out


def main(n: int = 3, workers: int = 3) -> int:
    from pcbenv.families import HARD_FAMILIES
    jobs = [(f, s) for s in range(n) for f in HARD_FAMILIES]
    with get_context("spawn").Pool(workers, maxtasksperchild=2) as pool:
        res = [r for rs in pool.map(one, jobs, chunksize=1) for r in rs]
    per = defaultdict(lambda: defaultdict(int))
    repaired = defaultdict(int)
    bad = 0
    for fam, seed, name, status, detail in res:
        per[name][status] += 1
        if "repair=1.0" in detail:
            repaired[name] += 1
        if status in ("BAD", "invalid"):
            bad += 1
            print(f"{status} {fam} {seed} {name}: {detail}")
    for name in sorted(per):
        print(f"{name:24s} {dict(per[name])} pcbtool-repaired {repaired[name]}")
    print(f"total applied {sum(v['ok'] + v['BAD'] for v in per.values())}, bad {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*(int(x) for x in sys.argv[1:3])))
