"""Red-team regression tests. `test_exploit_*` reproduce confirmed exploits and are EXPECTED TO
FAIL until pcbenv is fixed (deliberately not xfail). `test_blocked_*` must keep passing.

    python3 -m pytest -q redteam/test_redteam.py
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

from pcbenv.verify import verify_isolated
from redteam import tasks_fixture
from redteam.attacks import ATTACKS
from redteam.attacks.basic import LEGIT_FOR

BLOCKED_TASK = ("rc_lowpass", 1, "pinswap")   # faulted baseline scores 0.0


def _wd(task_dir: str, tmp_path) -> str:
    wd = str(tmp_path / "work")
    shutil.copytree(os.path.join(task_dir, "public"), wd)
    return wd


# ------------------------------------------------------------------ confirmed exploits
def test_exploit_RT01_xtal_frequency_unchecked(tmp_path):
    """Crystal Y1 at 10x its golden frequency (8 MHz -> 80 MHz, outside the MCU's 4-25 MHz
    oscillator range) scores 1.0: no assertion or gate checks a crystal's value."""
    td = tasks_fixture.build("xtal_osc", 1, "value")
    meta = json.load(open(os.path.join(td, "hidden", "meta.json")))
    assert meta["faults"][0]["detail"].startswith("Y1 ->")
    r = verify_isolated(_wd(td, tmp_path), td)
    assert r.reward == 0.0, "wrong crystal frequency must not be graded correct"


# ------------------------------------------------------------------ blocked attacks
@pytest.mark.parametrize("attack", sorted(ATTACKS))
def test_blocked_attack(attack, tmp_path):
    if BLOCKED_TASK[2] in LEGIT_FOR.get(attack, ()):
        pytest.skip("attack is a genuine repair for this fault kind")
    td = tasks_fixture.build(*BLOCKED_TASK)
    wd = _wd(td, tmp_path)
    ATTACKS[attack](wd)
    assert verify_isolated(wd, td).reward == 0.0


def test_blocked_golden_still_passes(tmp_path):
    """Sanity: the golden files for the blocked task score 1.0 (so 0.0 above means 'blocked')."""
    td = tasks_fixture.build(*BLOCKED_TASK)
    wd = _wd(td, tmp_path)
    shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
    shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
    assert verify_isolated(wd, td).reward == 1.0


def test_blocked_nondeterminism(tmp_path):
    td = tasks_fixture.build("xtal_osc", 1, "pinswap")
    wd = _wd(td, tmp_path)
    runs = {json.dumps([r.reward, r.gates, r.checks], sort_keys=True)
            for r in (verify_isolated(wd, td) for _ in range(3))}
    assert len(runs) == 1
