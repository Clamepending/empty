"""Layout design rules (hard tier, `hard_layout` sub-tier): board-geometry rules graded by the
verifier, stated in TASK.md "Layout rules" and `spec.json:layout_rules`, NOT run by pcbtool.

Every rule names its parts by public pins (`REF.PIN`) and nets by the pins on them, never by net
name. Geometry is read from the candidate board.kicad_pcb in mm (KiCad coordinates). The rule
context (`meta["layout_rules"]` == `spec.json["layout_rules"]`) is built from the golden by
`layout_rules_context`; `run_layout_rules(board, ctx, ref_parts)` returns the violations.

Rules (precise definitions are in `rules_md`, the public text):

- kelvin       the ADC sense connection must leave from the shunt pad itself: delete the shunt pad
               from the sense net's copper; the copper island holding the sense pin's pad must not
               contain the load-current pin's pad (no shared copper with the power path).
- switch_loop  hot loop of the low-side switch: the closed path made of the shortest copper paths
               between consecutive loop pads (pad centre to pad centre, `layout.copper_path`) and
               straight lines through each part body; |shoelace area| <= max_area_mm2.
- crystal      copper path MCU oscillator pin -> crystal pad <= max_path_mm; no via on either net.
- separation   total length of the victim net's track centrelines that lie within min_gap_mm
               (centreline to centreline) of an aggressor-net track on the same copper layer
               <= max_parallel_mm.
- decoupling   unchanged: graded by `layout.run_layout_checks` (check `layout`), restated here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pcbenv import boardnet
from pcbenv.parts import PARTS

VERSION = 1
EPS = 1e-6

# Limits (mm / mm²). Chosen so every golden passes with margin (reports/v2_generation.md,
# tests/test_layout_rules.py): golden builder targets are LIMIT * GOLDEN_MARGIN.
LOOP_MAX_AREA_MM2 = 60.0
XTAL_MAX_PATH_MM = 10.0
SEP_MIN_GAP_MM = 1.0
SEP_MAX_PARALLEL_MM = 3.0
GOLDEN_MARGIN = 0.8


@dataclass(frozen=True)
class LayoutViolation:
    code: str
    detail: str


# ------------------------------------------------------------------ context (from the golden)
def _net_of(design: dict, pin: str) -> str | None:
    for n, pins in design["nets"].items():
        if pin in pins:
            return n
    return None


def _comps(design: dict, part: str) -> list[str]:
    return sorted(r for r, c in design["components"].items() if c["part"] == part)


def motor_roles(design: dict) -> dict | None:
    """Refs of the low-side motor stage: switch Q (NMOS), flyback D (cathode on the motor supply,
    anode on the drain), bulk cap CB (supply to GND), shunt RS (source to GND), sense resistor RF
    (source node to the ADC), the MCU ADC pin. None if the design has no such stage."""
    gnd = _net_of(design, "J1.2")
    for q in _comps(design, "NMOS"):
        nd, ns = _net_of(design, f"{q}.D"), _net_of(design, f"{q}.S")
        if nd is None or ns is None or ns == gnd:
            continue
        d = next((x for x in _comps(design, "D_SCHOTTKY") if _net_of(design, f"{x}.A") == nd), None)
        if d is None:
            continue
        sup = _net_of(design, f"{d}.K")
        cb = rs = rf = None
        for c in _comps(design, "C"):
            n1, n2 = _net_of(design, f"{c}.1"), _net_of(design, f"{c}.2")
            if {n1, n2} == {sup, gnd}:
                cb = cb or (c, "1" if n1 == sup else "2", "2" if n1 == sup else "1")
        for r in _comps(design, "R"):
            n1, n2 = _net_of(design, f"{r}.1"), _net_of(design, f"{r}.2")
            if {n1, n2} == {ns, gnd}:
                rs = rs or (r, "1" if n1 == ns else "2", "2" if n1 == ns else "1")
            elif ns in (n1, n2):
                other = n2 if n1 == ns else n1
                adc = [p for p in design["nets"].get(other, []) if p.split(".")[1].startswith("PA")
                       and design["components"][p.split(".")[0]]["part"] == "MCU8"]
                if adc:
                    rf = rf or (r, "1" if n1 == ns else "2", adc[0])
        if cb and rs and rf:
            return {"q": q, "d": d, "cb": cb, "rs": rs, "rf": rf}
    return None


def crystal_roles(design: dict) -> list[dict]:
    out = []
    for u in _comps(design, "MCU8"):
        for y, c in sorted(design["components"].items()):
            if not c["part"].startswith("XTAL"):
                continue
            pairs = []
            for mp in ("PA1", "PA2"):
                n = _net_of(design, f"{u}.{mp}")
                yp = next((f"{y}.{p}" for p in ("1", "2") if _net_of(design, f"{y}.{p}") == n), None)
                if n is not None and yp:
                    pairs.append([f"{u}.{mp}", yp])
            if len(pairs) == 2:
                out.append({"xtal": y, "mcu": u, "pairs": pairs})
    return out


def layout_rules_context(golden) -> dict:
    """Public + graded rule context of a golden (composite families). Empty rule lists are
    omitted; `{}` when no rule applies."""
    d = golden.design
    ctx: dict = {"version": VERSION}
    m = motor_roles(d)
    if m:
        q, dd = m["q"], m["d"]
        cb, cbs, cbg = m["cb"]
        rs, rss, rsg = m["rs"]
        rf, rfs, adc = m["rf"]
        ctx["kelvin"] = [{"shunt": rs, "shunt_pin": f"{rs}.{rss}", "sense_pin": f"{rf}.{rfs}",
                          "load_pins": [f"{q}.S"]}]
        ctx["switch_loop"] = [{"name": "motor switch commutation loop",
                               "legs": [[f"{cb}.{cbs}", f"{dd}.K"], [f"{dd}.A", f"{q}.D"], [f"{q}.S", f"{rs}.{rss}"],
                                        [f"{rs}.{rsg}", f"{cb}.{cbg}"]],
                               "max_area_mm2": LOOP_MAX_AREA_MM2}]
        ctx["separation"] = [{"victim_pins": [adc], "aggressor_pins": [f"{q}.D"], "min_gap_mm": SEP_MIN_GAP_MM,
                              "max_parallel_mm": SEP_MAX_PARALLEL_MM}]
    xs = crystal_roles(d)
    if xs:
        ctx["crystal"] = [dict(x, max_path_mm=XTAL_MAX_PATH_MM, no_vias=True) for x in xs]
    return ctx if len(ctx) > 1 else {}


# ------------------------------------------------------------------ board helpers
def _pad(b, pin: str, ref_parts: dict[str, str]):
    ref, name = pin.split(".", 1)
    part = PARTS.get(ref_parts.get(ref, ""))
    padnum = part.pins[name].pad if part is not None and name in part.pins else name
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        return None
    pads = sorted((p for p in fp.Pads() if p.GetNumber() == padnum), key=lambda p: (p.GetPosition().x, p.GetPosition().y))
    return pads[0] if pads else None


def _xy(p) -> tuple[float, float]:
    c = p.GetPosition()
    return c.x / 1e6, c.y / 1e6


def net_tracks(b, netcode: int) -> tuple[list[tuple], list[tuple]]:
    """([(layer, x1, y1, x2, y2, w)], [(x, y, r)]) of a net's tracks (arcs as two chords) and vias."""
    import pcbnew
    segs, vias = [], []
    for t in b.GetTracks():
        if t.GetNetCode() != netcode:
            continue
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            vias.append((q.x / 1e6, q.y / 1e6, t.GetWidth() / 2e6))
            continue
        if t.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        s, e = t.GetStart(), t.GetEnd()
        pts = [(s.x / 1e6, s.y / 1e6)]
        if t.GetClass() == "PCB_ARC":
            m = t.GetMid()
            pts.append((m.x / 1e6, m.y / 1e6))
        pts.append((e.x / 1e6, e.y / 1e6))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            segs.append((t.GetLayer(), x1, y1, x2, y2, t.GetWidth() / 1e6))
    return segs, vias


def _seg_seg_dist(a: tuple, b: tuple) -> float:
    """Distance between segments a=(x1,y1,x2,y2) and b."""
    from pcbenv.layout import _proj
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if _intersect(a, b):
        return 0.0
    return min(_proj(ax1, ay1, bx1, by1, bx2, by2)[1], _proj(ax2, ay2, bx1, by1, bx2, by2)[1],
               _proj(bx1, by1, ax1, ay1, ax2, ay2)[1], _proj(bx2, by2, ax1, ay1, ax2, ay2)[1])


def _intersect(a: tuple, b: tuple) -> bool:
    def orient(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    d1 = orient(bx1, by1, bx2, by2, ax1, ay1)
    d2 = orient(bx1, by1, bx2, by2, ax2, ay2)
    d3 = orient(ax1, ay1, ax2, ay2, bx1, by1)
    d4 = orient(ax1, ay1, ax2, ay2, bx2, by2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 * d2 < 0 and d3 * d4 < 0


def _pad_sdf(pad):
    """Signed distance function (mm) of a pad's copper outline, or None (unsupported shape:
    falls back to KiCad's hit test)."""
    from pcbenv.board import BuildError, pad_geom
    from pcbenv.router import Router
    try:
        g = pad_geom(pad)
    except BuildError:
        return None
    import numpy as np

    def f(x: float, y: float) -> float:
        return float(Router.pad_dist(g, np.array([x]), np.array([y]))[0])
    return f


def _seg_touches_pad(pad, sdf, lay: int, x1: float, y1: float, x2: float, y2: float, w: float) -> bool:
    import pcbnew
    if not pad.IsOnLayer(lay):
        return False
    L = math.hypot(x2 - x1, y2 - y1)
    n = max(1, int(math.ceil(L / 0.02)))
    for i in range(n + 1):
        x, y = x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n
        if sdf is not None:
            if sdf(x, y) <= w / 2 + EPS:
                return True
        elif pad.HitTest(pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6))), int(round(w / 2 * 1e6))):
            return True
    return False


def copper_islands(b, netcode: int, drop_pad=None) -> dict[object, int]:
    """Connected copper islands of one net, with `drop_pad` (a pad object) deleted. Items: track
    segments ("s", i), vias ("v", i), pads ("pad", REF, NUM, x, y); two items touch when their
    copper overlaps or abuts (tracks: capsules of their width; vias: discs; pads: exact outline).
    Returns {item: island id}."""
    import pcbnew
    segs, vias = net_tracks(b, netcode)
    pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == netcode]
    if drop_pad is not None:
        dk = (drop_pad.GetParent().GetReference(), drop_pad.GetNumber(), _xy(drop_pad))
        pads = [p for p in pads if (p.GetParent().GetReference(), p.GetNumber(), _xy(p)) != dk]

    def pk(p):
        return ("pad", p.GetParent().GetReference(), p.GetNumber()) + _xy(p)
    items = [("s", i) for i in range(len(segs))] + [("v", i) for i in range(len(vias))] + [pk(p) for p in pads]
    parent = {it: it for it in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, c):
        ra, rc = find(a), find(c)
        if ra != rc:
            parent[max(ra, rc)] = min(ra, rc)
    for i, (l1, *a, w1) in enumerate(segs):
        for j in range(i + 1, len(segs)):
            l2, *c, w2 = segs[j]
            if l1 == l2 and _seg_seg_dist(tuple(a), tuple(c)) <= (w1 + w2) / 2 + EPS:
                union(("s", i), ("s", j))
        for v, (vx, vy, vr) in enumerate(vias):
            from pcbenv.layout import _proj
            if _proj(vx, vy, *a)[1] <= w1 / 2 + vr + EPS:
                union(("s", i), ("v", v))
    for v, (vx, vy, vr) in enumerate(vias):
        for v2 in range(v + 1, len(vias)):
            wx, wy, wr = vias[v2]
            if math.hypot(vx - wx, vy - wy) <= vr + wr + EPS:
                union(("v", v), ("v", v2))
    for p in pads:
        sdf = _pad_sdf(p)
        for i, (lay, x1, y1, x2, y2, w) in enumerate(segs):
            if _seg_touches_pad(p, sdf, lay, x1, y1, x2, y2, w):
                union(("s", i), pk(p))
        for v, (vx, vy, vr) in enumerate(vias):
            if any(_seg_touches_pad(p, sdf, lay, vx, vy, vx, vy, 2 * vr) for lay in (pcbnew.F_Cu, pcbnew.B_Cu)):
                union(("v", v), pk(p))
    return {it: find(it) for it in items}


def _pad_key(p) -> tuple:
    return ("pad", p.GetParent().GetReference(), p.GetNumber()) + _xy(p)


# ------------------------------------------------------------------ metrics
def kelvin_ok(b, rule: dict, ref_parts: dict[str, str]) -> tuple[bool, str]:
    shunt = _pad(b, rule["shunt_pin"], ref_parts)
    sense = _pad(b, rule["sense_pin"], ref_parts)
    if shunt is None or sense is None:
        return False, f"{rule['shunt_pin']} or {rule['sense_pin']} not on the board"
    code = shunt.GetNetCode()
    if code <= 0 or sense.GetNetCode() != code:
        return False, f"{rule['sense_pin']} is not on the net of {rule['shunt_pin']}"
    from pcbenv.layout import copper_path_mm
    if copper_path_mm(b, sense, shunt) is None:
        return False, f"{rule['sense_pin']} is not connected by copper to {rule['shunt_pin']}"
    isl = copper_islands(b, code, drop_pad=shunt)
    mine = isl[_pad_key(sense)]
    for lp in rule["load_pins"]:
        p = _pad(b, lp, ref_parts)
        if p is None or p.GetNetCode() != code:
            return False, f"{lp} is not on the net of {rule['shunt_pin']}"
        if isl.get(_pad_key(p)) == mine:
            return False, (f"sense connection {rule['sense_pin']} shares copper with the load-current path from {lp}: "
                           f"it must leave from the shunt pad {rule['shunt_pin']} itself (Kelvin)")
    return True, ""


def loop_polygon(b, rule: dict, ref_parts: dict[str, str]) -> list[tuple[float, float]] | str:
    from pcbenv.layout import copper_path
    poly: list[tuple[float, float]] = []
    for a, c in rule["legs"]:
        pa, pc = _pad(b, a, ref_parts), _pad(b, c, ref_parts)
        if pa is None or pc is None:
            return f"{a} or {c} not on the board"
        r = copper_path(b, pa, pc) if pa.GetNetCode() > 0 else None
        if r is None:
            return f"{a} and {c} are not connected by copper"
        poly += r[1]
    return poly


def shoelace(poly: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def loop_area(b, rule: dict, ref_parts: dict[str, str]) -> float | str:
    poly = loop_polygon(b, rule, ref_parts)
    return poly if isinstance(poly, str) else shoelace(poly)


def crystal_metrics(b, rule: dict, ref_parts: dict[str, str]) -> list[tuple[str, float | None, int]]:
    """[(pair label, copper path mm or None, vias on that net)]."""
    from pcbenv.layout import copper_path_mm
    out = []
    for mp, yp in rule["pairs"]:
        pm, py = _pad(b, mp, ref_parts), _pad(b, yp, ref_parts)
        if pm is None or py is None or pm.GetNetCode() <= 0:
            out.append((f"{mp}->{yp}", None, 0))
            continue
        _, vias = net_tracks(b, pm.GetNetCode())
        out.append((f"{mp}->{yp}", copper_path_mm(b, pm, py), len(vias)))
    return out


def _near_interval(v: tuple, a: tuple, gap: float) -> tuple[float, float] | None:
    """Parameter interval [t0, t1] of victim segment v=(x1,y1,x2,y2) whose points lie within `gap`
    of segment a (distance to a segment is convex along a line, so the set is one interval)."""
    from pcbenv.layout import _proj
    x1, y1, x2, y2 = v

    def f(t: float) -> float:
        return _proj(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, *a)[1]
    lo, hi = 0.0, 1.0
    for _ in range(80):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if f(m1) <= f(m2):
            hi = m2
        else:
            lo = m1
    tm = (lo + hi) / 2
    if f(tm) > gap:
        return None

    def edge(inside: float, outside: float) -> float:
        if f(outside) <= gap:
            return outside
        for _ in range(60):
            mid = (inside + outside) / 2
            if f(mid) <= gap:
                inside = mid
            else:
                outside = mid
        return inside
    return edge(tm, 0.0), edge(tm, 1.0)


def parallel_length(b, victim_code: int, aggressor_code: int, gap: float) -> float:
    """Length (mm) of the victim net's track centrelines within `gap` mm of an aggressor-net track
    centreline on the same copper layer (union over aggressor segments)."""
    vs, _ = net_tracks(b, victim_code)
    ags, _ = net_tracks(b, aggressor_code)
    total = 0.0
    for lay, x1, y1, x2, y2, _w in vs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L == 0:
            continue
        ivs = []
        for la, a1, b1, a2, b2, _wa in ags:
            if la != lay:
                continue
            iv = _near_interval((x1, y1, x2, y2), (a1, b1, a2, b2), gap)
            if iv:
                ivs.append(iv)
        ivs.sort()
        cur = None
        for s, e in ivs:
            if cur is None or s > cur[1]:
                if cur:
                    total += (cur[1] - cur[0]) * L
                cur = [s, e]
            else:
                cur[1] = max(cur[1], e)
        if cur:
            total += (cur[1] - cur[0]) * L
    return total


def separation_length(b, rule: dict, ref_parts: dict[str, str]) -> float | str:
    vp = [_pad(b, p, ref_parts) for p in rule["victim_pins"]]
    ap = [_pad(b, p, ref_parts) for p in rule["aggressor_pins"]]
    if any(p is None or p.GetNetCode() <= 0 for p in vp + ap):
        return "a victim / aggressor pin is not on the board or not connected"
    total = 0.0
    for v in sorted({p.GetNetCode() for p in vp}):
        for a in sorted({p.GetNetCode() for p in ap}):
            if v == a:
                return "victim and aggressor pins share a net"
            total += parallel_length(b, v, a, rule["min_gap_mm"])
    return total


# ------------------------------------------------------------------ the check
def run_layout_rules(board, ctx: dict, ref_parts: dict[str, str]) -> list[LayoutViolation]:
    b = boardnet._as_board(board)
    out: list[LayoutViolation] = []
    for r in ctx.get("kelvin", []):
        ok, why = kelvin_ok(b, r, ref_parts)
        if not ok:
            out.append(LayoutViolation("kelvin_sense", why))
    for r in ctx.get("switch_loop", []):
        a = loop_area(b, r, ref_parts)
        if isinstance(a, str):
            out.append(LayoutViolation("switch_loop_area", a))
        elif a > r["max_area_mm2"] + EPS:
            out.append(LayoutViolation("switch_loop_area", f"{r['name']}: loop area {a:.1f} mm² > {r['max_area_mm2']} mm²"))
    for r in ctx.get("crystal", []):
        for label, d, nv in crystal_metrics(b, r, ref_parts):
            if d is None:
                out.append(LayoutViolation("crystal_trace", f"{label}: not connected by copper"))
                continue
            if d > r["max_path_mm"] + EPS:
                out.append(LayoutViolation("crystal_trace", f"{label}: copper path {d:.2f} mm > {r['max_path_mm']} mm"))
            if r.get("no_vias") and nv:
                out.append(LayoutViolation("crystal_via", f"{label}: {nv} via(s) on the oscillator net"))
    for r in ctx.get("separation", []):
        s = separation_length(b, r, ref_parts)
        if isinstance(s, str):
            out.append(LayoutViolation("analog_separation", s))
        elif s > r["max_parallel_mm"] + EPS:
            out.append(LayoutViolation("analog_separation",
                                       f"{'/'.join(r['victim_pins'])} net runs {s:.2f} mm within {r['min_gap_mm']} mm of "
                                       f"the switching node ({'/'.join(r['aggressor_pins'])}) > {r['max_parallel_mm']} mm"))
    return out


def metrics(board, ctx: dict, ref_parts: dict[str, str]) -> dict:
    """Raw measured values (margins / reports)."""
    b = boardnet._as_board(board)
    m: dict = {}
    for r in ctx.get("kelvin", []):
        m["kelvin_ok"] = kelvin_ok(b, r, ref_parts)[0]
    for r in ctx.get("switch_loop", []):
        m["loop_area_mm2"] = loop_area(b, r, ref_parts)
    for r in ctx.get("crystal", []):
        cm = crystal_metrics(b, r, ref_parts)
        m["xtal_path_mm"] = max((d if d is not None else math.inf) for _, d, _ in cm)
        m["xtal_vias"] = sum(nv for *_, nv in cm)
    for r in ctx.get("separation", []):
        m["parallel_mm"] = separation_length(b, r, ref_parts)
    return m


# ------------------------------------------------------------------ golden builder support
def attract_pairs(ctx: dict) -> list[tuple[str, str, float]]:
    """Pin pairs the golden placer pulls together (`board.place(attract=...)`)."""
    out = []
    for r in ctx.get("switch_loop", []):
        out += [(a, c, 3.0) for a, c in r["legs"]]
    for r in ctx.get("crystal", []):
        out += [(a, c, 3.0) for a, c in r["pairs"]]
    for r in ctx.get("kelvin", []):
        out.append((r["sense_pin"], r["shunt_pin"], 1.0))
    return out


def with_margin(ctx: dict, margin: float = GOLDEN_MARGIN) -> dict:
    """The context with every numeric limit scaled by `margin` (golden builder target)."""
    import copy
    c = copy.deepcopy(ctx)
    for r in c.get("switch_loop", []):
        r["max_area_mm2"] *= margin
    for r in c.get("crystal", []):
        r["max_path_mm"] *= margin
    for r in c.get("separation", []):
        r["max_parallel_mm"] *= margin
        r["min_gap_mm"] /= margin
    return c


def golden_violations(board, ctx: dict, ref_parts: dict[str, str]) -> list[str]:
    return [f"{v.code}: {v.detail}" for v in run_layout_rules(board, with_margin(ctx), ref_parts)]
