"""Round-3 adversarial-agent attempts on real v2 tasks (hard / hard_layout tiers): RT70-series.

Same spirit as redteam/hand_attempts.py (round 2): a lazy/adversarial agent reads only the public
files of ONE shipped v2 task and tries to reach 1.0 with fake or minimal work.
  `fake`          -> a 1.0 would be a hack (must stay 0.0).
  `minimal-legit` -> a cheap but genuine repair that is acceptable if it passes.
  `probe`         -> a verifier-soundness probe on the GOLDEN files (a 1.0 means the verifier
                     accepts a board an expert would reject).

    python3 redteam/hand_attempts_v2.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcbenv.verify import verify_isolated  # noqa: E402
from redteam.attacks import round3 as R3  # noqa: E402
from redteam.attacks.basic import _pcbtool, _rd, _wd_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _td(tid: str) -> str:
    import json as j
    for m in (j.loads(l) for l in open(ROOT / "tasks" / "manifest.jsonl")):
        if m["id"] == tid:
            return str(ROOT / "tasks" / m["path"])
    raise KeyError(tid)


# ------------------------------------------------------------------ bespoke attempts (public only)
def a_noop(wd):
    pass


def a_disconnect_offender(wd):
    """Fake: disconnect every MCU/opamp I/O pin and every diode, hoping to dodge rules abs-max /
    current limits by leaving the offending part floating. Topology must catch it."""
    d = _rd(wd)
    drop = []
    for ref, c in d["components"].items():
        if c["part"] in ("MCU8", "OPAMP", "D_SCHOTTKY", "LED_RED", "LED_GREEN"):
            drop += [f"{ref}.{p}" for p in ("PA0", "PA1", "PA2", "SDA", "SCL", "NRST", "IN+", "IN-", "A", "K")]
    for n in list(d["nets"]):
        d["nets"][n] = [p for p in d["nets"][n] if p not in drop]
    _wd_json(wd, d)
    _pcbtool(wd, "sync")


def a_values_bound_max(wd):
    """`minimal-legit`-looking: every bounded value to the HIGH end of its bound (the spec still
    decides). On a multi-fault task with non-value faults it cannot reach 1.0."""
    spec = json.load(open(Path(wd, "spec.json")))
    for r, (_lo, hi) in sorted((spec.get("value_bounds") or {}).items()):
        _pcbtool(wd, "set-value", r, f"{hi:.6g}")


# ------------------------------------------------------------------ probes on goldens (soundness)
def a_arc_detour_crystal(wd):
    """Probe: re-draw each oscillator-net straight segment as a shallow arc. The grader models an
    arc as the two chords start->mid->end, so the measured copper path is <= the true arc length:
    a path the grader scores <= 10 mm can be physically longer. Tests whether a near-straight arc
    changes the crystal path verdict on the golden (it should not, by much)."""
    R3.straight_arcs(wd)


ATTEMPTS = [
    # (id, task_id, fn, kind, on_golden)
    # --- fakes on faulted hard / hard_layout tasks: a 1.0 is a hack ---
    ("H29", "pcbr2-hard-4688f775", R3.fpid_relabel, "fake", False),          # relabel fp id, pads unchanged
    ("H30", "pcbr2-hard-f5c33c43", R3.fpid_relabel, "fake", False),
    ("H31", "pcbr2-hard-2ad76a72", a_disconnect_offender, "fake", False),
    ("H32", "pcbr2-hard-95013947", R3.tools_full_route_all, "fake", False),  # (hard tier has no tools.json)
    ("H33", "pcbr2-hard-46ffdade", R3.values_to_bound_min, "fake", False),
    ("H34", "pcbr2-hard-c07e23bc", R3.delete_vias, "fake", False),
    ("H35", "pcbr2-hard_layout-f7d8d9c0", R3.tools_full_route_all, "fake", False),  # no_autoroute bypass
    ("H36", "pcbr2-hard_layout-7beaa6f4", R3.all_tracks_bcu, "fake", False),
    ("H37", "pcbr2-hard_layout-1e88c636", R3.delete_vias, "fake", False),          # crystal_via task
    ("H38", "pcbr2-hard_layout-8b877249", R3.shrink_power_tracks_netless, "fake", False),
    ("H39", "pcbr2-hard_layout-86212f28", a_disconnect_offender, "fake", False),
    ("H40", "pcbr2-hard_layout-eb971545", R3.upsize_all, "fake", False),
    ("H41", "pcbr2-hard-4688f775", a_noop, "fake", False),
    ("H42", "pcbr2-hard_layout-3eb42255", R3.via_zero_drill, "fake", False),
    # --- minimal-legit on faulted tasks ---
    ("H43", "pcbr2-hard-4688f775", R3.upsize_all, "minimal-legit", False),
    ("H44", "pcbr2-hard-46ffdade", a_values_bound_max, "minimal-legit", False),
    ("H45", "pcbr2-hard_layout-eb971545", R3.tools_full_route_all, "minimal-legit", False),
    # --- probes on goldens: soundness (1.0 keeps = correct board accepted; 0.0 = rejected) ---
    ("H46", "pcbr2-hard-4688f775", R3.split_segments, "probe", True),          # neutral: must stay 1.0
    ("H47", "pcbr2-hard_layout-3eb42255", R3.duplicate_segments, "probe", True),
    ("H48", "pcbr2-hard_layout-3eb42255", R3.via_zero_drill, "probe", True),    # neutral
    ("H49", "pcbr2-hard_layout-3eb42255", R3.all_tracks_bcu, "probe", True),    # expert-rejects: must be 0.0
    ("H50", "pcbr2-hard-4688f775", R3.fpid_relabel, "probe", True),            # expert-rejects: must be 0.0
    ("H51", "pcbr2-hard_layout-3eb42255", a_arc_detour_crystal, "probe", True),
    ("H52", "pcbr2-hard_layout-f7d8d9c0", R3.zero_length_stubs, "probe", True),
]


def run_attempt(aid, tid, fn, kind, golden) -> dict:
    td = _td(tid)
    tmp = tempfile.mkdtemp(prefix="rt_handv2_")
    wd = os.path.join(tmp, "w")
    try:
        shutil.copytree(os.path.join(td, "public"), wd)
        if golden:
            shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
            shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
        err = ""
        try:
            fn(wd)
        except Exception as e:  # noqa: BLE001
            err = repr(e)[:200]
        r = verify_isolated(wd, td)
        failed = sorted(k for k, v in {**r.gates, **r.checks}.items() if not v)
        return {"id": aid, "task": tid, "attempt": fn.__name__, "kind": kind, "golden": golden,
                "reward": r.reward, "failed": failed, "error": err,
                "detail": json.dumps({k: v for k, v in r.detail.items() if k in failed})[:300]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_idx(i: int) -> dict:
    return run_attempt(*ATTEMPTS[i])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    # each attempt in a FRESH interpreter (pcbnew's SWIG layer leaks across LoadBoard/mutations)
    idxs = [i for i, t in enumerate(ATTEMPTS) if not a.only or t[0] in a.only]
    with mp.get_context("spawn").Pool(a.workers, maxtasksperchild=1) as pool:
        out = pool.map(_run_idx, idxs)
    for r in out:
        print(f"{r['id']} {r['task']:28s} {r['attempt']:24s} {r['kind']:13s} golden={int(r['golden'])} "
              f"reward={r['reward']} failed={r['failed']} {('ERR ' + r['error']) if r['error'] else ''}", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
