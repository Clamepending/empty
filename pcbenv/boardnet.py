"""Extract netlist / identity facts from a KiCad 7 board (`board_info`).

Pin naming: a `.kicad_pcb` does not know which *part* (in `pcbenv.parts`) a footprint
implements, only its pad numbers. Callers pass `design` (a design dict) or `parts`
(`{ref: part name}`) to map pad numbers back to pin names via the part's pad map:
- known part, pad in its map  -> `REF.PINNAME`
- known part, pad not in map  -> `REF.#PADNUM` (can never equal a design pin)
- ref not in the map / no map -> `REF.PADNUM` (pin name := pad number)

Fingerprints are sha256 hex digests (first 16 chars) of a canonical repr.
`pad_fingerprint` covers, per footprint, every pad's number, attribute, shape, size,
position/orientation relative to the footprint, drill, offset, round-rect/chamfer params,
copper/mask/paste layer set, local clearance/mask/paste overrides, custom primitives, plus
footprint-level attributes, local clearance overrides, net-tie groups and courtyard
geometry. It is invariant to footprint position, rotation and side (flip).
"""
from __future__ import annotations

import functools
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field

import pcbnew

from pcbenv.parts import FOOTPRINT_ROOT, PARTS

MM = 1_000_000


@dataclass
class BoardInfo:
    partition: frozenset
    footprints: dict[str, str]
    values: dict[str, str]
    positions: dict[str, tuple[float, float, float]]
    sides: dict[str, str]                      # ref -> "F" | "B"
    pad_fingerprint: dict[str, str]
    outline_fingerprint: str
    track_widths: dict[str, float]
    net_pins: dict[str, set[str]]
    zone_count: int
    marker_count: int
    exclusion_count: int
    via_count: int = 0
    track_count: int = 0
    duplicate_refs: list[str] = field(default_factory=list)


def _h(obj) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()[:16]


def _um(v: int) -> int:
    return int(round(v / 1000.0))


def load_board(path: str) -> "pcbnew.BOARD":
    """Load a board from an isolated temp copy (no sibling .kicad_pro/.kicad_dru)."""
    with tempfile.TemporaryDirectory(prefix="pcbinfo_") as td:
        dst = os.path.join(td, "board.kicad_pcb")
        shutil.copyfile(path, dst)
        return pcbnew.LoadBoard(dst)


def _as_board(board) -> "pcbnew.BOARD":
    return load_board(board) if isinstance(board, (str, os.PathLike)) else board


def _part_map(design: dict | None, parts: dict[str, str] | None) -> dict[str, str]:
    if parts is not None:
        return dict(parts)
    if design is not None:
        return {ref: c["part"] for ref, c in design["components"].items()}
    return {}


def pin_name(ref: str, padnum: str, part_map: dict[str, str]) -> str:
    part = PARTS.get(part_map.get(ref, ""))
    if part is None:
        return f"{ref}.{padnum}"
    names = sorted(p for p, info in part.pins.items() if info.pad == padnum)
    return f"{ref}.{names[0]}" if names else f"{ref}.#{padnum}"


# ------------------------------------------------------------------ fingerprints
def _shape_repr(s) -> tuple:
    t = s.GetShape()
    pts = []
    if t == pcbnew.SHAPE_T_POLY:
        poly = s.GetPolyShape()
        for oi in range(poly.OutlineCount()):
            o = poly.Outline(oi)
            pts.append(tuple((_um(o.CPoint(i).x), _um(o.CPoint(i).y)) for i in range(o.PointCount())))
    elif t == pcbnew.SHAPE_T_ARC:
        pts.append((_um(s.GetArcMid().x), _um(s.GetArcMid().y)))
    elif t == pcbnew.SHAPE_T_BEZIER:
        pts.append((_um(s.GetBezierC1().x), _um(s.GetBezierC1().y), _um(s.GetBezierC2().x), _um(s.GetBezierC2().y)))
    return (int(t), _um(s.GetStart().x), _um(s.GetStart().y), _um(s.GetEnd().x), _um(s.GetEnd().y),
            _um(s.GetWidth()), bool(s.IsFilled()), tuple(pts))


def _pad_repr(p: "pcbnew.PAD") -> tuple:
    pos = p.GetPosition()
    prims = []
    if p.GetShape() == pcbnew.PAD_SHAPE_CUSTOM:
        prims = sorted(_shape_repr(pr) for pr in p.GetPrimitives())
    return (
        p.GetNumber(), int(p.GetAttribute()), int(p.GetShape()),
        _um(p.GetSize().x), _um(p.GetSize().y), _um(pos.x), _um(pos.y),
        round(p.GetOrientationDegrees() % 360.0, 2),
        _um(p.GetDrillSize().x), _um(p.GetDrillSize().y), int(p.GetDrillShape()),
        _um(p.GetOffset().x), _um(p.GetOffset().y),
        _um(p.GetDelta().x), _um(p.GetDelta().y),
        round(p.GetRoundRectRadiusRatio(), 4), round(p.GetChamferRectRatio(), 4), int(p.GetChamferPositions()),
        p.GetLayerSet().FmtHex(),
        _um(p.GetLocalClearance()), _um(p.GetLocalSolderMaskMargin()), _um(p.GetLocalSolderPasteMargin()),
        round(p.GetLocalSolderPasteMarginRatio(), 4), int(p.GetZoneConnection()),
        int(p.GetProperty()), int(p.GetAnchorPadShape()), tuple(prims),
    )


def footprint_fingerprint(fp: "pcbnew.FOOTPRINT") -> str:
    c = pcbnew.FOOTPRINT(fp)  # copy; normalise side, rotation and position
    if c.IsFlipped():
        c.Flip(c.GetPosition(), False)
    c.SetOrientationDegrees(0)
    c.SetPosition(pcbnew.VECTOR2I(0, 0))
    pads = sorted(_pad_repr(p) for p in c.Pads())
    crt = sorted(_shape_repr(g) for g in c.GraphicalItems()
                 if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd) and isinstance(g, pcbnew.PCB_SHAPE))
    try:
        ties = sorted(str(t) for t in c.GetNetTiePadGroups())
    except Exception:  # pragma: no cover
        ties = []
    fpl = (int(c.GetAttributes()), _um(c.GetLocalClearance()), _um(c.GetLocalSolderMaskMargin()),
           _um(c.GetLocalSolderPasteMargin()), round(c.GetLocalSolderPasteMarginRatio(), 4),
           int(c.GetZoneConnection()), bool(c.AllowMissingCourtyard()), tuple(ties))
    return _h((pads, crt, fpl))


@functools.lru_cache(maxsize=None)
def library_pad_fingerprint(fpid: str) -> str | None:
    """Fingerprint of the pristine library footprint "Lib:Name" (None if not found)."""
    if ":" not in fpid:
        return None
    lib, name = fpid.split(":", 1)
    path = os.path.join(FOOTPRINT_ROOT, lib + ".pretty")
    if not os.path.isfile(os.path.join(path, name + ".kicad_mod")):
        return None
    fp = pcbnew.FootprintLoad(path, name)
    return footprint_fingerprint(fp) if fp is not None else None


def outline_fingerprint(board: "pcbnew.BOARD") -> str:
    items = [_shape_repr(d) for d in board.GetDrawings()
             if d.GetLayer() == pcbnew.Edge_Cuts and isinstance(d, pcbnew.PCB_SHAPE)]
    for fp in board.GetFootprints():
        for g in fp.GraphicalItems():
            if g.GetLayer() == pcbnew.Edge_Cuts and isinstance(g, pcbnew.PCB_SHAPE):
                items.append(("fp",) + _shape_repr(g))
    return _h(sorted(items))


# ---------------------------------------------------------------------- info
def board_info(board, design: dict | None = None, parts: dict[str, str] | None = None) -> BoardInfo:
    """Facts about a board (path or BOARD). See module docstring for pin naming."""
    b = _as_board(board)
    pm = _part_map(design, parts)
    footprints, values, positions, sides, fps = {}, {}, {}, {}, {}
    net_pins: dict[str, set[str]] = {}
    seen: set[str] = set()
    dups: list[str] = []
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        if ref in seen:
            dups.append(ref)
        seen.add(ref)
        footprints[ref] = str(fp.GetFPID().GetUniStringLibId())
        values[ref] = fp.GetValue()
        pos = fp.GetPosition()
        positions[ref] = (round(pos.x / MM, 4), round(pos.y / MM, 4), round(fp.GetOrientationDegrees() % 360.0, 3))
        sides[ref] = "B" if fp.IsFlipped() else "F"
        fps[ref] = footprint_fingerprint(fp)
        for pad in fp.Pads():
            if pad.GetNetCode() <= 0:
                continue
            net_pins.setdefault(pad.GetNetname(), set()).add(pin_name(ref, pad.GetNumber(), pm))
    widths: dict[str, float] = {}
    vias = tracks = 0
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias += 1
            continue
        tracks += 1
        n = t.GetNetname()
        w = t.GetWidth() / MM
        widths[n] = min(widths.get(n, w), w)
    zones = b.GetAreaCount() + sum(len(fp.Zones()) for fp in b.GetFootprints())
    try:
        excl = len(b.GetDesignSettings().m_DrcExclusions)
    except Exception:  # pragma: no cover
        excl = 0
    return BoardInfo(
        partition=frozenset(frozenset(p) for p in net_pins.values() if p),
        footprints=footprints, values=values, positions=positions, sides=sides,
        pad_fingerprint=fps, outline_fingerprint=outline_fingerprint(b),
        track_widths=widths, net_pins=net_pins, zone_count=zones,
        marker_count=len(b.Markers()), exclusion_count=excl,
        via_count=vias, track_count=tracks, duplicate_refs=sorted(dups),
    )


def board_partition(board, design: dict | None = None, parts: dict[str, str] | None = None) -> frozenset:
    return board_info(board, design, parts).partition


def pad_position(board, ref: str, pin: str, design: dict | None = None,
                 parts: dict[str, str] | None = None) -> tuple[float, float] | None:
    """Absolute (x, y) mm of the pad implementing REF.PIN (first pad if several)."""
    b = _as_board(board)
    pm = _part_map(design, parts)
    part = PARTS.get(pm.get(ref, ""))
    padnum = part.pins[pin].pad if part is not None and pin in part.pins else pin
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        return None
    pads = sorted((p for p in fp.Pads() if p.GetNumber() == padnum),
                  key=lambda p: (p.GetPosition().x, p.GetPosition().y))
    if not pads:
        return None
    pos = pads[0].GetPosition()
    return (pos.x / MM, pos.y / MM)
