"""Small, stable public API for PCB-Repair. Everything a lab engineer needs is importable from here:

```python
from pcbenv import api
tasks = api.list_tasks("tasks", split="v2/normal")      # [TaskRef, ...] (splits: v2/normal, v2/hard, ...)
task = api.load_task(tasks[0].path)                       # public view: TASK.md, spec, file list
with api.PcbRepairEnv(max_steps=40) as env:               # gym-like episode (see harness.py)
    obs = env.reset(task.path)
    ...
res = api.verify(workdir, tasks[0].path)                  # VerifyResult(reward 0/1, gates, checks)
api.extract_tasks("dist/pcb-repair-v2.1-normal.tar.gz", "data")   # -> data/v2/normal/<task_id>/
```
Names in `__all__` are the stable surface (semver, see docs/VERSIONING.md); anything else in
`pcbenv` may change between minor versions.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from pcbenv.harness import EpisodeLog, PcbRepairEnv, run_task_with_policy
from pcbenv.verify import GATES, CHECKS, VerifyResult
from pcbenv.verify import verify as verify_inprocess
from pcbenv.verify import verify_isolated

__all__ = ["TaskRef", "Task", "list_tasks", "load_task", "verify", "verify_inprocess", "extract_tasks",
           "UnsafeArchive", "SplitNotFound", "available_splits", "canonical_split", "split_matches",
           "no_tasks_message", "run_cli", "PcbRepairEnv", "run_task_with_policy", "EpisodeLog", "VerifyResult",
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


MAX_SCAN_DEPTH = 4


def _find_manifests(root: Path) -> list[Path]:
    """[root/manifest.jsonl] if present; else every manifest one or two levels below (bundles wrap
    everything in a top-level dir, and `extract` puts each bundle in its own `v2/<split>/`)."""
    if (root / MANIFEST).is_file():
        return [root / MANIFEST]
    return sorted(root.glob(f"*/{MANIFEST}")) + sorted(root.glob(f"*/*/{MANIFEST}"))


def _scan(root: Path) -> list[Path]:
    if _is_task_dir(root):
        return [root]
    out, frontier = [], [root]
    for _ in range(MAX_SCAN_DEPTH):
        nxt = []
        for d in frontier:
            for c in sorted(p for p in d.iterdir() if p.is_dir() and not p.is_symlink()) if d.is_dir() else []:
                if _is_task_dir(c):
                    out.append(c)
                elif c.name not in (PUBLIC_DIR, HIDDEN_DIR):
                    nxt.append(c)
        frontier = nxt
    return out


_BUNDLE_RE = re.compile(r"^pcb-repair-(v\d+)(?:\.\d+)*-(.+)$")   # v2.1 bundles hold the v2/<split> splits


def canonical_split(name: str | None) -> str | None:
    """Bundle / dir names -> manifest split names: `pcb-repair-v2-hard-layout-holdout` (or the v2.1
    bundle `pcb-repair-v2.1-hard-layout-holdout`) -> `v2/hard_layout_holdout`; `v2/normal` is unchanged."""
    if name is None:
        return None
    m = _BUNDLE_RE.match(name)
    if m:
        return f"{m.group(1)}/{m.group(2).replace('-', '_')}"
    return name


def split_matches(wanted: str | None, split: str | None) -> bool:
    """`wanted` (what the user typed) selects `split`. Accepts the manifest name (`v2/normal`), the
    bundle name (`pcb-repair-v2-normal`) and, when either side is a bare dir name, the last
    component (`normal` <-> `v2/normal`)."""
    if wanted is None:
        return True
    if split is None:
        return False
    a, b = canonical_split(wanted), canonical_split(split)
    if a == b:
        return True
    if "/" not in a or "/" not in b:
        return a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]
    return False


class SplitNotFound(LookupError):
    """A split filter matched no task (the message lists the splits that do exist)."""


def _all_tasks(rootp: Path) -> list[TaskRef]:
    refs: list[TaskRef] = []
    mans = _find_manifests(rootp) if rootp.is_dir() else []
    if mans:
        seen: set[str] = set()
        known = {"task_id", "id", "path", "task_dir", "dir", "split", "family", "difficulty"}
        for man in mans:
            mroot = man.parent
            for line in man.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                p = _resolve(mroot, row)
                if p is None or str(p) in seen:
                    continue
                seen.add(str(p))
                refs.append(TaskRef(task_id=str(row.get("task_id") or row.get("id") or p.name), path=str(p),
                                    split=row.get("split") or (p.parent.name if p.parent != rootp.resolve() else None),
                                    family=row.get("family"),
                                    difficulty=row.get("difficulty"),
                                    extra={k: v for k, v in row.items() if k not in known}))
    else:
        for d in _scan(rootp):
            sp = d.parent.name if d != rootp else None
            family = difficulty = None
            mp = d / HIDDEN_DIR / "meta.json"
            if mp.is_file():
                try:
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    family, difficulty = m.get("family"), m.get("difficulty")
                except ValueError:
                    pass
            refs.append(TaskRef(task_id=d.name, path=str(d.resolve()), split=sp,
                                family=family, difficulty=difficulty))
    return refs


def available_splits(root: str | os.PathLike = "tasks") -> dict[str, int]:
    """{split name: number of tasks} under `root`."""
    out: dict[str, int] = {}
    for r in _all_tasks(Path(root)):
        out[r.split or "-"] = out.get(r.split or "-", 0) + 1
    return dict(sorted(out.items()))


def list_tasks(root: str | os.PathLike = "tasks", split: str | None = None,
               strict: bool = False) -> list[TaskRef]:
    """Tasks under `root`, sorted by (split, task_id). Uses `manifest.jsonl` when present (rows need
    a `task_id` and either `path` or `split`); without a root manifest, every manifest one or two
    levels down is merged (that is what `extract` produces: `root/v2/<split>/manifest.jsonl`).
    With no manifest at all it scans for `*/public/TASK.md` up to 4 levels deep, taking the split
    from the task's parent dir name (also accepts `root` being a split dir or a single task dir).
    Manifest rows whose directory is missing are skipped.

    `split` accepts `v2/normal`, `pcb-repair-v2-normal` or `normal` (see `split_matches`).
    `strict=True` raises `SplitNotFound` (listing the available splits) instead of returning []."""
    rootp = Path(root)
    refs = [r for r in _all_tasks(rootp) if split_matches(split, r.split)]
    if strict and not refs:
        raise SplitNotFound(no_tasks_message(root, split))
    return sorted(refs, key=lambda r: (r.split or "", r.task_id))


def no_tasks_message(root: str | os.PathLike, split: str | None) -> str:
    """Human-readable explanation of why nothing matched, with the splits that do exist."""
    if not Path(root).exists():
        return f"no tasks: {os.fspath(root)!r} does not exist (extract a bundle first: " \
               f"python3 -m pcbenv.api extract dist/pcb-repair-v2.1-normal.tar.gz {os.fspath(root)})"
    avail = available_splits(root)
    if not avail:
        return f"no tasks found under {os.fspath(root)!r} (no */public/TASK.md, no manifest.jsonl)"
    lst = ", ".join(f"{k} ({v})" for k, v in avail.items())
    return f"no tasks for split {split!r} under {os.fspath(root)!r}; available splits: {lst}"


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


_SAFE_SPLIT = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")


def _bundle_layout(members: list[tarfile.TarInfo], tf: tarfile.TarFile) -> tuple[str, str] | None:
    """(top-level dir, split) for a release bundle `<name>/manifest.jsonl + <name>/<task_id>/...`,
    so it can be extracted to `<split>/` (e.g. `v2/normal/`), the same layout as a git checkout.
    The split comes from the bundle manifest's `split` field (one value), else from the bundle name."""
    tops = {m.name.replace("\\", "/").split("/", 1)[0] for m in members}
    if len(tops) != 1:
        return None
    top = tops.pop()
    man = next((m for m in members if m.name.rstrip("/") == f"{top}/{MANIFEST}" and m.isfile()), None)
    if man is None:
        return None
    splits = set()
    fh = tf.extractfile(man)
    for line in (fh.read().decode("utf-8", errors="replace").splitlines() if fh else []):
        try:
            sp = json.loads(line).get("split") if line.strip() else None
        except ValueError:
            sp = None
        if sp:
            splits.add(str(sp))
    def safe(x: str) -> bool:
        return x != top and bool(_SAFE_SPLIT.match(x)) and not {"..", "."} & set(x.split("/"))

    split = splits.pop() if len(splits) == 1 else None
    if split is None or not safe(split):
        split = canonical_split(top)
    return (top, split) if safe(split) else None


def extract_tasks(tarball: str | os.PathLike, dest: str | os.PathLike) -> list[TaskRef]:
    """Safely extract a `dist/*.tar.gz` task bundle into `dest` and return the tasks it contained
    (not everything already in `dest`; use `list_tasks(dest)` for that).

    A release bundle (`pcb-repair-v2-normal/{manifest.jsonl,<task_id>/...}`) is extracted to
    `dest/v2/normal/` -- the same `<root>/v2/<split>/<task_id>` layout as a git checkout, so
    `--split v2/normal` works on both. Other archives are extracted as-is.
    Every member is checked BEFORE anything is written: absolute paths, `..`, symlinks, hardlinks,
    devices/FIFOs and members > 64 MB are rejected with `UnsafeArchive`. Extraction also uses
    tarfile's `data` filter (strips setuid bits, re-checks paths)."""
    dest_p = Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:*") as tf:
        members = tf.getmembers()
        for m in members:
            _check_member(m)
        layout = _bundle_layout(members, tf)
        sub = dest_p
        if layout is not None:
            top, split = layout
            for m in members:
                n = m.name.replace("\\", "/")
                m.name = split + n[len(top):]
            sub = dest_p / split
        root = dest_p.resolve()
        for m in members:
            _check_member(m)
            target = (root / m.name).resolve()
            if target != root and root not in target.parents:
                raise UnsafeArchive(f"member escapes destination: {m.name!r}")
        tf.extractall(dest_p, members=members, filter="data")
        names = {m.name.replace("\\", "/").rstrip("/") for m in members}
    refs = list_tasks(sub) if layout is not None else list_tasks(dest_p)
    if layout is None:  # only tasks whose TASK.md came from this archive
        mine = {str((dest_p / n).resolve().parent.parent) for n in names if n.endswith(f"/{PUBLIC_DIR}/TASK.md")}
        refs = [r for r in refs if r.path in mine]
    return refs


def run_cli(main, argv: list[str] | None = None) -> int:
    """Run a CLI `main(argv) -> int` so that `... | head` ends quietly: a closed stdout gives exit
    141 (like SIGPIPE) instead of a BrokenPipeError traceback."""
    try:
        rc = main(argv)
        sys.stdout.flush()
        return rc
    except BrokenPipeError:
        try:  # further writes (incl. the interpreter's final flush) go nowhere
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return 141


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    """python3 -m pcbenv.api {list,splits,extract,verify} ..."""
    import argparse

    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.api")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list", help="list tasks")
    p.add_argument("root", nargs="?", default="tasks")
    p.add_argument("--split", help="e.g. v2/normal, v2/hard, v2/hard_layout (bundle names also work)")
    p.add_argument("--json", action="store_true", help="one JSON object per line")
    p = sp.add_parser("splits", help="list the splits under ROOT with task counts")
    p.add_argument("root", nargs="?", default="tasks")
    p = sp.add_parser("extract", help="safely extract a task bundle (.tar.gz) into DEST/v2/<split>/")
    p.add_argument("tarball")
    p.add_argument("dest", nargs="?", default="data")
    p = sp.add_parser("verify", help="grade WORKDIR against TASK_DIR (exit 0 iff reward 1)")
    p.add_argument("workdir")
    p.add_argument("task_dir")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        try:
            refs = list_tasks(a.root, split=a.split, strict=True)
        except SplitNotFound as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        for r in refs:
            if a.json:
                print(json.dumps({"task_id": r.task_id, "split": r.split, "family": r.family,
                                  "difficulty": r.difficulty, "path": r.path}, default=str))
            else:
                print(f"{r.split or '-':18s} {r.task_id:28s} {r.family or '-':20s} {r.path}")
        print(f"{len(refs)} task(s)", file=sys.stderr)
        return 0
    if a.cmd == "splits":
        avail = available_splits(a.root)
        for k, v in avail.items():
            print(f"{k:24s} {v}")
        if not avail:
            print(f"error: {no_tasks_message(a.root, None)}", file=sys.stderr)
        return 0 if avail else 2
    if a.cmd == "extract":
        refs = extract_tasks(a.tarball, a.dest)
        splits = sorted({r.split or "-" for r in refs})
        total = len(list_tasks(a.dest))
        print(f"extracted {len(refs)} task(s) from {os.path.basename(a.tarball)} (split {', '.join(splits) or '-'}) "
              f"into {a.dest}; {a.dest} now holds {total} task(s)")
        return 0 if refs else 1
    res = verify(a.workdir, a.task_dir)
    print(json.dumps({"reward": res.reward, "gates": res.gates, "checks": res.checks, "detail": res.detail},
                     indent=2, sort_keys=True, default=str))
    return 0 if res.reward == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
