"""Re-verify every shipped v2.1 task (tasks/manifest.jsonl + tasks/refresh-v2/*/manifest.jsonl) with
the current verifier: faulted public files -> 0.0, oracle repair (hidden golden files) -> 1.0.
Worker processes; restart-safe (results appended to recheck_v21.jsonl).

    python3 reports/v2/recheck_v21.py > reports/v2/recheck_v21.txt
"""
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "v2" / "recheck_v21.jsonl"


def one(r: dict) -> dict:
    from pcbenv.verify import verify
    td = str(ROOT / "tasks" / r["path"])
    res = {"id": r["id"], "split": r["split"]}
    for kind in ("faulted", "oracle"):
        w = tempfile.mkdtemp(prefix="recheck_")
        shutil.copytree(td + "/public", w, dirs_exist_ok=True)
        if kind == "oracle":
            shutil.copy(td + "/hidden/golden_design.json", w + "/design.json")
            shutil.copy(td + "/hidden/golden_board.kicad_pcb", w + "/board.kicad_pcb")
        v = verify(w, td)
        res[kind] = v.reward
        if kind == "oracle" and v.reward != 1.0:
            res["oracle_failing"] = sorted(k for k, ok in {**v.gates, **v.checks}.items() if not ok)
        shutil.rmtree(w, ignore_errors=True)
    return res


def rows() -> list[dict]:
    out = [json.loads(x) for x in (ROOT / "tasks" / "manifest.jsonl").read_text().splitlines() if x.strip()]
    for sp in ("normal", "hard"):
        m = ROOT / "tasks" / "refresh-v2" / sp / "manifest.jsonl"
        if m.exists():
            for x in m.read_text().splitlines():
                if x.strip():
                    r = json.loads(x)
                    r["path"] = f"refresh-v2/{sp}/{r['id']}"
                    r["split"] = f"refresh-v2/{sp}"
                    out.append(r)
    return out


if __name__ == "__main__":
    allrows = rows()
    for r in allrows:
        r.setdefault("path", f"{r['split']}/{r['id']}")
    done = {json.loads(x)["id"] for x in OUT.read_text().splitlines()} if OUT.exists() else set()
    todo = [r for r in allrows if r["id"] not in done]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", "4")), max_tasks_per_child=20) as ex, open(OUT, "a") as f:
        for res in ex.map(one, todo, chunksize=4):
            f.write(json.dumps(res) + "\n")
            f.flush()
    ids = {r["id"] for r in allrows}
    got = [json.loads(x) for x in OUT.read_text().splitlines() if json.loads(x)["id"] in ids]
    from collections import Counter
    per = Counter(x["split"] for x in got)
    bad = [x for x in got if x["faulted"] != 0.0 or x["oracle"] != 1.0]
    print(f"rechecked {len(got)} of {len(allrows)} shipped v2.1 tasks; faulted 0.0 and oracle 1.0 for "
          f"{len(got) - len(bad)}; bad {len(bad)}")
    for sp, n in sorted(per.items()):
        print(f"  {sp}: {n}")
    for x in bad:
        print("BAD", json.dumps(x))
