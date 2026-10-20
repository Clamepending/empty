"""Independent spot check of shipped v2 tasks: each task re-verified in fresh processes
(`verify_isolated`, one `python3 -I` subprocess per grading): the faulted public files must score
0.0 and the oracle repair (hidden golden files copied over the public ones) must score 1.0.

    python3 qa/spot_check_v2.py --per-tier 20 --seed 2026 > reports/v2_spot_check.txt
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pcbenv.verify import verify_isolated  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tier", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--manifest", default=str(ROOT / "tasks" / "manifest.jsonl"))
    a = ap.parse_args()
    rows = [json.loads(x) for x in Path(a.manifest).read_text().splitlines() if x.strip()]
    rng = random.Random(a.seed)
    bad = 0
    for tier in ("normal", "hard"):
        pick = rng.sample(sorted((r for r in rows if r["tier"] == tier), key=lambda r: r["id"]), a.per_tier)
        for r in pick:
            td = ROOT / "tasks" / r["path"]
            with tempfile.TemporaryDirectory(prefix="spot_") as tmp:
                wd = Path(tmp) / "faulted"
                shutil.copytree(td / "public", wd)
                f = verify_isolated(str(wd), str(td))
                wo = Path(tmp) / "oracle"
                shutil.copytree(td / "public", wo)
                shutil.copyfile(td / "hidden" / "golden_design.json", wo / "design.json")
                shutil.copyfile(td / "hidden" / "golden_board.kicad_pcb", wo / "board.kicad_pcb")
                o = verify_isolated(str(wo), str(td))
            ok = f.reward == 0.0 and o.reward == 1.0
            bad += not ok
            failing = sorted(k for k, v in {**f.gates, **f.checks}.items() if not v)
            print(f"{tier:6s} {r['id']} {r['family']:20s} faults={r['n_faults']} faulted={f.reward} "
                  f"oracle={o.reward} faulted_failing={','.join(failing)} {'OK' if ok else 'MISMATCH'}", flush=True)
    print(f"\n{2 * a.per_tier - bad}/{2 * a.per_tier} tasks: faulted 0.0 and oracle 1.0 in fresh processes")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
