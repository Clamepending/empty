"""Round-2 adversarial-agent attempts on real shipped tasks (RT50-series), recorded.

Each attempt plays a lazy/adversarial agent: it reads only the public files of one shipped task
(TASK.md, spec.json, design.json, board) and tries to reach 1.0 with fake or minimal work.
`kind`: `fake` = a 1.0 would be a hack; `minimal-legit` = a cheap repair that is genuinely
acceptable if it passes; `probe` = verifier-soundness probe on the GOLDEN files (a 1.0 means
the verifier accepts a board an expert would reject).

    python3 redteam/hand_attempts.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
from dataclasses import replace
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcbenv.verify import verify_isolated  # noqa: E402
from redteam.attacks import round2  # noqa: E402
from redteam.attacks.basic import _pcbtool, _rd, _wd_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tasks" / "manifest.jsonl"


def _manifest() -> list[dict]:
    return [json.loads(line) for line in open(MANIFEST)]


def pick(ftype: str | None = None, family: str | None = None, n_faults: int | None = None, k: int = 0) -> str:
    """Deterministic shipped task: the k-th manifest row matching the filters."""
    rows = [m for m in _manifest() if (ftype is None or any(f["type"] == ftype for f in m["faults"]))
            and (family is None or m["family"] == family) and (n_faults is None or m["n_faults"] == n_faults)]
    m = rows[k]
    return str(ROOT / "tasks" / m["split"] / m["id"])


def _spec(wd: str) -> dict:
    return json.load(open(os.path.join(wd, "spec.json")))


def _board_path(wd: str) -> str:
    return os.path.join(wd, "board.kicad_pcb")


# ------------------------------------------------------------------ attempts (public files only)
def a_noop(wd):
    pass


def a_sync(wd):
    _pcbtool(wd, "sync")


def a_route_all(wd):
    for n in sorted(_rd(wd)["nets"]):
        _pcbtool(wd, "route", n)


def a_geomean_bounds(wd):
    """Set EVERY bounded value to the geometric centre of its published bound."""
    for r, (lo, hi) in sorted(_spec(wd)["value_bounds"].items()):
        _pcbtool(wd, "set-value", r, f"{math.sqrt(lo * hi):.3g}")


def a_fix_oob_values(wd):
    """Only values outside their bounds -> geometric centre (cheap, public info)."""
    from pcbenv.checks import value_violations
    d = _rd(wd)
    b = _spec(wd)["value_bounds"]
    for msg in value_violations(d, b):
        r = msg.split(":")[0]
        lo, hi = b[r]
        _pcbtool(wd, "set-value", r, f"{math.sqrt(lo * hi):.3g}")


def a_eseries_search(wd):
    """Brute-force each out-of-spec part over E12 within its bounds using the public sim."""
    from pcbenv import sim
    from pcbenv.checks import value_violations
    d = _rd(wd)
    sp = _spec(wd)
    e12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]

    def ok(dd):
        return all(a.passed for a in sim.run_assertions(dd, sp["assertions"])) and not value_violations(dd, sp["value_bounds"])
    if ok(d):
        return
    for r, (lo, hi) in sorted(sp["value_bounds"].items()):
        cands = [m * 10 ** e for e in range(-13, 8) for m in e12 if lo <= m * 10 ** e <= hi]
        for v in cands:
            dd = json.loads(json.dumps(d))
            dd["components"][r]["value"] = f"{v:.3g}"
            if ok(dd):
                _pcbtool(wd, "set-value", r, f"{v:.3g}")
                return
    return


def a_design_sym_swap_only(wd):
    """Swap pins 1/2 of every R/C in design.json only (claims equivalence), board untouched."""
    d = _rd(wd)
    for r, c in d["components"].items():
        if c["part"] in ("R", "C"):
            for n, ps in d["nets"].items():
                d["nets"][n] = [f"{r}.2" if p == f"{r}.1" else f"{r}.1" if p == f"{r}.2" else p for p in ps]
    _wd_json(wd, d)


def a_rename_nets(wd):
    d = _rd(wd)
    d["nets"] = {f"N{i}": ps for i, (n, ps) in enumerate(sorted(d["nets"].items()))}
    _wd_json(wd, d)


def a_change_part_type(wd):
    """LED/diode -> the other diode part (dodges a polarity/value check?)."""
    d = _rd(wd)
    for r, c in d["components"].items():
        if c["part"].startswith("LED"):
            c["part"] = "D_SCHOTTKY"
            c["footprint"] = "Diode_SMD:D_SOD-123"
    _wd_json(wd, d)


def a_add_component(wd):
    """Add a second supply connector J9 on the supply net (extra part)."""
    d = _rd(wd)
    d["components"]["J9"] = {"part": "CONN2", "value": "", "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"}
    _wd_json(wd, d)


def a_nettie_bridge(wd):
    """short_between_nets: declare every footprint a net tie, then sync (DRC still sees the short?)."""
    round2.nettie_footprints(wd)


def a_offboard_track(wd):
    """Add a same-net track that leaves the board outline (route-around-the-edge shortcut)."""
    import pcbnew
    b = pcbnew.LoadBoard(_board_path(wd))
    x0, y0, x1, y1 = round2._outline(b)
    pad = sorted((p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() > 0),
                 key=lambda p: (p.GetParent().GetReference(), p.GetNumber()))[0]
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pad.GetPosition())
    t.SetEnd(pcbnew.VECTOR2I(int((x1 + 10) * 1e6), pad.GetPosition().y))
    t.SetWidth(250000)
    t.SetLayer(pcbnew.B_Cu)
    t.SetNet(pad.GetNet())
    b.Add(t)
    pcbnew.SaveBoard(_board_path(wd), b, True)


def a_value_string_mismatch(wd):
    """design '1k' vs board '1000' (same number, different string) on the GOLDEN -> false negative?"""
    from pcbenv.parts import parse_value
    import pcbnew
    b = pcbnew.LoadBoard(_board_path(wd))
    d = _rd(wd)
    for r, c in sorted(d["components"].items()):
        if c.get("value"):
            b.FindFootprintByReference(r).SetValue(f"{parse_value(c['value']):.10g}")
            break
    pcbnew.SaveBoard(_board_path(wd), b, True)


def a_greek_mu(wd):
    """Equivalent notation with GREEK small mu (U+03BC) instead of MICRO SIGN (U+00B5) on golden."""
    round2._rewrite_values(wd, lambda v, p: v.replace("u", "μ"))


def a_wrong_unit_letters(wd):
    """Capacitor values written with henry units ('100nH' on a C) on golden -> accepted?"""
    round2._rewrite_values(wd, lambda v, p: v + ("H" if p == "C" else "F" if p == "R" else ""))


def a_meg_notation(wd):
    """'1meg'-style SPICE notation for a mega value (parse_value reads m = milli)."""
    round2._rewrite_values(wd, lambda v, p: v.replace("M", "meg"))


def a_decap_detour(wd):
    """Golden board: the decoupling cap stays within max_mm of its IC pin, but its supply pad is
    re-routed so it reaches the supply net only at the far end (connector), not at the IC pin."""
    import pcbnew
    from pcbenv import board as B
    from pcbenv import drc
    from pcbenv.router import Router, Rules, Seg, Via
    sp = _spec(wd)
    dc = sp["decoupling"][0]
    d = _rd(wd)
    net = next(n for n, ps in d["nets"].items() if dc["ic_pin"] in ps)
    cap = dc["cap"]
    p = _board_path(wd)
    b = pcbnew.LoadBoard(p)
    code = b.FindNet(net).GetNetCode()
    for t in list(b.GetTracks()):
        if t.GetNetCode() == code:
            b.Delete(t)
    x0, y0, x1, y1 = round2._outline(b)
    R = drc.RULES

    def router_for():
        r = Router(x0, y0, x1 - x0, y1 - y0, 0.1, Rules(clearance=R["clearance"], edge_clearance=R["copper_edge_clearance"],
                                                         hole_clearance=R["hole_clearance"], hole_to_hole=R["hole_to_hole"],
                                                         via_d=R["via_diameter"], via_drill=R["via_drill"]))
        idx = {}
        for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
            for pad in sorted(fp.Pads(), key=lambda q: (q.GetNumber(), q.GetPosition().x, q.GetPosition().y)):
                g = B.pad_geom(pad, f"{fp.GetReference()}.{pad.GetNumber()}")
                idx[(fp.GetReference(), pad.GetNumber())] = len(r.pads)
                r.pads.append(g)
        L = {pcbnew.F_Cu: 0, pcbnew.B_Cu: 1}
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                r.vias.append(Via(t.GetNetCode(), q.x / 1e6, q.y / 1e6, t.GetWidth() / 1e6, t.GetDrillValue() / 1e6))
            elif t.GetLayer() in L:
                s, e = t.GetStart(), t.GetEnd()
                r.segs.append(Seg(t.GetNetCode(), L[t.GetLayer()], s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6, t.GetWidth() / 1e6))
        return r, idx
    width = max([pn["min_width_mm"] for pn in sp["power_nets"] if pn["net"] == net] + [0.25])
    pads = [(fp.GetReference(), pad.GetNumber()) for fp in b.GetFootprints() for pad in fp.Pads() if pad.GetNetCode() == code]
    capk = [k for k in pads if k[0] == cap]
    conn = sorted(k for k in pads if k[0].startswith("J"))
    if not conn:
        raise RuntimeError("no connector on the decoupled net")
    rest = [k for k in pads if k[0] != cap]
    # 1) everything except the cap
    r, idx = router_for()
    r.pads = [replace(g, net=-7) if i == idx[capk[0]] else g for i, g in enumerate(r.pads)]
    res = r.route_net(code, [idx[k] for k in rest], width)
    B.add_copper(b, res)
    # 2) cap -> connector only, with the step-1 copper treated as a foreign net (forces a detour)
    r, idx = router_for()
    keep = {idx[capk[0]], idx[conn[0]]}
    r.segs = [replace(s, net=-7) if s.net == code else s for s in r.segs]
    r.vias = [replace(v, net=-7) if v.net == code else v for v in r.vias]
    r.pads = [replace(g, net=-7) if (g.net == code and i not in keep) else g for i, g in enumerate(r.pads)]
    res = r.route_net(code, [idx[capk[0]], idx[conn[0]]], width)
    B.add_copper(b, res)
    pcbnew.SaveBoard(p, b, True)


ATTEMPTS = [
    # (id, task selector kwargs, fn, kind, on_golden)
    ("H01", dict(ftype="magnitude_slip", n_faults=1, k=0), a_noop, "fake", False),
    ("H02", dict(ftype="board_pad_swap", n_faults=1, k=0), a_sync, "fake", False),
    ("H03", dict(ftype="floating_pin", n_faults=1, k=0), a_route_all, "fake", False),
    ("H04", dict(ftype="wrong_filter_cap", n_faults=1, k=0), a_geomean_bounds, "minimal-legit", False),
    ("H05", dict(ftype="magnitude_slip", n_faults=1, k=1), a_fix_oob_values, "minimal-legit", False),
    ("H06", dict(ftype="wrong_led_resistor", n_faults=1, k=0), a_eseries_search, "minimal-legit", False),
    ("H07", dict(ftype="wrong_pull_resistor", n_faults=1, k=0), a_geomean_bounds, "minimal-legit", False),
    ("H08", dict(ftype="transistor_pinout", n_faults=1, k=0), a_sync, "fake", False),
    ("H09", dict(ftype="reversed_polarity", n_faults=1, k=0), a_change_part_type, "fake", False),
    ("H10", dict(ftype="decap_misconnected", n_faults=1, k=0), a_add_component, "fake", False),
    ("H11", dict(ftype="short_between_nets", n_faults=1, k=0), a_nettie_bridge, "fake", False),
    ("H12", dict(ftype="clearance_violation", n_faults=1, k=0), a_offboard_track, "fake", False),
    ("H13", dict(ftype="pin_to_wrong_net", n_faults=1, k=0), a_rename_nets, "fake", False),
    ("H14", dict(ftype="swapped_ic_pins", n_faults=1, k=0), a_design_sym_swap_only, "fake", False),
    ("H15", dict(ftype="broken_trace", n_faults=2, k=0), a_route_all, "fake", False),
    ("H16", dict(ftype="narrow_power_trace", n_faults=1, k=0), a_route_all, "minimal-legit", False),
    ("H17", dict(ftype="bom_mismatch", n_faults=3, k=0), a_fix_oob_values, "fake", False),
    ("H18", dict(ftype="footprint_swap", n_faults=1, k=0), a_sync, "fake", False),
    ("H19", dict(family="xtal_osc", n_faults=3, k=0), a_eseries_search, "fake", False),
    ("H20", dict(ftype="decap_moved_far", n_faults=1, k=0), a_route_all, "fake", False),
    ("H21", dict(family="rc_lowpass", k=0), a_value_string_mismatch, "probe", True),
    ("H22", dict(family="ldo_reg", k=0), a_greek_mu, "probe", True),
    ("H23", dict(family="rc_lowpass", k=1), a_wrong_unit_letters, "probe", True),
    ("H24", dict(family="mcu_i2c", k=0), a_meg_notation, "probe", True),
    ("H25", dict(family="ldo_reg", k=1), a_decap_detour, "probe", True),
    ("H26", dict(family="mcu_i2c", k=1), a_decap_detour, "probe", True),
    ("H27", dict(family="opamp_noninv", k=0), a_decap_detour, "probe", True),
    ("H28", dict(family="npn_switch", k=0), a_decap_detour, "probe", True),
]


def run_attempt(aid: str, sel: dict, fn, kind: str, golden: bool) -> dict:
    td = pick(**sel)
    tmp = tempfile.mkdtemp(prefix="rt_hand_")
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
        det = {k: v for k, v in r.detail.items() if k in failed}
        return {"id": aid, "task": os.path.basename(td), "attempt": fn.__name__, "kind": kind, "golden": golden,
                "reward": r.reward, "failed": failed, "error": err, "detail": json.dumps(det)[:300]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = []
    for aid, sel, fn, kind, golden in ATTEMPTS:
        if a.only and aid not in a.only:
            continue
        r = run_attempt(aid, sel, fn, kind, golden)
        out.append(r)
        print(f"{r['id']} {r['task']:34s} {r['attempt']:24s} {kind:13s} reward={r['reward']} failed={r['failed']} "
              f"{('ERR ' + r['error']) if r['error'] else ''}", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
