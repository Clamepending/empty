"""Helpers for verifier / tool / harness tests: build golden tasks, copy workdirs, mutate files."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pcbnew

from pcbenv import boardnet
from pcbenv.families import FAMILIES
from pcbenv.taskio import make_golden_task

MM = 1_000_000


def build_task(root: str | os.PathLike, family: str, seed: int, board_seed: int = 0) -> str:
    """Golden task dir under `root` (built once, reused)."""
    td = Path(root) / f"{family}_{seed}_{board_seed}"
    if not (td / "hidden" / "meta.json").exists():
        make_golden_task(FAMILIES[family].generate(seed), td, board_seed)
    return str(td)


def build_task_args(args: tuple) -> str:
    return build_task(*args)


def workdir(task_dir: str, dst: str | os.PathLike) -> str:
    dst = str(dst)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(task_dir, "public"), dst)
    return dst


def edit_design(wd: str, fn) -> dict:
    p = os.path.join(wd, "design.json")
    d = json.loads(Path(p).read_text())
    fn(d)
    Path(p).write_text(json.dumps(d, indent=2, sort_keys=True))
    return d


def edit_board(wd: str, fn) -> None:
    p = os.path.join(wd, "board.kicad_pcb")
    b = boardnet.load_board(p)
    fn(b)
    assert pcbnew.SaveBoard(p, b, True)


def v(x: float, y: float) -> "pcbnew.VECTOR2I":
    return pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM)))


def pad_of(b, ref: str, padnum: str):
    return next(p for p in b.FindFootprintByReference(ref).Pads() if p.GetNumber() == padnum)


def net_of_pin(d: dict, pin: str) -> str:
    return next(n for n, pins in d["nets"].items() if pin in pins)


def comparable(res) -> tuple:
    """A VerifyResult without timing fields, for equality across runs."""
    detail = {k: v for k, v in res.detail.items() if k not in ("seconds", "wall_seconds")}
    return (res.reward, tuple(sorted(res.gates.items())), tuple(sorted(res.checks.items())),
            json.dumps(detail, sort_keys=True, default=str))
