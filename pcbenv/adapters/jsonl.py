"""JSONL export (HF-datasets style) and batch scoring.

Export: one row per task, built ONLY from `public/` (never `hidden/`):

    {"id": task_id, "prompt": TASK.md text,
     "files": {"design.json": {"encoding": "utf-8", "content": ...},
               "board.kicad_pcb": {"encoding": "base64", "content": ...},
               "spec.json": ..., "TASK.md": ..., "parts/LDO_ADJ.md": ...},
     "metadata": {"task_id", "split", "family", "difficulty", "title", "n_assertions"}}

`metadata.family` / `difficulty` come from the manifest (or hidden/meta.json when there is no
manifest) via an allow-list; faults, seeds, params and golden data are never exported.
Load with `datasets.load_dataset("json", data_files="train.jsonl")`.

Scoring: `score_jsonl(predictions.jsonl, tasks_root)` -- each prediction row is one JSON object
`{"id": task_id, "design.json": str, "board.kicad_pcb": str}` (both files as plain text), e.g.

    {"id": "pcbr2-normal-0076521e", "design.json": "{\"components\": ...}", "board.kicad_pcb": "(kicad_pcb (version ..."}

or
`{"id", "files": {...}}` in the export's `{"encoding", "content"}` form. Each row is written to a
fresh temp workdir and graded by `verify_isolated` (one `python3 -I` subprocess per row,
`workers` in parallel). Returns `[{"id", "reward", "gates", "checks", "error"}]` in input order.

CLI:
    python3 -m pcbenv.adapters.jsonl export --tasks data [--split v2/normal] --out train.jsonl
    python3 -m pcbenv.adapters.jsonl predict-unchanged --tasks data --split v2/normal --limit 5 --out preds.jsonl
    python3 -m pcbenv.adapters.jsonl score --tasks data --predictions preds.jsonl [--out scores.jsonl] [--workers 8]

`predict-unchanged` writes a predictions file holding each task's public files unmodified (a
zero-effort baseline that scores ~0, and a template for your own predictions).
A `--split` that matches nothing prints the available splits and exits 2.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pcbenv import api
from pcbenv.verify import DELIVERABLES, MAX_FILE_BYTES

BINARY_AS_BASE64 = {"board.kicad_pcb"}
META_ALLOW = ("family", "difficulty")


def _encode(rel: str, data: bytes) -> dict:
    if rel in BINARY_AS_BASE64 or rel.endswith(".kicad_pcb"):
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}
    try:
        return {"encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


def decode_file(entry) -> bytes:
    """Inverse of the export encoding; a bare string is taken as utf-8 text."""
    if isinstance(entry, str):
        return entry.encode("utf-8")
    if isinstance(entry, dict):
        if entry.get("encoding") == "base64":
            return base64.b64decode(entry.get("content", ""), validate=True)
        return str(entry.get("content", "")).encode("utf-8")
    raise ValueError("file entry must be a string or {encoding, content}")


def task_row(ref: api.TaskRef | str) -> dict:
    """One export row for a task (TaskRef or task dir)."""
    if not isinstance(ref, api.TaskRef):
        ref = api.TaskRef(task_id=Path(ref).name, path=str(Path(ref).resolve()))
    task = api.load_task(ref.path)  # public only
    pub = Path(ref.path) / api.PUBLIC_DIR
    files = {}
    for rel in task.public_files:
        p = pub / rel
        if p.is_symlink() or not p.is_file():
            continue
        files[rel] = _encode(rel, p.read_bytes())
    meta = {"task_id": ref.task_id, "split": ref.split, "family": ref.family, "difficulty": ref.difficulty,
            "title": task.spec.get("title", ""), "n_assertions": len(task.spec.get("assertions", []))}
    if meta["family"] is None and meta["difficulty"] is None:
        mp = Path(ref.path) / api.HIDDEN_DIR / "meta.json"
        if mp.is_file():
            hidden = json.loads(mp.read_text(encoding="utf-8"))
            meta.update({k: hidden.get(k) for k in META_ALLOW})
    return {"id": ref.task_id, "prompt": task.task_md, "files": files, "metadata": meta}


def export_jsonl(tasks_root: str | os.PathLike, out_path: str | os.PathLike, split: str | None = None,
                 limit: int | None = None, strict: bool = False) -> int:
    refs = api.list_tasks(tasks_root, split=split, strict=strict)[:limit]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ref in refs:
            f.write(json.dumps(task_row(ref), sort_keys=True) + "\n")
    return len(refs)


def unchanged_predictions(tasks_root: str | os.PathLike, out_path: str | os.PathLike, split: str | None = None,
                          limit: int | None = None, strict: bool = False) -> int:
    """Predictions file with each task's PUBLIC deliverables unmodified (format template)."""
    refs = api.list_tasks(tasks_root, split=split, strict=strict)[:limit]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ref in refs:
            pub = Path(ref.path) / api.PUBLIC_DIR
            row = {"id": ref.task_id, **{n: (pub / n).read_text(encoding="utf-8") for n in DELIVERABLES}}
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(refs)


# ------------------------------------------------------------------ scoring
def _prediction_files(row: dict) -> dict[str, bytes]:
    src = row.get("files") if isinstance(row.get("files"), dict) else row
    out = {}
    for name in DELIVERABLES:
        if name in src:
            data = decode_file(src[name])
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(f"{name}: larger than {MAX_FILE_BYTES} bytes")
            out[name] = data
    return out


def score_files(task_dir: str, files: dict[str, bytes | str], timeout: float = 120.0) -> dict:
    """Grade in-memory deliverables against `task_dir`. Only design.json and board.kicad_pcb are
    written (other keys are ignored); missing files fail the parse gate."""
    wd = tempfile.mkdtemp(prefix="pcbscore_")
    try:
        for name in DELIVERABLES:
            if name in files:
                data = files[name]
                Path(wd, name).write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        res = api.verify(wd, task_dir, isolated=True, timeout=timeout)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    failed = sorted(k for k, v in {**res.gates, **res.checks}.items() if not v)
    return {"reward": res.reward, "gates": res.gates, "checks": res.checks, "failed": failed,
            "error": res.detail.get("error")}


def score_rows(rows: list[dict], tasks_root: str | os.PathLike, workers: int | None = None,
               timeout: float = 120.0) -> list[dict]:
    index = {r.task_id: r.path for r in api.list_tasks(tasks_root)}
    workers = workers or min(8, os.cpu_count() or 1)

    def one(row: dict) -> dict:
        rid = str(row.get("id", ""))
        if rid not in index:
            return {"id": rid, "reward": 0.0, "gates": {}, "checks": {}, "failed": [], "error": "unknown task id"}
        try:
            files = _prediction_files(row)
        except (ValueError, TypeError) as e:
            return {"id": rid, "reward": 0.0, "gates": {}, "checks": {}, "failed": [], "error": f"bad row: {e}"}
        return {"id": rid, **score_files(index[rid], files, timeout=timeout)}

    # threads only dispatch: each verify runs in its own fresh python subprocess
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, rows))


def score_jsonl(predictions: str | os.PathLike, tasks_root: str | os.PathLike = "tasks",
                workers: int | None = None, out_path: str | os.PathLike | None = None,
                timeout: float = 120.0) -> list[dict]:
    rows = [json.loads(line) for line in Path(predictions).read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = score_rows(rows, tasks_root, workers=workers, timeout=timeout)
    if out_path is not None:
        with open(out_path, "w", encoding="utf-8") as f:
            for s in scores:
                f.write(json.dumps(s, sort_keys=True) + "\n")
    return scores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.adapters.jsonl")
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("export", help="export public task files as JSONL")
    e.add_argument("--tasks", default="tasks")
    e.add_argument("--split")
    e.add_argument("--limit", type=int)
    e.add_argument("--out", required=True)
    u = sp.add_parser("predict-unchanged", help="predictions JSONL = public files unmodified (template)")
    u.add_argument("--tasks", default="tasks")
    u.add_argument("--split")
    u.add_argument("--limit", type=int)
    u.add_argument("--out", required=True)
    s = sp.add_parser("score", help="grade a predictions JSONL")
    s.add_argument("--tasks", default="tasks")
    s.add_argument("--predictions", required=True)
    s.add_argument("--out")
    s.add_argument("--workers", type=int)
    a = ap.parse_args(argv)
    if a.cmd in ("export", "predict-unchanged"):
        fn = export_jsonl if a.cmd == "export" else unchanged_predictions
        try:
            n = fn(a.tasks, a.out, split=a.split, limit=a.limit, strict=True)
        except api.SplitNotFound as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"wrote {n} rows to {a.out}")
        return 0 if n else 1
    scores = score_jsonl(a.predictions, a.tasks, workers=a.workers, out_path=a.out)
    mean = sum(s["reward"] for s in scores) / len(scores) if scores else 0.0
    print(json.dumps({"n": len(scores), "mean_reward": mean}))
    return 0


if __name__ == "__main__":
    sys.exit(api.run_cli(main))
