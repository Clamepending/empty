"""Shared helpers for fault injectors: design edits, board loading/saving, re-routing, checks.

Board edits are deterministic: the KiCad UUID generator is seeded before every edit and all
UUIDs are canonicalised after saving (same as `board.build_board`), so the same
(golden, rng seed) always gives a byte-identical faulted board.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field

import pcbnew

from pcbenv import boardnet, drc, erc, sim
from pcbenv import design as D
from pcbenv.board import canonical_board_file, canonicalize_uuids, design_pad_nets  # noqa: F401 (re-export)
from pcbenv.golden import Golden
from pcbenv.layout import SYMMETRIC_PARTS, same_topology
from pcbenv.parts import PARTS, parse_value

MM = 1_000_000
DEFAULT_WIDTH = drc.RULES["default_track_width"]


class NotApplicable(Exception):
    """Raised inside an injector when the chosen candidate cannot be realised."""


@dataclass
class FaultRecord:
    type: str
    category: str                 # value | connectivity | board
    detail: str                   # one human-readable line (hidden; never shown to the agent)
    invisible_to_drc_erc: bool    # this fault alone leaves DRC and ERC clean
    targets: list[str]            # refs and "net:NAME" touched (used to keep faults disjoint)
    data: dict = field(default_factory=dict)  # machine-readable parameters (refs, pins, values)

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> str:
        """Canonical identity of the fault (for dedupe)."""
        return json.dumps({"type": self.type, "detail": self.detail}, sort_keys=True)


# ------------------------------------------------------------------ design helpers
def net_of(design: dict, pin: str) -> str | None:
    return D.net_of(design, pin)


def remove_pin(design: dict, pin: str) -> None:
    for name in list(design["nets"]):
        if pin in design["nets"][name]:
            design["nets"][name] = [p for p in design["nets"][name] if p != pin]
            if not design["nets"][name]:
                del design["nets"][name]


def move_pin(design: dict, pin: str, net: str | None) -> None:
    remove_pin(design, pin)
    if net is not None:
        design["nets"].setdefault(net, []).append(pin)
        design["nets"][net] = sorted(design["nets"][net])


def swap_pins(design: dict, a: str, b: str) -> None:
    na, nb = net_of(design, a), net_of(design, b)
    remove_pin(design, a)
    remove_pin(design, b)
    if nb is not None:
        design["nets"].setdefault(nb, []).append(a)
        design["nets"][nb] = sorted(design["nets"][nb])
    if na is not None:
        design["nets"].setdefault(na, []).append(b)
        design["nets"][na] = sorted(design["nets"][na])


def part_of(design: dict, ref: str) -> str:
    return design["components"][ref]["part"]


def ref_parts(design: dict) -> dict[str, str]:
    return {r: c["part"] for r, c in design["components"].items()}


def topology_differs(design: dict, golden: Golden) -> bool:
    return not same_topology(D.partition(design), D.partition(golden.design), ref_parts(golden.design))


def spec_fails(design: dict, golden: Golden) -> bool:
    return not all(r.passed for r in sim.run_assertions(design, golden.assertions))


def out_of_bounds(design: dict, golden: Golden) -> list[str]:
    """Refs whose value lies outside the golden's `value_bounds` (empty if the golden has none)."""
    vb = getattr(golden, "value_bounds", None) or {}
    out = []
    for ref, (lo, hi) in sorted(vb.items()):
        c = design["components"].get(ref)
        if not c or not c.get("value"):
            continue
        try:
            v = parse_value(c["value"])
        except ValueError:
            out.append(ref)
            continue
        if not lo * (1 - 1e-9) <= v <= hi * (1 + 1e-9):
            out.append(ref)
    return out


def value_detectable(design: dict, golden: Golden) -> bool:
    """A value change is gradeable: it breaks a spec assertion or leaves the published bounds."""
    return bool(out_of_bounds(design, golden)) or spec_fails(design, golden)


def erc_codes(design: dict) -> list[str]:
    return sorted(i.code for i in erc.errors(erc.run_erc(design)))


def rails(design: dict) -> tuple[str | None, str | None]:
    """(net of J1.1, net of J1.2): the input supply/signal net and ground (board convention)."""
    return net_of(design, "J1.1"), net_of(design, "J1.2")


def free(exclude: set[str], *items: str) -> bool:
    return not (set(items) & exclude)


def nets_target(*nets: str | None) -> list[str]:
    return [f"net:{n}" for n in nets if n]


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def design_hash(design: dict) -> str:
    return stable_hash(design)[:16]


# ------------------------------------------------------------------ board helpers
def load_board(path: str) -> "pcbnew.BOARD":
    b = boardnet.load_board(path)
    if b is None:
        raise NotApplicable(f"cannot load {path}")
    return b


def save_board(board: "pcbnew.BOARD", path: str, salt: str) -> None:
    tmp = path + ".tmp.kicad_pcb"
    if not pcbnew.SaveBoard(tmp, board, True):
        raise RuntimeError("SaveBoard failed")
    canonical_board_file(tmp, salt)
    os.replace(tmp, path)
    for ext in (".kicad_pro", ".kicad_prl"):
        p = tmp[: -len(".kicad_pcb")] + ext
        if os.path.exists(p):
            os.remove(p)


def seed_kiid(salt: str) -> None:
    pcbnew.KIID.SeedGenerator(int(hashlib.sha256(salt.encode()).hexdigest()[:8], 16))


def tracks_of(board, net: str) -> list:
    return [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net]


def pads_of_net(board, net: str) -> list:
    return [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode() > 0 and p.GetNetname() == net]


def net_width(golden: Golden, net: str) -> float:
    return max(golden.power_nets.get(net, DEFAULT_WIDTH), drc.RULES["track_min"])


def unroute(board, net: str) -> int:
    from pcbenv.tool import _unroute
    return _unroute(board, net)


def _span(board, net: str) -> float:
    ps = [p.GetPosition() for p in pads_of_net(board, net)]
    if len(ps) < 2:
        return 0.0
    return (max(p.x for p in ps) - min(p.x for p in ps) + max(p.y for p in ps) - min(p.y for p in ps)) / MM


def reroute(board, golden: Golden, nets: list[str], tries: int = 4) -> None:
    """Rip up `nets` and route them again among all other copper (KiCad board, in place).

    Tries a few net orders (failing net first). Raises NotApplicable when routing fails."""
    from pcbenv.tool import ToolError, route_net
    nets = sorted({n for n in nets if n and board.FindNet(n) is not None and board.FindNet(n).GetNetCode() > 0})
    order = sorted(nets, key=lambda n: (_span(board, n), n))
    last = ""
    for _ in range(tries):
        for n in nets:
            unroute(board, n)
        failed = None
        for n in order:
            if len(pads_of_net(board, n)) < 2:
                continue
            try:
                route_net(board, n, net_width(golden, n))
            except ToolError as e:
                failed, last = n, str(e)
                break
        if failed is None:
            return
        order = [failed] + [n for n in order if n != failed]
    raise NotApplicable(f"re-route failed: {last}")


def set_pad_nets(board, padnets: dict[str, dict[str, str]]) -> set[str]:
    """Make the board's pad nets equal `padnets` ({ref: {pad: net}}). Returns affected nets."""
    from pcbenv.tool import _net
    affected: set[str] = set()
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        want_map = padnets.get(ref, {})
        for pad in fp.Pads():
            want = want_map.get(pad.GetNumber())
            have = pad.GetNetname() if pad.GetNetCode() > 0 else None
            if want == have:
                continue
            affected |= {n for n in (want, have) if n}
            if want is None:
                pad.SetNetCode(0)
            else:
                pad.SetNet(_net(board, want))
    return affected


def drc_result(board_path: str) -> drc.DrcResult:
    return drc.run_drc(board_path)


def drc_clean(board_path: str) -> bool:
    return drc_result(board_path).clean


def rewire(golden: Golden, board_path: str, padnets: dict[str, dict[str, str]], salt: str,
           require_clean: bool = True) -> list[str]:
    """Set the board's pad nets to `padnets`, re-route the affected nets, save.

    Raises NotApplicable when routing fails or the result has more DRC errors / unconnected
    items than before (i.e. it is DRC clean when the input was)."""
    before = drc_result(board_path) if require_clean else None
    board = load_board(board_path)
    seed_kiid(salt)
    affected = set_pad_nets(board, padnets)
    if not affected:
        raise NotApplicable("no pad changes")
    reroute(board, golden, sorted(affected))
    with tempfile.TemporaryDirectory(prefix="pcbfault_") as td:
        tmp = os.path.join(td, "board.kicad_pcb")
        save_board(board, tmp, salt)
        if before is not None:
            after = drc_result(tmp)
            if len(after.errors) > len(before.errors) or after.unconnected > before.unconnected:
                raise NotApplicable("re-routed board has new DRC errors")
        shutil.copyfile(tmp, board_path)
    return sorted(affected)


def mirror_design(golden: Golden, design: dict, board_path: str, salt: str) -> list[str]:
    """Make the board follow `design` (pad nets + routing). Returns re-routed nets."""
    return rewire(golden, board_path, design_pad_nets(design), salt)


def set_board_values(board_path: str, values: dict[str, str], salt: str) -> None:
    board = load_board(board_path)
    seed_kiid(salt)
    for ref, v in values.items():
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise NotApplicable(f"{ref} not on board")
        fp.SetValue(v)
    save_board(board, board_path, salt)


def is_symmetric(part: str) -> bool:
    return part in SYMMETRIC_PARTS


def pad_xy(pad) -> tuple[float, float]:
    p = pad.GetPosition()
    return p.x / MM, p.y / MM


def seg_tuple(t) -> tuple[int, float, float, float, float, float]:
    s, e = t.GetStart(), t.GetEnd()
    layer = 0 if t.GetLayer() == pcbnew.F_Cu else 1
    return layer, s.x / MM, s.y / MM, e.x / MM, e.y / MM, t.GetWidth() / MM


def closest_on_seg(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    vx, vy = x2 - x1, y2 - y1
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / L2))
    return x1 + t * vx, y1 + t * vy


def add_track(board, net: str, layer: int, x1: float, y1: float, x2: float, y2: float, w: float) -> None:
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(int(round(x1 * MM)), int(round(y1 * MM))))
    t.SetEnd(pcbnew.VECTOR2I(int(round(x2 * MM)), int(round(y2 * MM))))
    t.SetWidth(int(round(w * MM)))
    t.SetLayer(pcbnew.F_Cu if layer == 0 else pcbnew.B_Cu)
    t.SetNet(board.FindNet(net))
    board.Add(t)


def copy_design(d: dict) -> dict:
    return copy.deepcopy(d)


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def valued_refs(design: dict) -> list[str]:
    return sorted(r for r, c in design["components"].items() if PARTS[c["part"]].value_required)
