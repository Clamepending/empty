"""Grade calibration rollouts and audit agent transcripts for contamination.

Usage:
  python3 reports/calibration/grade.py collect --plan PLAN.json --transcripts DIR [DIR ...]
      grade every workdir in the plan, audit transcripts, write rollouts.jsonl +
      deliverables.tar.gz into reports/calibration/
  python3 reports/calibration/grade.py regrade
      re-verify every committed deliverable from deliverables.tar.gz and check the
      rewards equal rollouts.jsonl (reproducibility check for the baseline report)
  python3 reports/calibration/grade.py summary
      print the calibration tables used by reports/baseline.md
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import re
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pcbenv.verify import verify_isolated  # noqa: E402

OUT = ROOT / "reports" / "calibration"
ROLLOUTS = OUT / "rollouts.jsonl"
DELIV = OUT / "deliverables.tar.gz"
THRESH = json.loads(json.dumps(__import__("yaml").safe_load((ROOT / "thresholds.yaml").read_text())))

# Anything an honest solver never needs to touch. Executing bin/pcbtool is allowed.
FORBIDDEN = [
    (re.compile(r"/home/user/empty/(?!bin/pcbtool)"), "repo path"),
    (re.compile(r"\bhidden/|golden_|golden\.|manifest\.jsonl"), "hidden/golden data"),
    (re.compile(r"import\s+pcbenv|from\s+pcbenv|import\s+pcbnew|pcbenv\.(verify|families|generate|faults)"), "imports pcbenv/pcbnew"),
    (re.compile(r"\.tar\.gz|dist/pcb-repair"), "task bundle"),
]
JOB_RE = re.compile(r"/calib/w/job(\d{4})")


def _tool_inputs(transcript: Path):
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield json.dumps(block.get("input", {}))


def audit(transcript_dirs: list[str]) -> dict[int, list[str]]:
    """Map job number -> list of violations found in the transcript(s) that worked on it."""
    violations: dict[int, list[str]] = collections.defaultdict(list)
    for d in transcript_dirs:
        for t in Path(d).rglob("*.jsonl"):
            if t.name == "journal.jsonl":
                continue
            inputs = list(_tool_inputs(t))
            jobs = {int(m) for s in inputs for m in JOB_RE.findall(s)}
            if not jobs:
                continue
            own = set(jobs)
            found = []
            for s in inputs:
                for rx, why in FORBIDDEN:
                    if rx.search(s):
                        found.append(f"{why}: {s[:160]}")
            # Touching more than its own (≤3) job dirs means peeking at other attempts.
            if len(own) > 3:
                found.append(f"touched {len(own)} job dirs: {sorted(own)}")
            for j in own:
                violations[j].extend(found)
                violations.setdefault(j, violations[j])
    return violations


def collect(plan_path: str, transcript_dirs: list[str]) -> None:
    plan = json.loads(Path(plan_path).read_text())
    mapping = plan["mapping"]
    viol = audit(transcript_dirs)
    audited_jobs = set(viol)

    def grade(item):
        wd, m = item
        task_dir = ROOT / "tasks" / "train" / m["task_id"]
        res = verify_isolated(wd, str(task_dir))
        failed = [k for k, v in {**res.gates, **res.checks}.items() if not v]
        return wd, res.reward, failed

    with ThreadPoolExecutor(4) as ex:
        graded = list(ex.map(grade, sorted(mapping.items())))

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for wd, reward, failed in graded:
            m = mapping[wd]
            job = int(wd[-4:])
            rows.append({
                "job": job, "task_id": m["task_id"], "model": m["model"], "attempt": m["attempt"],
                "reward": reward, "failed": failed,
                "audited": job in audited_jobs, "contaminated": bool(viol.get(job)),
                "violations": viol.get(job, [])[:5],
            })
            for name in ("design.json", "board.kicad_pcb"):
                p = Path(wd) / name
                if p.is_file():
                    data = p.read_bytes()
                    ti = tarfile.TarInfo(f"job{job:04d}/{name}")
                    ti.size, ti.mtime, ti.mode = len(data), 0, 0o644
                    tar.addfile(ti, io.BytesIO(data))
    DELIV.write_bytes(buf.getvalue())
    ROLLOUTS.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"graded {len(rows)} rollouts -> {ROLLOUTS}")


def regrade() -> None:
    rows = [json.loads(l) for l in ROLLOUTS.read_text().splitlines()]
    tmp = Path(tempfile.mkdtemp())
    with tarfile.open(DELIV) as tar:
        tar.extractall(tmp, filter="data")

    def one(r):
        wd = tmp / f"job{r['job']:04d}"
        wd.mkdir(exist_ok=True)
        return r, verify_isolated(str(wd), str(ROOT / "tasks" / "train" / r["task_id"])).reward

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, rows))
    mism = [(r["job"], r["reward"], got) for r, got in res if got != r["reward"]]
    print(f"regraded {len(res)}; mismatches: {len(mism)} {mism[:10]}")
    sys.exit(1 if mism else 0)


def summary() -> None:
    rows = [json.loads(l) for l in ROLLOUTS.read_text().splitlines()]
    clean = [r for r in rows if not r["contaminated"]]
    print(f"rollouts: {len(rows)}; contaminated (excluded): {len(rows) - len(clean)}; not matched to a transcript: {sum(not r['audited'] for r in rows)}")
    meta = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "tasks" / "manifest.jsonl").read_text().splitlines()}

    def table(key):
        acc = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in clean:
            acc[key(r)][r["model"]].append(r["reward"])
        models = ["haiku", "sonnet", "opus"]
        print("| " + " | ".join(["group"] + models) + " |")
        print("|" + "---|" * (len(models) + 1))
        for g in sorted(acc, key=str):
            cells = []
            for m in models:
                v = acc[g][m]
                cells.append(f"{sum(v) / len(v):.0%} ({int(sum(v))}/{len(v)})" if v else "–")
            print(f"| {g} | " + " | ".join(cells) + " |")
        print()

    print("## Overall"); table(lambda r: "all")
    print("## By family"); table(lambda r: meta[r["task_id"]]["family"])
    print("## By hint level"); table(lambda r: meta[r["task_id"]]["hint_level"])
    print("## By number of faults"); table(lambda r: meta[r["task_id"]]["n_faults"])

    lo, hi = THRESH["tasks"]["learnable_band"]
    per_task = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in clean:
        per_task[r["task_id"]][r["model"]].append(r["reward"])
    pooled_in = sum(1 for t in per_task.values() if lo <= sum(sum(v) for v in t.values()) / sum(len(v) for v in t.values()) <= hi)
    n = len(per_task)
    tiers = collections.Counter()
    for t in per_task.values():
        allr = [x for v in t.values() for x in v]
        p = sum(allr) / len(allr)
        tiers["easy (>70%)" if p > hi else "hard (<10%)" if p < lo else "learnable (10–70%)"] += 1
    print(f"## Learnable band ({lo:.0%}–{hi:.0%}, pooled over all attempts of all models per task)")
    print(f"tasks in band: {pooled_in}/{n} = {pooled_in / n:.0%} (threshold ≥ {THRESH['tasks']['learnable_share_of_sample_min']:.0%})")
    print("tiers:", dict(tiers))
    fails = collections.Counter(f for r in clean if r["reward"] == 0 for f in r["failed"])
    print("\n## Failing gate/check counts among failed rollouts")
    for k, v in fails.most_common():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--plan", required=True)
    c.add_argument("--transcripts", nargs="+", required=True)
    sub.add_parser("regrade")
    sub.add_parser("summary")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.plan, a.transcripts)
    elif a.cmd == "regrade":
        regrade()
    else:
        summary()
