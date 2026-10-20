"""Layout checks against golden requirements (SPEC §7 check 9).

- Power nets: each golden power net (name -> required width) is identified on the candidate
  board by its *pin set* (`meta["power_net_pins"]`, never by name). The board net(s) whose
  pin set equals it -- modulo the pin order of symmetric two-terminal parts, see
  `pin_label` -- must have every track segment at least the required width
  (`BoardInfo.track_widths` is the min width over the net). A matched net with >= 2 pins and
  no tracks fails. No matching net fails (the topology/consistency gates also fail then).
- Decoupling (v2, RT31): the cap's pad on the IC pin's net must reach the IC pin's pad through
  at most `max_path_mm` (default `max_mm`) of copper: shortest path over that net's tracks, vias and pads, pad centre to
  pad centre (`copper_path_mm`). Every cap pad must also lie within `max_mm` of the IC pin's pad
  centre in a straight line (a lower bound of any copper path; this also covers the cap's other
  pad). A cap whose supply pad is not on the IC pin's net, or not connected to it by copper, fails.
"""
from __future__ import annotations

import heapq
import math
from collections import Counter
from dataclasses import dataclass

from pcbenv import boardnet
from pcbenv.parts import PARTS

EPS = 1e-6

# Non-polarised two-terminal parts: swapping pins 1 and 2 is electrically identical.
SYMMETRIC_PARTS = frozenset({"R", "C", "L", "XTAL", "XTAL_CL18"})


def pin_label(pin: str, ref_parts: dict[str, str]) -> str:
    """`REF.*` for a pin of a symmetric part, else the pin itself."""
    ref = pin.split(".", 1)[0]
    return f"{ref}.*" if ref_parts.get(ref) in SYMMETRIC_PARTS else pin


def net_signature(pins, ref_parts: dict[str, str]) -> Counter:
    return Counter(pin_label(p, ref_parts) for p in pins)


def _sig_key(pins, ref_parts: dict[str, str]) -> tuple:
    return tuple(sorted(net_signature(pins, ref_parts).items()))


def same_topology(a: frozenset, b: frozenset, ref_parts: dict[str, str]) -> bool:
    """Partition equality up to swapping the two pins of symmetric parts (R, C, L, crystals).

    Equal multisets of per-net label multisets imply a net bijection under which every
    symmetric part's two pins land on corresponding nets, i.e. a consistent per-part swap
    exists; the converse is obvious."""
    if a == b:
        return True
    ka = sorted(_sig_key(n, ref_parts) for n in a)
    kb = sorted(_sig_key(n, ref_parts) for n in b)
    return ka == kb


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    detail: str


def run_layout_checks(info: boardnet.BoardInfo, meta: dict, board=None,
                      ref_parts: dict[str, str] | None = None) -> list[LayoutIssue]:
    """`board` (path or BOARD) is needed for decoupling distances; `ref_parts` defaults to
    `meta["ref_parts"]`."""
    issues: list[LayoutIssue] = []
    ref_parts = ref_parts if ref_parts is not None else meta.get("ref_parts", {})
    golden_nets = meta.get("power_net_pins") or {}
    board_sigs: dict[str, Counter] = {n: net_signature(p, ref_parts) for n, p in info.net_pins.items()}
    for name, width in sorted(meta.get("power_nets", {}).items()):
        pins = golden_nets.get(name)
        if not pins:
            continue
        sig = net_signature(pins, ref_parts)
        matches = sorted(n for n, s in board_sigs.items() if s == sig)
        if not matches:
            issues.append(LayoutIssue("power_net_missing", f"no board net has the pins of golden net {name}"))
            continue
        for n in matches:
            w = info.track_widths.get(n)
            if w is None:
                if len(pins) >= 2:
                    issues.append(LayoutIssue("power_net_unrouted", f"power net {n} has no tracks"))
            elif w < width - EPS:
                issues.append(LayoutIssue("power_width",
                                          f"power net {n}: narrowest track {w:.3f} mm < required {width} mm"))
    decaps = meta.get("decoupling") or []
    if decaps:
        if board is None:
            issues.append(LayoutIssue("decoupling", "no board given for decoupling check"))
            return issues
        b = boardnet._as_board(board)
        for dc in decaps:
            ref, pin = dc["ic_pin"].split(".", 1)
            ip = boardnet.pad_position(b, ref, pin, parts=ref_parts)
            cap = dc["cap"]
            part = PARTS.get(ref_parts.get(cap, ""))
            if ip is None or part is None:
                issues.append(LayoutIssue("decoupling", f"{dc['ic_pin']} or {cap} not found on board"))
                continue
            for cpin in sorted(part.pins):
                cp = boardnet.pad_position(b, cap, cpin, parts=ref_parts)
                if cp is None:
                    issues.append(LayoutIssue("decoupling", f"{cap}.{cpin} not found on board"))
                    continue
                d = math.hypot(cp[0] - ip[0], cp[1] - ip[1])
                if d > dc["max_mm"] + EPS:
                    issues.append(LayoutIssue("decoupling",
                                              f"{cap}.{cpin} is {d:.2f} mm from {dc['ic_pin']} (max {dc['max_mm']} mm)"))
            path = decoupling_path_mm(b, cap, dc["ic_pin"], ref_parts)
            lim = max_path_mm(dc)
            if path is None:
                issues.append(LayoutIssue("decoupling", f"{cap} has no pad connected by copper to {dc['ic_pin']}"))
            elif path > lim + EPS:
                issues.append(LayoutIssue("decoupling", f"{cap} reaches {dc['ic_pin']} through {path:.2f} mm of copper "
                                                        f"(max {lim} mm)"))
    return issues


# ------------------------------------------------------------------ copper path length (RT31)
DEFAULT_MAX_PATH_MM = 8.0


def max_path_mm(dc: dict) -> float:
    """Allowed copper path cap -> IC pin: `max_path_mm` of the rule (v2 goldens set it), else
    `max_mm` (a rule without the field: the straight-line limit applies to the path too)."""
    return float(dc.get("max_path_mm", dc["max_mm"]))


def _ic_pad(b, ic_pin: str, ref_parts: dict[str, str]):
    ref, pin = ic_pin.split(".", 1)
    part = PARTS.get(ref_parts.get(ref, ""))
    padnum = part.pins[pin].pad if part is not None and pin in part.pins else pin
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        return None
    pads = sorted((p for p in fp.Pads() if p.GetNumber() == padnum), key=lambda p: (p.GetPosition().x, p.GetPosition().y))
    return pads[0] if pads else None


def decoupling_path_mm(board, cap: str, ic_pin: str, ref_parts: dict[str, str]) -> float | None:
    """Shortest copper path (mm) from any pad of `cap` on the IC pin's net to the IC pin's pad;
    None if no cap pad shares that net or the copper does not connect them."""
    b = boardnet._as_board(board)
    ip = _ic_pad(b, ic_pin, ref_parts)
    fp = b.FindFootprintByReference(cap)
    if ip is None or fp is None or ip.GetNetCode() <= 0:
        return None
    best = None
    for cp in sorted(fp.Pads(), key=lambda p: p.GetNumber()):
        if cp.GetNetCode() != ip.GetNetCode():
            continue
        d = copper_path_mm(b, cp, ip)
        if d is not None and (best is None or d < best):
            best = d
    return best


def _proj(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float]:
    """(t in [0,1], distance, along-length) of point p projected onto segment 1-2."""
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    qx, qy = x1 + t * dx, y1 + t * dy
    return t, math.hypot(px - qx, py - qy), t * math.sqrt(L2)


def copper_path_mm(board, pad_a, pad_b) -> float | None:
    """Shortest path (mm) through the copper of pad_a's net from pad_a's centre to pad_b's centre.

    Graph: every track segment (arcs as two chords) is split at the points where another item of
    the net touches it (segment ends, via centres, pad centres projected onto it); vias join both
    layers; a pad joins every point of its layers that lies inside it (KiCad pad hit test, inflated
    by half the track width). Edge weights are Euclidean lengths. None if not connected."""
    r = copper_path(board, pad_a, pad_b)
    return None if r is None else r[0]


def copper_path(board, pad_a, pad_b) -> tuple[float, list[tuple[float, float]]] | None:
    """`copper_path_mm` plus the path itself: the (x, y) mm points of the graph nodes visited,
    pad_a's centre first, pad_b's centre last (layout rules: switching-loop polygon)."""
    import pcbnew
    b = boardnet._as_board(board)
    net = pad_a.GetNetCode()
    if net <= 0 or pad_b.GetNetCode() != net:
        return None
    MM = 1e6
    xy: dict[object, tuple[float, float]] = {}
    segs = []   # (layer, x1, y1, x2, y2, w)
    vias = []   # (x, y, r)
    for t in b.GetTracks():
        if t.GetNetCode() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            vias.append((q.x / MM, q.y / MM, t.GetWidth() / MM / 2))
            continue
        lay = t.GetLayer()
        if lay not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        s, e = t.GetStart(), t.GetEnd()
        pts = [(s.x / MM, s.y / MM)]
        if t.GetClass() == "PCB_ARC":
            m = t.GetMid()
            pts.append((m.x / MM, m.y / MM))
        pts.append((e.x / MM, e.y / MM))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            segs.append((lay, x1, y1, x2, y2, t.GetWidth() / MM))
    pads = [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == net]
    layers = (pcbnew.F_Cu, pcbnew.B_Cu)

    def in_pad(p, x: float, y: float, lay: int, infl: float) -> bool:
        return p.IsOnLayer(lay) and p.HitTest(pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM))), int(infl * MM))

    adj: dict[object, list[tuple[float, object]]] = {}

    def edge(u, v, w: float) -> None:
        adj.setdefault(u, []).append((w, v))
        adj.setdefault(v, []).append((w, u))

    def pkey(p) -> tuple:
        c = p.GetPosition()
        key = ("pad", p.GetParent().GetReference(), p.GetNumber(), c.x, c.y)
        xy.setdefault(key, (c.x / MM, c.y / MM))
        return key
    for v, (vx, vy, vr) in enumerate(vias):
        xy[("via", v)] = (vx, vy)
    for k, (lay, x1, y1, x2, y2, w) in enumerate(segs):
        xy[("s", k, 0)] = (x1, y1)
        xy[("s", k, 1)] = (x2, y2)
        marks = [(0.0, ("s", k, 0)), (math.hypot(x2 - x1, y2 - y1), ("s", k, 1))]
        for j, (l2, a1, b1, a2, b2, w2) in enumerate(segs):
            if j == k or l2 != lay:
                continue
            for end, (px, py) in enumerate(((a1, b1), (a2, b2))):
                t, d, along = _proj(px, py, x1, y1, x2, y2)
                if d <= (w + w2) / 2 + 1e-6:
                    node = ("p", k, round(along, 6))
                    xy.setdefault(node, _at(x1, y1, x2, y2, along))
                    marks.append((along, node))
                    edge(node, ("s", j, end), d)
        for v, (vx, vy, vr) in enumerate(vias):
            t, d, along = _proj(vx, vy, x1, y1, x2, y2)
            if d <= w / 2 + vr + 1e-6:
                node = ("p", k, round(along, 6))
                xy.setdefault(node, _at(x1, y1, x2, y2, along))
                marks.append((along, node))
                edge(node, ("via", v), d)
        for p in pads:
            c = p.GetPosition()
            cx, cy = c.x / MM, c.y / MM
            for end, (px, py) in enumerate(((x1, y1), (x2, y2))):
                if in_pad(p, px, py, lay, w / 2):
                    edge(("s", k, end), pkey(p), math.hypot(px - cx, py - cy))
            t, d, along = _proj(cx, cy, x1, y1, x2, y2)
            qx, qy = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
            if 0.0 < t < 1.0 and in_pad(p, qx, qy, lay, w / 2):
                node = ("p", k, round(along, 6))
                xy.setdefault(node, _at(x1, y1, x2, y2, along))
                marks.append((along, node))
                edge(node, pkey(p), d)
        marks.sort(key=lambda m: m[0])
        for (a, u), (c2, v) in zip(marks, marks[1:]):
            edge(u, v, c2 - a)
    for v, (vx, vy, vr) in enumerate(vias):
        for p in pads:
            if any(in_pad(p, vx, vy, lay, vr) for lay in layers):
                c = p.GetPosition()
                edge(("via", v), pkey(p), math.hypot(vx - c.x / MM, vy - c.y / MM))
        for v2, (wx, wy, wr) in enumerate(vias):
            if v2 > v and math.hypot(vx - wx, vy - wy) <= vr + wr:
                edge(("via", v), ("via", v2), math.hypot(vx - wx, vy - wy))
    for i, p in enumerate(pads):   # overlapping pads of the net (e.g. a pad stack)
        c = p.GetPosition()
        for q in pads[i + 1:]:
            e = q.GetPosition()
            if any(in_pad(p, e.x / MM, e.y / MM, lay, 0.0) or in_pad(q, c.x / MM, c.y / MM, lay, 0.0) for lay in layers):
                edge(pkey(p), pkey(q), math.hypot((c.x - e.x) / MM, (c.y - e.y) / MM))
    src, dst = pkey(pad_a), pkey(pad_b)
    if src == dst:
        return 0.0, [xy[src]]
    dist = {src: 0.0}
    prev: dict[object, object] = {}
    heap = [(0.0, 0, src)]
    n = 1
    while heap:
        d, _, u = heapq.heappop(heap)
        if u == dst:
            pts, cur = [], u
            while True:
                pts.append(xy[cur])
                if cur == src:
                    break
                cur = prev[cur]
            return d, pts[::-1]
        if d > dist.get(u, math.inf):
            continue
        for w, v in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, math.inf) - 1e-12:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, n, v))
                n += 1
    return None


def _at(x1: float, y1: float, x2: float, y2: float, along: float) -> tuple[float, float]:
    L = math.hypot(x2 - x1, y2 - y1)
    if L == 0:
        return (x1, y1)
    return (x1 + (x2 - x1) * along / L, y1 + (y2 - y1) * along / L)
