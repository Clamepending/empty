"""Grid-based 2-layer maze router (A* with vias), pure Python + numpy.

Model
-----
- Uniform grid of `pitch` mm over the board rectangle; layer 0 = F.Cu, layer 1 = B.Cu.
  Moves: 8-neighbour on a layer (cost 1 / sqrt2 per cell) and a via (cost `via_cost` mm).
- Obstacles are exact shapes (rotated round-rects for pads, capsules for tracks, circles
  for vias/holes). For each net, a cell is blocked for the track *centreline* if it lies
  within `w/2 + clearance + margin` of copper of another net (or of the board edge minus
  `edge_clearance`). `margin` (~0.3 * pitch) absorbs the fact that a straight/diagonal
  step between two free cell centres can pass slightly closer to a convex obstacle than
  either endpoint.
- A cell may hold a via if the via copper (diameter `via_d`) clears other nets' copper on
  both layers, its hole clears every other hole by `hole_to_hole`, it is not inside/near
  any pad, and it clears the edge.
- A multi-pin net is routed as a tree: start from one pad, repeatedly A* from all tree cells
  to the nearest unconnected pad (target = grid cells strictly inside that pad's copper,
  on the pad's layers), add the path to the tree. Track ends therefore always lie inside
  pads or on other track vertices of the same net (segments are split at every junction),
  which is what KiCad's connectivity needs.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

SQRT2 = math.sqrt(2.0)


@dataclass
class PadGeom:
    net: int
    x: float
    y: float
    angle: float          # degrees, KiCad convention (counter-clockwise, y down)
    hx: float             # half size along local x
    hy: float
    rr: float             # corner radius (0 = sharp rect; min(hx,hy) = oval/circle)
    layers: tuple[bool, bool]
    hole_r: float = 0.0   # drill radius (0 = SMD)
    key: str = ""         # "REF.PADNUM" for diagnostics


@dataclass
class Seg:
    net: int
    layer: int
    x1: float
    y1: float
    x2: float
    y2: float
    w: float


@dataclass
class Via:
    net: int
    x: float
    y: float
    d: float
    drill: float


@dataclass
class Rules:
    clearance: float = 0.2
    edge_clearance: float = 0.3
    hole_clearance: float = 0.25
    hole_to_hole: float = 0.25
    via_d: float = 0.6
    via_drill: float = 0.3


@dataclass
class NetResult:
    segs: list[Seg] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)


class RouteError(RuntimeError):
    def __init__(self, net: int, msg: str):
        super().__init__(msg)
        self.net = net


class Router:
    def __init__(self, x0: float, y0: float, w: float, h: float, pitch: float = 0.1,
                 rules: Rules | None = None, via_cost: float = 1.5, turn_penalty: float = 0.6):
        self.x0, self.y0, self.bw, self.bh = x0, y0, w, h
        self.p = pitch
        self.rules = rules or Rules()
        self.margin = 0.3 * pitch + 0.01
        self.W = int(math.floor(w / pitch)) + 1
        self.H = int(math.floor(h / pitch)) + 1
        self.NN = self.W * self.H
        self.via_cost = via_cost / pitch  # in cell units
        self.turn_penalty = turn_penalty
        self.xs = x0 + np.arange(self.W) * pitch
        self.ys = y0 + np.arange(self.H) * pitch
        self.pads: list[PadGeom] = []
        self.segs: list[Seg] = []
        self.vias: list[Via] = []

    # ---------------------------------------------------------------- geometry
    def _window(self, cx: float, cy: float, r: float):
        p = self.p
        i0 = max(0, int(math.floor((cx - r - self.x0) / p)))
        i1 = min(self.W - 1, int(math.ceil((cx + r - self.x0) / p)))
        j0 = max(0, int(math.floor((cy - r - self.y0) / p)))
        j1 = min(self.H - 1, int(math.ceil((cy + r - self.y0) / p)))
        if i0 > i1 or j0 > j1:
            return None
        X, Y = np.meshgrid(self.xs[i0:i1 + 1], self.ys[j0:j1 + 1])
        return (j0, j1 + 1, i0, i1 + 1), X, Y

    @staticmethod
    def pad_dist(pad: PadGeom, X, Y):
        """Signed distance from points to the pad's copper outline (negative inside)."""
        a = math.radians(pad.angle)
        c, s = math.cos(a), math.sin(a)
        dx, dy = X - pad.x, Y - pad.y
        # KiCad rotates counter-clockwise on screen with y pointing down.
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        rr = min(pad.rr, pad.hx, pad.hy)
        qx = np.abs(lx) - (pad.hx - rr)
        qy = np.abs(ly) - (pad.hy - rr)
        out = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
        ins = np.minimum(np.maximum(qx, qy), 0)
        return out + ins - rr

    @staticmethod
    def seg_dist(sg: Seg, X, Y):
        vx, vy = sg.x2 - sg.x1, sg.y2 - sg.y1
        L2 = vx * vx + vy * vy
        if L2 == 0:
            return np.hypot(X - sg.x1, Y - sg.y1) - sg.w / 2
        t = np.clip(((X - sg.x1) * vx + (Y - sg.y1) * vy) / L2, 0, 1)
        return np.hypot(X - (sg.x1 + t * vx), Y - (sg.y1 + t * vy)) - sg.w / 2

    def _pad_radius(self, pad: PadGeom) -> float:
        return math.hypot(pad.hx, pad.hy)

    def _mark(self, grid, obj_kind: str, obj, infl: float) -> None:
        if obj_kind == "pad":
            win = self._window(obj.x, obj.y, self._pad_radius(obj) + infl)
            if win is None:
                return
            sl, X, Y = win
            d = self.pad_dist(obj, X, Y)
        elif obj_kind == "seg":
            cx, cy = (obj.x1 + obj.x2) / 2, (obj.y1 + obj.y2) / 2
            r = math.hypot(obj.x2 - obj.x1, obj.y2 - obj.y1) / 2 + obj.w / 2
            win = self._window(cx, cy, r + infl)
            if win is None:
                return
            sl, X, Y = win
            d = self.seg_dist(obj, X, Y)
        else:  # circle: (x, y, r)
            x, y, r = obj
            win = self._window(x, y, r + infl)
            if win is None:
                return
            sl, X, Y = win
            d = np.hypot(X - x, Y - y) - r
        j0, j1, i0, i1 = sl
        grid[j0:j1, i0:i1] |= d < infl

    def _edge_mask(self, dist: float) -> np.ndarray:
        X, Y = np.meshgrid(self.xs, self.ys)
        d = np.minimum.reduce([X - self.x0, self.x0 + self.bw - X, Y - self.y0, self.y0 + self.bh - Y])
        return d < dist

    # ------------------------------------------------------------- obstacle maps
    def blocked_maps(self, net: int, w: float):
        r = self.rules
        m = self.margin
        lay = [self._edge_mask(r.edge_clearance + w / 2 + m) for _ in range(2)]
        infl = w / 2 + r.clearance + m
        for pad in self.pads:
            if pad.net == net and net != 0:
                continue
            for L in (0, 1):
                if pad.layers[L]:
                    self._mark(lay[L], "pad", pad, infl)
            if pad.hole_r > 0:
                for L in (0, 1):
                    self._mark(lay[L], "circ", (pad.x, pad.y, pad.hole_r), w / 2 + r.hole_clearance + m)
        for sg in self.segs:
            if sg.net != net:
                self._mark(lay[sg.layer], "seg", sg, infl)
        for v in self.vias:
            if v.net != net:
                for L in (0, 1):
                    self._mark(lay[L], "circ", (v.x, v.y, v.d / 2), infl)
        # vias
        vr = r.via_d / 2
        vb = self._edge_mask(r.edge_clearance + vr + m)
        vinfl = vr + r.clearance + m
        for pad in self.pads:
            # no vias in or near any pad (own net included: no via-in-pad)
            self._mark(vb, "pad", pad, vinfl)
            if pad.hole_r > 0:
                self._mark(vb, "circ", (pad.x, pad.y, pad.hole_r), r.via_drill / 2 + r.hole_to_hole + m)
        for sg in self.segs:
            if sg.net != net:
                self._mark(vb, "seg", sg, vinfl)
        for v in self.vias:
            self._mark(vb, "circ", (v.x, v.y, v.drill / 2), r.via_drill / 2 + r.hole_to_hole + m)
            if v.net != net:
                self._mark(vb, "circ", (v.x, v.y, v.d / 2), vinfl)
        return lay, vb

    def terminal_cells(self, pad: PadGeom, lay) -> list[int]:
        """Free cells whose centre is well inside the pad copper, on the pad's layers."""
        win = self._window(pad.x, pad.y, self._pad_radius(pad))
        out: list[int] = []
        if win is None:
            return out
        (j0, j1, i0, i1), X, Y = win
        d = self.pad_dist(pad, X, Y)
        inside = d < -min(0.05, 0.25 * min(pad.hx, pad.hy))
        for L in (0, 1):
            if not pad.layers[L]:
                continue
            ok = inside & ~lay[L][j0:j1, i0:i1]
            jj, ii = np.nonzero(ok)
            base = L * self.NN
            out.extend(int(base + (j0 + a) * self.W + (i0 + b)) for a, b in zip(jj, ii))
        return out

    # ------------------------------------------------------------------- search
    def astar(self, blocked: bytearray, via_ok: bytearray, sources: list[int],
              targets: set[int], tx: float, ty: float, max_expand: int = 400_000):
        W, H, NN = self.W, self.H, self.NN
        vc = self.via_cost
        gi = (tx - self.x0) / self.p
        gj = (ty - self.y0) / self.p
        g: dict[int, float] = {}
        came: dict[int, int] = {}
        heap: list = []
        for s in sources:
            if blocked[s]:
                continue
            g[s] = 0.0
            came[s] = -1
            r = s % NN
            dx, dy = abs(r % W - gi), abs(r // W - gj)
            h = max(dx, dy) + (SQRT2 - 1) * min(dx, dy)
            heapq.heappush(heap, (h, h, s))
        moves = ((1, 0, 1.0, 0), (-1, 0, 1.0, 1), (0, 1, 1.0, 2), (0, -1, 1.0, 3),
                 (1, 1, SQRT2, 4), (1, -1, SQRT2, 5), (-1, 1, SQRT2, 6), (-1, -1, SQRT2, 7))
        tp = self.turn_penalty
        dirs: dict[int, int] = {}
        closed = set()
        n = 0
        while heap:
            f, h0, cur = heapq.heappop(heap)
            if cur in closed:
                continue
            if cur in targets:
                path = [cur]
                while came[path[-1]] != -1:
                    path.append(came[path[-1]])
                path.reverse()
                return path
            closed.add(cur)
            n += 1
            if n > max_expand:
                return None
            gc = g[cur]
            L, r = divmod(cur, NN)
            y, x = divmod(r, W)
            cd = dirs.get(cur, -1)
            for ddx, ddy, c, k in moves:
                nx, ny = x + ddx, y + ddy
                if nx < 0 or ny < 0 or nx >= W or ny >= H:
                    continue
                if c > 1.0:
                    # no squeezing diagonally between two blocked orthogonal cells
                    if blocked[L * NN + y * W + nx] and blocked[L * NN + ny * W + x]:
                        continue
                nb = L * NN + ny * W + nx
                if blocked[nb] or nb in closed:
                    continue
                ng = gc + c
                if cd != k and cd >= 0:
                    ng += tp
                if ng < g.get(nb, 1e18):
                    g[nb] = ng
                    came[nb] = cur
                    dirs[nb] = k
                    dx, dy = abs(nx - gi), abs(ny - gj)
                    h = max(dx, dy) + (SQRT2 - 1) * min(dx, dy)
                    heapq.heappush(heap, (ng + h, h, nb))
            if via_ok[r]:
                nb = (1 - L) * NN + r
                if not blocked[nb] and nb not in closed:
                    ng = gc + vc
                    if ng < g.get(nb, 1e18):
                        g[nb] = ng
                        came[nb] = cur
                        dirs[nb] = -1
                        dx, dy = abs(x - gi), abs(y - gj)
                        h = max(dx, dy) + (SQRT2 - 1) * min(dx, dy)
                        heapq.heappush(heap, (ng + h, h, nb))
        return None

    # ------------------------------------------------------------------ routing
    def cell_xy(self, idx: int) -> tuple[int, float, float]:
        L, r = divmod(idx, self.NN)
        y, x = divmod(r, self.W)
        return L, self.x0 + x * self.p, self.y0 + y * self.p

    def route_net(self, net: int, pad_ids: list[int], w: float) -> NetResult:
        """Route one net connecting the pads `pad_ids` (indices into self.pads)."""
        if len(pad_ids) < 2:
            return NetResult()
        lay, vb = self.blocked_maps(net, w)
        blocked = bytearray(np.concatenate([lay[0].ravel(), lay[1].ravel()]).astype(np.uint8).tobytes())
        via_ok = bytearray((~vb).ravel().astype(np.uint8).tobytes())
        pads = [self.pads[i] for i in pad_ids]
        terms = []
        for pd in pads:
            t = self.terminal_cells(pd, lay)
            if not t:
                raise RouteError(net, f"pad {pd.key} has no free terminal cell")
            terms.append(t)
        # start with the pad closest to the centroid
        cx = sum(pd.x for pd in pads) / len(pads)
        cy = sum(pd.y for pd in pads) / len(pads)
        start = min(range(len(pads)), key=lambda k: (math.hypot(pads[k].x - cx, pads[k].y - cy), k))
        tree: list[int] = list(terms[start])
        tree_set = set(tree)
        connected = {start}
        paths: list[list[int]] = []
        while len(connected) < len(pads):
            # nearest unconnected pad (to any connected pad / tree vertex)
            pts = [(pads[k].x, pads[k].y) for k in connected]
            for pth in paths:
                for idx in (pth[0], pth[-1]):
                    _, px, py = self.cell_xy(idx)
                    pts.append((px, py))
            best = None
            for k in range(len(pads)):
                if k in connected:
                    continue
                d = min(math.hypot(pads[k].x - px, pads[k].y - py) for px, py in pts)
                if best is None or d < best[0]:
                    best = (d, k)
            k = best[1]
            tset = set(terms[k])
            hit = tset & tree_set
            if hit:  # pads overlap / already touched by the tree
                connected.add(k)
                continue
            path = self.astar(blocked, via_ok, tree, tset, pads[k].x, pads[k].y)
            if path is None:
                raise RouteError(net, f"no path to {pads[k].key}")
            paths.append(path)
            connected.add(k)
            for idx in path:
                if idx not in tree_set:
                    tree_set.add(idx)
                    tree.append(idx)
            for idx in terms[k]:
                if idx not in tree_set:
                    tree_set.add(idx)
                    tree.append(idx)
        res = self._emit(net, paths, w)
        self.segs.extend(res.segs)
        self.vias.extend(res.vias)
        return res

    def _emit(self, net: int, paths: list[list[int]], w: float) -> NetResult:
        NN = self.NN
        breaks: set[int] = set()
        via_cells: list[int] = []
        for pth in paths:
            breaks.add(pth[0])
            breaks.add(pth[-1])
            for a, b in zip(pth, pth[1:]):
                if a % NN == b % NN:  # layer change
                    breaks.add(a)
                    breaks.add(b)
                    if a % NN not in via_cells:
                        via_cells.append(a % NN)
        res = NetResult()
        r = self.rules
        for rc in via_cells:
            _, x, y = self.cell_xy(rc)
            res.vias.append(Via(net, round(x, 4), round(y, 4), r.via_d, r.via_drill))
        for pth in paths:
            run = [pth[0]]
            for a, b in zip(pth, pth[1:]):
                if a % NN == b % NN:
                    self._flush(net, run, w, res)
                    run = [b]
                    continue
                if len(run) >= 2:
                    d0 = self._dir(run[-2], run[-1])
                    if self._dir(a, b) != d0 or a in breaks:
                        self._flush(net, run, w, res)
                        run = [a]
                run.append(b)
            self._flush(net, run, w, res)
        return res

    def _dir(self, a: int, b: int) -> tuple[int, int]:
        ra, rb = a % self.NN, b % self.NN
        return (rb % self.W - ra % self.W, rb // self.W - ra // self.W)

    def _flush(self, net: int, run: list[int], w: float, res: NetResult) -> None:
        if len(run) < 2:
            return
        L, x1, y1 = self.cell_xy(run[0])
        _, x2, y2 = self.cell_xy(run[-1])
        res.segs.append(Seg(net, L, round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4), w))

    def rip_up(self, net: int) -> None:
        self.segs = [s for s in self.segs if s.net != net]
        self.vias = [v for v in self.vias if v.net != net]
