"""Neutral public net names (RT34).

Faults keep the golden net names in the public files, and a golden name often says where a pin
belongs (`U1.FB` floating while a net `FB` exists). Before a task is published, every net whose
name is not referenced in the public text (TASK.md, spec.json) is renamed, in design.json and on
the board, to a KiCad-style auto name built from the net's own public pins: the first pin in
(ref, pad) order gives `Net-(R3-Pad2)`. The name therefore carries no information beyond the
public connectivity itself. Nets left without pins are dropped from design.json. Graders compare
partitions, never names, so grading is unaffected. Deterministic.
"""
from __future__ import annotations

import re

from pcbenv.parts import PARTS


def _natural(ref: str) -> tuple:
    m = re.match(r"([A-Za-z]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def referenced(name: str, texts: list[str]) -> bool:
    """`name` appears as a token in one of `texts` (not as part of a longer word or a REF.PIN)."""
    if not name:
        return False
    pat = re.compile(r"(?<![A-Za-z0-9_.+\-])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    return any(pat.search(t) for t in texts)


def auto_name(design: dict, pins: list[str]) -> str:
    def key(p: str) -> tuple:
        ref, pin = p.split(".", 1)
        part = PARTS.get(design["components"].get(ref, {}).get("part", ""))
        pad = part.pins[pin].pad if part is not None and pin in part.pins else pin
        return _natural(ref) + (int(pad) if pad.isdigit() else 0, pad)
    first = min(pins, key=key)
    ref, pin = first.split(".", 1)
    part = PARTS.get(design["components"].get(ref, {}).get("part", ""))
    pad = part.pins[pin].pad if part is not None and pin in part.pins else pin
    return f"Net-({ref}-Pad{pad})"


def rename_map(design: dict, board_nets: dict[str, list[str]], texts: list[str]) -> dict[str, str]:
    """old -> new name for every net (design or board) not referenced in `texts`.
    `board_nets`: board net name -> its pins (REF.PIN), used for nets missing from design.json."""
    out: dict[str, str] = {}
    taken = set()
    names = sorted(set(design["nets"]) | set(board_nets))
    keep = {n for n in names if referenced(n, texts)}
    taken |= keep
    for n in names:
        if n in keep:
            continue
        pins = design["nets"].get(n) or board_nets.get(n) or []
        if not pins:
            continue
        new = auto_name(design, pins)
        k = 1
        base = new
        while new in taken:
            k += 1
            new = f"{base}-{k}"
        taken.add(new)
        if new != n:
            out[n] = new
    return out


def apply_to_design(design: dict, renames: dict[str, str]) -> dict:
    nets = {}
    for n, pins in design["nets"].items():
        if not pins:
            continue  # an empty net only carries a (possibly golden) name
        nets[renames.get(n, n)] = pins
    out = dict(design)
    out["nets"] = dict(sorted(nets.items()))
    return out


def apply_to_board(board_path: str, renames: dict[str, str], salt: str) -> None:
    """Rename nets on the board file in place (then canonical UUIDs / ordering)."""
    import pcbnew

    from pcbenv.faults.common import canonical_board_file
    b = pcbnew.LoadBoard(board_path)
    for old, new in sorted(renames.items()):
        ni = b.FindNet(old)
        if ni is not None and ni.GetNetCode() > 0:
            ni.SetNetname(new)
    pcbnew.SaveBoard(board_path, b, True)
    canonical_board_file(board_path, salt)


def neutralise_public(task_dir: str, design_parts: dict | None = None, salt: str = "") -> dict[str, str]:
    """Rename unreferenced nets in `task_dir/public/{design.json, board.kicad_pcb}`; returns the map."""
    import json
    import os

    from pcbenv import boardnet
    from pcbenv import design as D
    pub = os.path.join(task_dir, "public")
    design = json.load(open(os.path.join(pub, "design.json"), encoding="utf-8"))
    texts = []
    for f in ("TASK.md", "spec.json"):
        p = os.path.join(pub, f)
        if os.path.exists(p):
            texts.append(open(p, encoding="utf-8").read())
    bpath = os.path.join(pub, "board.kicad_pcb")
    parts = design_parts or {r: c["part"] for r, c in design["components"].items()}
    info = boardnet.board_info(bpath, parts=parts)
    board_nets = {n: sorted(ps) for n, ps in info.net_pins.items()}
    renames = rename_map(design, board_nets, texts)
    D.save(apply_to_design(design, renames), os.path.join(pub, "design.json"))
    # RT70: ALWAYS re-save + re-canonicalise with the public salt, even with nothing to rename, so no
    # public board byte (UUIDs) derives from the fault pipeline's seed-bearing salt
    apply_to_board(bpath, renames, salt or "netnames")
    return renames
