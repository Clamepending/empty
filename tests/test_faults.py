"""G4 fault injector: every fault type, on >= 5 applicable goldens, produces a valid task that
scores 0.0 and whose oracle repair scores 1.0; value faults are also repaired with
`pcbtool set-value`, and every connectivity / board fault type is repaired with the agent's
tools (connect / disconnect / sync / route / move / set-footprint) on at least one example.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from multiprocessing import get_context
from pathlib import Path

import pytest

from pcbenv.faults import FAULT_TYPES, apply_fault
from pcbenv.families import FAMILIES

ROOT = Path(__file__).resolve().parent.parent
PCBTOOL = str(ROOT / "bin" / "pcbtool")
SEEDS = range(4)
CASES = 5


def _build(args: tuple) -> tuple:
    from pcbenv.board import build_board
    fam, seed, root = args
    path = os.path.join(root, f"golden_{fam}_{seed}.kicad_pcb")
    build_board(FAMILIES[fam].generate(seed), path, 0)
    return fam, seed, path


def _pcbtool(wd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PCBTOOL, *args], cwd=wd, capture_output=True, text=True, timeout=300)


def realistic_repair(rec: dict, wd: str) -> list[list[str]]:
    """The pcbtool commands an agent would use to undo this fault (never touches hidden data)."""
    t, d = rec["type"], rec["data"]
    if rec["category"] == "value":
        vals = d.get("golden_values") or {d["ref"]: d["golden_value"]}
        return [["set-value", r, v] for r, v in sorted(vals.items())]
    if rec["category"] == "connectivity":
        cmds, nets = [], set()
        for pin, (gnet, fnet) in sorted(d["moves"].items()):
            cmds.append(["disconnect", pin] if gnet is None else ["connect", pin, gnet])
            nets |= {n for n in (gnet, fnet) if n}
        return cmds + [["route", n] for n in sorted(nets)]
    if t == "board_pad_swap":
        return [["sync"]] + [["route", n] for n in sorted(set(d["nets"]))]
    if t in ("clearance_violation", "short_between_nets", "broken_trace", "narrow_power_trace"):
        return [["route", d["net"]]]
    if t == "decap_moved_far":
        x, y = d["golden_pos"]
        return [["move", d["cap"], f"{x}", f"{y}", f"{d['rot']}"]] + [["route", n] for n in d["nets"]]
    if t == "footprint_swap":
        return [["set-footprint", d["ref"], d["golden_footprint"]]]
    raise AssertionError(t)


def _check_type(args: tuple) -> dict:
    from pcbenv.taskio import write_task
    from pcbenv.verify import verify
    name, cands, root = args
    out = {"type": name, "cases": [], "repairs": []}
    for fam, seed, gboard in cands:
        if len(out["cases"]) >= CASES and out["repairs"] and any(r["reward"] == 1.0 for r in out["repairs"]):
            break
        g = FAMILIES[fam].generate(seed)
        design = json.loads(json.dumps(g.design))
        base = os.path.join(root, name, f"{fam}_{seed}")
        os.makedirs(base, exist_ok=True)
        board = os.path.join(base, "faulted.kicad_pcb")
        shutil.copyfile(gboard, board)
        rec = apply_fault(name, g, design, board, random.Random(f"test:{fam}:{seed}:{name}"), salt="t")
        if rec is None:
            continue
        td = os.path.join(base, "task")
        write_task(td, g, gboard, public_design=design, public_board=board, faults=[rec.to_dict()])
        faulted = verify(os.path.join(td, "public"), td)
        oracle = os.path.join(base, "oracle")
        shutil.copytree(os.path.join(td, "public"), oracle)
        shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(oracle, "design.json"))
        shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(oracle, "board.kicad_pcb"))
        case = {"family": fam, "seed": seed, "detail": rec.detail, "faulted": faulted.reward,
                "parse": faulted.gates.get("parse"), "oracle": verify(oracle, td).reward}
        out["cases"].append(case)
        # realistic repair with pcbtool: every value case, else until one works
        is_value = rec.category == "value"
        if is_value or not any(r["reward"] == 1.0 for r in out["repairs"]):
            wd = os.path.join(base, "agent")
            shutil.copytree(os.path.join(td, "public"), wd)
            log = []
            for cmd in realistic_repair(rec.to_dict(), wd):
                p = _pcbtool(wd, *cmd)
                log.append((cmd, p.returncode, (p.stderr or "")[-200:]))
            out["repairs"].append({"family": fam, "seed": seed, "reward": verify(wd, td).reward, "log": log})
    return out


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("faults"))
    fams = sorted(FAMILIES)
    jobs = [(f, s, root) for s in SEEDS for f in fams]   # seed-major: candidates alternate families
    ctx = get_context("spawn")
    with ctx.Pool(4, maxtasksperchild=8) as pool:
        built = pool.map(_build, jobs, chunksize=2)
    with ctx.Pool(4, maxtasksperchild=2) as pool:
        res = pool.map(_check_type, [(n, built, root) for n in sorted(FAULT_TYPES)], chunksize=1)
    return {r["type"]: r for r in res}


def test_at_least_15_fault_types():
    assert len(FAULT_TYPES) >= 15
    cats = {f.category for f in FAULT_TYPES.values()}
    assert cats == {"value", "connectivity", "board"}


@pytest.mark.parametrize("name", sorted(FAULT_TYPES))
def test_fault_type_valid_detected_repairable(results, name):
    r = results[name]
    assert len(r["cases"]) >= CASES, f"{name}: only {len(r['cases'])} applicable goldens"
    for c in r["cases"]:
        assert c["parse"], c                       # injected task loads and validates
        assert c["faulted"] == 0.0, c              # detected
        assert c["oracle"] == 1.0, c               # golden restore scores 1.0
    assert any(x["reward"] == 1.0 for x in r["repairs"]), r["repairs"]   # solvable with pcbtool
    if FAULT_TYPES[name].category == "value":
        assert all(x["reward"] == 1.0 for x in r["repairs"]), r["repairs"]


def test_inapplicable_returns_none_and_leaves_files(tmp_path):
    from pcbenv.board import build_board
    g = FAMILIES["rc_lowpass"].generate(0)
    b = str(tmp_path / "b.kicad_pcb")
    build_board(g, b, 0)
    before = Path(b).read_bytes()
    d = json.loads(json.dumps(g.design))
    assert apply_fault("transistor_pinout", g, d, b, random.Random(0)) is None
    assert d == g.design and Path(b).read_bytes() == before


def test_injection_deterministic(tmp_path):
    from pcbenv.board import build_board
    g = FAMILIES["ldo_reg"].generate(2)
    gb = str(tmp_path / "g.kicad_pcb")
    build_board(g, gb, 0)
    outs = []
    for i in range(2):
        b = str(tmp_path / f"b{i}.kicad_pcb")
        shutil.copyfile(gb, b)
        d = json.loads(json.dumps(g.design))
        rec = apply_fault("decap_moved_far", g, d, b, random.Random(7), salt="s")
        assert rec is not None
        outs.append((rec.detail, json.dumps(d, sort_keys=True), Path(b).read_bytes()))
    assert outs[0] == outs[1]


def test_exclusion_keeps_faults_disjoint(tmp_path):
    from pcbenv.board import build_board
    g = FAMILIES["mcu_i2c"].generate(1)
    b = str(tmp_path / "b.kicad_pcb")
    build_board(g, b, 0)
    d = json.loads(json.dumps(g.design))
    r1 = apply_fault("wrong_pull_resistor", g, d, b, random.Random(1))
    r2 = apply_fault("magnitude_slip", g, d, b, random.Random(1), exclude=frozenset(r1.targets))
    assert r1 and r2 and not set(r1.targets) & set(r2.targets)
