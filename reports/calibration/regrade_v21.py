"""Regrade committed calibration deliverables with the current (v2.1) verifier against the
archived v2.0 task dirs they were attempted on; report every verdict change.

  python3 reports/calibration/regrade_v21.py [--archive tasks/v2.0_archive]
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcbenv.verify import verify_isolated  # noqa: E402

RUNS = {"v2hard": "hard", "v2hard_layout": "hard_layout", "v2hard_sonnet_high_rerun": "hard"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=str(ROOT / "tasks" / "v2.0_archive"))
    a = ap.parse_args()
    out = {}
    for run, tier in RUNS.items():
        d = ROOT / "reports" / "calibration" / run
        rows = [json.loads(l) for l in (d / "rollouts.jsonl").read_text().splitlines()]
        tmp = Path(tempfile.mkdtemp())
        with tarfile.open(d / "deliverables.tar.gz") as tar:
            tar.extractall(tmp, filter="data")

        def one(r):
            wd = tmp / f"job{r['job']:04d}"
            res = verify_isolated(str(wd), str(Path(a.archive) / tier / r["task_id"]))
            return {**r, "reward_v21": res.reward,
                    "failed_v21": [k for k, v in {**res.gates, **res.checks}.items() if not v]}

        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(one, rows))
        changes = [r for r in res if r["reward_v21"] != r["reward"]]
        (d / "regrade_v21.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in res))
        out[run] = {"n": len(res), "changed": len(changes),
                    "0->1": sum(r["reward"] == 0 and r["reward_v21"] == 1 for r in changes),
                    "1->0": sum(r["reward"] == 1 and r["reward_v21"] == 0 for r in changes),
                    "examples": [(r["model"], r["task_id"], r["failed"], r["failed_v21"]) for r in changes[:8]]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
