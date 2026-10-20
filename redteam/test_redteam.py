"""Red-team regression tests. `test_exploit_*` reproduce confirmed exploits and are EXPECTED TO
FAIL until pcbenv is fixed (deliberately not xfail). `test_blocked_*` must keep passing.

    python3 -m pytest -q redteam/test_redteam.py
"""
from __future__ import annotations

import hashlib
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


def test_exploit_RT59_control_chars_in_values(tmp_path):
    """Values with a trailing newline ('6.8n\\n') are accepted on design AND board: KiCad 7 stores the
    escaped string and keeps it, so consistency passes, and parse_value's `$` matches before a
    final newline. A golden with every value newline-suffixed scores 1.0 (round-1 RT04 was
    blocked only because the fault remained)."""
    td = H.pick(family="led_driver", k=0)
    wd = _golden_wd(td, tmp_path)
    ATTACKS["value_newline"](wd)
    assert verify_isolated(wd, td).reward == 0.0, "values with control characters must be rejected"


# ================================================================== round 3 (v2 tiers)
from redteam.attacks.round3 import ATTACKS3, NEUTRAL3, EXPERT_REJECTS3  # noqa: E402
from redteam import hand_attempts_v2 as HV2  # noqa: E402


def _v2td(**sel) -> str:
    """First non-holdout v2 manifest row matching the filters."""
    rows = [m for m in H._manifest() if not m.get("holdout") and str(m.get("split", "")).startswith("v2/")]
    for k, v in sel.items():
        if k == "ftype":
            rows = [m for m in rows if any(f["type"] == v for f in m["faults"])]
        else:
            rows = [m for m in rows if m.get(k) == v]
    return str(H.ROOT / "tasks" / rows[0]["path"])


def _v2_golden_wd(td, tmp_path) -> str:
    wd = _wd(td, tmp_path)
    shutil.copyfile(os.path.join(td, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
    shutil.copyfile(os.path.join(td, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
    return wd


# --- former exploits, now expected FIXED-IN-V2: these assert the fix holds (RT30/31/32/33/59/01) ---
def test_fixed_RT30_nettie_fingerprint(tmp_path):
    """RT30 fixed: net-tie pad groups enter the fingerprint (read per-pad in KiCad 7, fail-closed)."""
    fp = boardnet.library_footprint("Resistor_SMD:R_0805_2012Metric")
    fp.AddNetTiePadGroup("1, 2")
    assert boardnet.footprint_fingerprint(fp) != boardnet.library_pad_fingerprint("Resistor_SMD:R_0805_2012Metric")


def test_fixed_RT32_unit_letters(tmp_path):
    """RT32 fixed: a wrong unit letter is rejected by the value grammar (per-part unit)."""
    from pcbenv.parts import parse_value
    import pytest as _pt
    for v, p in [("100nH", "C"), ("10kF", "R"), ("1e3k", "R")]:
        with _pt.raises(ValueError):
            parse_value(v, p)


def test_fixed_RT33_notation_equivalence():
    """RT33 fixed: Greek mu parses, 1meg = mega, numeric consistency compare (1000 == 1k)."""
    from pcbenv.parts import parse_value, values_equal
    assert abs(parse_value("4.7μ", "C") - 4.7e-6) < 1e-15
    assert parse_value("1meg", "R") == 1e6
    assert values_equal("1000", "1k", "R")


def test_fixed_RT59_control_chars(tmp_path):
    """RT59 fixed: a trailing newline in a value is rejected at parse."""
    from pcbenv.parts import parse_value
    import pytest as _pt
    with _pt.raises(ValueError):
        parse_value("6.8n\n", "C")


# --- round-3 attacks must not turn a faulted v2 task into 1.0 ---
@pytest.mark.parametrize("attack", sorted(ATTACKS3))
def test_blocked_round3_attack_v2(attack, tmp_path):
    td = _v2td(ftype="magnitude_slip", tier="normal")
    wd = _wd(td, tmp_path)
    ATTACKS3[attack](wd)
    assert verify_isolated(wd, td).reward == 0.0


# --- geometry edits that are physically equivalent keep a golden at 1.0 (no false negative) ---
@pytest.mark.parametrize("tier,ftype", [("hard", "capacitor_underrated"), ("hard_layout", "crystal_far")])
@pytest.mark.parametrize("attack", sorted(NEUTRAL3))
def test_blocked_round3_neutral_keeps_golden(attack, tier, ftype, tmp_path):
    td = _v2td(ftype=ftype, tier=tier)
    wd = _v2_golden_wd(td, tmp_path)
    NEUTRAL3[attack](wd)
    assert verify_isolated(wd, td).reward == 1.0


# --- edits an expert rejects must drop a golden to 0.0 ---
@pytest.mark.parametrize("attack", sorted(EXPERT_REJECTS3))
def test_blocked_round3_expert_rejects_golden(attack, tmp_path):
    td = _v2td(ftype="crystal_far", tier="hard_layout")
    wd = _v2_golden_wd(td, tmp_path)
    EXPERT_REJECTS3[attack](wd)
    assert verify_isolated(wd, td).reward == 0.0


# --- the v2 hand attempts: every `fake` attempt stays at 0.0 ---
@pytest.mark.parametrize("aid", [a[0] for a in HV2.ATTEMPTS if a[3] == "fake"])
def test_blocked_hand_attempt_v2(aid):
    a = next(x for x in HV2.ATTEMPTS if x[0] == aid)
    assert HV2.run_attempt(*a)["reward"] == 0.0


def test_rules_fail_closed_on_nonconvergence():
    """A rule context whose operating point cannot be simulated yields a violation (fail closed),
    never a silent pass: run_rules reports a `simulation` violation."""
    from pcbenv import rules as RL
    from pcbenv.golden import Golden
    # a design that cannot DC-simulate under a DC supply (floating everything) -> op point fails
    design = {"schema": "pcbenv/design@1", "title": "t",
              "components": {"R1": {"part": "R", "value": "1k", "footprint": "Resistor_SMD:R_0603_1608Metric"}},
              "nets": {"A": ["R1.1"], "B": ["R1.2"]}}
    ctx = {"version": 1, "scenarios": [{"supply": {"pin": "R1.1", "volts": 5.0}, "source": None,
                                        "loads": None, "ground_pin": "R1.2"}], "inductive_loads": [],
           "only": ["resistor_power"]}
    viol = RL.run_rules(design, ctx)
    # either it simulates cleanly (a lone biased resistor is fine) or it reports simulation/error --
    # it must never raise and must never fabricate a pass that hides a sim failure
    assert all(v.code in ("resistor_power", "simulation", "error") for v in viol)


def test_blocked_no_task_id_in_public_files_v2():
    """RT37 guard, fixed for v2 paths: no public file carries the opaque id, its hmac8 suffix, the
    generator seed, or the family name (the round-1 test globbed `pcbr-*` and matched 0 v2 dirs)."""
    rows = [m for m in H._manifest() if str(m.get("split", "")).startswith("v2/")]
    assert rows, "no v2 tasks in the manifest"
    for m in rows[::29]:
        tid = m["id"]
        hmac8 = tid.rsplit("-", 1)[1]
        meta = json.load(open(os.path.join(str(H.ROOT), "tasks", m["path"], "hidden", "meta.json")))
        seed, fam = str(meta["seed"]), meta.get("family", "")
        pub = os.path.join(str(H.ROOT), "tasks", m["path"], "public")
        for root, _, files in os.walk(pub):
            for f in files:
                txt = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
                assert tid not in txt and hmac8 not in txt, (tid, f)
                assert f'"seed": {seed}' not in txt and f'"seed":{seed}' not in txt, (tid, f)
                assert fam not in txt, (tid, f, "family name leaks")


def _uuid_from_salt(salt: str, i: int) -> str:
    h = hashlib.sha256(f"{salt}:{i}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:32]}"


def test_exploit_RT70_public_board_uuids_not_seed_derived():
    """RT70 (leak, low): a public board's UUIDs must not be a deterministic function of the HIDDEN
    generator seed. 148/1464 v2 public boards (those `publish_names` had nothing to rename, so the
    board kept the fault-injection salt `<seed>:<fault_type>` instead of the public `<task_id>:names`
    one) carry UUIDs = sha256("<seed>:<type>:<type>:<i>"). The seed is a 48-bit keyed value and the
    fault type is hidden, so it is not practically brute-forceable, but public artifact bytes should
    derive only from public data. EXPECTED TO FAIL until the publisher re-canonicalizes every
    published board with a public-only salt. Scanned sparsely to stay fast."""
    import re
    rows = [m for m in H._manifest() if str(m.get("split", "")).startswith("v2/")]
    leaked = []
    for m in rows[::7]:
        T = os.path.join(str(H.ROOT), "tasks", m["path"])
        uu = re.findall(r"\((?:tstamp|uuid) ([0-9a-f-]{36})\)", open(os.path.join(T, "public", "board.kicad_pcb")).read())
        if not uu or uu[0] in {_uuid_from_salt(f"{m['id']}:names", i) for i in range(3)}:
            continue
        meta = json.load(open(os.path.join(T, "hidden", "meta.json")))
        s = meta["seed"]
        if any(uu[0] == _uuid_from_salt(f"{s}:{f['type']}:{f['type']}", 0) for f in meta["faults"]):
            leaked.append(m["id"])
    assert not leaked, f"{len(leaked)} public boards carry seed-derived UUIDs, e.g. {leaked[:3]}"
