"""Board faults: design.json is correct (except footprint_swap, where both files agree), the
layout is not.

- board_pad_swap        pad nets of one footprint permuted vs design.json (pinout mapping error),
                        re-routed so the board itself is DRC clean
- clearance_violation   a track stub of one net routed too close to another net's track
- broken_trace          a gap cut into a track (net left unconnected)
- short_between_nets    a track joining copper of two different nets
- narrow_power_trace    part of a power track necked down below its required width (DRC clean)
- decap_moved_far       a decoupling cap placed beyond its maximum distance, nets re-routed (DRC clean)
- footprint_swap        a passive given another allowed footprint in place, tracks not fixed
"""
from __future__ import annotations

import math
import os
import random
import shutil
import tempfile

import pcbnew

from pcbenv import boardnet
from pcbenv.board import EDGE_KEEP, ORIGIN, design_pad_nets
from pcbenv.faults.common import (MM, FaultRecord, NotApplicable, add_track, closest_on_seg, drc_result, free,
                                  is_symmetric, load_board, nets_target, pads_of_net, reroute, rewire, save_board,
                                  seed_kiid, seg_tuple, tracks_of)
from pcbenv.golden import Golden
from pcbenv.parts import PARTS


def _save_checked(board, board_path: str, salt: str, accept) -> bool:
    """Save `board` to a temp file, DRC it; copy over board_path iff accept(DrcResult)."""
    with tempfile.TemporaryDirectory(prefix="pcbfault_") as td:
        tmp = os.path.join(td, "board.kicad_pcb")
        save_board(board, tmp, salt)
        res = drc_result(tmp)
        if not accept(res):
            return False
        shutil.copyfile(tmp, board_path)
    return True


def _types(res) -> set[str]:
    return {e["type"] for e in res.errors}


def _is_touch(e: dict) -> bool:
    """Copper of two nets touching: KiCad 7 reports it as shorting_items / tracks_crossing or as
    a clearance violation with actual 0."""
    return e["type"] in ("shorting_items", "tracks_crossing") or (
        e["type"] in ("clearance", "hole_clearance") and "actual 0.0000 mm" in e["description"])


def _routed_nets(board, exclude: set[str]) -> list[str]:
    nets = sorted({t.GetNetname() for t in board.GetTracks() if t.GetNetCode() > 0})
    return [n for n in nets if free(exclude, f"net:{n}")]


# ------------------------------------------------------------------ pad swap
def board_pad_swap(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    exclude = set(exclude)
    padnets = design_pad_nets(design)
    cands = []
    for ref, c in sorted(design["components"].items()):
        part = PARTS[c["part"]]
        if is_symmetric(c["part"]) or not free(exclude, ref):
            continue
        pins = sorted(part.pins)
        for i, a in enumerate(pins):
            for b in pins[i + 1:]:
                pa, pb = part.pins[a].pad, part.pins[b].pad
                na, nb = padnets[ref].get(pa), padnets[ref].get(pb)
                if na == nb or (na is None and nb is None) or na is None or nb is None:
                    continue
                if free(exclude, *nets_target(na, nb)):
                    cands.append((ref, a, b, pa, pb, na, nb))
    rng.shuffle(cands)
    for ref, a, b, pa, pb, na, nb in cands[:8]:
        pn = {r: dict(m) for r, m in padnets.items()}
        pn[ref][pa], pn[ref][pb] = nb, na
        try:
            nets = rewire(golden, board_path, pn, salt)
        except NotApplicable:
            continue
        return FaultRecord("board_pad_swap", "board",
                           f"board pads of {ref}.{a} (pad {pa}) and {ref}.{b} (pad {pb}) carry each other's nets",
                           True, [ref] + nets_target(*nets),
                           {"ref": ref, "pins": [f"{ref}.{a}", f"{ref}.{b}"], "pads": [pa, pb], "nets": [na, nb]})
    return None


# ------------------------------------------------------------------ track geometry faults
def _near_candidates(board, exclude: set[str], lo: float, hi: float) -> list[tuple]:
    """(netA, layer, P, Q, wA, wB, netB): an endpoint P of a netA track and the closest point Q
    on a netB track centreline on the same layer, edge-to-edge gap in (lo, hi)."""
    segs = [(t.GetNetname(), *seg_tuple(t)) for t in board.GetTracks()
            if t.GetClass() == "PCB_TRACK" and t.GetNetCode() > 0]
    out = []
    ok = {n for n in {s[0] for s in segs} if free(exclude, f"net:{n}")}
    for na, la, ax1, ay1, ax2, ay2, wa in segs:
        if na not in ok:
            continue
        for px, py in ((ax1, ay1), (ax2, ay2)):
            for nb, lb, bx1, by1, bx2, by2, wb in segs:
                if nb == na or lb != la or nb not in ok:
                    continue
                qx, qy = closest_on_seg(px, py, bx1, by1, bx2, by2)
                gap = math.hypot(px - qx, py - qy) - wa / 2 - wb / 2
                if lo < gap < hi:
                    out.append((na, la, (round(px, 4), round(py, 4)), (round(qx, 4), round(qy, 4)), wa, wb, nb))
    return sorted(set(out))


def _stub_fault(ftype: str, golden, design, board_path, rng, exclude, salt, touch: bool) -> FaultRecord | None:
    exclude = set(exclude)
    board = load_board(board_path)
    cands = _near_candidates(board, exclude, 0.3, 2.0)
    rng.shuffle(cands)
    for na, layer, P, Q, wa, wb, nb in cands[:10]:
        board = load_board(board_path)
        seed_kiid(salt + ftype)
        dx, dy = P[0] - Q[0], P[1] - Q[1]
        L = math.hypot(dx, dy)
        if touch:
            E = Q
            gap = 0.0
        else:
            gap = round(rng.uniform(0.05, 0.14), 3)
            k = (wa / 2 + wb / 2 + gap) / L
            E = (Q[0] + dx * k, Q[1] + dy * k)
        add_track(board, na, layer, P[0], P[1], E[0], E[1], wa)

        def accept(res):
            t = _types(res)
            if res.unconnected:
                return False
            touching = any(_is_touch(e) for e in res.errors)
            if touch:
                return touching
            return "clearance" in t and not touching
        if not _save_checked(board, board_path, salt, accept):
            continue
        lay = "F.Cu" if layer == 0 else "B.Cu"
        if touch:
            detail = f"track of net {na} on {lay} runs into net {nb} at ({Q[0]:.2f}, {Q[1]:.2f})"
        else:
            detail = f"track stub of net {na} on {lay} ends {gap:.2f} mm from net {nb} at ({E[0]:.2f}, {E[1]:.2f})"
        return FaultRecord(ftype, "board", detail, False, nets_target(na, nb),
                           {"net": na, "other_net": nb, "layer": lay, "from": list(P), "to": [round(E[0], 4), round(E[1], 4)],
                            "gap_mm": gap})
    return None


def clearance_violation(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    return _stub_fault("clearance_violation", golden, design, board_path, rng, exclude, salt, touch=False)


def short_between_nets(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    return _stub_fault("short_between_nets", golden, design, board_path, rng, exclude, salt, touch=True)


def broken_trace(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    exclude = set(exclude)
    board = load_board(board_path)
    cands = []
    for net in _routed_nets(board, exclude):
        for t in tracks_of(board, net):
            layer, x1, y1, x2, y2, w = seg_tuple(t)
            if math.hypot(x2 - x1, y2 - y1) >= 1.2:
                cands.append((net, layer, x1, y1, x2, y2, w))
    cands.sort()
    rng.shuffle(cands)
    for net, layer, x1, y1, x2, y2, w in cands[:8]:
        board = load_board(board_path)
        seed_kiid(salt + "broken")
        victim = None
        for t in tracks_of(board, net):
            if seg_tuple(t) == (layer, x1, y1, x2, y2, w):
                victim = t
                break
        if victim is None:
            continue
        L = math.hypot(x2 - x1, y2 - y1)
        gap = 0.4
        t0 = rng.uniform(0.3, 0.7)
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        mx, my = x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0
        a = (mx - ux * gap / 2, my - uy * gap / 2)
        b = (mx + ux * gap / 2, my + uy * gap / 2)
        board.Delete(victim)
        add_track(board, net, layer, x1, y1, a[0], a[1], w)
        add_track(board, net, layer, b[0], b[1], x2, y2, w)
        if not _save_checked(board, board_path, salt, lambda r: r.unconnected > 0 and not r.errors):
            continue
        lay = "F.Cu" if layer == 0 else "B.Cu"
        return FaultRecord("broken_trace", "board", f"track of net {net} on {lay} cut near ({mx:.2f}, {my:.2f})",
                           False, nets_target(net), {"net": net, "layer": lay, "at": [round(mx, 3), round(my, 3)]})
    return None


def narrow_power_trace(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    exclude = set(exclude)
    board = load_board(board_path)
    nets = [n for n, w in sorted(golden.power_nets.items()) if w > 0.2 + 1e-9 and free(exclude, f"net:{n}")
            and tracks_of(board, n)]
    rng.shuffle(nets)
    for net in nets:
        req = golden.power_nets[net]
        board = load_board(board_path)
        seed_kiid(salt + "narrow")
        segs = sorted((seg_tuple(t), t) for t in tracks_of(board, net))
        longish = [s for s in segs if math.hypot(s[0][3] - s[0][1], s[0][4] - s[0][2]) >= 0.8] or segs
        k = min(len(longish), 1 + rng.randrange(3))
        pick = rng.sample(range(len(longish)), k)
        new_w = 0.2 if req <= 0.3 else [0.2, 0.25, 0.3][rng.randrange(3)]
        for i in pick:
            longish[i][1].SetWidth(int(round(new_w * MM)))
        if not _save_checked(board, board_path, salt, lambda r: r.clean):
            continue
        return FaultRecord("narrow_power_trace", "board",
                           f"{k} segment(s) of power net {net} are {new_w} mm wide (required {req} mm)", True,
                           nets_target(net), {"net": net, "width": new_w, "required": req, "segments": k})
    return None


# ------------------------------------------------------------------ placement fault
def _bbox(item) -> tuple[float, float, float, float]:
    bb = item.GetBoundingBox()
    return bb.GetLeft() / MM, bb.GetTop() / MM, bb.GetRight() / MM, bb.GetBottom() / MM


def _fp_box(fp) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for p in fp.Pads():
        x0, y0, x1, y1 = _bbox(p)
        xs += [x0, x1]
        ys += [y0, y1]
    for g in fp.GraphicalItems():
        if g.GetLayer() == pcbnew.F_CrtYd:
            x0, y0, x1, y1 = _bbox(g)
            xs += [x0, x1]
            ys += [y0, y1]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b, m: float) -> bool:
    return a[0] < b[2] + m and a[2] > b[0] - m and a[1] < b[3] + m and a[3] > b[1] - m


def decap_moved_far(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    exclude = set(exclude)
    rp = {r: c["part"] for r, c in design["components"].items()}
    dcs = [dc for dc in golden.decoupling if dc["cap"] in design["components"]]
    rng.shuffle(dcs)
    for dc in dcs:
        cap = dc["cap"]
        board = load_board(board_path)
        fp = board.FindFootprintByReference(cap)
        if fp is None:
            continue
        cap_nets = sorted({p.GetNetname() for p in fp.Pads() if p.GetNetCode() > 0})
        if not free(exclude, cap, *nets_target(*cap_nets)):
            continue
        ic_ref, ic_pin = dc["ic_pin"].split(".", 1)
        ip = boardnet.pad_position(board, ic_ref, ic_pin, parts=rp)
        if ip is None:
            continue
        pos = fp.GetPosition()
        cx, cy = pos.x / MM, pos.y / MM
        box = _fp_box(fp)
        rel = (box[0] - cx, box[1] - cy, box[2] - cx, box[3] - cy)
        pad_rel = [(p.GetPosition().x / MM - cx, p.GetPosition().y / MM - cy) for p in fp.Pads()]
        others = [_fp_box(f) for f in board.GetFootprints() if f.GetReference() != cap]
        obst = [_bbox(t) for t in board.GetTracks() if t.GetNetname() not in cap_nets]
        x0, y0 = ORIGIN
        W, H = golden.board_w_mm, golden.board_h_mm
        lim = dc["max_mm"]
        spots = []
        steps_x = int(W / 0.5)
        steps_y = int(H / 0.5)
        for i in range(steps_x + 1):
            for j in range(steps_y + 1):
                x, y = x0 + i * 0.5, y0 + j * 0.5
                b = (x + rel[0], y + rel[1], x + rel[2], y + rel[3])
                if b[0] < x0 + EDGE_KEEP or b[1] < y0 + EDGE_KEEP or b[2] > x0 + W - EDGE_KEEP or b[3] > y0 + H - EDGE_KEEP:
                    continue
                dmin = min(math.hypot(x + dx - ip[0], y + dy - ip[1]) for dx, dy in pad_rel)
                if not (lim + 1.0 < dmin < lim + 10.0):
                    continue
                if any(_overlap(b, o, 0.4) for o in others) or any(_overlap(b, o, 0.25) for o in obst):
                    continue
                spots.append((x, y))
        rng.shuffle(spots)
        for x, y in spots[:6]:
            board = load_board(board_path)
            seed_kiid(salt + "decap")
            f2 = board.FindFootprintByReference(cap)
            f2.SetPosition(pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM))))
            try:
                reroute(board, golden, cap_nets)
            except NotApplicable:
                continue
            if not _save_checked(board, board_path, salt, lambda r: r.clean):
                continue
            d = min(math.hypot(x + dx - ip[0], y + dy - ip[1]) for dx, dy in pad_rel)
            return FaultRecord("decap_moved_far", "board",
                               f"{cap} placed at ({x:.1f}, {y:.1f}), {d:.1f} mm from {dc['ic_pin']} (max {lim} mm)",
                               True, [cap] + nets_target(*cap_nets),
                               {"cap": cap, "ic_pin": dc["ic_pin"], "pos": [x, y], "golden_pos": [cx, cy],
                                "rot": fp.GetOrientationDegrees(), "max_mm": lim, "nets": cap_nets})
    return None


# ------------------------------------------------------------------ footprint swap
def footprint_swap(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    from pcbenv.tool import _replace_footprint
    exclude = set(exclude)
    cands = []
    padnets = design_pad_nets(design)
    for ref, c in sorted(design["components"].items()):
        fps = PARTS[c["part"]].footprints
        nets = sorted(set(padnets[ref].values()))
        if len(fps) < 2 or not free(exclude, ref, *nets_target(*nets)):
            continue
        for fpid in fps:
            if fpid != c["footprint"]:
                cands.append((ref, fpid, tuple(nets)))
    rng.shuffle(cands)
    for ref, fpid, nets in cands[:6]:
        board = load_board(board_path)
        seed_kiid(salt + "fpswap")
        old = design["components"][ref]["footprint"]
        _replace_footprint(board, ref, fpid, design["components"][ref].get("value", ""))
        if not _save_checked(board, board_path, salt, lambda r: not r.clean):
            continue
        design["components"][ref]["footprint"] = fpid
        return FaultRecord("footprint_swap", "board",
                           f"{ref} footprint changed to {fpid} (was {old}); tracks no longer fit", False,
                           [ref] + nets_target(*nets), {"ref": ref, "footprint": fpid, "golden_footprint": old,
                                                        "nets": list(nets)})
    return None
