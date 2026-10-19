"""G3 acceptance: verifier, ERC, layout checks.

- every golden task (10 families x seeds 0..19; PCBENV_GOLDEN_SEEDS=N for more) scores 1.0
- each gate / check fails on a targeted mutation, and only the intended ones fail
- hostile inputs (symlinks, huge files, garbage, rules files in the workdir) score 0 / are ignored
- determinism (10 subprocess runs), latency (median / p99), parallel isolation (16 tasks)
"""
from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pcbnew
import pytest
import yaml

from pcbenv import boardnet, erc, layout, verify as V
from pcbenv.families import FAMILIES
from pcbenv.parts import PARTS, parse_value, format_value
from pcbenv.verify import CHECKS, GATES, verify, verify_isolated
from tests.fixtures.verify_tasks import (MM, build_task, build_task_args, comparable, edit_board, edit_design,
                                         net_of_pin, pad_of, v, workdir)

ROOT = Path(__file__).resolve().parent.parent
THRESH = yaml.safe_load((ROOT / "thresholds.yaml").read_text())["harness"]
GOLDEN_SEEDS = range(int(os.environ.get("PCBENV_GOLDEN_SEEDS", "20")))
GOLDEN_CASES = [(f, s) for f in sorted(FAMILIES) for s in GOLDEN_SEEDS]
ALL_KEYS = GATES + CHECKS


@pytest.fixture(scope="session")
def task_root(tmp_path_factory):
    return tmp_path_factory.mktemp("tasks")


@pytest.fixture(scope="session")
def golden_results(task_root):
    """Build every golden task (process pool) and verify each one in its own subprocess."""
    args = [(str(task_root), f, s) for f, s in GOLDEN_CASES]
    with get_context("spawn").Pool(4, maxtasksperchild=10) as pool:
        dirs = pool.map(build_task_args, args, chunksize=4)
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda td: verify_isolated(os.path.join(td, "public"), td), dirs))
    return {case: (td, r) for case, td, r in zip(GOLDEN_CASES, dirs, results)}


@pytest.mark.parametrize("family,seed", GOLDEN_CASES, ids=[f"{f}-{s}" for f, s in GOLDEN_CASES])
def test_golden_scores_one(golden_results, family, seed):
    _, r = golden_results[(family, seed)]
    assert r.reward == 1.0, (r.gates, r.checks, r.detail)
    assert all(r.gates[g] for g in GATES) and all(r.checks[c] for c in CHECKS)


def test_erc_all_goldens_40_seeds():
    for f, m in sorted(FAMILIES.items()):
        for s in range(40):
            iss = erc.run_erc(m.generate(s).design)
            assert not erc.errors(iss), (f, s, iss)


# ------------------------------------------------------------------ ERC unit
def _ldo_design():
    return FAMILIES["ldo_reg"].generate(0).design


def _codes(d):
    return {i.code for i in erc.errors(erc.run_erc(d))}


def test_erc_rules():
    d = _ldo_design()
    assert _codes(d) == set()
    # required pin unconnected
    d1 = json.loads(json.dumps(d))
    n = net_of_pin(d1, "U1.EN"); d1["nets"][n].remove("U1.EN")
    assert "unconnected_required" in _codes(d1)
    # single-pin net
    d2 = json.loads(json.dumps(d))
    n = net_of_pin(d2, "U1.EN"); d2["nets"][n].remove("U1.EN"); d2["nets"]["LONELY"] = ["U1.EN"]
    assert "single_pin_net" in _codes(d2)
    # two power outputs on one net / output conflict: VOUT onto the VIN net
    d3 = json.loads(json.dumps(d))
    n = net_of_pin(d3, "U1.VOUT"); d3["nets"][n].remove("U1.VOUT"); d3["nets"][net_of_pin(d3, "U1.VIN")].append("U1.VOUT")
    assert "driver_conflict" not in _codes(d3)  # one power_out only; but VIN has a connector -> ok
    # supply short: VIN net merged with GND net (name-insensitive: rename nets)
    d4 = json.loads(json.dumps(d))
    vin, gnd = net_of_pin(d4, "U1.VIN"), net_of_pin(d4, "U1.GND")
    d4["nets"] = {f"N{i}": pins for i, (k, pins) in enumerate(sorted(d4["nets"].items())) if k not in (vin, gnd)}
    d4["nets"]["whatever"] = d["nets"][vin] + d["nets"][gnd]
    assert "supply_short" in _codes(d4)
    # power_in without a source: move U1.VIN onto a net of passives only
    d5 = json.loads(json.dumps(d))
    d5["nets"][net_of_pin(d5, "U1.VIN")].remove("U1.VIN"); d5["nets"][net_of_pin(d5, "U1.FB")].append("U1.VIN")
    assert "no_supply" in _codes(d5)


def test_erc_driver_conflict_and_output_to_ground():
    d = FAMILIES["opamp_noninv"].generate(0).design
    assert _codes(d) == set()
    d1 = json.loads(json.dumps(d))
    d1["nets"][net_of_pin(d1, "U1.OUT")].remove("U1.OUT"); d1["nets"][net_of_pin(d1, "U1.V-")].append("U1.OUT")
    assert "output_to_ground" in _codes(d1)
    d2 = FAMILIES["ldo_reg"].generate(0).design
    d2["components"]["U2"] = {"part": "OPAMP", "value": "", "footprint": PARTS["OPAMP"].footprints[0]}
    d2["nets"][net_of_pin(d2, "U1.VOUT")].append("U2.OUT")
    assert "driver_conflict" in _codes(d2)
    d3 = json.loads(json.dumps(d))
    for p in ("U1.IN+", "U1.IN-"):
        d3["nets"][net_of_pin(d3, p)].remove(p)
    d3["nets"]["X"] = ["U1.IN+", "U1.IN-"]
    assert "undriven_input" in _codes(d3)


def test_same_topology_symmetric_parts():
    parts = {"R1": "R", "J1": "CONN2", "U1": "OPAMP"}
    a = frozenset({frozenset({"J1.1", "R1.1"}), frozenset({"R1.2", "U1.IN+"})})
    b = frozenset({frozenset({"J1.1", "R1.2"}), frozenset({"R1.1", "U1.IN+"})})
    c = frozenset({frozenset({"J1.2", "R1.1"}), frozenset({"R1.2", "U1.IN+"})})
    assert layout.same_topology(a, b, parts)
    assert not layout.same_topology(a, c, parts)
    assert not layout.same_topology(a, b, {"R1": "OPAMP"})


# ------------------------------------------------------------------ mutations
def _first(d: dict, part: str) -> str:
    return sorted(r for r, c in d["components"].items() if c["part"] == part)[0]


def m_value(wd):
    d = json.loads(Path(wd, "design.json").read_text())
    ref = _first(d, "R")
    new = format_value(parse_value(d["components"][ref]["value"]) * 3.3)
    edit_design(wd, lambda d: d["components"][ref].update(value=new))
    edit_board(wd, lambda b: b.FindFootprintByReference(ref).SetValue(new))


def _swap_pads(b, ref, p1, p2):
    a, c = pad_of(b, ref, p1), pad_of(b, ref, p2)
    na, nc = a.GetNet(), c.GetNet()
    a.SetNet(nc); c.SetNet(na)


def _swap_design(d, x, y):
    nx, ny = net_of_pin(d, x), net_of_pin(d, y)
    d["nets"][nx] = [y if p == x else p for p in d["nets"][nx]]
    d["nets"][ny] = [x if p == y else p for p in d["nets"][ny]]


def m_swap_fb_en(wd):  # LDO: FB (pad 4) <-> EN (pad 3), design and board
    edit_design(wd, lambda d: _swap_design(d, "U1.FB", "U1.EN"))
    edit_board(wd, lambda b: _swap_pads(b, "U1", "3", "4"))


def m_swap_resistor(wd):  # R2.1 <-> R2.2 everywhere: electrically identical
    edit_design(wd, lambda d: _swap_design(d, "R2.1", "R2.2"))
    edit_board(wd, lambda b: _swap_pads(b, "R2", "1", "2"))


def m_board_only_swap(wd):
    edit_board(wd, lambda b: _swap_pads(b, "U1", "3", "4"))


def m_board_only_value(wd):
    edit_board(wd, lambda b: b.FindFootprintByReference("R1").SetValue("1k"))


def m_design_only_value(wd):
    edit_design(wd, lambda d: d["components"]["R1"].update(value="1k"))


def m_pad_resize(wd):
    def f(b):
        p = pad_of(b, "C1", "1")
        p.SetSize(p.GetSize() + v(0.2, 0))
    edit_board(wd, f)


def m_footprint_design_only(wd):  # allowed footprint, but board still has the old one
    def f(d):
        c = d["components"]["R1"]
        c["footprint"] = next(x for x in PARTS["R"].footprints if x != c["footprint"])
    edit_design(wd, f)


def m_footprint_not_allowed(wd):
    edit_design(wd, lambda d: d["components"]["R1"].update(footprint="Resistor_SMD:R_2512_6332Metric"))


def m_part_changed(wd):
    edit_design(wd, lambda d: d["components"]["C1"].update(part="L"))


def m_delete_component(wd):
    def f(d):
        del d["components"]["R2"]
        for n in d["nets"]:
            d["nets"][n] = [p for p in d["nets"][n] if not p.startswith("R2.")]
    edit_design(wd, f)


def m_extra_footprint(wd):
    def f(b):
        fp = boardnet.library_footprint("Resistor_SMD:R_0603_1608Metric")
        fp.SetReference("R99")
        b.Add(fp)
        fp.SetPosition(v(101.5, 101.5))
    edit_board(wd, f)


def m_duplicate_ref(wd):
    edit_board(wd, lambda b: b.FindFootprintByReference("C2").SetReference("C1"))


def m_edge_cuts(wd):
    def f(b):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(v(101, 101)); s.SetEnd(v(102, 101))
        b.Add(s)
    edit_board(wd, f)


def m_zone(wd):
    def f(b):
        z = pcbnew.ZONE(b)
        z.SetLayer(pcbnew.B_Cu)
        for x, y in ((101, 101), (103, 101), (103, 103)):
            z.AppendCorner(v(x, y), -1)
        b.Add(z)
    edit_board(wd, f)


def m_copper_drawing(wd):
    def f(b):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.B_Cu); s.SetWidth(int(0.2 * MM))
        s.SetStart(v(100.6, 100.6)); s.SetEnd(v(100.7, 100.6))
        b.Add(s)
    edit_board(wd, f)


def m_remove_track(wd):
    def f(b):
        ts = sorted((t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"), key=lambda t: -t.GetLength())
        b.Delete(ts[0])
    edit_board(wd, f)


def m_narrow_power(wd):  # LDO: one VIN segment 0.3 -> 0.2 mm (legal for DRC, too thin for layout)
    def f(b):
        t = next(t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "VIN")
        t.SetWidth(int(0.2 * MM))
    edit_board(wd, f)


def m_move_decap(wd):  # LDO: C1 > 5 mm from U1.VIN, still inside the board
    def f(b):
        u = b.FindFootprintByReference("U1").GetPosition()
        fp = b.FindFootprintByReference("C1")
        bb = b.GetBoardEdgesBoundingBox()
        cx = bb.GetLeft() + 3 * MM if u.x - bb.GetLeft() > bb.GetRight() - u.x else bb.GetRight() - 3 * MM
        fp.SetPosition(pcbnew.VECTOR2I(int(cx), int(u.y)))
    edit_board(wd, f)


def m_disconnect_en(wd):  # design+board: U1.EN unconnected -> ERC error (and topology)
    def f(d):
        d["nets"][net_of_pin(d, "U1.EN")].remove("U1.EN")
    edit_design(wd, f)
    edit_board(wd, lambda b: pad_of(b, "U1", "3").SetNetCode(0))


def m_dru_violation(wd):
    """A clearance violation plus loosening rules files next to the deliverables."""
    def f(b):
        for net, dy in (("FB", 0.0), ("VIN", 0.3)):
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(v(100.8, 100.8 + dy)); t.SetEnd(v(101.6, 100.8 + dy)); t.SetWidth(int(0.2 * MM))
            t.SetLayer(pcbnew.B_Cu); t.SetNet(b.FindNet(net)); b.Add(t)
    edit_board(wd, f)
    _loosen(wd)


def _loosen(wd):
    Path(wd, "board.kicad_dru").write_text("(version 1)\n(rule loose (constraint clearance (min 0mm)))\n")
    Path(wd, "board.kicad_pro").write_text(json.dumps({"board": {"design_settings": {
        "rules": {"min_clearance": 0.0}, "rule_severities": {"clearance": "ignore", "unconnected_items": "ignore"}}}}))


def m_symlink_design(wd):
    td = Path(wd).parent / "task_hidden_copy.json"
    td.write_text(Path(wd, "design.json").read_text())
    os.remove(os.path.join(wd, "design.json"))
    os.symlink(td, os.path.join(wd, "design.json"))


def m_symlink_board(wd):
    real = Path(wd).parent / "real_board.kicad_pcb"
    os.replace(os.path.join(wd, "board.kicad_pcb"), real)
    os.symlink(real, os.path.join(wd, "board.kicad_pcb"))


def m_big_design(wd):  # 6 MB of valid JSON (whitespace)
    p = Path(wd, "design.json")
    p.write_text(p.read_text() + " " * (6 * 1024 * 1024))


def m_garbage_json(wd):
    Path(wd, "design.json").write_text("{not json")


def m_garbage_board(wd):
    Path(wd, "board.kicad_pcb").write_text("(kicad_pcb (version 2022) garbage (((")


def m_missing_board(wd):
    os.remove(os.path.join(wd, "board.kicad_pcb"))


def m_design_is_dir(wd):
    os.remove(os.path.join(wd, "design.json"))
    os.mkdir(os.path.join(wd, "design.json"))


def m_design_fifo(wd):
    os.remove(os.path.join(wd, "design.json"))
    os.mkfifo(os.path.join(wd, "design.json"))


def m_marker_sexpr(wd):  # KiCad 7 cannot store markers in a board: such a file must not pass
    p = Path(wd, "board.kicad_pcb")
    t = p.read_text().rstrip()
    assert t.endswith(")")
    p.write_text(t[:-1] + '  (marker (type "clearance") (pos 101 101) (excluded yes))\n)\n')


def m_bad_schema(wd):
    edit_design(wd, lambda d: d.update(schema="pcbenv/design@0"))


def m_unknown_pin(wd):
    edit_design(wd, lambda d: d["nets"][net_of_pin(d, "R1.1")].append("R1.3"))


def m_none(wd):
    pass


def m_rules_files_only(wd):
    _loosen(wd)
    Path(wd, "evil.py").write_text("raise SystemExit('should never run')\n")
    Path(wd, "pcbenv").mkdir()
    Path(wd, "pcbenv", "__init__.py").write_text("raise SystemExit('shadowed')\n")


# name -> (mutation, expected reward, {key: expected bool} for keys whose value is asserted)
OK = {k: True for k in ALL_KEYS}
MUTATIONS = {
    "value_changed": (m_value, 0.0, {**OK, "spec": False}),
    "swap_fb_en": (m_swap_fb_en, 0.0, {"parse": True, "components": True, "topology": False, "consistency": True,
                                       "integrity": True, "drc": False}),
    "swap_symmetric_resistor": (m_swap_resistor, 0.0, {"components": True, "topology": True, "consistency": True,
                                                       "integrity": True, "erc": True, "spec": True, "drc": False}),
    "board_only_swap": (m_board_only_swap, 0.0, {"components": True, "topology": True, "consistency": False,
                                                 "integrity": True}),
    "board_only_value": (m_board_only_value, 0.0, {**OK, "consistency": False}),
    "design_only_value": (m_design_only_value, 0.0, {"components": True, "topology": True, "consistency": False,
                                                     "integrity": True, "spec": False}),
    "pad_resize": (m_pad_resize, 0.0, {"components": False, "topology": True, "consistency": True,
                                       "integrity": True}),
    "footprint_design_only": (m_footprint_design_only, 0.0, {"components": False, "topology": True}),
    "footprint_not_allowed": (m_footprint_not_allowed, 0.0, {"components": False}),
    "part_changed": (m_part_changed, 0.0, {"components": False}),
    "delete_component": (m_delete_component, 0.0, {"components": False, "topology": False}),
    "extra_footprint": (m_extra_footprint, 0.0, {"components": False, "topology": True, "integrity": True}),
    "duplicate_ref": (m_duplicate_ref, 0.0, {"components": False}),
    "edge_cuts": (m_edge_cuts, 0.0, {"integrity": False, "components": True, "topology": True,
                                     "consistency": True}),
    "zone": (m_zone, 0.0, {"integrity": False, "components": True, "topology": True, "consistency": True}),
    "copper_drawing": (m_copper_drawing, 0.0, {"integrity": False, "components": True, "consistency": True}),
    "remove_track": (m_remove_track, 0.0, {**OK, "drc": False}),
    "narrow_power_track": (m_narrow_power, 0.0, {**OK, "layout": False}),
    "move_decap": (m_move_decap, 0.0, {"components": True, "topology": True, "consistency": True,
                                       "integrity": True, "erc": True, "spec": True, "layout": False}),
    "disconnect_en": (m_disconnect_en, 0.0, {"consistency": True, "topology": False, "erc": False}),
    "dru_in_workdir": (m_dru_violation, 0.0, {"drc": False, "components": True, "integrity": True}),
    "symlink_design": (m_symlink_design, 0.0, {"parse": False}),
    "symlink_board": (m_symlink_board, 0.0, {"parse": False}),
    "big_design_6mb": (m_big_design, 0.0, {"parse": False}),
    "garbage_json": (m_garbage_json, 0.0, {"parse": False}),
    "garbage_board": (m_garbage_board, 0.0, {"parse": False}),
    "missing_board": (m_missing_board, 0.0, {"parse": False}),
    "design_is_dir": (m_design_is_dir, 0.0, {"parse": False}),
    "design_fifo": (m_design_fifo, 0.0, {"parse": False}),
    "marker_sexpr": (m_marker_sexpr, 0.0, {}),
    "bad_schema": (m_bad_schema, 0.0, {"parse": False}),
    "unknown_pin": (m_unknown_pin, 0.0, {"parse": False}),
    "unchanged": (m_none, 1.0, OK),
    "rules_and_code_files_ignored": (m_rules_files_only, 1.0, OK),
}


@pytest.fixture(scope="module")
def ldo_task(task_root):
    return build_task(task_root, "ldo_reg", 0)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mutation(ldo_task, tmp_path, name):
    fn, reward, expect = MUTATIONS[name]
    wd = workdir(ldo_task, tmp_path / "w")
    fn(wd)
    r = verify(wd, ldo_task)
    assert r.reward == reward, (r.gates, r.checks, r.detail)
    got = {**r.gates, **r.checks}
    wrong = {k: got.get(k) for k, want in expect.items() if got.get(k) != want}
    assert not wrong, (wrong, r.detail)


def test_exclusion_or_marker_counts_fail_integrity(ldo_task, tmp_path, monkeypatch):
    """KiCad 7 cannot persist markers/exclusions in a .kicad_pcb; check the gate logic anyway."""
    wd = workdir(ldo_task, tmp_path / "w")
    real = boardnet.board_info
    calls = {"n": 0}

    def fake(board, design=None, parts=None):
        info = real(board, design, parts)
        calls["n"] += 1
        if calls["n"] == 1:  # the candidate is analysed first
            info.exclusion_count = 1
        return info
    monkeypatch.setattr(boardnet, "board_info", fake)
    r = verify(wd, ldo_task)
    assert r.reward == 0.0 and r.gates["integrity"] is False and "exclusions" in r.detail["integrity"][0]


def test_exception_gives_zero(ldo_task, tmp_path, monkeypatch):
    wd = workdir(ldo_task, tmp_path / "w")
    from pcbenv import sim

    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(boardnet, "board_info", boom)
    r = verify(wd, ldo_task)
    assert r.reward == 0.0 and "kaboom" in r.detail["error"]
    monkeypatch.undo()
    monkeypatch.setattr(sim, "run_assertions", boom)
    r = verify(wd, ldo_task)
    assert r.reward == 0.0 and r.checks["spec"] is False


def test_missing_hidden_gives_zero(ldo_task, tmp_path):
    wd = workdir(ldo_task, tmp_path / "w")
    r = verify(wd, str(tmp_path / "no_such_task"))
    assert r.reward == 0.0 and "error" in r.detail
    r = verify_isolated(wd, str(tmp_path / "no_such_task"))
    assert r.reward == 0.0


def test_verify_isolated_crash_and_timeout(ldo_task, tmp_path, monkeypatch):
    wd = workdir(ldo_task, tmp_path / "w")
    r = verify_isolated(wd, ldo_task, timeout=0.01)
    assert r.reward == 0.0 and "timed out" in r.detail["error"]
    monkeypatch.setattr(V, "_MARK", "NOPE")  # parent cannot find the result line -> 0
    r = verify_isolated(wd, ldo_task)
    assert r.reward == 0.0


def test_cli_prints_json(ldo_task, tmp_path):
    import subprocess
    import sys
    wd = workdir(ldo_task, tmp_path / "w")
    p = subprocess.run([sys.executable, "-m", "pcbenv.verify", wd, ldo_task], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0
    line = [ln for ln in p.stdout.splitlines() if ln.startswith(V._MARK)][-1]
    assert json.loads(line[len(V._MARK):])["reward"] == 1.0


# ------------------------------------------------------------------ determinism / latency / isolation
def test_determinism_10_subprocesses(ldo_task, tmp_path):
    n = THRESH["determinism_reruns"]
    for name in ("unchanged", "value_changed", "remove_track"):
        wd = workdir(ldo_task, tmp_path / name)
        MUTATIONS[name][0](wd)
        runs = [comparable(verify_isolated(wd, ldo_task)) for _ in range(n)]
        assert len(set(runs)) == 1, name
    print(f"\ndeterminism: 3 workdirs x {n} subprocess runs, identical results")


def test_latency(golden_results):
    cases = [(f, s) for f in sorted(FAMILIES) for s in range(3)]
    times = []
    for c in cases:
        td, _ = golden_results[c]
        t = time.monotonic()
        r = verify_isolated(os.path.join(td, "public"), td)
        times.append(time.monotonic() - t)
        assert r.reward == 1.0
    times.sort()
    med = statistics.median(times)
    p99 = times[min(len(times) - 1, int(round(0.99 * (len(times) - 1))))]
    print(f"\nverify_isolated latency over {len(times)} tasks: median {med:.2f} s, p99 {p99:.2f} s, max {times[-1]:.2f} s")
    assert med <= THRESH["verify_latency_median_s"]
    assert p99 <= THRESH["verify_latency_p99_s"]


GENERIC = ["m_none", "m_value_generic", "m_remove_track", "m_board_value_generic", "m_garbage_json",
           "m_edge_cuts", "m_design_disconnect_generic", "m_rules_files_only", "m_zone", "m_symlink_design",
           "m_big_design", "m_pad_generic", "m_delete_generic", "m_narrow_generic", "m_garbage_board", "m_none"]


def m_value_generic(wd):
    m_value(wd)


def m_board_value_generic(wd):
    d = json.loads(Path(wd, "design.json").read_text())
    ref = _first(d, "R")
    edit_board(wd, lambda b: b.FindFootprintByReference(ref).SetValue("123k"))


def m_design_disconnect_generic(wd):
    def f(d):
        big = max(sorted(d["nets"]), key=lambda n: len(d["nets"][n]))
        d["nets"][big].pop(0)
    edit_design(wd, f)


def m_pad_generic(wd):
    def f(b):
        p = sorted(b.GetFootprints(), key=lambda x: x.GetReference())[0].Pads()[0]
        p.SetSize(p.GetSize() + v(0.1, 0.1))
    edit_board(wd, f)


def m_delete_generic(wd):
    def f(d):
        ref = _first(d, "R")
        del d["components"][ref]
        for n in d["nets"]:
            d["nets"][n] = [p for p in d["nets"][n] if p.split(".")[0] != ref]
    edit_design(wd, f)


def m_narrow_generic(wd):
    spec = json.loads(Path(wd, "spec.json").read_text())
    nets = {p["net"] for p in spec["power_nets"]}

    def f(b):
        t = next(t for t in sorted(b.GetTracks(), key=lambda t: (t.GetNetname(), t.GetStart().x, t.GetStart().y))
                 if t.GetClass() == "PCB_TRACK" and t.GetNetname() in nets)
        t.SetWidth(int(0.2 * MM))
    edit_board(wd, f)


def _verify_pair(args):
    wd, td = args
    return verify(wd, td)


def test_parallel_isolation(golden_results, tmp_path):
    n = THRESH["parallel_isolation_tasks"]
    fams = sorted(FAMILIES)
    jobs = []
    for i in range(n):
        td, _ = golden_results[(fams[i % len(fams)], i // len(fams))]
        wd = workdir(td, tmp_path / f"w{i}")
        globals()[GENERIC[i]](wd)
        jobs.append((wd, td))
    seq = [comparable(verify_isolated(wd, td)) for wd, td in jobs]
    with ProcessPoolExecutor(8, mp_context=get_context("spawn")) as ex:
        par = [comparable(r) for r in ex.map(_verify_pair, jobs)]
    with ThreadPoolExecutor(n) as ex:
        par_iso = [comparable(r) for r in ex.map(lambda j: verify_isolated(*j), jobs)]
    assert par == seq
    assert par_iso == seq
    rewards = [s[0] for s in seq]
    assert rewards.count(1.0) == 3 and rewards.count(0.0) == n - 3  # m_none x2 + rules files only
    print(f"\nparallel isolation: {n} tasks, process pool (8) and {n} concurrent subprocesses == sequential")
