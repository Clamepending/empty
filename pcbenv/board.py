"""Build a placed + fully routed KiCad 7 board from a Golden.

Conventions
-----------
- Board outline: rectangle on Edge.Cuts from ORIGIN = (100, 100) mm to
  (100 + board_w_mm, 100 + board_h_mm) (KiCad y axis points down). Positions in
  `board_info` are absolute KiCad coordinates in mm.
- 2 copper layers (F.Cu, B.Cu), all footprints on F.Cu, rotations in {0, 90, 180, 270}.
- Rules: canonical rules of `pcbenv.drc.RULES` (the .kicad_pro is not written; KiCad 7
  keeps rules there, and the verifier never trusts it).
- Placement: greedy, seeded. Parts are placed one by one (most pins first, decoupling
  caps right after their IC) at the free 0.5 mm grid position / rotation that minimises
  the distance of its pads to already-placed pads on the same nets plus a seeded jitter.
  Courtyards are kept `gap` mm apart (routing channels) and `EDGE_KEEP` mm from the edge.
- Routing: `pcbenv.router.Router` (grid A*, 2 layers, vias). On failure: rip up all and
  retry with the failing net first; after a few orderings, re-place with another seed.
- The finished board is saved, re-loaded and DRC'd with `drc.run_drc`; only a board with
  0 errors and 0 unconnected is accepted. UUIDs are rewritten deterministically, so the
  same (golden, seed) gives a byte-identical file.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass

import numpy as np
import pcbnew

from pcbenv import drc
from pcbenv.boardnet import library_footprint
from pcbenv.golden import Golden
from pcbenv.parts import PARTS
from pcbenv.router import PadGeom, Router, RouteError, Rules

ORIGIN = (100.0, 100.0)
EDGE_KEEP = 0.5          # courtyard to board edge (mm)
PLACE_STEP = 0.5         # placement grid (mm)
DEFAULT_WIDTH = drc.RULES["default_track_width"]
MM = 1_000_000


class BuildError(RuntimeError):
    pass


def _nm(v: float) -> int:
    return int(round(v * MM))


def _mm(v: int) -> float:
    return v / MM


def load_footprint(fpid: str) -> "pcbnew.FOOTPRINT":
    fp = library_footprint(fpid)
    if fp is None:
        raise BuildError(f"footprint not found: {fpid}")
    return fp


def design_pad_nets(design: dict) -> dict[str, dict[str, str]]:
    """{ref: {pad number: net name}} from design nets via the parts pad map."""
    out: dict[str, dict[str, str]] = {ref: {} for ref in design["components"]}
    for name, pins in design["nets"].items():
        for p in pins:
            ref, pin = p.split(".", 1)
            part = PARTS[design["components"][ref]["part"]]
            out[ref][part.pins[pin].pad] = name
    return out


# ------------------------------------------------------------------ placement
@dataclass
class _FpShape:
    rect: tuple[float, float, float, float]       # courtyard bbox rel. to origin
    pads: list[tuple[str, float, float]]          # (pad number, dx, dy)


def _fp_shapes(fp: "pcbnew.FOOTPRINT") -> list[_FpShape]:
    """Courtyard bbox and pad offsets for rotations 0, 90, 180, 270."""
    out = []
    for rot in (0, 90, 180, 270):
        fp.SetPosition(pcbnew.VECTOR2I(0, 0))
        fp.SetOrientationDegrees(rot)
        xs, ys = [], []
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_CrtYd:
                bb = it.GetBoundingBox()
                xs += [bb.GetLeft(), bb.GetRight()]
                ys += [bb.GetTop(), bb.GetBottom()]
        pads = [(p.GetNumber(), _mm(p.GetPosition().x), _mm(p.GetPosition().y)) for p in fp.Pads()]
        if not xs:
            for p in fp.Pads():
                bb = p.GetBoundingBox()
                xs += [bb.GetLeft() - _nm(0.25), bb.GetRight() + _nm(0.25)]
                ys += [bb.GetTop() - _nm(0.25), bb.GetBottom() + _nm(0.25)]
        out.append(_FpShape((_mm(min(xs)), _mm(min(ys)), _mm(max(xs)), _mm(max(ys))), pads))
    fp.SetOrientationDegrees(0)
    return out


def place(golden: Golden, seed: int, gap: float = 1.0) -> dict[str, tuple[float, float, int]]:
    """Return {ref: (x_mm, y_mm, rot_deg)} (absolute KiCad coordinates)."""
    rng = random.Random(seed)
    d = golden.design
    comps = d["components"]
    padnets = design_pad_nets(d)
    shapes = {ref: _fp_shapes(load_footprint(c["footprint"])) for ref, c in sorted(comps.items())}
    x0, y0 = ORIGIN
    W, H = golden.board_w_mm, golden.board_h_mm
    gx = np.arange(x0, x0 + W + 1e-9, PLACE_STEP)
    gy = np.arange(y0, y0 + H + 1e-9, PLACE_STEP)
    CX, CY = np.meshgrid(gx, gy)
    CX, CY = CX.ravel(), CY.ravel()
    jitter_field = np.array([rng.random() for _ in range(CX.size)])

    decaps: dict[str, list[dict]] = {}
    decap_of: dict[str, dict] = {}
    for dc in golden.decoupling:
        ic = dc["ic_pin"].split(".", 1)[0]
        decaps.setdefault(ic, []).append(dc)
        decap_of[dc["cap"]] = dc

    npins = {ref: len(padnets[ref]) for ref in comps}
    adj: dict[str, dict[str, int]] = {ref: {} for ref in comps}
    for pins in d["nets"].values():
        refs = sorted({p.split(".", 1)[0] for p in pins})
        for a in refs:
            for b in refs:
                if a != b:
                    adj[a][b] = adj[a].get(b, 0) + 1

    placed: dict[str, tuple[float, float, int]] = {}
    rects: list[tuple[float, float, float, float, float]] = []   # x0,y0,x1,y1,gap
    placed_pads: dict[str, list[tuple[float, float]]] = {}
    ic_pin_pos: dict[str, tuple[float, float]] = {}

    def pin_pad(pinref: str) -> str:
        ref, pin = pinref.split(".", 1)
        return PARTS[comps[ref]["part"]].pins[pin].pad

    def do_place(ref: str) -> None:
        best = None
        dc = decap_of.get(ref)
        my_gap = gap
        for attempt in range(3):
            for ri in rng.sample(range(4), 4):
                sh = shapes[ref][ri]
                rx0, ry0, rx1, ry1 = sh.rect
                ok = (CX + rx0 >= x0 + EDGE_KEEP) & (CX + rx1 <= x0 + W - EDGE_KEEP) & \
                     (CY + ry0 >= y0 + EDGE_KEEP) & (CY + ry1 <= y0 + H - EDGE_KEEP)
                for (a0, b0, a1, b1, g2) in rects:
                    gg = max(my_gap, g2) if dc is None else my_gap
                    ok &= ~((CX + rx0 < a1 + gg) & (CX + rx1 > a0 - gg) &
                            (CY + ry0 < b1 + gg) & (CY + ry1 > b0 - gg))
                if not ok.any():
                    continue
                cost = np.zeros(CX.size)
                for num, dx, dy in sh.pads:
                    net = padnets[ref].get(num)
                    if net is None or net not in placed_pads:
                        continue
                    P = np.array(placed_pads[net])
                    dd = np.hypot(CX[:, None] + dx - P[None, :, 0], CY[:, None] + dy - P[None, :, 1]).min(axis=1)
                    cost += dd
                if dc is not None:
                    icx, icy = ic_pin_pos[dc["ic_pin"]]
                    lim = dc["max_mm"] * 0.85
                    for num, dx, dy in sh.pads:
                        ok &= np.hypot(CX + dx - icx, CY + dy - icy) <= lim
                    if not ok.any():
                        continue
                if not placed:
                    cost += 0.3 * np.hypot(CX - (x0 + W / 2), CY - (y0 + H / 2))
                elif cost.max() == 0:
                    # unconnected to anything placed: stay near the board centre
                    cost += 0.2 * np.hypot(CX - (x0 + W / 2), CY - (y0 + H / 2))
                cost += 1.5 * jitter_field + rng.random() * 0.5
                cost = np.where(ok, cost, np.inf)
                i = int(np.argmin(cost))
                if best is None or cost[i] < best[0]:
                    best = (float(cost[i]), float(CX[i]), float(CY[i]), ri)
            if best is not None:
                break
            my_gap = my_gap * 0.5 if attempt == 0 else 0.25
        if best is None:
            raise BuildError(f"cannot place {ref}")
        _, x, y, ri = best
        sh = shapes[ref][ri]
        placed[ref] = (round(x, 4), round(y, 4), ri * 90)
        rx0, ry0, rx1, ry1 = sh.rect
        rects.append((x + rx0, y + ry0, x + rx1, y + ry1, my_gap))
        for num, dx, dy in sh.pads:
            net = padnets[ref].get(num)
            if net is not None:
                placed_pads.setdefault(net, []).append((x + dx, y + dy))
        part = PARTS[comps[ref]["part"]]
        for pin, info in part.pins.items():
            for num, dx, dy in sh.pads:
                if num == info.pad:
                    ic_pin_pos[f"{ref}.{pin}"] = (x + dx, y + dy)

    order = sorted(comps, key=lambda r: (-npins[r], r))
    order = [r for r in order if r not in decap_of]
    # first: the part with most pins; then by connectivity to placed parts
    todo = list(order)
    while todo:
        if not placed:
            ref = todo[0]
        else:
            ref = max(todo, key=lambda r: (sum(adj[r].get(p, 0) for p in placed), npins[r], -order.index(r)))
        todo.remove(ref)
        do_place(ref)
        for dc in sorted(decaps.get(ref, []), key=lambda e: e["cap"]):
            if dc["cap"] not in placed:
                do_place(dc["cap"])
    for dc in golden.decoupling:  # caps whose IC is placed through another path
        if dc["cap"] not in placed:
            do_place(dc["cap"])
    return placed


# --------------------------------------------------------------- board build
def new_board(golden: Golden) -> "pcbnew.BOARD":
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    x0, y0 = ORIGIN
    rect = pcbnew.PCB_SHAPE(board)
    rect.SetShape(pcbnew.SHAPE_T_RECT)
    rect.SetLayer(pcbnew.Edge_Cuts)
    rect.SetWidth(_nm(0.05))
    rect.SetStart(pcbnew.VECTOR2I(_nm(x0), _nm(y0)))
    rect.SetEnd(pcbnew.VECTOR2I(_nm(x0 + golden.board_w_mm), _nm(y0 + golden.board_h_mm)))
    board.Add(rect)
    drc.apply_rules(board)
    return board


def add_footprints(board: "pcbnew.BOARD", golden: Golden,
                   placement: dict[str, tuple[float, float, int]]) -> dict[str, int]:
    """Add placed footprints with nets; returns {net name: netcode}."""
    d = golden.design
    netcodes: dict[str, int] = {}
    for name in sorted(n for n, pins in d["nets"].items() if pins):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netcodes[name] = ni.GetNetCode()
    padnets = design_pad_nets(d)
    for ref in sorted(d["components"]):
        c = d["components"][ref]
        fp = load_footprint(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c.get("value", ""))
        board.Add(fp)
        x, y, rot = placement[ref]
        fp.SetPosition(pcbnew.VECTOR2I(_nm(x), _nm(y)))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net = padnets[ref].get(pad.GetNumber())
            if net is not None:
                pad.SetNet(board.FindNet(net))
    return netcodes


def pad_geom(pad: "pcbnew.PAD", key: str = "") -> PadGeom:
    shape = pad.GetShape()
    sx, sy = _mm(pad.GetSize().x), _mm(pad.GetSize().y)
    rr = 0.0
    if shape == pcbnew.PAD_SHAPE_CIRCLE:
        rr = min(sx, sy) / 2
    elif shape == pcbnew.PAD_SHAPE_OVAL:
        rr = min(sx, sy) / 2
    elif shape == pcbnew.PAD_SHAPE_ROUNDRECT:
        rr = _mm(pad.GetRoundRectCornerRadius())
    elif shape not in (pcbnew.PAD_SHAPE_RECT, pcbnew.PAD_SHAPE_CHAMFERED_RECT):
        # trapezoid / custom: conservative axis-aligned bounding box
        bb = pad.GetBoundingBox()
        c = pad.GetPosition()
        hx = max(abs(bb.GetLeft() - c.x), abs(bb.GetRight() - c.x))
        hy = max(abs(bb.GetTop() - c.y), abs(bb.GetBottom() - c.y))
        return _pad_geom_common(pad, key, 0.0, _mm(hx), _mm(hy), 0.0)
    off = pad.GetOffset()
    if off.x or off.y:
        raise BuildError(f"pad offset not supported: {key}")
    return _pad_geom_common(pad, key, pad.GetOrientationDegrees(), sx / 2, sy / 2, rr)


def _pad_geom_common(pad, key, angle, hx, hy, rr) -> PadGeom:
    attr = pad.GetAttribute()
    hole = 0.0
    if attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
        ds = pad.GetDrillSize()
        hole = _mm(max(ds.x, ds.y)) / 2
    if attr == pcbnew.PAD_ATTRIB_NPTH:
        layers = (False, False)
    else:
        layers = (pad.IsOnLayer(pcbnew.F_Cu), pad.IsOnLayer(pcbnew.B_Cu))
    pos = pad.GetPosition()
    return PadGeom(pad.GetNetCode(), _mm(pos.x), _mm(pos.y), angle, hx, hy, rr, layers, hole, key)


def route_board(board: "pcbnew.BOARD", golden: Golden, netcodes: dict[str, int],
                pitch: float, max_orders: int = 6, deadline: float = 1e18) -> Router:
    R = drc.RULES
    router = Router(ORIGIN[0], ORIGIN[1], golden.board_w_mm, golden.board_h_mm, pitch,
                    Rules(clearance=R["clearance"], edge_clearance=R["copper_edge_clearance"],
                          hole_clearance=R["hole_clearance"], hole_to_hole=R["hole_to_hole"],
                          via_d=R["via_diameter"], via_drill=R["via_drill"]))
    net_pads: dict[int, list[int]] = {}
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        for pad in sorted(fp.Pads(), key=lambda p: (p.GetNumber(), p.GetPosition().x, p.GetPosition().y)):
            g = pad_geom(pad, f"{fp.GetReference()}.{pad.GetNumber()}")
            router.pads.append(g)
            if g.net > 0 and (g.layers[0] or g.layers[1]):
                net_pads.setdefault(g.net, []).append(len(router.pads) - 1)
    widths = {code: max(golden.power_nets.get(name, DEFAULT_WIDTH), drc.RULES["track_min"])
              for name, code in netcodes.items()}

    def span(code: int) -> float:
        ps = [router.pads[i] for i in net_pads.get(code, [])]
        if len(ps) < 2:
            return 0.0
        return (max(p.x for p in ps) - min(p.x for p in ps)) + (max(p.y for p in ps) - min(p.y for p in ps))

    order = sorted((c for c in net_pads if len(net_pads[c]) >= 2), key=lambda c: (span(c), c))
    last_err = None
    for _ in range(max_orders):
        if time.monotonic() > deadline:
            break
        router.segs, router.vias = [], []
        failed = None
        for code in order:
            try:
                router.route_net(code, net_pads[code], widths[code])
            except RouteError as e:
                failed, last_err = code, e
                break
        if failed is None:
            return router
        order = [failed] + [c for c in order if c != failed]
    raise BuildError(f"routing failed: {last_err}")


def add_copper(board: "pcbnew.BOARD", router: Router) -> None:
    layer = (pcbnew.F_Cu, pcbnew.B_Cu)
    for s in router.segs:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(_nm(s.x1), _nm(s.y1)))
        t.SetEnd(pcbnew.VECTOR2I(_nm(s.x2), _nm(s.y2)))
        t.SetWidth(_nm(s.w))
        t.SetLayer(layer[s.layer])
        t.SetNetCode(s.net)
        board.Add(t)
    for v in router.vias:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(_nm(v.x), _nm(v.y)))
        via.SetWidth(_nm(v.d))
        via.SetDrill(_nm(v.drill))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNetCode(v.net)
        board.Add(via)


_UUID_RE = re.compile(r"\((tstamp|uuid) ([0-9a-fA-F-]{36})\)")


def canonicalize_uuids(path: str, salt: str) -> None:
    """Rewrite all UUIDs to deterministic ones (consistent mapping)."""
    text = open(path, encoding="utf-8").read()
    mapping: dict[str, str] = {}

    def sub(m: re.Match) -> str:
        old = m.group(2)
        if old not in mapping:
            h = hashlib.sha256(f"{salt}:{len(mapping)}".encode()).hexdigest()
            mapping[old] = f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:32]}"
        return f"({m.group(1)} {mapping[old]})"

    text = _UUID_RE.sub(sub, text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


_TOP_RE = re.compile(r"^  \((\w+)")
_UUID_STRIP_RE = re.compile(r"\((?:tstamp|uuid) [0-9a-fA-F-]{36}\)")
_SORTABLE = {"footprint", "segment", "via", "arc", "gr_line", "gr_rect", "gr_circle", "gr_arc", "gr_poly", "gr_text"}


def canonical_board_file(path: str, salt: str) -> None:
    """Make a saved .kicad_pcb independent of the KiCad UUID generator's history.

    KiCad sorts footprints / tracks by UUID when saving, and the UUIDs it hands out depend on
    everything the process did before (library footprint loads consume generator draws), so
    the same board can be saved in different item orders. Here every run of consecutive
    top-level items of one kind is sorted by its UUID-free text, then UUIDs are renumbered in
    order of appearance (`board.canonicalize_uuids`)."""
    lines = open(path, encoding="utf-8").read().split("\n")
    head, blocks, tail = [], [], []
    i = 0
    while i < len(lines) and not _TOP_RE.match(lines[i]):
        head.append(lines[i])
        i += 1
    cur: list[str] | None = None
    for line in lines[i:]:
        if _TOP_RE.match(line):
            cur = [line]
            blocks.append(cur)
        elif (line.startswith("  ") or not line.strip()) and cur is not None:
            cur.append(line)
        else:
            tail.append(line)
            cur = None
    out: list[list[str]] = []
    run: list[list[str]] = []
    kind = None

    def flush() -> None:
        if kind in _SORTABLE:
            run.sort(key=lambda b: _UUID_STRIP_RE.sub("", "\n".join(b)))
        out.extend(run)

    for b in blocks:
        k = _TOP_RE.match(b[0]).group(1)
        if k != kind:
            flush()
            run, kind = [], k
        run.append(b)
    flush()
    body: list[str] = []
    prev = None
    for b in out:
        while len(b) > 1 and not b[-1].strip():
            b.pop()
        k = _TOP_RE.match(b[0]).group(1)
        if prev is not None and (k != prev or k == "footprint"):
            body.append("")
        body.extend(b)
        prev = k
    tail = [line for line in tail if line.strip()]
    text = "\n".join(head + body + tail) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    canonicalize_uuids(path, salt)


def build_board(golden: Golden, out_path: str, seed: int, pitch: float = 0.1,
                time_budget_s: float = 60.0) -> dict:
    """Build, route, DRC-check and save. Returns build stats. Raises BuildError."""
    t0 = time.monotonic()
    deadline = t0 + time_budget_s
    errors = []
    attempt = 0
    for attempt in range(40):
        if attempt and time.monotonic() > deadline:
            break
        pseed = int(hashlib.sha256(f"{golden.family}:{golden.seed}:{seed}:{attempt}".encode()).hexdigest()[:8], 16)
        gap = (1.0, 1.0, 0.8, 1.2, 0.6)[attempt % 5]
        # KiCad orders footprints by UUID when saving: seed the UUID generator.
        pcbnew.KIID.SeedGenerator(pseed)
        try:
            placement = place(golden, pseed, gap=gap)
            board = new_board(golden)
            netcodes = add_footprints(board, golden, placement)
            router = route_board(board, golden, netcodes, pitch, deadline=deadline)
        except BuildError as e:
            errors.append(f"attempt {attempt}: {e}")
            continue
        add_copper(board, router)
        with tempfile.TemporaryDirectory(prefix="pcbbuild_") as td:
            tmp = os.path.join(td, "board.kicad_pcb")
            if not pcbnew.SaveBoard(tmp, board, True):
                raise BuildError("SaveBoard failed")
            canonicalize_uuids(tmp, f"{golden.family}:{golden.seed}:{seed}")
            res = drc.run_drc(tmp)
            if res.errors or res.unconnected:
                errors.append(f"attempt {attempt}: DRC {len(res.errors)} errors "
                              f"{[e['type'] for e in res.errors][:5]}, {res.unconnected} unconnected")
                continue
            # UUIDs handed out above depend on the process history (library footprint loads draw
            # from the generator, cached loads do not), and KiCad saves in UUID order: make the
            # file depend only on (golden, seed). Same salt as the task generator's pass, which
            # is idempotent on top of this one.
            canonical_board_file(tmp, f"{golden.family}:{golden.seed}:{seed}")
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            shutil.copyfile(tmp, out_path)
        return {"attempts": attempt + 1, "seconds": time.monotonic() - t0,
                "tracks": len(router.segs), "vias": len(router.vias), "log": errors}
    raise BuildError(f"build failed for {golden.family}/{golden.seed} seed {seed}: " + "; ".join(errors[-5:]))
