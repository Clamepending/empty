"""Round-3 attacks (v2 tasks: hard tier `rules`, hard_layout `layout_rules`, no_autoroute mode).

Same contract as round 2: `fn(workdir)` edits public files only.
- ATTACKS3: must NOT turn a faulted task into 1.0.
- NEUTRAL3: geometric edits an expert accepts (copper is physically the same or equivalent);
  on a GOLDEN they must keep 1.0 (else false negative).
- EXPERT_REJECTS3: edits an expert rejects; on a GOLDEN they must give 0.0.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from redteam.attacks.basic import _pcbtool, _rd, _wd_json
from redteam.attacks.round2 import _board, _mm, _save

R_C_BIG = {"R": "Resistor_SMD:R_1206_3216Metric", "C": "Capacitor_SMD:C_1206_3216Metric"}


def _tracks(b, cls: str):
    return [t for t in b.GetTracks() if t.GetClass() == cls]


# ------------------------------------------------------------------ ATTACKS3
def fpid_relabel(wd: str) -> None:
    """Relabel every R/C footprint id as 1206 (design + board) without changing the pads:
    the cheap 'upsizing' a rules fault (resistor/capacitor underrated) would need."""
    import pcbnew
    d = _rd(wd)
    b = _board(wd)
    for ref, c in d["components"].items():
        new = R_C_BIG.get(c["part"])
        fp = b.FindFootprintByReference(ref)
        if not new or fp is None:
            continue
        lib, name = new.split(":")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        c["footprint"] = new
    _save(wd, b)
    _wd_json(wd, d)


def tools_full_route_all(wd: str) -> None:
    """no_autoroute bypass: flip tools.json to full, then auto-route every net."""
    t = Path(wd, "tools.json")
    if t.exists():
        t.write_text(json.dumps({"mode": "full"}), encoding="utf-8")
    for n in sorted(_rd(wd)["nets"]):
        _pcbtool(wd, "route", n)


def upsize_all(wd: str) -> None:
    """Every R/C/LED to its largest allowed footprint via pcbtool (rule-fault 'blanket fix')."""
    d = _rd(wd)
    big = {**R_C_BIG, "LED_RED": "LED_SMD:LED_0805_2012Metric", "LED_GREEN": "LED_SMD:LED_0805_2012Metric"}
    for ref, c in sorted(d["components"].items()):
        if c["part"] in big and c["footprint"] != big[c["part"]]:
            _pcbtool(wd, "set-footprint", ref, big[c["part"]])


def values_to_bound_min(wd: str) -> None:
    """Every bounded value to the low end of its published bound (rules: less dissipation in R)."""
    spec = json.load(open(Path(wd, "spec.json")))
    for r, (lo, _hi) in sorted((spec.get("value_bounds") or {}).items()):
        _pcbtool(wd, "set-value", r, f"{lo:.6g}")


def via_zero_drill(wd: str) -> None:
    b = _board(wd)
    for v in _tracks(b, "PCB_VIA"):
        v.SetDrill(0)
    _save(wd, b)


def all_tracks_bcu(wd: str) -> None:
    """Every track to B.Cu (no layer-dependent rule sees a same-layer run)."""
    import pcbnew
    b = _board(wd)
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            t.SetLayer(pcbnew.B_Cu)
    _save(wd, b)


def delete_vias(wd: str) -> None:
    """Remove every via (crystal_via fault: 'no via on the oscillator net')."""
    b = _board(wd)
    for v in _tracks(b, "PCB_VIA"):
        b.Remove(v)
    _save(wd, b)


def shrink_power_tracks_netless(wd: str) -> None:
    """Narrow every track to 0.2 mm and move it to net 0 (width rule keyed by net name)."""
    b = _board(wd)
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            t.SetWidth(_mm(0.2))
        t.SetNetCode(0)
    _save(wd, b)


# ------------------------------------------------------------------ NEUTRAL3 (physically equivalent)
def split_segments(wd: str) -> None:
    """Split every straight segment in two at its midpoint (same copper)."""
    import pcbnew
    b = _board(wd)
    for t in _tracks(b, "PCB_TRACK"):
        s, e = t.GetStart(), t.GetEnd()
        m = pcbnew.VECTOR2I((s.x + e.x) // 2, (s.y + e.y) // 2)
        if (m.x, m.y) in ((s.x, s.y), (e.x, e.y)):
            continue
        t2 = pcbnew.PCB_TRACK(b)
        t2.SetStart(m)
        t2.SetEnd(e)
        t2.SetWidth(t.GetWidth())
        t2.SetLayer(t.GetLayer())
        t2.SetNetCode(t.GetNetCode())
        t.SetEnd(m)
        b.Add(t2)
    _save(wd, b)


def duplicate_segments(wd: str) -> None:
    """Every straight segment twice (same copper; duplicates are legal same-net overlap)."""
    import pcbnew
    b = _board(wd)
    for t in _tracks(b, "PCB_TRACK"):
        t2 = pcbnew.PCB_TRACK(b)
        t2.SetStart(t.GetStart())
        t2.SetEnd(t.GetEnd())
        t2.SetWidth(t.GetWidth())
        t2.SetLayer(t.GetLayer())
        t2.SetNetCode(t.GetNetCode())
        b.Add(t2)
    _save(wd, b)


def zero_length_stubs(wd: str) -> None:
    """A zero-length segment at every track start."""
    import pcbnew
    b = _board(wd)
    for t in _tracks(b, "PCB_TRACK"):
        t2 = pcbnew.PCB_TRACK(b)
        t2.SetStart(t.GetStart())
        t2.SetEnd(t.GetStart())
        t2.SetWidth(t.GetWidth())
        t2.SetLayer(t.GetLayer())
        t2.SetNetCode(t.GetNetCode())
        b.Add(t2)
    _save(wd, b)


def straight_arcs(wd: str) -> None:
    """Every straight segment of 0.5-20 mm re-drawn as an arc with a 50 µm bulge (inside the track's
    own copper; radius stays < 2^31 nm -- a near-straight arc with a larger radius makes KiCad 7 abort
    in kimath, which the verifier reports as a failure: fail closed)."""
    import pcbnew
    b = _board(wd)
    for t in _tracks(b, "PCB_TRACK"):
        s, e = t.GetStart(), t.GetEnd()
        L = math.hypot(e.x - s.x, e.y - s.y)
        if not 5e5 <= L <= 2e7:
            continue
        nx, ny = -(e.y - s.y) / L, (e.x - s.x) / L
        m = pcbnew.VECTOR2I(int((s.x + e.x) / 2 + nx * 50000), int((s.y + e.y) / 2 + ny * 50000))
        a = pcbnew.PCB_ARC(b)
        a.SetStart(s)
        a.SetMid(m)
        a.SetEnd(e)
        a.SetWidth(t.GetWidth())
        a.SetLayer(t.GetLayer())
        a.SetNetCode(t.GetNetCode())
        b.Remove(t)
        b.Add(a)
    _save(wd, b)


ATTACKS3 = {f.__name__: f for f in (
    fpid_relabel, tools_full_route_all, upsize_all, values_to_bound_min, via_zero_drill, all_tracks_bcu,
    delete_vias, shrink_power_tracks_netless, split_segments, duplicate_segments, zero_length_stubs,
    straight_arcs)}
NEUTRAL3 = {f.__name__: f for f in (split_segments, duplicate_segments, zero_length_stubs, via_zero_drill)}
EXPERT_REJECTS3 = {f.__name__: f for f in (fpid_relabel, all_tracks_bcu, shrink_power_tracks_netless)}


def via_tiny_drill(wd: str) -> None:
    """Every via with an explicit 10 µm drill (unmanufacturable; DRC min hole 0.3 mm)."""
    b = _board(wd)
    for v in _tracks(b, "PCB_VIA"):
        v.SetDrill(_mm(0.01))
    _save(wd, b)


ATTACKS3["via_tiny_drill"] = via_tiny_drill
EXPERT_REJECTS3["via_tiny_drill"] = via_tiny_drill
