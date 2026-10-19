"""Round-2 attacks (see redteam/exploits.md, RT30+).

Two kinds:
- ATTACKS2: attacks that must NOT turn a faulted task into 1.0 (scripted run, like round 1).
- NEUTRAL: edits an expert accepts (equivalent value notation, symmetric-pin swap, flipping a
  part, another allowed footprint size, grouping/locking). Applied to the GOLDEN they must keep
  reward 1.0 (else the verifier rejects a correct board = false negative); applied to a faulted
  task they must not fix it.
- EXPERT_REJECTS: edits an expert rejects. Applied to the GOLDEN they must give 0.0, else the
  verifier accepts a bad board (EXPERT-DISAGREES).
All functions take the workdir only and read public files only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from redteam.attacks.basic import B, D, _pcbtool, _rd, _wd_json

SYM = {"R", "C", "L", "XTAL", "XTAL_CL18"}
POLAR = {"A": "K", "K": "A"}


def _board(wd: str):
    import pcbnew
    return pcbnew.LoadBoard(str(Path(wd, B)))


def _save(wd: str, b) -> None:
    import pcbnew
    assert pcbnew.SaveBoard(str(Path(wd, B)), b, True)


def _mm(x: float) -> int:
    return int(round(x * 1e6))


def _outline(b) -> tuple[float, float, float, float]:
    bb = b.GetBoardEdgesBoundingBox()
    return bb.GetX() / 1e6, bb.GetY() / 1e6, bb.GetRight() / 1e6, bb.GetBottom() / 1e6


def _nets_of_ref(d: dict, ref: str) -> list[str]:
    return sorted(n for n, ps in d["nets"].items() if any(p.split(".", 1)[0] == ref for p in ps))


def _reroute(wd: str, nets) -> None:
    for n in sorted(set(nets)):
        _pcbtool(wd, "route", n)


def _victim(d: dict) -> str:
    """A non-connector part (deterministic): the first R/C, else the first non-J ref."""
    refs = sorted(d["components"])
    for r in refs:
        if d["components"][r]["part"] in ("R", "C"):
            return r
    return next(r for r in refs if not r.startswith("J"))


# ------------------------------------------------------------- must-not-fix attacks
def nettie_footprints(wd: str) -> None:
    """Declare every footprint a net tie (DRC then ignores shorts between its pads)."""
    b = _board(wd)
    for fp in b.GetFootprints():
        nums = sorted({p.GetNumber() for p in fp.Pads()})
        if len(nums) >= 2:
            fp.AddNetTiePadGroup(", ".join(nums))
    _save(wd, b)


def zero_size_pads(wd: str) -> None:
    import pcbnew
    b = _board(wd)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            p.SetSize(pcbnew.VECTOR2I(0, 0))
    _save(wd, b)


def keepout_area(wd: str) -> None:
    """A rule area (keepout) over the whole board, no tracks/vias/pads allowed."""
    import pcbnew
    b = _board(wd)
    x0, y0, x1, y1 = _outline(b)
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowCopperPour(True)
    z.SetLayer(pcbnew.F_Cu)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(_mm(x), _mm(y))
    b.Add(z)
    _save(wd, b)


def _board_text(wd: str) -> str:
    return Path(wd, B).read_text(encoding="utf-8")


def _put_board_text(wd: str, s: str) -> None:
    Path(wd, B).write_text(s, encoding="utf-8")


def _new_net(s: str, name: str) -> tuple[str, int]:
    """Declare a new net code (text level) right after the last top-level net declaration."""
    decls = list(re.finditer(r'^  \(net (\d+) "[^"]*"\)\n', s, re.M))
    k = max(int(m.group(1)) for m in decls) + 1
    i = decls[-1].end()
    return s[:i] + f'  (net {k} "{name}")\n' + s[i:], k


_TRACK_NET = re.compile(r'^(\s*\((?:segment|via|arc) .*?\(net )(\d+)(\))', re.M)


def power_tracks_other_net(wd: str) -> None:
    """Move every track/via to a fresh pad-less net (text level)."""
    s, k = _new_net(_board_text(wd), "RT_SHADOW")
    _put_board_text(wd, _TRACK_NET.sub(lambda m: f"{m.group(1)}{k}{m.group(3)}", s))


def netless_tracks(wd: str) -> None:
    """Every track/via on net 0 (no net)."""
    _put_board_text(wd, _TRACK_NET.sub(lambda m: f"{m.group(1)}0{m.group(3)}", _board_text(wd)))


def dup_net_names(wd: str) -> None:
    """Second net code with an existing name; every other pad of that net moved to it (text)."""
    s = _board_text(wd)
    m = re.search(r'^  \(net (\d+) "([^"]+)"\)\n', s, re.M)
    if not m:
        return
    code, name = m.group(1), m.group(2)
    s, k = _new_net(s, name)
    pat = re.compile(r'(\(pad "[^"]*" [^\n]*?|\n\s+)\(net ' + code + r' "' + re.escape(name) + r'"\)')
    n = [0]

    def sub(mm):
        n[0] += 1
        return mm.group(0) if n[0] % 2 else mm.group(1) + f'(net {k} "{name}")'
    _put_board_text(wd, pat.sub(sub, s))


def sync_design_from_board(wd: str) -> None:
    """Make design.json follow the board's pad nets (the opposite of `pcbtool sync`)."""
    from pcbenv import boardnet
    d = _rd(wd)
    parts = {r: c["part"] for r, c in d["components"].items()}
    info = boardnet.board_info(str(Path(wd, B)), parts=parts)
    nets = {}
    for n, pins in sorted(info.net_pins.items()):
        ok = sorted(p for p in pins if "#" not in p)
        if ok:
            nets[n or "N"] = ok
    d["nets"] = nets
    for r, v in info.values.items():
        if r in d["components"]:
            d["components"][r]["value"] = v
    _wd_json(wd, d)


def polarity_and_symmetric(wd: str) -> None:
    """Swap A/K of every diode/LED plus 1/2 of every symmetric part (design + board + reroute)."""
    _swap_pins(wd, polar=True)


def lock_everything(wd: str) -> None:
    """Group + lock everything (neutral by itself; checks the verifier copes)."""
    import pcbnew
    b = _board(wd)
    g = pcbnew.PCB_GROUP(b)
    g.SetName("rt_all")
    b.Add(g)
    for fp in b.GetFootprints():
        fp.SetLocked(True)
        g.AddItem(fp)
    for t in b.GetTracks():
        t.SetLocked(True)
    _save(wd, b)


# ------------------------------------------------------------- value notation
def _rewrite_values(wd: str, fn) -> None:
    from pcbenv.parts import PARTS
    d = _rd(wd)
    vals = {}
    for r, c in sorted(d["components"].items()):
        if c.get("value") and PARTS[c["part"]].value_required:
            c["value"] = vals[r] = fn(c["value"], c["part"])
    _wd_json(wd, d)
    b = _board(wd)
    for r, v in vals.items():
        fp = b.FindFootprintByReference(r)
        if fp is not None:
            fp.SetValue(v)
    _save(wd, b)


_UNIT = {"R": "Ω", "C": "F", "L": "H", "XTAL": "Hz", "XTAL_CL18": "Hz"}


def value_sci(wd: str) -> None:
    from pcbenv.parts import parse_value
    _rewrite_values(wd, lambda v, p: f"{parse_value(v):.6e}")


def value_plain(wd: str) -> None:
    from pcbenv.parts import parse_value
    _rewrite_values(wd, lambda v, p: f"{parse_value(v):.10g}")


def value_units(wd: str) -> None:
    _rewrite_values(wd, lambda v, p: v + _UNIT.get(p, ""))


def value_micro_sign(wd: str) -> None:
    _rewrite_values(wd, lambda v, p: v.replace("u", "µ"))


def value_spaces(wd: str) -> None:
    _rewrite_values(wd, lambda v, p: f" {v} ")


# ------------------------------------------------------------- placement / footprints
def _swap_pins(wd: str, polar: bool) -> None:
    import pcbnew
    from pcbenv.parts import PARTS
    d = _rd(wd)
    idx = {p: n for n, ps in d["nets"].items() for p in ps}
    touched, swaps = set(), []
    for r, c in sorted(d["components"].items()):
        part = c["part"]
        if part in SYM:
            a, b_ = f"{r}.1", f"{r}.2"
        elif polar and set(PARTS[part].pins) == {"A", "K"}:
            a, b_ = f"{r}.A", f"{r}.K"
        else:
            continue
        na, nb = idx.get(a), idx.get(b_)
        if na == nb:
            continue
        swaps.append((r, a, b_, na, nb))
    for r, a, b_, na, nb in swaps:
        if na:
            d["nets"][na] = [b_ if p == a else p for p in d["nets"][na]]
        if nb:
            d["nets"][nb] = [a if p == b_ else p for p in d["nets"][nb]]
        touched |= {na, nb} - {None}
    _wd_json(wd, d)
    b = _board(wd)
    for n in touched:
        code = b.GetNetcodeFromNetname(n)
        for t in list(b.GetTracks()):
            if t.GetNetCode() == code:
                b.Delete(t)
    for r, a, b_, na, nb in swaps:
        part = PARTS[d["components"][r]["part"]]
        fp = b.FindFootprintByReference(r)
        pa, pb = part.pins[a.split(".")[1]].pad, part.pins[b_.split(".")[1]].pad
        pads = {p.GetNumber(): p for p in fp.Pads()}
        ca, cb = pads[pa].GetNetCode(), pads[pb].GetNetCode()
        pads[pa].SetNetCode(cb)
        pads[pb].SetNetCode(ca)
    _save(wd, b)
    _reroute(wd, touched)


def symmetric_pinswap(wd: str) -> None:
    """Swap pins 1/2 of every R/C/L/crystal (design + board pads), re-route the touched nets."""
    _swap_pins(wd, polar=False)


def flip_part(wd: str) -> None:
    """Put one passive on the back side (same x, y) and re-route its nets."""
    import pcbnew
    d = _rd(wd)
    r = _victim(d)
    b = _board(wd)
    fp = b.FindFootprintByReference(r)
    fp.Flip(fp.GetPosition(), False)
    nets = _nets_of_ref(d, r)
    for t in list(b.GetTracks()):
        if t.GetNetname() in nets:
            b.Delete(t)
    _save(wd, b)
    _reroute(wd, nets)


def other_footprint_size(wd: str) -> None:
    """Every R/C/L/LED to another allowed footprint (pcbtool set-footprint), then re-route all."""
    from pcbenv.parts import PARTS
    d = _rd(wd)
    for r, c in sorted(d["components"].items()):
        fps = PARTS[c["part"]].footprints
        if c["part"] in ("R", "C", "L") and len(fps) > 1:
            _pcbtool(wd, "set-footprint", r, fps[(fps.index(c["footprint"]) + 1) % len(fps)] if c["footprint"] in fps else fps[0])
    _reroute(wd, _rd(wd)["nets"])


def offboard_part(wd: str) -> None:
    """Move one passive 15 mm outside the board outline and re-route its nets to it."""
    d = _rd(wd)
    r = _victim(d)
    x0, y0, x1, y1 = _outline(_board(wd))
    _pcbtool(wd, "move", r, f"{x1 + 15:.2f}", f"{(y0 + y1) / 2:.2f}", "0")
    _reroute(wd, _nets_of_ref(d, r))


def overlap_part(wd: str) -> None:
    """Move one passive exactly onto another component's position (stacked parts)."""
    d = _rd(wd)
    r = _victim(d)
    b = _board(wd)
    other = next(fp for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()) if fp.GetReference() != r)
    p = other.GetPosition()
    _pcbtool(wd, "move", r, f"{p.x / 1e6:.3f}", f"{p.y / 1e6:.3f}", "0")
    _reroute(wd, _nets_of_ref(d, r))


ATTACKS2 = {f.__name__: f for f in (
    nettie_footprints, zero_size_pads, keepout_area, power_tracks_other_net, netless_tracks,
    dup_net_names, sync_design_from_board, polarity_and_symmetric, lock_everything,
    value_sci, value_plain, value_units, value_micro_sign, value_spaces,
    symmetric_pinswap, flip_part, other_footprint_size, offboard_part, overlap_part,
)}
NEUTRAL = {f.__name__: f for f in (lock_everything, value_sci, value_plain, value_units, value_micro_sign,
                                    value_spaces, symmetric_pinswap, flip_part, other_footprint_size)}
EXPERT_REJECTS = {f.__name__: f for f in (offboard_part, overlap_part, polarity_and_symmetric,
                                          nettie_footprints, zero_size_pads)}
# genuine repairs for some fault types (shipped tasks): excluded from those pairs
LEGIT_FOR2 = {
    "flip_part": {"broken_trace", "clearance_violation", "short_between_nets", "narrow_power_trace"},
    "other_footprint_size": {"broken_trace", "clearance_violation", "short_between_nets", "narrow_power_trace",
                             "footprint_swap"},
    "symmetric_pinswap": {"broken_trace", "clearance_violation", "short_between_nets", "narrow_power_trace"},
    "offboard_part": set(), "overlap_part": set(),
}
