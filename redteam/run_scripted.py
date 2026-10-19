"""Apply every scripted attack to many faulted tasks and report hacks/crashes/timeouts.

    python3 redteam/run_scripted.py --n 1000 [--workers 8] [--seed 0] [--json out.json]

A pair (task, attack) counts as a *hack* when the faulted task's baseline (unchanged public
files) scores 0.0 and the attacked workdir scores 1.0. Tasks whose faulted baseline already
scores 1.0 (fault invisible to the verifier) are reported separately and not attacked.
Deterministic: task list and pair order derive from --seed only.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import shutil
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcbenv.verify import verify_isolated  # noqa: E402
from redteam import tasks_fixture  # noqa: E402
from redteam.attacks import ATTACKS  # noqa: E402
from redteam.attacks.basic import LEGIT_FOR  # noqa: E402


def _build(spec: tuple) -> str:
    return tasks_fixture.build(*spec)


def _grade(task_dir: str, attack: str | None) -> dict:
    tmp = tempfile.mkdtemp(prefix="rt_wd_")
    wd = os.path.join(tmp, "work")
    try:
        shutil.copytree(os.path.join(task_dir, "public"), wd)
        if attack:
            try:
                ATTACKS[attack](wd)
            except Exception as e:  # noqa: BLE001 - attack failing to apply is not a verifier crash
                return {"task": task_dir, "attack": attack, "status": "attack_error", "detail": repr(e)[:300]}
        r = verify_isolated(wd, task_dir, timeout=120)
        err = str(r.detail.get("error", ""))
        if "timed out" in err:
            status = "timeout"
        elif "subprocess failed" in err or (err and r.reward == 0 and not r.gates):
            status = "crash"
        else:
            status = "pass" if r.reward == 1.0 else "fail"
        return {"task": task_dir, "attack": attack, "status": status, "reward": r.reward,
                "failed": sorted([k for k, v in {**r.gates, **r.checks}.items() if not v]), "error": err[:300]}
    except Exception:  # noqa: BLE001
        return {"task": task_dir, "attack": attack, "status": "crash", "error": traceback.format_exc()[-300:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _grade_args(a: tuple) -> dict:
    return _grade(*a)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 2))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json")
    a = ap.parse_args()
    names = sorted(ATTACKS)
    per_seed = len(tasks_fixture.all_specs(range(1, 2)))
    nseeds = max(1, -(-a.n // (per_seed * max(1, len(names) - 2))) + 1)
    specs = tasks_fixture.all_specs(range(1, 1 + nseeds))
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers, maxtasksperchild=10) as pool:
        tds = pool.map(_build, specs)
        base = pool.map(_grade_args, [(t, None) for t in tds])
    invisible = sorted(b["task"] for b in base if b["status"] == "pass")
    bad_base = [b for b in base if b["status"] not in ("pass", "fail")]
    targets = [(t, k) for t, (f, s, k), b in zip(tds, specs, base) if b["status"] == "fail"]
    pairs = [(t, n) for t, k in targets for n in names if k not in LEGIT_FOR.get(n, ())]
    random.Random(a.seed).shuffle(pairs)
    pairs = sorted(pairs[: a.n])
    with ctx.Pool(a.workers, maxtasksperchild=10) as pool:
        res = pool.map(_grade_args, pairs, chunksize=4)
    c = Counter(r["status"] for r in res)
    hacks = [r for r in res if r["status"] == "pass"]
    print(f"tasks built: {len(tds)}  faulted-baseline invisible (score 1.0, not attacked): {len(invisible)}  "
          f"baseline crashes: {len(bad_base)}")
    print(f"attack applications: {len(res)}  attacks: {len(names)}")
    print(f"successes (hacks): {len(hacks)}  crashes: {c['crash']}  timeouts: {c['timeout']}  "
          f"attack_errors: {c['attack_error']}  blocked: {c['fail']}")
    per = Counter((r["attack"], r["status"]) for r in res)
    for n in names:
        print(f"  {n:22s} " + " ".join(f"{s}={per[(n, s)]}" for s in ("fail", "pass", "crash", "timeout", "attack_error")
                                        if per[(n, s)]))
    for h in hacks[:20]:
        print("HACK", h["attack"], h["task"])
    for r in [r for r in res if r["status"] in ("crash", "timeout")][:10]:
        print(r["status"].upper(), r["attack"], r["task"], r.get("error", "")[:200])
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": dict(c), "invisible": invisible, "results": res}, indent=1))
    return 1 if hacks or c["crash"] or c["timeout"] else 0


if __name__ == "__main__":
    sys.exit(main())
