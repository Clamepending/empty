"""Fault-specific shortcut repairs on the shipped tasks (round 2, RT40-series).

For every single-fault shipped task, apply the cheapest "repair" a lazy agent could make for that
fault type and grade it. The fault record (hidden meta) is used ONLY to aim the shortcut, so
this measures verifier soundness, not what an agent can see. Each shortcut is labelled:
- `wrong`: an expert rejects the result -> a 1.0 is a finding (EXPERT-DISAGREES / EXPLOIT)
- `legit`: an acceptable alternative repair -> a 1.0 is fine (a 0.0 would be a false negative)

    python3 redteam/shortcuts.py [--per-type 6] [--workers 4] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcbenv.verify import verify_isolated  # noqa: E402
from redteam.attacks.basic import _pcbtool, _rd, _wd_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _set_value_both(wd: str, ref: str, v: str) -> None:
    _pcbtool(wd, "set-value", ref, v)


def _board_value(wd: str, ref: str) -> str:
    import pcbnew
    b = pcbnew.LoadBoard(os.path.join(wd, "board.kicad_pcb"))
    return b.FindFootprintByReference(ref).GetValue()


def _delete_tracks(wd: str, pred) -> int:
    import pcbnew
    p = os.path.join(wd, "board.kicad_pcb")
    b = pcbnew.LoadBoard(p)
    dead = [t for t in b.GetTracks() if pred(t)]
    for t in dead:
        b.Delete(t)
    pcbnew.SaveBoard(p, b, True)
    return len(dead)


def _power(td: str) -> dict:
    return {p["net"]: p["min_width_mm"] for p in json.load(open(os.path.join(td, "public", "spec.json")))["power_nets"]}


# each: (label, fn(wd, td, fault_data) -> None)
def sc_route_thin(wd, td, d):
    _pcbtool(wd, "route", d["net"], "--width", "0.2")


def sc_route_default(wd, td, d):
    _pcbtool(wd, "route", d["net"])


def sc_delete_narrow(wd, td, d):
    w = int(round(d["width"] * 1e6))
    _delete_tracks(wd, lambda t: t.GetClass() != "PCB_VIA" and t.GetNetname() == d["net"] and t.GetWidth() <= w)


def sc_reroute_both(wd, td, d):
    for n in (d["net"], d["other_net"]):
        _pcbtool(wd, "unroute", n)
    for n in (d["net"], d["other_net"]):
        _pcbtool(wd, "route", n)


def sc_reroute_net_only(wd, td, d):
    _pcbtool(wd, "route", d["net"])


def sc_design_follows_board(wd, td, d):
    """bom_mismatch: change design.json to the (wrong) board value instead of fixing the board."""
    v = _board_value(wd, d["ref"])
    dd = _rd(wd)
    dd["components"][d["ref"]]["value"] = v
    _wd_json(wd, dd)


def sc_board_follows_design(wd, td, d):
    _pcbtool(wd, "sync")


def sc_keep_new_footprint(wd, td, d):
    """footprint_swap: keep the swapped (allowed) footprint, put it in design.json, re-route."""
    _pcbtool(wd, "set-footprint", d["ref"], d["footprint"])
    for n in d["nets"]:
        _pcbtool(wd, "route", n)


def sc_bound_edge(wd, td, d):
    """value faults: any in-bounds value that the public sim accepts (lo end of the bound)."""
    sp = json.load(open(os.path.join(td, "public", "spec.json")))
    refs = d.get("refs") or [d["ref"]]
    for r in refs:
        lo, hi = sp["value_bounds"][r]
        _set_value_both(wd, r, f"{lo:.6g}")


def sc_disconnect_pin(wd, td, d):
    """connectivity faults: just disconnect the offending pin(s) (ERC may or may not notice)."""
    pins = d.get("pins") or [d["pin"]]
    for p in pins:
        _pcbtool(wd, "disconnect", p)
    _pcbtool(wd, "sync")


def sc_board_pads_to_design(wd, td, d):
    """board_pad_swap: make design.json follow the (wrong) board pads."""
    from redteam.attacks.round2 import sync_design_from_board
    sync_design_from_board(wd)


def sc_move_ic_to_cap(wd, td, d):
    """decap_moved_far: move the cap back next to its IC pin (golden position), re-route its nets."""
    x, y = d["golden_pos"]
    _pcbtool(wd, "move", d["cap"], str(x), str(y), "0")
    for n in d["nets"]:
        _pcbtool(wd, "route", n)


def sc_cap_far_side(wd, td, d):
    """decap_moved_far: leave the cap where it is and re-route only (no placement fix)."""
    for n in d["nets"]:
        _pcbtool(wd, "route", n)


SHORTCUTS = {
    "broken_trace": [("route_thin_0.2", sc_route_thin, "power?"), ("route_default", sc_route_default, "legit")],
    "narrow_power_trace": [("delete_narrow_only", sc_delete_narrow, "legit-if-connected"),
                           ("route_thin_0.2", sc_route_thin, "wrong")],
    "clearance_violation": [("reroute_both", sc_reroute_both, "legit"), ("route_net_only", sc_reroute_net_only, "legit")],
    "short_between_nets": [("reroute_both", sc_reroute_both, "legit"), ("route_net_only", sc_reroute_net_only, "legit")],
    "bom_mismatch": [("design_follows_board", sc_design_follows_board, "wrong"),
                     ("board_follows_design", sc_board_follows_design, "legit")],
    "footprint_swap": [("keep_new_footprint", sc_keep_new_footprint, "legit")],
    "magnitude_slip": [("bound_lo", sc_bound_edge, "legit-if-spec")],
    "wrong_feedback_resistor": [("bound_lo", sc_bound_edge, "legit-if-spec")],
    "wrong_filter_cap": [("bound_lo", sc_bound_edge, "legit-if-spec")],
    "wrong_led_resistor": [("bound_lo", sc_bound_edge, "legit-if-spec")],
    "wrong_pull_resistor": [("bound_lo", sc_bound_edge, "legit-if-spec")],
    "pin_to_wrong_net": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "floating_pin": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "swapped_ic_pins": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "transistor_pinout": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "reversed_polarity": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "decap_misconnected": [("disconnect_pin", sc_disconnect_pin, "wrong")],
    "board_pad_swap": [("design_follows_board", sc_board_pads_to_design, "wrong")],
    "decap_moved_far": [("move_back", sc_move_ic_to_cap, "legit"), ("reroute_only", sc_cap_far_side, "wrong")],
}


def _one(args) -> dict:
    td, ftype, name, label = args
    meta = json.load(open(os.path.join(td, "hidden", "meta.json")))
    f = meta["faults"][0]
    fn = dict((n, f_) for n, f_, _ in SHORTCUTS[ftype])[name]
    tmp = tempfile.mkdtemp(prefix="rt_sc_")
    wd = os.path.join(tmp, "w")
    try:
        shutil.copytree(os.path.join(td, "public"), wd)
        data = dict(f.get("data", {}))
        if ftype == "broken_trace":
            label = "wrong" if (name == "route_thin_0.2" and data["net"] in _power(td)) else "legit"
        try:
            fn(wd, td, data)
        except Exception as e:  # noqa: BLE001
            return {"task": td, "type": ftype, "shortcut": name, "label": label, "status": "attack_error", "err": repr(e)[:200]}
        r = verify_isolated(wd, td)
        failed = sorted(k for k, v in {**r.gates, **r.checks}.items() if not v)
        return {"task": td, "type": ftype, "shortcut": name, "label": label, "reward": r.reward, "failed": failed,
                "status": "pass" if r.reward == 1.0 else "fail"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def single_fault_tasks(per_type: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for line in open(ROOT / "tasks" / "manifest.jsonl"):
        m = json.loads(line)
        if m["n_faults"] != 1:
            continue
        t = m["faults"][0]["type"]
        if len(out[t]) < per_type:
            out[t].append(str(ROOT / "tasks" / m["split"] / m["id"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=6)
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 2))
    ap.add_argument("--json")
    a = ap.parse_args()
    jobs = [(td, t, n, lab) for t, tds in sorted(single_fault_tasks(a.per_type).items())
            for td in tds for n, _, lab in SHORTCUTS[t]]
    with mp.get_context("spawn").Pool(a.workers, maxtasksperchild=10) as pool:
        res = pool.map(_one, jobs, chunksize=2)
    agg = Counter((r["type"], r["shortcut"], r["label"], r["status"]) for r in res)
    keys = sorted({k[:3] for k in agg})
    for k in keys:
        print(f"{k[0]:24s} {k[1]:22s} {k[2]:18s} " + " ".join(f"{s}={agg[k + (s,)]}" for s in ("pass", "fail", "attack_error") if agg[k + (s,)]))
    for r in res:
        if r["label"] == "wrong" and r["status"] == "pass":
            print("WRONG-REPAIR-PASSES", r["type"], r["shortcut"], r["task"])
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
