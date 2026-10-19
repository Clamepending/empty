#!/usr/bin/env python3
"""Scripted demo policy: repairs a single wrong-value fault using only what an agent sees.

It acts purely through tool calls (via `pcbenv.adapters.rollout.run_agent`):
  1. `pcbtool sim`                  -- which spec assertions fail?
  2. `cat design.json`, `cat spec.json`  -- read the public files from the tool output
  3. local search: for each R/C/L, try standard E24 then E96 values (±3 decades) and keep the first
     one that makes every public assertion pass (pcbenv.sim on the public spec only)
  4. `pcbtool set-value REF VALUE`, `pcbtool check`, `submit`
It solves single value faults; anything else (topology, footprint, layout faults) it submits
unfixed and scores 0 -- it is a demo of the plumbing, not a baseline.

    python3 examples/demo_policy.py --make-demo /tmp/pcb_demo      # build a value-fault task, solve it
    python3 examples/demo_policy.py tasks/train/<task_id> [...] --transcript runs/demo.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pcbenv.adapters.rollout import read_results, run_agent  # noqa: E402

E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2,
       6.8, 7.5, 8.2, 9.1]
E96 = [round(10 ** (i / 96), 2) for i in range(96)]
TUNABLE = {"R", "C", "L"}


def _strip(tool_text: str) -> str:
    return re.sub(r"\n\[exit code -?\d+\]\s*$", "", tool_text)


def _candidates(current: float, series: list[float]) -> list[float]:
    d0 = math.floor(math.log10(current)) if current > 0 else 0
    vals = [m * 10 ** d for d in range(d0 - 3, d0 + 4) for m in series]
    return sorted(vals, key=lambda v: abs(math.log10(v / current)) if current > 0 else 0)


def find_value_fix(design: dict, assertions: list[dict]) -> tuple[str, str] | None:
    """(ref, value) that makes all assertions pass, or None."""
    from pcbenv.parts import format_value, parse_value
    from pcbenv.sim import run_assertions

    if all(r.passed for r in run_assertions(design, assertions)):
        return None
    refs = sorted(r for r, c in design["components"].items() if c["part"] in TUNABLE and c.get("value"))
    for series in (E24, E96):
        for ref in refs:
            cur = parse_value(design["components"][ref]["value"])
            for v in _candidates(cur, series):
                s = format_value(v)
                if s == design["components"][ref]["value"]:
                    continue
                d = copy.deepcopy(design)
                d["components"][ref]["value"] = s
                try:
                    if all(r.passed for r in run_assertions(d, assertions)):
                        return ref, s
                except Exception:  # noqa: BLE001 - a candidate the simulator rejects is just skipped
                    continue
    return None


class DemoPolicy:
    """A `call_model(messages, tools)` that follows a fixed script."""

    def __init__(self) -> None:
        self.fix: tuple[str, str] | None = None

    def __call__(self, messages: list[dict], tools: list[dict]) -> dict:
        tool_out = [m["content"] for m in messages if m["role"] == "tool"]
        n = len(tool_out)
        if n == 0:
            return {"name": "pcbtool", "input": {"args": ["sim"]}, "text": "Run the spec assertions first."}
        if n == 1:
            if "FAIL" not in tool_out[0]:
                return {"name": "pcbtool", "input": {"args": ["check"]}, "text": "Spec passes; final check."}
            return {"name": "bash", "input": {"cmd": "cat design.json"}}
        if n == 2 and "FAIL" in tool_out[0]:
            return {"name": "bash", "input": {"cmd": "cat spec.json"}}
        if n == 3 and "FAIL" in tool_out[0]:
            design = json.loads(_strip(tool_out[1]))
            spec = json.loads(_strip(tool_out[2]))
            self.fix = find_value_fix(design, spec.get("assertions", []))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_dirs", nargs="*")
    ap.add_argument("--make-demo", metavar="DIR", help="build a demo value-fault task under DIR and run on it")
    ap.add_argument("--transcript", default=None, help="append JSONL transcript here")
    ap.add_argument("--max-steps", type=int, default=12)
    a = ap.parse_args(argv)
    dirs = list(a.task_dirs)
    if a.make_demo:
        dirs.append(make_demo_task(a.make_demo))
        print(f"demo task: {dirs[-1]}")
    if not dirs:
        ap.error("give task dirs or --make-demo DIR")
    total = 0.0
    for td in dirs:
        r = run_agent(td, DemoPolicy(), max_steps=a.max_steps, model="scripted-demo", transcript=a.transcript)
        total += r["reward"]
        print(f"{r['task_id']}: reward {r['reward']:.0f}  steps {r['steps']}  tool calls {r['n_tool_calls']}  "
              f"{r['wall_time_s']:.1f}s  failed={r['failed']}")
    print(f"mean reward {total / len(dirs):.3f} over {len(dirs)} task(s)")
    if a.transcript:
        print(f"transcript: {a.transcript} ({len(read_results(a.transcript))} result rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
