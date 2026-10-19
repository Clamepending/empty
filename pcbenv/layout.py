"""Layout checks against golden requirements (SPEC §7 check 9).

- Power nets: each golden power net (name -> required width) is identified on the candidate
  board by its *pin set* (`meta["power_net_pins"]`, never by name). The board net(s) whose
  pin set equals it -- modulo the pin order of symmetric two-terminal parts, see
  `pin_label` -- must have every track segment at least the required width
  (`BoardInfo.track_widths` is the min width over the net). A matched net with >= 2 pins and
  no tracks fails. No matching net fails (the topology/consistency gates also fail then).
- Decoupling: every pad of the cap within `max_mm` of the IC pin's pad centre
  (`boardnet.pad_position`, pads named through the golden ref->part map).
"""
from __future__ import annotations

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
    return issues
