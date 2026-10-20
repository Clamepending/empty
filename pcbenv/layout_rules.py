"""Layout design rules (hard tier, `hard_layout` sub-tier): board-geometry rules graded by the
verifier, stated in TASK.md "Layout rules" and `spec.json:layout_rules`, NOT run by pcbtool.

Every rule names its parts by public pins (`REF.PIN`) and nets by the pins on them, never by net
name. Geometry is read from the candidate board.kicad_pcb in mm (KiCad coordinates). The rule
context (`meta["layout_rules"]` == `spec.json["layout_rules"]`) is built from the golden by
`layout_rules_context`; `run_layout_rules(board, ctx, ref_parts)` returns the violations.

Rules (precise definitions are in `rules_md`, the public text):

- kelvin       the ADC sense connection must leave from the shunt pad itself (v2.1, QA F1): delete
               the shunt pad AND all copper inside its outline (tracks cut at the pad edge; contacts
               count only outside the pad); the copper island holding the sense pin's pad must still
               touch the shunt pad and must not contain the load-current pin's pad. Sense and load
               tracks meeting inside the pad (e.g. both at its centre) is the textbook Kelvin layout.
- switch_loop  hot loop of the low-side switch: the closed path made of the shortest copper paths
               between consecutive loop pads (pad centre to pad centre, `layout.copper_path`) and
               straight lines through each part body; |shoelace area| <= max_area_mm2.
- crystal      copper path MCU oscillator pin -> crystal pad <= max_path_mm; no via on either net.
- separation   total length of the victim net's track centrelines that lie within min_gap_mm
               (centreline to centreline, in projection) of an aggressor-net track on EITHER copper
               layer <= max_parallel_mm (v2.1, QA F3; opposite-layer crossings at >= 45° excluded).
- decoupling   unchanged: graded by `layout.run_layout_checks` (check `layout`), restated here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from pcbenv import boardnet
from pcbenv.parts import PARTS

VERSION = 1   # context format (unchanged in v2.1; the rule definitions changed, see rules_md)
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


def motor_roles(design: dict, decaps: set[str] = frozenset()) -> dict | None:
    """Refs of the low-side motor stage: switch Q (NMOS), flyback D (cathode on the motor supply,
    anode on the drain), bulk cap CB (supply to GND, the largest such cap that is not an IC
    decoupling cap in `decaps`), shunt RS (source to GND), sense resistor RF (source node to the
    ADC), the MCU ADC pin. None if the design has no such stage."""
    from pcbenv.parts import parse_value
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
        bulk = []
        for c in _comps(design, "C"):
            n1, n2 = _net_of(design, f"{c}.1"), _net_of(design, f"{c}.2")
            if {n1, n2} == {sup, gnd} and c not in decaps:
                bulk.append((-parse_value(design["components"][c]["value"]), c,
                             "1" if n1 == sup else "2", "2" if n1 == sup else "1"))
        if bulk:
            cb = min(bulk)[1:]
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
    m = motor_roles(d, {dc["cap"] for dc in golden.decoupling})
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


def net_tracks(b, netcode: int, objs: list | None = None) -> tuple[list[tuple], list[tuple]]:
    """([(layer, x1, y1, x2, y2, w)], [(x, y, r)]) of a net's tracks (arcs as two chords) and vias.
    `objs` (a list): filled with the KiCad item of every returned segment, then of every via."""
    import pcbnew
    segs, vias = [], []
    vobjs: list = []
    for t in b.GetTracks():
        if t.GetNetCode() != netcode:
            continue
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            vias.append((q.x / 1e6, q.y / 1e6, t.GetWidth() / 2e6))
            vobjs.append(t)
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
            if objs is not None:
                objs.append(t)
    if objs is not None:
        objs.extend(vobjs)
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


def island_items(b, netcode: int, pad, drop_pad=None) -> list:
    """KiCad tracks / vias in the copper island of `pad` (with `drop_pad` deleted)."""
    objs: list = []
    segs, vias = net_tracks(b, netcode, objs)
    isl = copper_islands(b, netcode, drop_pad=drop_pad)
    mine = isl[_pad_key(pad)]
    out = []
    for k, v in isl.items():
        if v != mine:
            continue
        if k[0] == "s":
            out.append(objs[k[1]])
        elif k[0] == "v":
            out.append(objs[len(segs) + k[1]])
    uniq, seen = [], set()
    for t in out:
        if id(t) not in seen:
            seen.add(id(t))
            uniq.append(t)
    return uniq


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
def _inside_fn(pad, sdf):
    """inside(x, y): the point lies inside the pad's copper outline (layer not considered)."""
    import pcbnew
    if sdf is not None:
        return lambda x, y: sdf(x, y) <= EPS
    return lambda x, y: pad.HitTest(pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6))), 0)


def _clip_outside(inside, x1: float, y1: float, x2: float, y2: float) -> list[tuple[float, float, float, float]]:
    """The pieces of centreline segment (x1,y1)-(x2,y2) that lie outside the pad (`inside`)."""
    L = math.hypot(x2 - x1, y2 - y1)
    n = max(1, int(math.ceil(L / 0.02)))
    ts = [i / n for i in range(n + 1)]

    def pt(t: float) -> tuple[float, float]:
        return x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
    flags = [inside(*pt(t)) for t in ts]
    if not any(flags):
        return [(x1, y1, x2, y2)]

    def edge(t_in: float, t_out: float) -> float:
        for _ in range(30):
            m = (t_in + t_out) / 2
            if inside(*pt(m)):
                t_in = m
            else:
                t_out = m
        return t_out
    out = []
    i = 0
    while i <= n:
        if flags[i]:
            i += 1
            continue
        j = i
        while j + 1 <= n and not flags[j + 1]:
            j += 1
        a = ts[i] if i == 0 else edge(ts[i - 1], ts[i])
        b = ts[j] if j == n else edge(ts[j + 1], ts[j])
        if (b - a) * L > 1e-6:
            out.append((*pt(a), *pt(b)))
        i = j + 1
    return out


def _contact_outside(inside, a: tuple, wa: float, b: tuple, wb: float) -> bool:
    """Do the copper capsules of centreline segments a and b (widths wa, wb; a zero-length segment
    is a disc) overlap at some point OUTSIDE the pad (`inside`)? Witness points are sampled every
    0.02 mm along both centrelines."""
    from pcbenv.layout import _proj
    for (p, wp), (q, wq) in (((a, wa), (b, wb)), ((b, wb), (a, wa))):
        x1, y1, x2, y2 = p
        L = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(math.ceil(L / 0.02)))
        for i in range(n + 1):
            x, y = x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n
            t, d, _ = _proj(x, y, *q)
            if d > (wp + wq) / 2 + EPS:
                continue
            qx, qy = q[0] + (q[2] - q[0]) * t, q[1] + (q[3] - q[1]) * t
            f = wp / (wp + wq) if wp + wq > 0 else 0.5
            wx, wy = x + (qx - x) * f, y + (qy - y) * f
            if not inside(wx, wy):
                return True
    return False


def kelvin_islands(b, netcode: int, shunt) -> tuple[dict, list]:
    """Copper islands of a net with the shunt pad AND every piece of copper inside its outline
    removed (on the layers the pad is on): track centrelines are clipped to their parts outside the
    pad, and two items count as touching only if their copper overlaps outside the pad (or on a
    layer the pad is not on). Returns ({item: island id}, pieces) with items ("s", i) for
    pieces[i] = (layer, x1, y1, x2, y2, w), ("v", i) for vias, and pad keys (`_pad_key`)."""
    import pcbnew
    from pcbenv.layout import _proj
    segs, vias = net_tracks(b, netcode)
    sdf = _pad_sdf(shunt)
    inside = _inside_fn(shunt, sdf)
    pieces = []
    for lay, x1, y1, x2, y2, w in segs:
        if shunt.IsOnLayer(lay):
            pieces += [(lay, *c, w) for c in _clip_outside(inside, x1, y1, x2, y2)]
        else:
            pieces.append((lay, x1, y1, x2, y2, w))
    sk = _pad_key(shunt)
    pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == netcode and _pad_key(p) != sk]
    items = [("s", i) for i in range(len(pieces))] + [("v", i) for i in range(len(vias))] + [_pad_key(p) for p in pads]
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

    def touch(lay: int, a: tuple, wa: float, c: tuple, wc: float) -> bool:
        if _seg_seg_dist(a, c) > (wa + wc) / 2 + EPS:
            return False
        return not shunt.IsOnLayer(lay) or _contact_outside(inside, a, wa, c, wc)
    for i, (l1, *a, w1) in enumerate(pieces):
        for j in range(i + 1, len(pieces)):
            l2, *c, w2 = pieces[j]
            if l1 == l2 and touch(l1, tuple(a), w1, tuple(c), w2):
                union(("s", i), ("s", j))
        for v, (vx, vy, vr) in enumerate(vias):
            if _proj(vx, vy, *a)[1] <= w1 / 2 + vr + EPS and touch(l1, tuple(a), w1, (vx, vy, vx, vy), 2 * vr):
                union(("s", i), ("v", v))
    both = shunt.IsOnLayer(pcbnew.F_Cu) and shunt.IsOnLayer(pcbnew.B_Cu)
    for v, (vx, vy, vr) in enumerate(vias):
        for v2 in range(v + 1, len(vias)):
            wx, wy, wr = vias[v2]
            if math.hypot(vx - wx, vy - wy) <= vr + wr + EPS and (
                    not both or _contact_outside(inside, (vx, vy, vx, vy), 2 * vr, (wx, wy, wx, wy), 2 * wr)):
                union(("v", v), ("v", v2))
    for p in pads:
        psdf = _pad_sdf(p)
        for i, (lay, x1, y1, x2, y2, w) in enumerate(pieces):
            if _seg_touches_pad(p, psdf, lay, x1, y1, x2, y2, w):
                union(("s", i), _pad_key(p))
        for v, (vx, vy, vr) in enumerate(vias):
            if any(_seg_touches_pad(p, psdf, lay, vx, vy, vx, vy, 2 * vr) for lay in (pcbnew.F_Cu, pcbnew.B_Cu)):
                union(("v", v), _pad_key(p))
    return {it: find(it) for it in items}, pieces


def kelvin_ok(b, rule: dict, ref_parts: dict[str, str]) -> tuple[bool, str]:
    """Kelvin rule (v2.1, QA F1): the sense pin's copper must attach to the shunt pad, and must not
    share copper with the load-current path OUTSIDE the shunt pad. Copper inside the shunt pad's
    outline (e.g. the sense and load tracks both ending at the pad centre) is the pad itself and is
    allowed. Check: remove the shunt pad and every piece of copper inside its outline; the island
    holding the sense pin's pad must still touch the shunt pad and must not contain a load pin."""
    import pcbnew
    b = boardnet._as_board(b)
    shunt = _pad(b, rule["shunt_pin"], ref_parts)
    sense = _pad(b, rule["sense_pin"], ref_parts)
    if shunt is None or sense is None:
        return False, f"{rule['shunt_pin']} or {rule['sense_pin']} not on the board"
    code = shunt.GetNetCode()
    if code <= 0 or sense.GetNetCode() != code:
        return False, f"{rule['sense_pin']} is not on the net of {rule['shunt_pin']}"
    isl, pieces = kelvin_islands(b, code, shunt)
    mine = isl[_pad_key(sense)]
    for lp in rule["load_pins"]:
        p = _pad(b, lp, ref_parts)
        if p is None or p.GetNetCode() != code:
            return False, f"{lp} is not on the net of {rule['shunt_pin']}"
        if isl.get(_pad_key(p)) == mine:
            return False, (f"sense connection {rule['sense_pin']} shares copper with the load-current path from {lp} "
                           f"outside the shunt pad: it must leave from the shunt pad {rule['shunt_pin']} itself, on "
                           f"its own trace (Kelvin)")
    sdf = _pad_sdf(shunt)
    _, vias = net_tracks(b, code)
    attached = False
    for k, v in isl.items():
        if v != mine:
            continue
        if k[0] == "s":
            lay, x1, y1, x2, y2, w = pieces[k[1]]
            attached = _seg_touches_pad(shunt, sdf, lay, x1, y1, x2, y2, w)
        elif k[0] == "v":
            vx, vy, vr = vias[k[1]]
            attached = any(_seg_touches_pad(shunt, sdf, lay, vx, vy, vx, vy, 2 * vr) for lay in (pcbnew.F_Cu, pcbnew.B_Cu))
        if attached:
            break
    if not attached:
        return False, (f"sense connection {rule['sense_pin']} is not connected by its own copper to the shunt pad "
                       f"{rule['shunt_pin']} (Kelvin)")
    return True, ""


def loop_polygon(b, rule: dict, ref_parts: dict[str, str]) -> list[tuple[float, float]] | str:
    b = boardnet._as_board(b)
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


RASTER_MM = 0.02


def _clean(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for p in poly:
        if not out or math.dist(p, out[-1]) > 1e-9:
            out.append(p)
    while len(out) > 1 and math.dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


def is_simple(poly: list[tuple[float, float]]) -> bool:
    """No two non-adjacent edges of the closed polygon intersect or touch."""
    pts = _clean(poly)
    n = len(pts)
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            (a1, a2), (b1, b2) = edges[i], edges[j]
            if _seg_seg_dist((*a1, *a2), (*b1, *b2)) <= 1e-9:
                return False
    return True


def winding_area(poly: list[tuple[float, float]], step: float = RASTER_MM) -> float:
    """∫ |winding number| dA of the closed polygon, on a `step` mm grid of cell centres."""
    import numpy as np
    pts = np.array(_clean(poly), dtype=float)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    xs = np.arange(math.floor(x0 / step) * step + step / 2, x1 + step, step)
    ys = np.arange(math.floor(y0 / step) * step + step / 2, y1 + step, step)
    X, Y = np.meshgrid(xs, ys)
    w = np.zeros(X.shape, dtype=np.int32)
    for (ax, ay), (bx, by) in zip(pts, np.roll(pts, -1, axis=0)):
        up = (ay <= Y) & (by > Y)
        down = (ay > Y) & (by <= Y)
        cross = (bx - ax) * (Y - ay) - (X - ax) * (by - ay)
        w += (up & (cross > 0)).astype(np.int32) - (down & (cross < 0)).astype(np.int32)
    return float(np.abs(w).sum() * step * step)


def polygon_area(poly: list[tuple[float, float]]) -> float:
    """Loop area: the shoelace area of a simple polygon; for a self-intersecting one, every region
    counted |winding number| times (lobes never cancel)."""
    pts = _clean(poly)
    if len(pts) < 3:
        return 0.0
    return shoelace(pts) if is_simple(pts) else winding_area(pts)


def loop_area(b, rule: dict, ref_parts: dict[str, str]) -> float | str:
    poly = loop_polygon(b, rule, ref_parts)
    return poly if isinstance(poly, str) else polygon_area(poly)


def crystal_metrics(b, rule: dict, ref_parts: dict[str, str]) -> list[tuple[str, float | None, int]]:
    """[(pair label, copper path mm or None, vias on that net)]."""
    b = boardnet._as_board(b)
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


CROSS_ANGLE_DEG = 45.0


def _angle_deg(a: tuple, c: tuple) -> float:
    """Acute angle (degrees, 0..90) between the directions of segments a and c."""
    ux, uy = a[2] - a[0], a[3] - a[1]
    vx, vy = c[2] - c[0], c[3] - c[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if nu == 0 or nv == 0:
        return 0.0
    cs = min(1.0, abs(ux * vx + uy * vy) / (nu * nv))
    return math.degrees(math.acos(cs))


def parallel_length(b, victim_code: int, aggressor_code: int, gap: float, same_layer_only: bool = False) -> float:
    """Length (mm) of the victim net's track centrelines within `gap` mm (centreline to centreline,
    in projection onto the board plane) of an aggressor-net track centreline (union over aggressor
    segments). v2.1 (QA F3): tracks on BOTH copper layers count -- a victim running over / under the
    switching node on the other layer couples at least as strongly -- except that an opposite-layer
    pair crossing at >= CROSS_ANGLE_DEG degrees is a crossing, not a parallel run, and does not
    count. `same_layer_only`: the v2.0 definition."""
    b = boardnet._as_board(b)
    vs, _ = net_tracks(b, victim_code)
    ags, _ = net_tracks(b, aggressor_code)
    total = 0.0
    for lay, x1, y1, x2, y2, _w in vs:
        L = math.hypot(x2 - x1, y2 - y1)
        if L == 0:
            continue
        ivs = []
        for la, a1, b1, a2, b2, _wa in ags:
            if la != lay and (same_layer_only or _angle_deg((x1, y1, x2, y2), (a1, b1, a2, b2)) >= CROSS_ANGLE_DEG):
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


def separation_length(b, rule: dict, ref_parts: dict[str, str], same_layer_only: bool = False) -> float | str:
    b = boardnet._as_board(b)
    vp = [_pad(b, p, ref_parts) for p in rule["victim_pins"]]
    ap = [_pad(b, p, ref_parts) for p in rule["aggressor_pins"]]
    if any(p is None or p.GetNetCode() <= 0 for p in vp + ap):
        return "a victim / aggressor pin is not on the board or not connected"
    total = 0.0
    for v in sorted({p.GetNetCode() for p in vp}):
        for a in sorted({p.GetNetCode() for p in ap}):
            if v == a:
                return "victim and aggressor pins share a net"
            total += parallel_length(b, v, a, rule["min_gap_mm"], same_layer_only)
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
        if isinstance(a, str):   # QA F6: e.g. a pinout fault disconnects a loop leg
            out.append(LayoutViolation("switch_loop_area", f"{r['name']}: loop area cannot be measured: {a} (the "
                                                           f"loop must be a closed copper path; once it is, its "
                                                           f"area must be ≤ {r['max_area_mm2']:g} mm²)"))
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


# ------------------------------------------------------------------ public text (TASK.md)
def rules_md(ctx: dict, decoupling: bool = True) -> str:
    """The "Layout rules" TASK.md section: every rule with its pins, limit and the exact geometric
    definition, so an engineer can check it by hand from board.kicad_pcb coordinates."""
    out = ["## Layout rules (board geometry)", "",
           "The board must also follow these layout rules. **`pcbtool` does not check any of them** (not `check`, "
           "not `drc`, not `show`) -- they are graded from the geometry in `board.kicad_pcb`; `spec.json` lists the "
           "same rules under `layout_rules` with their pins and limits. All lengths in mm, KiCad board coordinates "
           "(y grows downwards). Definitions used below:", "",
           "- *Pad centre*: the pad's absolute position (footprint `(at x y rot)` plus the pad's `(at ...)` offset "
           "rotated by the footprint orientation; KiCad Python: `pad.GetPosition()`).",
           "- *Copper path* from pad A to pad B: the shortest route along the net's copper -- track centrelines "
           "(each `segment` from start to end), vias (joining F.Cu and B.Cu at their centre) and pads (a pad joins "
           "every track point that lies inside it) -- measured from A's centre to B's centre. Tracks connect where "
           "their copper touches (same layer). As a polyline it runs through A's centre, the track end / junction "
           "points it follows, and B's centre.",
           "- *Touch*: two copper items of a net touch when their copper overlaps or abuts (a track is its "
           "centreline swept by half its width, a via a disc of its diameter, a pad its outline).", ""]
    for r in ctx.get("kelvin", []):
        out += [f"**Kelvin sense connection** (current shunt {r['shunt']}): the ADC sense connection {r['sense_pin']} must "
                f"leave from the shunt pad {r['shunt_pin']} itself, on its own trace -- not from a point on the "
                f"load-current path. Copper inside the outline of pad {r['shunt_pin']} is the pad itself: the sense "
                f"trace and the load-current track may both run into the pad (e.g. both to its centre) and meet "
                f"there. Check: delete pad {r['shunt_pin']} together with every piece of copper inside its outline "
                f"(on the pad's layer: track centrelines are cut at the pad edge, and two items count as touching "
                f"only where their copper overlaps outside the pad); the copper island (items of the net that touch, "
                f"transitively) holding pad {r['sense_pin']} must still touch pad {r['shunt_pin']} and must not "
                f"contain pad {', '.join(r['load_pins'])} (the load current's pin). So outside the shunt pad the sense "
                f"trace must not touch, tee into or share any track or via with the load-current copper. The "
                f"power-net width rule still applies to the sense trace (it is on the same net).", ""]
    for r in ctx.get("switch_loop", []):
        legs = r["legs"]
        seq = ", ".join(f"{a} -> {c}" for a, c in legs)
        out += [f"**Switching loop area** ({r['name']}): the loop through the bulk capacitor, the flyback diode, the "
                f"switch and the shunt is the polygon made of the copper paths {seq} (each as a polyline, see above), "
                f"joined by straight lines across each part from one leg's end pad to the next leg's start pad "
                f"({', '.join(f'{legs[i][1]} -> {legs[(i + 1) % len(legs)][0]}' for i in range(len(legs)))}). Its "
                f"area A = ½·|Σ (x_i·y_(i+1) − x_(i+1)·y_i)| over the polygon's vertices (shoelace formula) must be "
                f"≤ {r['max_area_mm2']:g} mm². (If the polygon crosses itself, A is the area it encloses with every "
                f"region counted |winding number| times, so lobes never cancel; the grader evaluates that case on a "
                f"{RASTER_MM:g} mm grid.) Keep these parts tight together and route the legs directly.", ""]
    for r in ctx.get("crystal", []):
        pairs = "; ".join(f"{a} -> {c}" for a, c in r["pairs"])
        out += [f"**Crystal traces** (crystal {r['xtal']} on {r['mcu']}): the copper path of each oscillator connection "
                f"({pairs}) must be ≤ {r['max_path_mm']:g} mm, and the two oscillator nets (the nets of "
                f"{' and '.join(a for a, _ in r['pairs'])}) must have no via at all.", ""]
    for r in ctx.get("separation", []):
        out += [f"**Analog / switching separation**: the analog net (the net of {', '.join(r['victim_pins'])}, the ADC "
                f"input) must not run alongside the switching node (the net of {', '.join(r['aggressor_pins'])}). The "
                f"total length of analog-net track centreline that lies within {r['min_gap_mm']:g} mm (centreline to "
                f"centreline, measured in projection onto the board plane) of any switching-node track centreline must "
                f"be ≤ {r['max_parallel_mm']:g} mm. Tracks on BOTH copper layers count: an analog track running over "
                f"or under the switching node on the other layer is a parallel run too. Only an opposite-layer "
                f"crossing at an angle of {CROSS_ANGLE_DEG:g}° or more does not count.", ""]
    if decoupling:
        out += ["**Decoupling** (as stated under Design rules: copper path cap pad -> IC pin, plus straight-line "
                "distance) is part of the same layout review.", ""]
    out += ["Grading: the `layout_rules` check fails if any rule above is violated; the decoupling rule is graded "
            "by the `layout` check. `pcbtool route` knows nothing about these rules (it joins a net's pads as a "
            "shortest tree, which can itself violate them); review and, if needed, hand-edit the tracks.", ""]
    return "\n".join(out)


def evidence_groups(rec: dict, lctx: dict) -> list[list[str]]:
    """Public text a layout-latent fault needs (fairness gate; same format as latent.evidence_groups)."""
    t, d = rec["type"], rec.get("data", {})
    if t == "kelvin_sense_tap":
        r = lctx["kelvin"][0]
        return [["**Kelvin sense connection**"], [f"line:{r['sense_pin']}&{r['shunt_pin']}"]]
    if t == "switch_loop_spread":
        r = lctx["switch_loop"][0]
        return [["**Switching loop area**"], [f"line:{r['legs'][0][0]}&{r['legs'][0][1]}"], ["shoelace"]]
    if t in ("crystal_far", "crystal_via"):
        r = lctx["crystal"][0]
        return [["**Crystal traces**"], [f"line:{r['pairs'][0][0]}&{r['pairs'][0][1]}"]]
    if t == "analog_near_switch":
        r = lctx["separation"][0]
        return [["**Analog / switching separation**"], [f"line:{r['victim_pins'][0]}&{r['aggressor_pins'][0]}"]]
    if t == "decap_long_path":
        return [[f"- {d['cap']} within"], ["copper path"]]
    return []


# ------------------------------------------------------------------ golden margin sweep (CLI)
def _sweep_job(args: tuple) -> dict:
    fam, seed = args
    import os
    import tempfile

    from pcbenv import rules
    from pcbenv.board import build_board
    from pcbenv.families import FAMILIES
    g, _ = rules.harden(FAMILIES[fam].generate(seed))
    ctx = layout_rules_context(g)
    rp = {r: c["part"] for r, c in g.design["components"].items()}
    with tempfile.TemporaryDirectory() as td:
        bp = os.path.join(td, "b.kicad_pcb")
        st = build_board(g, bp, 0, layout_rules=ctx)
        m = metrics(bp, ctx, rp)
        v = [f"{x.code}: {x.detail}" for x in run_layout_rules(bp, ctx, rp)]
    return {"family": fam, "seed": seed, "attempts": st["attempts"], "metrics": m, "violations": v}


def sweep(seeds: int, families: tuple[str, ...] = ("sys_motor_ctrl", "sys_clocked_mcu"), workers: int = 4) -> str:
    """Golden boards (layout-rule builder) of `families` x seeds 0..seeds-1: every rule's measured
    value vs its limit. Returns a plain-text report."""
    from multiprocessing import get_context
    jobs = [(f, s) for f in families for s in range(seeds)]
    with get_context("spawn").Pool(workers) as pool:
        res = pool.map(_sweep_job, jobs)
    lim = {"loop_area_mm2": LOOP_MAX_AREA_MM2, "xtal_path_mm": XTAL_MAX_PATH_MM, "parallel_mm": SEP_MAX_PARALLEL_MM}
    lines = [f"layout-rule golden sweep: {', '.join(families)} x seeds 0..{seeds - 1} (board seed 0)",
             f"limits: loop area <= {LOOP_MAX_AREA_MM2:g} mm2, crystal path <= {XTAL_MAX_PATH_MM:g} mm (no vias), "
             f"analog parallel run within {SEP_MIN_GAP_MM:g} mm <= {SEP_MAX_PARALLEL_MM:g} mm, Kelvin sense; golden "
             f"builder target = {GOLDEN_MARGIN:g} x limit", ""]
    bad = [r for r in res if r["violations"]]
    for key, L in lim.items():
        vals = [r["metrics"][key] for r in res if key in r["metrics"]]
        if vals:
            vals.sort()
            lines.append(f"{key}: n={len(vals)} min={vals[0]:.2f} median={vals[len(vals) // 2]:.2f} max={vals[-1]:.2f} "
                         f"limit={L:g} -> worst margin {100 * (1 - vals[-1] / L):.1f} % below the limit")
    kel = [r["metrics"]["kelvin_ok"] for r in res if "kelvin_ok" in r["metrics"]]
    vias = [r["metrics"]["xtal_vias"] for r in res if "xtal_vias" in r["metrics"]]
    lines += [f"kelvin_ok: {sum(kel)}/{len(kel)}", f"crystal-net vias: total {sum(vias)} over {len(vias)} boards",
              f"build attempts: mean {sum(r['attempts'] for r in res) / len(res):.2f}, max {max(r['attempts'] for r in res)}",
              f"boards violating a rule: {len(bad)}/{len(res)}", ""]
    lines += [f"{r['family']} {r['seed']}: " + json.dumps(r["metrics"], sort_keys=True, default=lambda x: round(x, 3))
              + (f" VIOLATIONS {r['violations']}" if r["violations"] else "") for r in res]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.layout_rules")
    ap.add_argument("--sweep", type=int, default=50, help="seeds per family")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    text = sweep(a.sweep, workers=a.workers)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text.split("\n\n")[0] + "\n" + text.split("\n\n")[1])
    return 0 if "boards violating a rule: 0/" in text else 1


if __name__ == "__main__":
    raise SystemExit(main())
