"""Grade the v2 hard-tier calibration (G12): verify each workdir, re-verify the oracle, audit
transcripts for contamination. Incremental: results are appended to a cache so a container
restart never loses grading work.

  python3 reports/calibration/grade_v2hard.py grade --plan PLAN --jobs 1-132 [--transcripts DIR ...]
  python3 reports/calibration/grade_v2hard.py summary
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import shutil
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade import audit  # noqa: E402
from pcbenv.verify import verify_isolated  # noqa: E402

OUT = ROOT / "reports" / "calibration" / "v2hard"
CACHE = OUT / "rollouts.jsonl"
DELIV = OUT / "deliverables.tar.gz"


def _done() -> dict[int, dict]:
    if not CACHE.exists():
        return {}
    return {r["job"]: r for r in map(json.loads, CACHE.read_text().splitlines())}


def grade(plan_path: str, jobs: set[int], transcripts: list[str]) -> None:
    plan = json.loads(Path(plan_path).read_text())
    done = _done()
    todo = [(wd, m) for wd, m in sorted(plan["mapping"].items()) if int(wd[-4:]) in jobs and int(wd[-4:]) not in done]
    OUT.mkdir(parents=True, exist_ok=True)

    def one(item):
        wd, m = item
        td = ROOT / "tasks" / m["split"] / m["task_id"]
        res = verify_isolated(wd, str(td))
        o = Path(tempfile.mkdtemp())
        shutil.copytree(td / "public", o, dirs_exist_ok=True)
        shutil.copy(td / "hidden" / "golden_design.json", o / "design.json")
        shutil.copy(td / "hidden" / "golden_board.kicad_pcb", o / "board.kicad_pcb")
        oracle = verify_isolated(str(o), str(td)).reward
        return {"job": int(wd[-4:]), "task_id": m["task_id"], "model": m["model"], "reward": res.reward,
                "failed": [k for k, v in {**res.gates, **res.checks}.items() if not v], "oracle": oracle}

    with ThreadPoolExecutor(4) as ex, CACHE.open("a") as f:
        for r in ex.map(one, todo):
            f.write(json.dumps(r, sort_keys=True) + "\n")
            f.flush()
    if transcripts:
        viol = audit(transcripts)
        rows = list(_done().values())
        for r in rows:
            r["audited"] = r["job"] in viol
            r["violations"] = viol.get(r["job"], [])[:5]
            r["contaminated"] = bool(r["violations"])
        CACHE.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in sorted(rows, key=lambda r: r["job"])))
    # Keep the graded deliverables so the numbers can be re-verified later.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for wd in sorted(plan["mapping"]):
            j = int(wd[-4:])
            if j not in _done():
                continue
            for name in ("design.json", "board.kicad_pcb"):
                p = Path(wd) / name
                if p.is_file():
                    data = p.read_bytes()
                    ti = tarfile.TarInfo(f"job{j:04d}/{name}")
                    ti.size, ti.mtime, ti.mode = len(data), 0, 0o644
                    tar.addfile(ti, io.BytesIO(data))
    DELIV.write_bytes(buf.getvalue())
    print(f"graded {len(todo)} new; total {len(_done())}")


def summary() -> None:
    rows = list(_done().values())
    man = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "tasks" / "manifest.jsonl").read_text().splitlines()}
    clean = [r for r in rows if not r.get("contaminated")]
    print(f"rollouts {len(rows)}; contaminated {len(rows) - len(clean)}; oracle != 1: {sum(r['oracle'] != 1 for r in rows)}")
    for key, name in ((lambda r: "all", "Overall"), (lambda r: man[r["task_id"]]["family"], "By family"),
                      (lambda r: man[r["task_id"]]["n_faults"], "By number of faults"),
                      (lambda r: man[r["task_id"]].get("tools_mode", "?"), "By tool mode")):
        acc = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in clean:
            acc[key(r)][r["model"]].append(r["reward"])
        print(f"\n## {name}\n| group | haiku | sonnet | opus |\n|---|---|---|---|")
        for g in sorted(acc, key=str):
            cells = [f"{sum(v) / len(v):.0%} ({int(sum(v))}/{len(v)})" if (v := acc[g][m]) else "–" for m in ("haiku", "sonnet", "opus")]
            print(f"| {g} | " + " | ".join(cells) + " |")
    fails = collections.Counter(f for r in clean if r["reward"] == 0 for f in r["failed"])
    print("\n## Failing gate/check counts among failed rollouts")
    for k, v in fails.most_common():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--plan", required=True)
    g.add_argument("--jobs", required=True, help="e.g. 1-132 or 1,2,5")
    g.add_argument("--transcripts", nargs="*", default=[])
    sub.add_parser("summary")
    a = ap.parse_args()
    if a.cmd == "grade":
        js: set[int] = set()
        for part in a.jobs.split(","):
            lo, _, hi = part.partition("-")
            js |= set(range(int(lo), int(hi or lo) + 1))
        grade(a.plan, js, a.transcripts)
    else:
        summary()
