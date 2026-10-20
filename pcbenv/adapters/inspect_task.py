"""UK AISI Inspect (`inspect_ai`) adapter.

    pip install inspect-ai            # not a pcbenv dependency
    docker build --target agent -t pcb-repair-agent .
    inspect eval pcbenv/adapters/inspect_task.py@pcb_repair -T tasks_root=data -T split=v2/normal \
        -T limit=20 --model anthropic/<model-id>

Prerequisites (not needed for anything else in pcbenv): network access for `pip install
inspect-ai` and a running Docker daemon for the sandbox image. `tasks_root` defaults to `tasks`
(the git checkout); pass `-T tasks_root=data` for bundles extracted with `pcbenv.api extract`.

Design (see docs/SECURITY.md):
- each Sample carries only the task's PUBLIC files (`Sample.files`, copied by Inspect into the
  sandbox working dir /work); `hidden/` is never referenced by the sample;
- the agent gets `bash` + a `pcbtool` tool, both executed inside the sandbox
  (docker/compose.inspect.yaml, target `agent` of the Dockerfile, no network);
- the scorer reads design.json and board.kicad_pcb back out of the sandbox and grades them on the
  HOST with `pcbenv.verify` (isolated subprocess) against `hidden/` -- verification never runs
  inside the agent's container.

`inspect_ai` is optional: this module imports without it; `pcb_repair()` raises a clear
ImportError if it is missing. The pure helpers (`sample_dict`, `build_samples`,
`score_deliverables`) need no Inspect and are unit-tested.
"""
from __future__ import annotations

import os
from pathlib import Path

from pcbenv import api
from pcbenv.adapters.jsonl import score_files
from pcbenv.adapters.rollout import SYSTEM_PROMPT
from pcbenv.verify import DELIVERABLES, MAX_FILE_BYTES

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker" / "compose.inspect.yaml"
INSTALL_HINT = ("inspect_ai is not installed. Install it with `pip install inspect-ai` (it is an optional "
                "dependency of pcbenv), or use pcbenv.adapters.rollout / pcbenv.adapters.jsonl instead.")

try:  # only to register @task for `inspect eval file.py@pcb_repair`; absence is fine
    from inspect_ai import task as _inspect_task_decorator
except ImportError:  # pragma: no cover - depends on environment
    _inspect_task_decorator = None


def _require_inspect():
    try:
        import inspect_ai  # noqa: F401
    except ImportError as e:
        raise ImportError(INSTALL_HINT) from e
    return inspect_ai


# ------------------------------------------------------------------ pure helpers (no inspect_ai)
def sample_dict(ref: api.TaskRef | str) -> dict:
    """Fields of one Inspect Sample: id, input (TASK.md), files (sandbox path -> host path of a
    PUBLIC file), metadata (task_dir for the host-side scorer + descriptive fields)."""
    if not isinstance(ref, api.TaskRef):
        ref = api.TaskRef(task_id=Path(ref).name, path=str(Path(ref).resolve()))
    task = api.load_task(ref.path)
    files = {rel: os.path.join(task.public_dir, rel) for rel in task.public_files}
    return {
        "id": ref.task_id,
        "input": task.task_md,
        "files": files,
        "metadata": {"task_dir": ref.path, "split": ref.split, "family": ref.family,
                     "title": task.spec.get("title", "")},
    }


def build_samples(tasks_root: str | os.PathLike = "tasks", split: str | None = "v2/normal",
                  limit: int | None = None) -> list[dict]:
    """Raises `api.SplitNotFound` (with the available splits) when nothing matches."""
    return [sample_dict(r) for r in api.list_tasks(tasks_root, split=split, strict=True)[:limit]]


def score_deliverables(task_dir: str, files: dict[str, bytes | str | None]) -> dict:
    """Scorer core: grade deliverables read back from the sandbox. Returns
    {"value": 1.0|0.0, "answer", "explanation", "metadata"}."""
    clean = {k: v for k, v in files.items() if k in DELIVERABLES and v is not None
             and len(v) <= MAX_FILE_BYTES}
    r = score_files(task_dir, clean)
    expl = "PASS" if r["reward"] == 1.0 else ("FAIL: " + ", ".join(r["failed"]) if r["failed"] else "FAIL")
    if r.get("error"):
        expl += f" ({r['error']})"
    return {"value": r["reward"], "answer": "submitted files", "explanation": expl, "metadata": r}


# ------------------------------------------------------------------ inspect objects (lazy)
def _pcbtool_tool(timeout: int):
    from inspect_ai.tool import tool
    from inspect_ai.util import sandbox

    @tool
    def pcbtool():
        async def execute(args: list[str]) -> str:
            """Run the PCB-Repair CLI `pcbtool <args>` in the task directory.

            Read-only: show, netlist, drc, erc, sim, parts [PART], check. Mutating: set-value REF VALUE,
            set-footprint REF LIB:FP, connect REF.PIN NET, disconnect REF.PIN, move REF X Y ROT,
            unroute NET, route NET [--width W], sync.

            Args:
                args: Arguments, e.g. ["set-value", "R1", "10k"].
            """
            res = await sandbox().exec(["pcbtool", *[str(a) for a in args]], timeout=timeout)
            return f"{res.stdout}{res.stderr}\n[exit code {res.returncode}]"
        return execute

    return pcbtool()


def _scorer():
    import asyncio

    from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer, stderr
    from inspect_ai.util import sandbox

    @scorer(metrics=[accuracy(), stderr()])
    def pcb_verifier():
        async def score(state, target):
            files: dict[str, bytes | None] = {}
            for name in DELIVERABLES:
                try:
                    data = await sandbox().read_file(name, text=False)
                    files[name] = bytes(data)
                except Exception:  # noqa: BLE001 - missing/unreadable = parse gate fails
                    files[name] = None
            r = await asyncio.to_thread(score_deliverables, state.metadata["task_dir"], files)
            return Score(value=CORRECT if r["value"] == 1.0 else INCORRECT, answer=r["answer"],
                         explanation=r["explanation"], metadata=r["metadata"])
        return score

    return pcb_verifier()


def pcb_repair(tasks_root: str = "tasks", split: str | None = "v2/normal", limit: int | None = None,
               message_limit: int = 100, tool_timeout: int = 180, sandbox: str | None = None):
    """The Inspect Task. `sandbox` = path to a compose file (default docker/compose.inspect.yaml)."""
    _require_inspect()
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.solver import basic_agent, system_message
    from inspect_ai.tool import bash

    samples = [Sample(id=s["id"], input=s["input"], files=s["files"], metadata=s["metadata"])
               for s in build_samples(tasks_root, split, None if limit is None else int(limit))]
    if not samples:
        raise ValueError(f"no tasks found under {tasks_root!r} (split={split!r})")
    solver = basic_agent(init=system_message(SYSTEM_PROMPT),
                         tools=[bash(timeout=tool_timeout), _pcbtool_tool(tool_timeout)],
                         max_attempts=1, message_limit=int(message_limit),
                         submit_description="Finish: the deliverables in the working dir are graded pass/fail.")
    return Task(dataset=MemoryDataset(samples, name=f"pcb-repair-{split or 'all'}"), solver=solver,
                scorer=_scorer(), sandbox=("docker", str(sandbox or COMPOSE)))


if _inspect_task_decorator is not None:  # pragma: no cover
    pcb_repair = _inspect_task_decorator(pcb_repair)
