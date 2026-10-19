"""Small, stable public API for PCB-Repair. Everything a lab engineer needs is importable from here:

```python
from pcbenv import api
tasks = api.list_tasks("tasks", split="train")          # [TaskRef, ...]
task = api.load_task(tasks[0].path)                       # public view: TASK.md, spec, file list
with api.PcbRepairEnv(max_steps=40) as env:               # gym-like episode (see harness.py)
    obs = env.reset(task.path)
    ...
res = api.verify(workdir, tasks[0].path)                  # VerifyResult(reward 0/1, gates, checks)
api.extract_tasks("dist/pcb-repair-train.tar.gz", "tasks")  # safe tarball extraction
```
Names in `__all__` are the stable surface (semver, see docs/VERSIONING.md); anything else in
`pcbenv` may change between minor versions.
"""
from __future__ import annotations

import json
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from pcbenv.harness import EpisodeLog, PcbRepairEnv, run_task_with_policy
from pcbenv.verify import GATES, CHECKS, VerifyResult
from pcbenv.verify import verify as verify_inprocess
from pcbenv.verify import verify_isolated

__all__ = ["TaskRef", "Task", "list_tasks", "load_task", "verify", "verify_inprocess", "extract_tasks",
           "UnsafeArchive", "PcbRepairEnv", "run_task_with_policy", "EpisodeLog", "VerifyResult",
           "GATES", "CHECKS", "PUBLIC_DIR", "HIDDEN_DIR"]

PUBLIC_DIR = "public"
HIDDEN_DIR = "hidden"
MANIFEST = "manifest.jsonl"


@dataclass(frozen=True)
class TaskRef:
    """A pointer to one task directory plus the manifest's descriptive fields (no hidden data
    beyond what the manifest itself publishes, e.g. family / difficulty)."""
    task_id: str
    path: str
    split: str | None = None
    family: str | None = None
    difficulty: object = None
    extra: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass
class Task:
    """Public view of a task (what the agent sees) and, optionally, the grader-side meta."""
    task_id: str
    path: str
    task_md: str
    spec: dict
    public_files: list[str]
    meta: dict | None = None      # hidden/meta.json, only with include_hidden=True

    @property
    def public_dir(self) -> str:
        return os.path.join(self.path, PUBLIC_DIR)


def _is_task_dir(p: Path) -> bool:
    return (p / PUBLIC_DIR / "TASK.md").is_file()


def _resolve(root: Path, row: dict) -> Path | None:
    tid = str(row.get("task_id") or row.get("id") or "")
    rel = row.get("path") or row.get("task_dir") or row.get("dir")
    cands = []
    if rel:
        rp = Path(rel)
        cands += [rp] if rp.is_absolute() else [root / rp, root.parent / rp]
    if tid:
        cands += [root / str(row.get("split", "")) / tid, root / tid]
    for c in cands:
        if _is_task_dir(c):
            return c.resolve()
    return None


def list_tasks(root: str | os.PathLike = "tasks", split: str | None = None) -> list[TaskRef]:
    """Tasks under `root`, sorted by task_id. Uses `root/manifest.jsonl` when present (rows need a
    `task_id` and either `path` or `split`); otherwise scans `root/<split>/<task_id>/public/TASK.md`
    (also accepts `root` being a split dir or a single task dir). Manifest rows whose directory is
    missing are skipped."""
    rootp = Path(root)
    refs: list[TaskRef] = []
    man = rootp / MANIFEST
    if man.is_file():
        for line in man.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if split is not None and row.get("split") != split:
                continue
            p = _resolve(rootp, row)
            if p is None:
                continue
            known = {"task_id", "id", "path", "task_dir", "dir", "split", "family", "difficulty"}
            refs.append(TaskRef(task_id=str(row.get("task_id") or row.get("id") or p.name), path=str(p),
                                split=row.get("split"), family=row.get("family"),
                                difficulty=row.get("difficulty"),
                                extra={k: v for k, v in row.items() if k not in known}))
    else:
        if _is_task_dir(rootp):
            found = [(None, rootp)]
        else:
            found = [(None, d) for d in sorted(rootp.glob("*")) if _is_task_dir(d)]
            found += [(s.name, d) for s in sorted(rootp.glob("*")) if s.is_dir()
                      for d in sorted(s.glob("*")) if _is_task_dir(d)]
        for sp, d in found:
            if split is not None and sp != split and not (sp is None and d.parent.name == split):
                continue
            family = difficulty = None
            mp = d / HIDDEN_DIR / "meta.json"
            if mp.is_file():
                try:
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    family, difficulty = m.get("family"), m.get("difficulty")
                except ValueError:
                    pass
            refs.append(TaskRef(task_id=d.name, path=str(d.resolve()), split=sp or d.parent.name,
                                family=family, difficulty=difficulty))
    return sorted(refs, key=lambda r: (r.split or "", r.task_id))


def load_task(task_dir: str | os.PathLike, include_hidden: bool = False) -> Task:
    """Read a task's public files (TASK.md, spec.json, file list). `include_hidden=True` also loads
    hidden/meta.json -- grader-side only, never hand it to a policy."""
    p = Path(task_dir).resolve()
    pub = p / PUBLIC_DIR
    if not (pub / "TASK.md").is_file():
        raise FileNotFoundError(f"{p}: not a task dir (missing {PUBLIC_DIR}/TASK.md)")
    spec_p = pub / "spec.json"
    spec = json.loads(spec_p.read_text(encoding="utf-8")) if spec_p.is_file() else {}
    files = sorted(str(f.relative_to(pub)) for f in pub.rglob("*") if f.is_file())
    meta = None
    if include_hidden:
        meta = json.loads((p / HIDDEN_DIR / "meta.json").read_text(encoding="utf-8"))
    tid = (meta or {}).get("task_id") or p.name
    return Task(task_id=tid, path=str(p), task_md=(pub / "TASK.md").read_text(encoding="utf-8"),
                spec=spec, public_files=files, meta=meta)


def verify(workdir: str | os.PathLike, task_dir: str | os.PathLike, isolated: bool = True,
           timeout: float = 120.0) -> VerifyResult:
    """Grade `workdir/design.json` + `workdir/board.kicad_pcb` against `task_dir/hidden`.
    Default runs in a fresh `python3 -I` subprocess (`verify_isolated`); `isolated=False` runs
    in-process (faster, but KiCad state leaks between calls). Never raises; errors give reward 0."""
    if isolated:
        return verify_isolated(os.fspath(workdir), os.fspath(task_dir), timeout=timeout)
    return verify_inprocess(os.fspath(workdir), os.fspath(task_dir))


# ------------------------------------------------------------------ distribution tarballs
class UnsafeArchive(ValueError):
    pass


MAX_MEMBER_BYTES = 64 * 1024 * 1024


def _check_member(m: tarfile.TarInfo) -> None:
    name = m.name
    if not name or name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchive(f"absolute path in archive: {name!r}")
    parts = Path(name.replace("\\", "/")).parts
    if ".." in parts:
        raise UnsafeArchive(f"path traversal in archive: {name!r}")
    if m.issym() or m.islnk():
        raise UnsafeArchive(f"link in archive: {name!r}")
    if not (m.isfile() or m.isdir()):
        raise UnsafeArchive(f"special file in archive: {name!r}")
    if m.size > MAX_MEMBER_BYTES:
        raise UnsafeArchive(f"member too large: {name!r} ({m.size} bytes)")


def extract_tasks(tarball: str | os.PathLike, dest: str | os.PathLike) -> list[TaskRef]:
    """Safely extract a `dist/*.tar.gz` task bundle into `dest` and return the tasks found there.
    Every member is checked BEFORE anything is written: absolute paths, `..`, symlinks, hardlinks,
    devices/FIFOs and members > 64 MB are rejected with `UnsafeArchive`. Extraction also uses
    tarfile's `data` filter (strips setuid bits, re-checks paths)."""
    dest_p = Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:*") as tf:
        members = tf.getmembers()
        for m in members:
            _check_member(m)
        root = dest_p.resolve()
        for m in members:
            target = (root / m.name).resolve()
            if target != root and root not in target.parents:
                raise UnsafeArchive(f"member escapes destination: {m.name!r}")
        tf.extractall(dest_p, members=members, filter="data")
    return list_tasks(dest_p) or _find_nested(dest_p)


def _find_nested(dest: Path) -> list[TaskRef]:
    """Bundles may wrap everything in one top-level dir (e.g. `pcb-repair-v1/tasks/...`)."""
    for man in sorted(dest.rglob(MANIFEST)):
        refs = list_tasks(man.parent)
        if refs:
            return refs
    for sub in sorted(p for p in dest.rglob("*") if p.is_dir()):
        refs = list_tasks(sub)
        if refs:
            return refs
    return []


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    """python3 -m pcbenv.api {list,extract,verify} ..."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.api")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list", help="list tasks")
    p.add_argument("root", nargs="?", default="tasks")
    p.add_argument("--split")
    p.add_argument("--json", action="store_true", help="one JSON object per line")
    p = sp.add_parser("extract", help="safely extract a task bundle (.tar.gz)")
    p.add_argument("tarball")
    p.add_argument("dest", nargs="?", default="tasks")
    p = sp.add_parser("verify", help="grade WORKDIR against TASK_DIR (exit 0 iff reward 1)")
    p.add_argument("workdir")
    p.add_argument("task_dir")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        refs = list_tasks(a.root, split=a.split)
        for r in refs:
            if a.json:
                print(json.dumps({"task_id": r.task_id, "split": r.split, "family": r.family,
                                  "difficulty": r.difficulty, "path": r.path}, default=str))
            else:
                print(f"{r.split or '-':8s} {r.task_id:40s} {r.family or '-':14s} {r.path}")
        print(f"{len(refs)} task(s)", file=sys.stderr)
        return 0 if refs else 1
    if a.cmd == "extract":
        refs = extract_tasks(a.tarball, a.dest)
        print(f"extracted {len(refs)} task(s) into {a.dest}")
        return 0 if refs else 1
    res = verify(a.workdir, a.task_dir)
    print(json.dumps({"reward": res.reward, "gates": res.gates, "checks": res.checks, "detail": res.detail},
                     indent=2, sort_keys=True, default=str))
    return 0 if res.reward == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
