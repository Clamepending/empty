"""hard_layout tier: board-geometry layout rules (`pcbenv/layout_rules.py`), layout-latent faults
(`latent.LAYOUT_LATENT_TYPES`) and the shipped `tasks/v2/hard_layout*` splits.

- every rule passes on layout-rule goldens of the composites x 20 seeds (margins recorded);
- every rule fails on a targeted geometric mutation;
- every layout-latent fault: valid (design untouched, DRC clean), invisible to pcbtool, detected only by
  `layout_rules` / `layout`, repairable to 1.0 by board edits;
- in full tool mode `pcbtool route` on a fault's nets never repairs a shipped layout fault;
- the v2 normal / hard tiers are unaffected (sampled tasks: faulted 0.0, oracle 1.0)."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import get_context
from pathlib import Path

import pytest

from pcbenv import layout_rules as LR
from pcbenv import rules as R
from pcbenv import taskio
from pcbenv.board import build_board
from pcbenv.faults.latent import (LAYOUT_LATENT_TYPES, apply_latent, autoroute_fixes, layout_issues,
                                  layout_still_present, visible_failures)
from pcbenv.families import FAMILIES
from pcbenv.verify import verify

ROOT = Path(__file__).resolve().parent.parent
LAYOUT_FAMILIES = ("sys_motor_ctrl", "sys_clocked_mcu")
SWEEP_SEEDS = 20
WHERE = {"kelvin_sense_tap": "sys_motor_ctrl", "switch_loop_spread": "sys_motor_ctrl",
         "analog_near_switch": "sys_motor_ctrl", "crystal_far": "sys_clocked_mcu", "crystal_via": "sys_clocked_mcu",
         "decap_long_path": "sys_clocked_mcu"}
HL = ROOT / "tasks" / "v2" / "hard_layout"
HLH = ROOT / "tasks" / "v2" / "hard_layout_holdout"


def _golden(fam: str, seed: int):
    g, _ = R.harden(FAMILIES[fam].generate(seed))
    return g, LR.layout_rules_context(g)


def _rp(g) -> dict[str, str]:
    return {r: c["part"] for r, c in g.design["components"].items()}


def _sweep_one(args):
    fam, seed = args
    import sys as _s
    _s.path.insert(0, str(ROOT))
    g, ctx = _golden(fam, seed)
    with tempfile.TemporaryDirectory() as td:
        bp = os.path.join(td, "b.kicad_pcb")
        build_board(g, bp, 0, layout_rules=ctx)
        v = [f"{x.code}: {x.detail}" for x in LR.run_layout_rules(bp, ctx, _rp(g))]
        m = LR.metrics(bp, ctx, _rp(g))
    return fam, seed, v, m


# ------------------------------------------------------------------ goldens: every rule passes, with margin
def test_goldens_pass_layout_rules_with_margin():
    jobs = [(f, s) for f in LAYOUT_FAMILIES for s in range(SWEEP_SEEDS)]
    with get_context("spawn").Pool(4) as pool:
        res = pool.map(_sweep_one, jobs)
    worst = {}
    for fam, seed, v, m in res:
        assert not v, f"{fam}/{seed}: {v}"
        if fam == "sys_motor_ctrl":
            assert m["kelvin_ok"]
            worst["loop"] = max(worst.get("loop", 0), m["loop_area_mm2"] / LR.LOOP_MAX_AREA_MM2)
            worst["sep"] = max(worst.get("sep", 0), m["parallel_mm"] / LR.SEP_MAX_PARALLEL_MM)
        else:
            assert m["xtal_vias"] == 0
            worst["xtal"] = max(worst.get("xtal", 0), m["xtal_path_mm"] / LR.XTAL_MAX_PATH_MM)
    # the builder accepts only boards within GOLDEN_MARGIN of each limit
    assert all(v <= LR.GOLDEN_MARGIN + 1e-9 for v in worst.values()), worst


def test_context_only_for_layout_composites():
    for fam in ("sys_sensor_node", "sys_analog_frontend", "ldo_reg", "nmos_switch"):
        g, ctx = _golden(fam, 0)
        assert not any(k in ctx for k in ("kelvin", "switch_loop", "separation")), fam
    g, ctx = _golden("sys_motor_ctrl", 0)
    assert {"kelvin", "switch_loop", "separation"} <= set(ctx)
    g, ctx = _golden("sys_clocked_mcu", 0)
    assert "crystal" in ctx


def test_golden_board_with_rules_is_deterministic(tmp_path):
    g, ctx = _golden("sys_motor_ctrl", 3)
    a, b = tmp_path / "a.kicad_pcb", tmp_path / "b.kicad_pcb"
    build_board(g, str(a), 0, layout_rules=ctx)
    build_board(g, str(b), 0, layout_rules=ctx)
    assert a.read_bytes() == b.read_bytes()


def test_v2_boards_unchanged_without_rules(tmp_path):
    """build_board without layout_rules is the v2 builder: the shipped hard golden boards rebuild
    byte-identically (sampled)."""
    from pcbenv.faults.common import canonical_board_file
    rows = [json.loads(x) for x in (ROOT / "tasks" / "private" / "hard.jsonl").read_text().splitlines()
            if x.strip()] if (ROOT / "tasks" / "private" / "hard.jsonl").exists() else []
    rows = [r for r in rows if not r.get("dropped")][:3]
    if not rows:
        pytest.skip("private hard manifest not present")
    for r in rows:
        tdir = ROOT / "tasks" / r["split"] / r["id"]
        meta = taskio.load_meta(tdir)
        g, _ = R.harden(FAMILIES[meta["family"]].generate(meta["seed"]))
        out = tmp_path / f"{r['id']}.kicad_pcb"
        build_board(g, str(out), 0)
        canonical_board_file(str(out), f"{g.family}:{g.seed}:0:hard")
        assert out.read_bytes() == (tdir / "hidden" / "golden_board.kicad_pcb").read_bytes(), r["id"]


# ------------------------------------------------------------------ each rule fails on a targeted mutation
@pytest.fixture(scope="module")
def goldens(tmp_path_factory):
    root = tmp_path_factory.mktemp("lrg")
    out = {}
    for fam in LAYOUT_FAMILIES:
        for seed in range(3):
            g, ctx = _golden(fam, seed)
            bp = str(root / f"{fam}_{seed}.kicad_pcb")
            build_board(g, bp, 0, layout_rules=ctx)
            out[(fam, seed)] = (g, ctx, bp)
    return out


def _add_track(board, net_code: int, layer, x1, y1, x2, y2, w=0.25):
    import pcbnew
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(int(x1 * 1e6), int(y1 * 1e6)))
    t.SetEnd(pcbnew.VECTOR2I(int(x2 * 1e6), int(y2 * 1e6)))
    t.SetWidth(int(w * 1e6))
    t.SetLayer(layer)
    t.SetNetCode(net_code)
    board.Add(t)


def _codes(board, ctx, g) -> set[str]:
    return {v.code for v in LR.run_layout_rules(board, ctx, _rp(g))}


def test_kelvin_fails_when_sense_touches_power_path(goldens):
    import pcbnew
    from pcbenv.boardnet import load_board
    g, ctx, bp = goldens[("sys_motor_ctrl", 0)]
    b = load_board(bp)
    assert "kelvin_sense" not in _codes(b, ctx, g)
    r = ctx["kelvin"][0]
    s, q = LR._pad(b, r["sense_pin"], _rp(g)), LR._pad(b, r["load_pins"][0], _rp(g))
    (x1, y1), (x2, y2) = LR._xy(s), LR._xy(q)
    _add_track(b, s.GetNetCode(), pcbnew.F_Cu, x1, y1, x2, y2)
    assert "kelvin_sense" in _codes(b, ctx, g)


def test_kelvin_allows_meeting_inside_the_shunt_pad(goldens, tmp_path):
    """v2.1 (QA F1): the textbook Kelvin layout -- the load track and the sense track both run to the
    shunt pad centre and meet only inside the pad -- passes; a sense track that tees into the load
    track just outside the pad still fails."""
    import pcbnew
    from pcbenv.boardnet import load_board
    passed = 0
    for seed in range(3):
        g, ctx, bp = goldens[("sys_motor_ctrl", seed)]
        r = ctx["kelvin"][0]
        b = load_board(bp)
        sh = LR._pad(b, r["shunt_pin"], _rp(g))
        c = sh.GetPosition()
        moved = 0
        for t in b.GetTracks():
            if t.GetNetCode() != sh.GetNetCode() or t.GetClass() == "PCB_VIA":
                continue
            for get, set_ in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
                p = get()
                if sh.HitTest(p) and p != c:
                    set_(pcbnew.VECTOR2I(c.x, c.y))
                    moved += 1
        assert moved >= 2
        ok, why = LR.kelvin_ok(b, r, _rp(g))
        out = tmp_path / f"centre_{seed}.kicad_pcb"
        b.Save(str(out))
        if not ok:   # the moved ends made the two tracks merge before the pad edge: real sharing
            assert "outside the shunt pad" in why
            continue
        assert "kelvin_sense" not in _codes(str(out), ctx, g)
        passed += 1
        # a stub from the sense track to the load track, outside the pad -> shared copper
        q = LR._pad(b, r["load_pins"][0], _rp(g))
        s = LR._pad(b, r["sense_pin"], _rp(g))
        (x1, y1), (x2, y2) = LR._xy(s), LR._xy(q)
        _add_track(b, s.GetNetCode(), pcbnew.F_Cu, x1, y1, x2, y2)
        assert "kelvin_sense" in _codes(b, ctx, g)
    assert passed >= 1


def test_loop_area_formula_and_limit(goldens):
    assert LR.shoelace([(0, 0), (4, 0), (4, 3), (0, 3)]) == pytest.approx(12.0)
    assert LR.shoelace([(0, 0), (0, 3), (4, 3), (4, 0)]) == pytest.approx(12.0)   # orientation-free
    g, ctx, bp = goldens[("sys_motor_ctrl", 1)]
    a = LR.loop_area(bp, ctx["switch_loop"][0], _rp(g))
    assert 0 < a <= LR.LOOP_MAX_AREA_MM2 * LR.GOLDEN_MARGIN
    tight = json.loads(json.dumps(ctx))
    tight["switch_loop"][0]["max_area_mm2"] = a * 0.9
    assert "switch_loop_area" in _codes(bp, tight, g)


def test_crystal_via_and_length_fail(goldens):
    import pcbnew
    from pcbenv.boardnet import load_board
    g, ctx, bp = goldens[("sys_clocked_mcu", 0)]
    r = ctx["crystal"][0]
    tight = json.loads(json.dumps(ctx))
    m = LR.metrics(bp, ctx, _rp(g))
    tight["crystal"][0]["max_path_mm"] = m["xtal_path_mm"] * 0.9
    assert "crystal_trace" in _codes(bp, tight, g)
    b = load_board(bp)
    p = LR._pad(b, r["pairs"][0][0], _rp(g))
    via = pcbnew.PCB_VIA(b)
    x, y = LR._xy(p)
    via.SetPosition(pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6)))
    via.SetWidth(int(0.6e6))
    via.SetDrill(int(0.3e6))
    via.SetNetCode(p.GetNetCode())
    b.Add(via)
    assert "crystal_via" in _codes(b, ctx, g)


def test_separation_fails_on_parallel_run(goldens):
    import pcbnew
    from pcbenv.boardnet import load_board
    g, ctx, bp = goldens[("sys_motor_ctrl", 2)]
    b = load_board(bp)
    r = ctx["separation"][0]
    vcode = LR._pad(b, r["victim_pins"][0], _rp(g)).GetNetCode()
    acode = LR._pad(b, r["aggressor_pins"][0], _rp(g)).GetNetCode()
    assert LR.parallel_length(b, vcode, acode, r["min_gap_mm"]) <= r["max_parallel_mm"]
    _add_track(b, acode, pcbnew.B_Cu, 110.0, 105.0, 116.0, 105.0)
    _add_track(b, vcode, pcbnew.B_Cu, 110.0, 105.7, 116.0, 105.7)
    assert LR.parallel_length(b, vcode, acode, r["min_gap_mm"]) == pytest.approx(
        LR.parallel_length(load_board(bp), vcode, acode, r["min_gap_mm"]) + 6.0, abs=1e-3)
    assert "analog_separation" in _codes(b, ctx, g)
    # v2.1 (QA F3 loophole): a parallel run on the OPPOSITE layer (here directly over the switching
    # node, broadside) counts too; v2.0 ignored it ("only same-layer copper counts")
    b2 = load_board(bp)
    _add_track(b2, acode, pcbnew.B_Cu, 110.0, 105.0, 116.0, 105.0)
    _add_track(b2, vcode, pcbnew.F_Cu, 110.0, 105.0, 116.0, 105.0)
    assert LR.parallel_length(b2, vcode, acode, r["min_gap_mm"]) == pytest.approx(
        LR.parallel_length(load_board(bp), vcode, acode, r["min_gap_mm"]) + 6.0, abs=1e-3)
    assert LR.parallel_length(b2, vcode, acode, r["min_gap_mm"], same_layer_only=True) == pytest.approx(
        LR.parallel_length(load_board(bp), vcode, acode, r["min_gap_mm"], same_layer_only=True), abs=1e-3)
    assert "analog_separation" in _codes(b2, ctx, g)
    # ... but a perpendicular crossing on the opposite layer is not a parallel run
    b3 = load_board(bp)
    _add_track(b3, acode, pcbnew.B_Cu, 110.0, 105.0, 116.0, 105.0)
    _add_track(b3, vcode, pcbnew.F_Cu, 113.0, 102.0, 113.0, 108.0)
    assert LR.parallel_length(b3, vcode, acode, r["min_gap_mm"]) == pytest.approx(
        LR.parallel_length(load_board(bp), vcode, acode, r["min_gap_mm"]), abs=1e-3)


# ------------------------------------------------------------------ layout-latent faults
@pytest.fixture(scope="module")
def layout_cases(goldens, tmp_path_factory):
    """type -> (task_dir, golden, record, golden board)."""
    root = tmp_path_factory.mktemp("lrcases")
    out = {}
    for t, fam in WHERE.items():
        found = None
        for seed in range(3):
            g, ctx, gb = goldens[(fam, seed)]
            d = json.loads(json.dumps(g.design))
            b = str(root / f"{t}_{seed}.kicad_pcb")
            shutil.copyfile(gb, b)
            rec = apply_latent(t, g, d, b, random.Random(f"test:{t}"), salt=t)
            if rec is not None:
                found = (g, ctx, gb, d, b, rec)
                break
        assert found, f"no applicable instance of {t}"
        g, ctx, gb, d, b, rec = found
        assert d == g.design            # board-only fault
        td = root / f"task_{t}"
        taskio.write_task(td, g, gb, public_design=d, public_board=b, faults=[rec.to_dict()],
                          extra_meta={"tier": "hard_layout", "rules": R.rules_context(g), "layout_rules": ctx},
                          hard=True)
        (td / "public" / "tools.json").write_text(json.dumps({"mode": "full"}))
        out[t] = (str(td), g, rec, gb)
    return out


def _pcbtool(wd: str, *args: str) -> subprocess.CompletedProcess:
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from pcbenv.tool import main; sys.exit(main())"
    return subprocess.run([sys.executable, "-c", code, *args], cwd=wd, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("ftype", sorted(LAYOUT_LATENT_TYPES))
def test_layout_fault_valid_invisible_detected(layout_cases, ftype, tmp_path):
    from pcbenv import drc
    tdir, g, rec, gb = layout_cases[ftype]
    pub = os.path.join(tdir, "public")
    board = os.path.join(pub, "board.kicad_pcb")
    r = drc.run_drc(board)
    assert not r.errors and not r.unconnected
    assert visible_failures(g, g.design, board) == []
    wd = str(tmp_path / "wd")
    taskio.copy_public(tdir, wd)
    p = _pcbtool(wd, "check")
    assert p.returncode == 0, p.stdout[-2000:]          # the real tool sees nothing
    res = verify(wd, tdir)
    failing = {k for k, v in {**res.gates, **res.checks}.items() if not v}
    assert res.reward == 0.0 and failing and failing <= {"layout_rules", "layout"}, failing
    assert layout_still_present(rec.to_dict(), g, board)
    assert rec.data["metric_ratio"] >= 1.25 or rec.data["metric_ratio"] == float("inf")
    # one rule only
    codes = set(layout_issues(g, board))
    assert codes <= set(LAYOUT_LATENT_TYPES[ftype].rule_codes), codes


@pytest.mark.parametrize("ftype", sorted(LAYOUT_LATENT_TYPES))
def test_layout_fault_repairable_by_board_edits(layout_cases, ftype, tmp_path):
    """Restoring the golden copper (the oracle board edit) scores 1.0; for the routing faults a
    targeted hand-style re-route of the faulted branch also scores 1.0."""
    tdir, g, rec, gb = layout_cases[ftype]
    wd = str(tmp_path / "wd")
    taskio.copy_public(tdir, wd)
    shutil.copyfile(gb, os.path.join(wd, "board.kicad_pcb"))
    assert verify(wd, tdir).reward == 1.0
    if ftype in ("kelvin_sense_tap", "decap_long_path"):
        from pcbenv.faults import geom as G
        from pcbenv.faults.common import load_board, net_width, save_board
        from pcbenv.faults.latent import _board_pad, _key
        wd2 = str(tmp_path / "wd2")
        taskio.copy_public(tdir, wd2)
        bp = os.path.join(wd2, "board.kicad_pcb")
        b = load_board(bp)
        if ftype == "kelvin_sense_tap":
            r = LR.layout_rules_context(g)["kelvin"][0]
            sp, hp = _board_pad(b, g, r["sense_pin"]), _board_pad(b, g, r["shunt_pin"])
            code = hp.GetNetCode()
            # rip the net, route the load path, then the sense trace from the shunt pad as its own branch
            G.delete_items(b, [t for t in b.GetTracks() if t.GetNetCode() == code])
            name = b.GetNetInfo().GetNetItem(code).GetNetname()
            w = net_width(g, name)
            G.route_branch(b, code, _key(g, r["load_pins"][0]), _key(g, r["shunt_pin"]), w, isolated=False)
            G.route_branch(b, code, _key(g, r["sense_pin"]), _key(g, r["shunt_pin"]), w, isolated=True)
        else:
            d = rec.data
            cpin = next(f"{d['cap']}.{p}" for p in ("1", "2") if f"{d['cap']}.{p}" in
                        g.design["nets"][next(n for n, ps in g.design["nets"].items() if d["ic_pin"] in ps)])
            p = _board_pad(b, g, cpin)
            code = p.GetNetCode()
            G.detach_pad(b, p)
            name = b.GetNetInfo().GetNetItem(code).GetNetname()
            G.reconnect(b, code, net_width(g, name), skip={_key(g, cpin)})
            G.route_branch(b, code, _key(g, cpin), _key(g, d["ic_pin"]), net_width(g, name), isolated="prefer")
        save_board(b, bp, "repair")
        res = verify(wd2, tdir)
        assert res.reward == 1.0, (res.checks, res.detail)


def test_autoroute_check_is_consistent(layout_cases):
    """`autoroute_fixes` is what the generator uses to force no_autoroute; for the routing-only
    faults (sense tap / long decap path / analog re-route / via) a re-route is enough, for the
    placement faults (moved crystal / loop part) it never is."""
    for t in ("crystal_far", "switch_loop_spread"):
        tdir, g, rec, gb = layout_cases[t]
        assert not autoroute_fixes(g, g.design, os.path.join(tdir, "public", "board.kicad_pcb"), rec.to_dict())


# ------------------------------------------------------------------ shipped hard_layout tasks
def _shipped() -> list[Path]:
    return sorted(p for d in (HL, HLH) if d.is_dir() for p in d.iterdir() if (p / "hidden").is_dir())


def test_shipped_hard_layout_split():
    tasks = _shipped()
    if not tasks:
        pytest.skip("tasks/v2/hard_layout not generated")
    rows = [json.loads(x) for d in (HL, HLH) for x in (d / "manifest.jsonl").read_text().splitlines() if x.strip()]
    assert len([r for r in rows if not r["holdout"]]) >= 150
    assert len(rows) == len(tasks)
    nh = sum(r["holdout"] for r in rows)
    assert abs(nh / len(rows) - 0.2) < 0.01
    noauto = sum(r["tools_mode"] == "no_autoroute" for r in rows)
    assert noauto / len(rows) >= 0.6
    for r in rows:
        assert 3 <= r["n_faults"] <= 6 and r["n_layout"] >= 1 and r["n_latent"] - r["n_layout"] >= 1
        assert r["family"] in LAYOUT_FAMILIES and "seed" not in r and "index" not in r
        if r["tools_mode"] == "full":
            assert not r["autoroute_fixable"]
    man = [json.loads(x) for x in (ROOT / "tasks" / "manifest.jsonl").read_text().splitlines() if x.strip()]
    ids = {r["id"] for r in man if r["split"] in ("v2/hard_layout", "v2/hard_layout_holdout")}
    assert ids == {r["id"] for r in rows}


def _sample(paths: list[Path], n: int, seed: str) -> list[Path]:
    paths = sorted(paths)
    random.Random(seed).shuffle(paths)
    return paths[:n]


def test_shipped_hard_layout_public_text_and_meta():
    tasks = _shipped()
    if not tasks:
        pytest.skip("tasks/v2/hard_layout not generated")
    for t in _sample(tasks, 25, "text"):
        meta = taskio.load_meta(t)
        task_md = (t / "public" / "TASK.md").read_text()
        spec = json.loads((t / "public" / "spec.json").read_text())
        assert meta["tier"] == "hard_layout" and meta["layout_rules"] == spec["layout_rules"]
        assert "## Layout rules (board geometry)" in task_md and "`pcbtool` does not check any of them" in task_md
        mode = json.loads((t / "public" / "tools.json").read_text())["mode"]
        assert mode == meta["tools_mode"]
        if "switch_loop" in meta["layout_rules"]:
            assert "shoelace" in task_md and f"{LR.LOOP_MAX_AREA_MM2:g} mm²" in task_md
        if "crystal" in meta["layout_rules"]:
            assert f"≤ {LR.XTAL_MAX_PATH_MM:g} mm" in task_md and "no via" in task_md


def _verify_pair(task: str) -> tuple[str, float, float]:
    import sys as _s
    _s.path.insert(0, str(ROOT))
    from pcbenv import taskio as T
    from pcbenv.verify import verify as V
    faulted = V(os.path.join(task, "public"), task).reward
    with tempfile.TemporaryDirectory() as wd:
        T.copy_public(task, wd)
        shutil.copyfile(os.path.join(task, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
        shutil.copyfile(os.path.join(task, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
        oracle = V(wd, task).reward
    return task, faulted, oracle


@pytest.mark.parametrize("split,n", [("hard_layout", 30), ("normal", 30), ("hard", 30)])
def test_sampled_tasks_faulted_zero_oracle_one(split, n):
    """Shipped tasks under the current code: faulted 0.0, oracle repair 1.0 (v2 normal / hard unaffected
    by the layout-rules work; hard_layout gated)."""
    dirs = [ROOT / "tasks" / "v2" / split, ROOT / "tasks" / "v2" / f"{split}_holdout"]
    tasks = [str(p) for d in dirs if d.is_dir() for p in d.iterdir() if (p / "hidden").is_dir()]
    if not tasks:
        pytest.skip(f"tasks/v2/{split} not present")
    sample = _sample([Path(t) for t in tasks], n, f"sample:{split}")
    with get_context("spawn").Pool(4) as pool:
        res = pool.map(_verify_pair, [str(p) for p in sample])
    bad = [(t, f, o) for t, f, o in res if f != 0.0 or o != 1.0]
    assert not bad, bad


def test_full_mode_route_does_not_fix_shipped_layout_faults(tmp_path):
    """For shipped full-mode tasks: running the real `pcbtool route` on every net a layout fault
    touched leaves that layout rule violated (the generator forces no_autoroute otherwise)."""
    tasks = [t for t in _shipped() if taskio.load_meta(t)["tools_mode"] == "full"]
    if not tasks:
        pytest.skip("no full-mode hard_layout tasks")
    for t in _sample(tasks, 6, "route"):
        meta = taskio.load_meta(t)
        renames = meta.get("public_net_renames") or {}
        for f in meta["faults"]:
            if f["type"] not in LAYOUT_LATENT_TYPES:
                continue
            for net in f["data"].get("nets", []):
                wd = str(tmp_path / f"{t.name}_{f['type']}_{len(os.listdir(tmp_path))}")
                taskio.copy_public(t, wd)
                pub_net = renames.get(net, net)
                p = _pcbtool(wd, "route", pub_net)
                assert p.returncode in (0, 1), p.stderr[-500:]
                lc = meta["layout_rules"]
                from pcbenv.boardnet import load_board
                b = load_board(os.path.join(wd, "board.kicad_pcb"))
                codes = {v.code for v in LR.run_layout_rules(b, lc, meta["ref_parts"])}
                if f["type"] == "decap_long_path":
                    continue  # decap faults are autoroute-fixable by construction -> never full mode
                assert codes & set(LAYOUT_LATENT_TYPES[f["type"]].rule_codes), (t.name, f["type"], net)


def test_no_autoroute_mode_refuses_route():
    tasks = [t for t in _shipped() if taskio.load_meta(t)["tools_mode"] == "no_autoroute"]
    if not tasks:
        pytest.skip("no no_autoroute hard_layout tasks")
    t = tasks[0]
    with tempfile.TemporaryDirectory() as wd:
        taskio.copy_public(t, wd)
        net = sorted(json.loads((t / "public" / "design.json").read_text())["nets"])[0]
        assert _pcbtool(wd, "route", net).returncode == 2


def test_generator_deterministic(tmp_path):
    """Same index + secret -> the same task id and byte-identical task files."""
    from pcbenv.generate_hard_layout import build_one_layout
    outs = []
    for k in range(2):
        st = tmp_path / f"s{k}"
        st.mkdir()
        r = build_one_layout((1, str(st), "default"))
        assert r["ok"], r.get("reason")
        tdir = st / r["entry"]["id"]
        outs.append((r["entry"]["id"], {str(p.relative_to(tdir)): p.read_bytes() for p in sorted(tdir.rglob("*"))
                                         if p.is_file()}))
    assert outs[0][0] == outs[1][0]
    assert outs[0][1] == outs[1][1]
