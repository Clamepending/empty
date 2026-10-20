#!/usr/bin/env python3
"""Scripted demo policy: repairs a single wrong-value fault using only what an agent sees.

It acts purely through tool calls (via `pcbenv.adapters.rollout.run_agent`):
  1. `pcbtool sim`                       -- which spec assertions fail?
  2. `cat design.json`, `cat spec.json`  -- read the public files from the tool output
  3. a small local search (pcbenv.sim on the PUBLIC spec only), at most --max-sims simulations:
     suspects are R/C/L parts outside their published `value_bounds` first, then those whose
     value sits nearest the edge of their bounds; for each suspect it bisects over standard
     E24/E96 values inside the bounds, steered by which side of its window a failing assertion
     lands on. A part outside its bounds with a passing spec is moved back inside its bounds.
  4. `pcbtool set-value REF VALUE`, `pcbtool check`, `submit`
It solves single value faults only. Anything else (topology, footprint, layout, latent faults,
several interacting values) it submits unfixed and scores 0, so expect a LOW mean reward
(roughly 0-10 % on normal tasks, ~0 % on hard): it is a demo of the plumbing, not a baseline.
Each episode stops acting after --max-seconds (default 20 s) and is then graded.

    python3 examples/demo_policy.py --make-demo /tmp/pcb_demo                 # build a value-fault task, solve it
    python3 examples/demo_policy.py --tasks data --split v2/normal --limit 20 --workers 4 --transcript runs/demo20.jsonl
    python3 examples/demo_policy.py data/v2/normal/<task_id> [...] --transcript runs/demo.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pcbenv import api  # noqa: E402
from pcbenv.adapters.rollout import read_results, run_agent  # noqa: E402

E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2,
       6.8, 7.5, 8.2, 9.1]
E96 = [round(10 ** (i / 96), 2) for i in range(96)]
TUNABLE = {"R", "C", "L"}
MAX_SIMS = 20
MAX_SECONDS = 20.0


def _strip(tool_text: str) -> str:
    return re.sub(r"\n\[exit code -?\d+\]\s*$", "", tool_text)


def _standard_values(lo: float, hi: float) -> list[float]:
    """Sorted E24 + E96 values in [lo, hi]."""
    out = set()
    for d in range(math.floor(math.log10(lo)) - 1, math.ceil(math.log10(hi)) + 1):
        for m in E24 + E96:
            v = float(f"{m * 10 ** d:.4g}")
            if lo <= v <= hi:
                out.add(v)
    return sorted(out)


def _window(a: dict) -> tuple[float, float] | None:
    if "min" in a or "max" in a:
        return float(a.get("min", -math.inf)), float(a.get("max", math.inf))
    if a.get("check") == "xtal_load" and "cl" in a:
        cl, tol = float(a["cl"]), float(a.get("tol", 0.1))
        return cl * (1 - tol), cl * (1 + tol)  # measured = effective load incl. stray
    return None


def _side(a: dict, measured: float | None) -> int | None:
    """-1 below the window, +1 above, 0 inside, None unknown."""
    w = _window(a)
    if w is None or measured is None or not math.isfinite(measured):
        return None
    return -1 if measured < w[0] else (1 if measured > w[1] else 0)


class _Search:
    """Bounded value search: at most `max_sims` simulations and `deadline` (monotonic s)."""

    def __init__(self, design: dict, assertions: list[dict], bounds: dict, max_sims: int, deadline: float):
        self.design, self.assertions, self.bounds = design, assertions, bounds
        self.max_sims, self.deadline, self.sims = max_sims, deadline, 0

    def out_of_budget(self) -> bool:
        return self.sims >= self.max_sims or time.monotonic() > self.deadline

    def run(self, ref: str | None = None, value: str | None = None):
        from pcbenv.sim import run_assertions

        d = self.design
        if ref is not None:
            d = copy.deepcopy(self.design)
            d["components"][ref]["value"] = value
        self.sims += 1
        try:
            return run_assertions(d, self.assertions)
        except Exception:  # noqa: BLE001 - a candidate the simulator rejects is just a miss
            return None


def _suspects(design: dict, bounds: dict) -> list[tuple[str, float, float, float]]:
    """(ref, current, lo, hi) for tunable parts, most suspicious first."""
    from pcbenv.parts import parse_value

    out = []
    for ref, c in sorted(design["components"].items()):
        if c["part"] not in TUNABLE or not c.get("value"):
            continue
        try:
            cur = parse_value(c["value"])
        except ValueError:
            continue
        if cur <= 0:
            continue
        if ref in bounds:
            lo, hi = float(bounds[ref][0]), float(bounds[ref][1])
            if not (0 < lo <= hi):
                continue
            span = max(math.log10(hi / lo), 1e-6)
            centre = math.sqrt(lo * hi)
            # > 1 means outside the bounds; ~1 means at an edge; 0 means centred
            score = abs(math.log10(cur / centre)) / (span / 2)
        else:
            lo, hi, score = cur / 1000, cur * 1000, -1.0  # no published bounds: least suspicious
        out.append((ref, cur, lo, hi, score))
    out.sort(key=lambda t: (-t[4], t[0]))
    return [t[:4] for t in out]


def find_value_fix(design: dict, assertions: list[dict], bounds: dict | None = None,
                   max_sims: int = MAX_SIMS, deadline: float | None = None) -> tuple[str, str] | None:
    """(ref, value) that makes every public assertion pass and every value in bounds, or None.
    Uses at most `max_sims` simulations and stops at `deadline` (time.monotonic())."""
    from pcbenv.parts import format_value

    bounds = bounds or {}
    s = _Search(design, assertions, bounds, max_sims, deadline or time.monotonic() + MAX_SECONDS)
    base = s.run()
    if base is None:
        return None
    failing = [(a, r) for a, r in zip(assertions, base) if not r.passed]
    suspects = _suspects(design, bounds)
    out_of_bounds = [t for t in suspects if not (t[2] * (1 - 1e-9) <= t[1] <= t[3] * (1 + 1e-9))]

    if not failing:  # spec passes: only an out-of-bounds value to bring back inside
        for ref, cur, lo, hi in out_of_bounds:
            vals = _standard_values(lo, hi)
            for v in sorted(vals, key=lambda x: abs(math.log10(x / cur)))[:3]:
                if s.out_of_budget():
                    return None
                res = s.run(ref, format_value(v))
                if res is not None and all(r.passed for r in res):
                    return ref, format_value(v)
        return None

    target_a, _ = next(((a, r) for a, r in failing if _window(a) is not None), failing[0])
    ti = assertions.index(target_a)

    def probe(ref: str, v: float) -> tuple[int | None, bool]:
        res = s.run(ref, format_value(v))
        if res is None:
            return None, False
        return _side(target_a, res[ti].measured), all(r.passed for r in res)

    for ref, cur, lo, hi in suspects:
        vals = _standard_values(lo, hi)
        if len(vals) < 2 or s.out_of_budget():
            if s.out_of_budget():
                return None
            continue
        i, j = 0, len(vals) - 1
        si, ok = probe(ref, vals[i])
        if ok:
            return ref, format_value(vals[i])
        if s.out_of_budget():
            return None
        sj, ok = probe(ref, vals[j])
        if ok:
            return ref, format_value(vals[j])
        if si is None or sj is None or si == sj:
            continue  # this part does not move the failing assertion across its window
        while j - i > 1 and not s.out_of_budget():
            m = (i + j) // 2
            sm, ok = probe(ref, vals[m])
            if ok:
                return ref, format_value(vals[m])
            if sm is None:
                break
            if sm == 0:
                break  # target passes but something else fails: not a single-value fix
            if sm == si:
                i = m
            else:
                j = m
    return None


class DemoPolicy:
    """A `call_model(messages, tools)` that follows a fixed script within a time / sim budget."""

    def __init__(self, max_seconds: float = MAX_SECONDS, max_sims: int = MAX_SIMS) -> None:
        self.fix: tuple[str, str] | None = None
        self.max_seconds, self.max_sims = max_seconds, max_sims
        self.t0: float | None = None
        self.sims_used = 0

    def __call__(self, messages: list[dict], tools: list[dict]) -> dict:
        if self.t0 is None:
            self.t0 = time.monotonic()
        deadline = self.t0 + self.max_seconds
        tool_out = [m["content"] for m in messages if m["role"] == "tool"]
        n = len(tool_out)
        if n > 0 and time.monotonic() > deadline:
            return {"name": "submit", "input": {}, "text": "Time budget used up; submitting."}
        if n == 0:
            return {"name": "pcbtool", "input": {"args": ["sim"]}, "text": "Run the spec assertions first."}
        if n == 1:
            return {"name": "bash", "input": {"cmd": "cat design.json"}}
        if n == 2:
            return {"name": "bash", "input": {"cmd": "cat spec.json"}}
        if n == 3:
            try:
                design = json.loads(_strip(tool_out[1]))
                spec = json.loads(_strip(tool_out[2]))
            except ValueError:
                return {"name": "submit", "input": {}, "text": "Could not read the public files; giving up."}
            # keep ~40 % of the budget for set-value / check / grading
            self.fix = find_value_fix(design, spec.get("assertions", []), spec.get("value_bounds", {}),
                                      max_sims=self.max_sims, deadline=self.t0 + 0.6 * self.max_seconds)
            if self.fix is None:
                return {"name": "submit", "input": {}, "text": "No single value change fixes the spec; giving up."}
            ref, val = self.fix
            return {"name": "pcbtool", "input": {"args": ["set-value", ref, val]},
                    "text": f"Changing {ref} to {val} makes every assertion pass in simulation."}
        if n == 4 and self.fix is not None:
            return {"name": "pcbtool", "input": {"args": ["check"]}}
        return {"name": "submit", "input": {}}


def make_demo_task(dest: str, family: str = "ldo_reg", seed: int = 0, ref: str = "R1", bad: str = "10k") -> str:
    """Build a golden task and derive a wrong-value task from it (host side; uses the generators)."""
    import pcbnew

    from pcbenv import boardnet, taskio
    from pcbenv.families import FAMILIES

    root = Path(dest)
    golden_td = root / f"{family}_{seed}_golden"
    g = FAMILIES[family].generate(seed)
    if not (golden_td / "hidden" / "meta.json").exists():
        taskio.make_golden_task(g, golden_td)
    good = g.design["components"][ref]["value"]
    bad_design = copy.deepcopy(g.design)
    bad_design["components"][ref]["value"] = bad
    bad_board = root / "_bad.kicad_pcb"
    b = boardnet.load_board(taskio.golden_board_path(golden_td))
    b.FindFootprintByReference(ref).SetValue(bad)
    assert pcbnew.SaveBoard(str(bad_board), b, True)
    td = taskio.write_task(root / f"{family}_{seed}_value_fault", g, taskio.golden_board_path(golden_td),
                           public_design=bad_design, public_board=str(bad_board),
                           faults=[{"type": "wrong_value", "detail": {"ref": ref, "golden": good, "faulted": bad}}],
                           problem="Bench test: the output is well off its nominal value. Find and fix the fault.")
    bad_board.unlink()
    return str(td)


def _sigterm(signum, frame):  # let run_agent's finally write an `aborted` result row
    raise SystemExit(128 + signum)


def run_one(td: str, transcript: str | None, max_steps: int, max_seconds: float, max_sims: int) -> dict:
    signal.signal(signal.SIGTERM, _sigterm)
    pol = DemoPolicy(max_seconds=max_seconds, max_sims=max_sims)
    # hard stop for the whole episode (tool calls included); grading comes on top
    return run_agent(td, pol, max_steps=max_steps, model="scripted-demo", transcript=transcript,
                     max_seconds=max_seconds)


def _line(r: dict) -> str:
    flag = " TIMED-OUT" if r.get("timed_out") else ""
    return (f"{r['task_id']}: reward {r['reward']:.0f}  steps {r['steps']}  tool calls {r['n_tool_calls']}  "
            f"{r['wall_time_s']:.1f}s{flag}  failed={r['failed']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_dirs", nargs="*")
    ap.add_argument("--make-demo", metavar="DIR", help="build a demo value-fault task under DIR and run on it")
    ap.add_argument("--tasks", metavar="ROOT", help="tasks root (e.g. data or tasks); used with --split/--limit")
    ap.add_argument("--split", action="append",
                    help="split to run, repeatable (e.g. --split v2/normal --split v2/hard)")
    ap.add_argument("--limit", type=int, help="first N tasks of EACH --split (sorted by task id)")
    ap.add_argument("--transcript", default=None, help="append JSONL transcript here")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-seconds", type=float, default=MAX_SECONDS,
                    help="per-task wall-clock budget for acting (default %(default)s s; grading adds ~1-5 s)")
    ap.add_argument("--max-sims", type=int, default=MAX_SIMS, help="simulations per task (default %(default)s)")
    ap.add_argument("--workers", type=int, default=1, help="episodes in parallel (default %(default)s)")
    a = ap.parse_args(argv)
    dirs = list(a.task_dirs)
    if a.tasks:
        for sp in a.split or [None]:
            try:
                dirs += [r.path for r in api.list_tasks(a.tasks, split=sp, strict=True)[: a.limit]]
            except api.SplitNotFound as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
    elif a.split or a.limit:
        ap.error("--split / --limit need --tasks ROOT")
    if a.make_demo:
        dirs.append(make_demo_task(a.make_demo))
        print(f"demo task: {dirs[-1]}", flush=True)
    if not dirs:
        ap.error("give task dirs, --tasks ROOT or --make-demo DIR")
    signal.signal(signal.SIGTERM, _sigterm)
    t0 = time.monotonic()
    args = [(td, a.transcript, a.max_steps, a.max_seconds, a.max_sims) for td in dirs]
    results: list[dict] = []
    if a.workers <= 1 or len(dirs) == 1:
        for x in args:
            results.append(run_one(*x))
            print(_line(results[-1]), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=a.workers, mp_context=get_context("spawn")) as ex:
            for r in ex.map(run_one, *zip(*args)):
                results.append(r)
                print(_line(r), flush=True)
    total = sum(r["reward"] for r in results)
    print(f"mean reward {total / len(results):.3f} over {len(results)} task(s) "
          f"in {time.monotonic() - t0:.1f}s ({a.workers} worker(s))")
    if a.transcript:
        print(f"transcript: {a.transcript} ({len(read_results(a.transcript))} result rows in file)")
    return 0


if __name__ == "__main__":
    sys.exit(api.run_cli(main))
