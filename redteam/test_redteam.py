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


# ================================================================== round 2 (shipped tasks)
from pcbenv import boardnet  # noqa: E402
from redteam import hand_attempts as H  # noqa: E402
from redteam import shortcuts as SC  # noqa: E402
from redteam.attacks.round2 import ATTACKS2, NEUTRAL  # noqa: E402

SHIPPED_BLOCKED = dict(ftype="magnitude_slip", n_faults=1, k=0)   # faulted baseline 0.0 (spec/values)


def _golden_wd(td: str, tmp_path) -> str:
    wd = _wd(td, tmp_path)
    shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
    shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
    return wd


# ------------------------------------------------------------------ round-2 exploits (fail until fixed)
def test_exploit_RT30_nettie_invisible_to_pad_fingerprint(tmp_path):
    """boardnet.footprint_fingerprint swallows a TypeError from GetNetTiePadGroups() (KiCad 7 SWIG
    returns an unwrapped std::vector), so net-tie pad groups never enter the fingerprint: a library
    resistor re-declared as a net tie still 'matches the library footprint'."""
    fp = boardnet.library_footprint("Resistor_SMD:R_0805_2012Metric")
    fp.AddNetTiePadGroup("1, 2")
    assert boardnet.footprint_fingerprint(fp) != boardnet.library_pad_fingerprint("Resistor_SMD:R_0805_2012Metric")



def test_exploit_RT31_decoupling_detour(tmp_path):
    """Golden board, decoupling cap left within max_mm of its IC pin, but its supply pad re-routed
    so it joins the supply net only at the connector (copper path cap->IC pin 1.9 mm -> ~9 mm,
    the cap no longer decouples the pin). Scores 1.0: decoupling is checked by pad distance only."""
    td = H.pick(family="ldo_reg", k=1)
    wd = _golden_wd(td, tmp_path)
    H.a_decap_detour(wd)
    assert verify_isolated(wd, td).reward == 0.0, "cap reached only via the connector must not count as decoupling"


def test_exploit_RT32_unit_letters_unchecked(tmp_path):
    """Trailing unit letters are ignored by parse_value: '100nH' on a capacitor and '10kF' on a
    resistor are accepted on design and board (BOM an assembler would reject/query)."""
    td = H.pick(family="rc_lowpass", k=1)
    wd = _golden_wd(td, tmp_path)
    H.a_wrong_unit_letters(wd)
    assert verify_isolated(wd, td).reward == 0.0, "wrong unit letters in a value must be rejected"


# ------------------------------------------------------------------ round-2 blocked attacks
@pytest.mark.parametrize("attack", sorted(ATTACKS2))
def test_blocked_round2_attack_shipped(attack, tmp_path):
    td = H.pick(**SHIPPED_BLOCKED)
    wd = _wd(td, tmp_path)
    ATTACKS2[attack](wd)
    assert verify_isolated(wd, td).reward == 0.0


@pytest.mark.parametrize("attack", sorted(NEUTRAL))
def test_blocked_neutral_edit_keeps_golden(attack, tmp_path):
    """Edits an expert accepts (equivalent notation, symmetric pin swap, flip, other allowed
    footprint, group/lock) keep the golden at 1.0 (no false negative)."""
    td = H.pick(family="led_driver", k=0)
    wd = _golden_wd(td, tmp_path)
    NEUTRAL[attack](wd)
    assert verify_isolated(wd, td).reward == 1.0


@pytest.mark.parametrize("attack", ["overlap_part", "offboard_part", "zero_size_pads", "keepout_area",
                                    "polarity_and_symmetric"])
def test_blocked_expert_rejects_on_golden(attack, tmp_path):
    td = H.pick(family="led_driver", k=0)
    wd = _golden_wd(td, tmp_path)
    ATTACKS2[attack](wd)
    assert verify_isolated(wd, td).reward == 0.0


def test_blocked_offboard_copper(tmp_path):
    """A same-net track leaving the board outline is a DRC error (copper-to-edge)."""
    td = H.pick(family="divider_adc", k=0)
    wd = _golden_wd(td, tmp_path)
    H.a_offboard_track(wd)
    r = verify_isolated(wd, td)
    assert r.reward == 0.0 and not r.checks["drc"]


_WRONG = sorted({(t, n) for t, scs in SC.SHORTCUTS.items() for n, _, lab in scs if lab == "wrong"})


@pytest.mark.parametrize("ftype,shortcut", _WRONG)
def test_blocked_wrong_shortcut_repair(ftype, shortcut):
    """Fault-specific shortcut repairs an expert rejects score 0.0 on the first single-fault task."""
    td = SC.single_fault_tasks(1)[ftype][0]
    r = SC._one((td, ftype, shortcut, "wrong"))
    assert r["status"] == "fail", r


@pytest.mark.parametrize("aid", [a[0] for a in H.ATTEMPTS if a[3] == "fake"])
def test_blocked_hand_attempt(aid):
    a = next(x for x in H.ATTEMPTS if x[0] == aid)
    assert H.run_attempt(*a)["reward"] == 0.0


def test_blocked_no_task_id_in_public_files():
    """Public files carry no task id / seed (the id itself is only in manifests and adapters)."""
    import glob
    for td in sorted(glob.glob(os.path.join(os.path.dirname(H.MANIFEST), "*", "pcbr-*")))[::40]:
        tid = os.path.basename(td)
        seed = tid.split("-")[2]
        for root, _, files in os.walk(os.path.join(td, "public")):
            for f in files:
                txt = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                assert tid not in txt and tid.rsplit("-", 1)[1] not in txt, (tid, f)
                assert f'"seed": {seed}' not in txt


def test_blocked_fault_type_not_named_in_task_md():
    for m in H._manifest():
        md = open(os.path.join(os.path.dirname(H.MANIFEST), m["split"], m["id"], "public", "TASK.md"), encoding="utf-8").read()
        for f in m["faults"]:
            assert f["type"] not in md and f["type"].replace("_", " ") not in md.lower(), (m["id"], f["type"])
