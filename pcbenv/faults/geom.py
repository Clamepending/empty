"""Board-geometry editing helpers for the layout-latent faults (hard_layout tier).

All edits go through the grid router (`pcbenv/router.py`) so new copper keeps the canonical
clearances; callers re-run DRC on the result. Deterministic: no randomness here (callers pass the
choices), the router is deterministic, and `common.save_board` canonicalises the file.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pcbnew

from pcbenv import drc
from pcbenv.faults.common import NotApplicable
from pcbenv.router import PadGeom, Router, RouteError, Rules

MM = 1e6
CLEAR = drc.RULES["clearance"]


def board_router(board) -> tuple[Router, dict[str, int]]:
    """A Router loaded with every pad, track and via of `board`; ({"REF.PAD": router pad index})."""
    from pcbenv import board as B
    from pcbenv.tool import _outline
    x0, y0, w, h = _outline(board)
    R = drc.RULES
    router = Router(x0, y0, w, h, 0.1, Rules(clearance=R["clearance"], edge_clearance=R["copper_edge_clearance"],
                                             hole_clearance=R["hole_clearance"], hole_to_hole=R["hole_to_hole"],
                                             via_d=R["via_diameter"], via_drill=R["via_drill"]))
    idx: dict[str, int] = {}
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        for pad in sorted(fp.Pads(), key=lambda p: (p.GetNumber(), p.GetPosition().x, p.GetPosition().y)):
            try:
                g = B.pad_geom(pad, f"{fp.GetReference()}.{pad.GetNumber()}")
            except B.BuildError as e:
                raise NotApplicable(str(e)) from None
            router.pads.append(g)
            idx.setdefault(g.key, len(router.pads) - 1)
    from pcbenv.router import Seg, Via
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            router.vias.append(Via(t.GetNetCode(), p.x / MM, p.y / MM, t.GetWidth() / MM, t.GetDrillValue() / MM))
        elif t.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            s, e = t.GetStart(), t.GetEnd()
            router.segs.append(Seg(t.GetNetCode(), 0 if t.GetLayer() == pcbnew.F_Cu else 1, s.x / MM, s.y / MM,
                                   e.x / MM, e.y / MM, t.GetWidth() / MM))
    return router, idx


def add_new_copper(board, router: Router, n_segs: int, n_vias: int) -> None:
    from pcbenv.board import add_copper
    add_copper(board, SimpleNamespace(segs=router.segs[n_segs:], vias=router.vias[n_vias:]))


def pad_key(board, ref: str, padnum: str) -> str:
    return f"{ref}.{padnum}"


def _copy_wp(w: PadGeom) -> PadGeom:
    from dataclasses import replace
    return replace(w)


def waypoint(x: float, y: float, layer: int) -> PadGeom:
    """A router-only pad (one grid cell) the path must pass through on `layer` (0 F.Cu, 1 B.Cu)."""
    return PadGeom(0, round(x, 1), round(y, 1), 0.0, 0.06, 0.06, 0.0, (layer == 0, layer == 1), 0.0, "WP")


def route_branch(board, netcode: int, pad_a: str, pad_b: str, width: float,
                 waypoints: list[PadGeom] | None = None, isolated: bool | str = True) -> None:
    """Add copper pad_a -> waypoints -> pad_b ("REF.PAD" keys). `isolated`: the net's existing copper
    is an obstacle (the branch meets the net only inside pad_b); False: a plain 2-pin route that may
    merge into same-net copper; "prefer": isolated, else plain. Raises NotApplicable on failure."""
    if isolated == "prefer":
        try:
            return route_branch(board, netcode, pad_a, pad_b, width, [_copy_wp(w) for w in waypoints or []], True)
        except NotApplicable:
            return route_branch(board, netcode, pad_a, pad_b, width, waypoints, False)
    from pcbenv.board import route_branch as rb
    router, idx = board_router(board)
    if pad_a not in idx or pad_b not in idx:
        raise NotApplicable(f"{pad_a} / {pad_b} not on the board")
    ia, ib = idx[pad_a], idx[pad_b]
    n_s, n_v = len(router.segs), len(router.vias)
    try:
        if isolated:
            rb(router, netcode, ia, ib, width, waypoints)
        else:
            base = len(router.pads)
            wps = list(waypoints or [])
            for w in wps:
                w.net = netcode
            router.pads.extend(wps)
            chain = [ia] + list(range(base, base + len(wps))) + [ib]
            try:
                for i, j in zip(chain, chain[1:]):
                    router.route_net(netcode, [i, j], width, [i, j])
            finally:
                del router.pads[base:]
    except RouteError as e:
        raise NotApplicable(f"branch route failed: {e}") from None
    add_new_copper(board, router, n_s, n_v)


# ------------------------------------------------------------------ deleting copper
def _seg_list(board, code: int) -> list:
    return [t for t in board.GetTracks() if t.GetNetCode() == code]


def _pt_seg(px: float, py: float, t) -> float:
    from pcbenv.layout import _proj
    s, e = t.GetStart(), t.GetEnd()
    return _proj(px, py, s.x / MM, s.y / MM, e.x / MM, e.y / MM)[1]


def _pad_touch_pt(pad, x: float, y: float, r: float, layer: int | None) -> bool:
    if layer is not None and not pad.IsOnLayer(layer):
        return False
    from pcbenv.layout_rules import _pad_sdf
    f = _pad_sdf(pad)
    if f is not None:
        return f(x, y) <= r + 1e-6
    return pad.HitTest(pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM))), int(round(r * MM)))


def delete_items(board, items: list) -> None:
    for t in items:
        board.Delete(t)


def prune_dangling(board, code: int) -> int:
    """Delete track segments of net `code` with an end touching nothing else of the net (no other
    track, via or pad), and vias touching fewer than two items; repeat until stable."""
    pads = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode() == code]
    n_del = 0
    while True:
        items = _seg_list(board, code)
        dead = []
        for t in items:
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                vx, vy, vr = q.x / MM, q.y / MM, t.GetWidth() / 2 / MM
                n = sum(1 for o in items if o is not t and o.GetClass() != "PCB_VIA"
                        and _pt_seg(vx, vy, o) <= vr + o.GetWidth() / 2 / MM + 1e-6)
                n += sum(1 for p in pads if _pad_touch_pt(p, vx, vy, vr, None))
                if n < 2:
                    dead.append(t)
                continue
            w = t.GetWidth() / MM
            for end in (t.GetStart(), t.GetEnd()):
                ex, ey = end.x / MM, end.y / MM
                ok = any(_pad_touch_pt(p, ex, ey, w / 2, t.GetLayer()) for p in pads)
                if not ok:
                    for o in items:
                        if o is t:
                            continue
                        if o.GetClass() == "PCB_VIA":
                            q = o.GetPosition()
                            if math.hypot(q.x / MM - ex, q.y / MM - ey) <= o.GetWidth() / 2 / MM + w / 2 + 1e-6:
                                ok = True
                                break
                        elif o.GetLayer() == t.GetLayer() and _pt_seg(ex, ey, o) <= (w + o.GetWidth() / MM) / 2 + 1e-6:
                            ok = True
                            break
                if not ok:
                    dead.append(t)
                    break
        if not dead:
            return n_del
        n_del += len(dead)
        delete_items(board, dead)


def tracks_touching_pad(board, pad) -> list:
    out = []
    code = pad.GetNetCode()
    for t in _seg_list(board, code):
        if t.GetClass() == "PCB_VIA":
            q = t.GetPosition()
            if _pad_touch_pt(pad, q.x / MM, q.y / MM, t.GetWidth() / 2 / MM, None):
                out.append(t)
            continue
        s, e = t.GetStart(), t.GetEnd()
        w = t.GetWidth() / MM
        L = math.hypot((e.x - s.x) / MM, (e.y - s.y) / MM)
        n = max(1, int(math.ceil(L / 0.02)))
        for i in range(n + 1):
            x = (s.x + (e.x - s.x) * i / n) / MM
            y = (s.y + (e.y - s.y) * i / n) / MM
            if _pad_touch_pt(pad, x, y, w / 2, t.GetLayer()):
                out.append(t)
                break
    return out


def detach_pad(board, pad) -> None:
    """Remove the copper that serves `pad` only: the tracks touching it, then dangling leftovers."""
    delete_items(board, tracks_touching_pad(board, pad))
    prune_dangling(board, pad.GetNetCode())


def reconnect(board, code: int, width: float, skip: set[str] = frozenset()) -> None:
    """Join every copper island of net `code` holding pads to the island of the net's first pad
    (sorted by key) with isolated branches (nearest pad pairs). Pads keyed "REF.PAD" in `skip`
    are left alone."""
    from pcbenv.layout_rules import copper_islands
    for _ in range(20):
        isl = copper_islands(board, code)
        pads = sorted(((k[1] + "." + k[2], v) for k, v in isl.items() if k[0] == "pad"
                       and (k[1] + "." + k[2]) not in skip), key=lambda kv: kv[0])
        if not pads:
            return
        groups: dict = {}
        for k, v in pads:
            groups.setdefault(v, []).append(k)
        if len(groups) <= 1:
            return
        main = groups[pads[0][1]]
        other = next(g for v, g in sorted(groups.items(), key=lambda kv: kv[1][0]) if g is not main)
        pos = {k: _pad_xy(board, k) for k in main + other}
        a, c = min(((x, y) for x in other for y in main),
                   key=lambda xy: (math.dist(pos[xy[0]], pos[xy[1]]), xy))
        route_branch(board, code, a, c, width, isolated=True)
    raise NotApplicable("cannot reconnect net islands")


def _pad_xy(board, key: str) -> tuple[float, float]:
    ref, num = key.split(".", 1)
    fp = board.FindFootprintByReference(ref)
    p = sorted((q for q in fp.Pads() if q.GetNumber() == num), key=lambda q: (q.GetPosition().x, q.GetPosition().y))[0]
    c = p.GetPosition()
    return c.x / MM, c.y / MM


def find_pad(board, ref: str, padnum: str):
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        return None
    ps = sorted((p for p in fp.Pads() if p.GetNumber() == padnum), key=lambda p: (p.GetPosition().x, p.GetPosition().y))
    return ps[0] if ps else None


# ------------------------------------------------------------------ moving parts
def courtyard_bbox(fp) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            bb = it.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]
            ys += [bb.GetTop(), bb.GetBottom()]
    if not xs:
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]
            ys += [bb.GetTop(), bb.GetBottom()]
    return min(xs) / MM, min(ys) / MM, max(xs) / MM, max(ys) / MM


def placement_ok(board, fp, gap: float = 0.5, edge: float = 0.5) -> bool:
    """Courtyard of `fp` clear of other courtyards by `gap`, inside the outline by `edge`, and its
    pads clear of other nets' tracks / vias by the clearance."""
    from pcbenv.tool import _outline
    x0, y0, w, h = _outline(board)
    a0, b0, a1, b1 = courtyard_bbox(fp)
    if a0 < x0 + edge or b0 < y0 + edge or a1 > x0 + w - edge or b1 > y0 + h - edge:
        return False
    me = fp.GetReference()
    for o in board.GetFootprints():
        if o.GetReference() == me:
            continue
        c0, d0, c1, d1 = courtyard_bbox(o)
        if a0 < c1 + gap and a1 > c0 - gap and b0 < d1 + gap and b1 > d0 - gap:
            return False
    from pcbenv.layout_rules import _pad_sdf
    for p in fp.Pads():
        f = _pad_sdf(p)
        for t in board.GetTracks():
            if t.GetNetCode() == p.GetNetCode() and p.GetNetCode() > 0:
                continue
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                if f(q.x / MM, q.y / MM) <= t.GetWidth() / 2 / MM + CLEAR + 0.05:
                    return False
                continue
            if not p.IsOnLayer(t.GetLayer()):
                continue
            s, e = t.GetStart(), t.GetEnd()
            L = math.hypot((e.x - s.x) / MM, (e.y - s.y) / MM)
            n = max(1, int(math.ceil(L / 0.05)))
            ts = np.linspace(0, 1, n + 1)
            X = (s.x + (e.x - s.x) * ts) / MM
            Y = (s.y + (e.y - s.y) * ts) / MM
            from pcbenv.board import pad_geom
            g = pad_geom(p)
            if float(Router.pad_dist(g, X, Y).min()) <= t.GetWidth() / 2 / MM + CLEAR + 0.05:
                return False
    return True


def move_footprint(fp, x: float, y: float, rot: float) -> None:
    fp.SetPosition(pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM))))
    fp.SetOrientationDegrees(rot)


def board_outline(board) -> tuple[float, float, float, float]:
    from pcbenv.tool import _outline
    return _outline(board)
