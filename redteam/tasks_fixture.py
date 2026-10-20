"""Faulted tasks for red-team runs, built with pcbenv.taskio (independent of pcbenv/faults*.py).

Fault kinds (each applied to design.json AND the board so the public files stay consistent):
- `value`:   a value-required part's value scaled by 10x (spec fault, DRC/ERC-invisible)
- `pinswap`: two pins of one non-symmetric part exchanged (topology fault)
- `track`:   one track segment deleted (DRC unconnected fault)
Deterministic in (family, seed, kind).
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from pathlib import Path

import pcbnew

from pcbenv import boardnet, taskio
from pcbenv.board import build_board
from pcbenv.families import FAMILIES
from pcbenv.layout import SYMMETRIC_PARTS
from pcbenv.parts import PARTS, format_value, parse_value

KINDS = ("value", "pinswap", "track")
ROOT = Path(__file__).resolve().parent / "_tasks"


def _value_fault(design: dict, board, rng: random.Random) -> dict:
    refs = sorted(r for r, c in design["components"].items() if PARTS[c["part"]].value_required)
    ref = rng.choice(refs)
    new = format_value(parse_value(design["components"][ref]["value"]) * 10)
    design["components"][ref]["value"] = new
    board.FindFootprintByReference(ref).SetValue(new)
    return {"type": "value", "detail": f"{ref} -> {new}"}


def _pinswap_fault(design: dict, board, rng: random.Random) -> dict:
    cands = []
    for ref, c in sorted(design["components"].items()):
        if c["part"] in SYMMETRIC_PARTS:
            continue
        idx = {p: n for n, pins in design["nets"].items() for p in pins}
        pins = [f"{ref}.{p}" for p in PARTS[c["part"]].pins]
        for i in range(len(pins)):
            for j in range(i + 1, len(pins)):
                if idx.get(pins[i]) and idx.get(pins[j]) and idx[pins[i]] != idx[pins[j]]:
                    cands.append((pins[i], pins[j]))
    a, b = rng.choice(cands)
    na = next(n for n, ps in design["nets"].items() if a in ps)
    nb = next(n for n, ps in design["nets"].items() if b in ps)
    design["nets"][na] = [b if p == a else p for p in design["nets"][na]]
    design["nets"][nb] = [a if p == b else p for p in design["nets"][nb]]
    ref = a.split(".")[0]
    part = PARTS[design["components"][ref]["part"]]
    fp = board.FindFootprintByReference(ref)
    pa, pb = part.pins[a.split(".", 1)[1]].pad, part.pins[b.split(".", 1)[1]].pad
    pads = {p.GetNumber(): p for p in fp.Pads()}
    ca, cb = pads[pa].GetNetCode(), pads[pb].GetNetCode()
    pads[pa].SetNetCode(cb)
    pads[pb].SetNetCode(ca)
    return {"type": "pinswap", "detail": f"{a} <-> {b}"}


def _track_fault(design: dict, board, rng: random.Random) -> dict:
    tracks = sorted((t for t in board.GetTracks() if t.GetClass() != "PCB_VIA"),
                    key=lambda t: (t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y))
    t = rng.choice(tracks)
    net = t.GetNetname()
    board.Delete(t)
    return {"type": "track", "detail": f"deleted a segment of {net}"}


_FAULTS = {"value": _value_fault, "pinswap": _pinswap_fault, "track": _track_fault}


def build(family: str, seed: int, kind: str, root: Path = ROOT) -> str:
    """Faulted task dir (cached on disk)."""
    td = root / f"{family}_{seed}_{kind}"
    if (td / "hidden" / "meta.json").exists():
        return str(td)
    g = FAMILIES[family].generate(seed)
    rng = random.Random(f"{family}/{seed}/{kind}")
    with tempfile.TemporaryDirectory(prefix="rt_task_") as tmp:
        gb = os.path.join(tmp, "golden.kicad_pcb")
        build_board(g, gb, 0)
        design = json.loads(json.dumps(g.design))
        board = boardnet.load_board(gb)
        fault = _FAULTS[kind](design, board, rng)
        pb = os.path.join(tmp, "public.kicad_pcb")
        assert pcbnew.SaveBoard(pb, board, True)
        taskio.write_task(td, g, gb, public_design=design, public_board=pb, faults=[fault])
    return str(td)


def all_specs(seeds: range = range(1, 3)) -> list[tuple[str, int, str]]:
    # round-1 fixture = the v1 families (composite sys_* boards are covered by --source v2 / shipped)
    from pcbenv.families import V1_FAMILIES
    return [(f, s, k) for f in sorted(V1_FAMILIES) for s in seeds for k in KINDS]


if __name__ == "__main__":
    for spec in all_specs():
        print(build(*spec))
