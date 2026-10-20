"""G2 acceptance: board builder, router, DRC wrapper, board netlist extraction."""
from __future__ import annotations

import math
import os
import shutil
import statistics
import time

import pcbnew
import pytest

from pcbenv import boardnet, design as D
from pcbenv.board import ORIGIN, build_board
from pcbenv.drc import RULES, run_drc
from tests.fixtures.board_goldens import FIXTURES

try:
    import pcbenv.parts_lib  # noqa: F401  (registers more parts, if present)
except ImportError:  # pragma: no cover
    pass

try:
    from pcbenv.families import FAMILIES  # type: ignore
except Exception:  # pragma: no cover - families not available yet
    FAMILIES = {}

FAMILY_SEEDS = range(10)
FIXTURE_SEEDS = range(3)
MM = 1_000_000
TIMINGS: dict[str, list[float]] = {"build": [], "drc": []}

CASES = [("fixture", n, s) for n in sorted(FIXTURES) for s in FIXTURE_SEEDS] + \
        [("family", n, s) for n in sorted(FAMILIES) for s in FAMILY_SEEDS]


def _golden(kind: str, name: str, seed: int):
    return FIXTURES[name](seed) if kind == "fixture" else FAMILIES[name].generate(seed)


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("boards")
    cache: dict = {}

    def get(kind: str, name: str, seed: int):
        key = (kind, name, seed)
        if key not in cache:
            g = _golden(kind, name, seed)
            path = str(root / f"{kind}_{name}_{seed}.kicad_pcb")
            t = time.monotonic()
            build_board(g, path, 0)
            TIMINGS["build"].append(time.monotonic() - t)
            cache[key] = (g, path)
        return cache[key]
    return get


def test_families_registry_present():
    if not FAMILIES:
        pytest.skip("pcbenv.families.FAMILIES not importable yet; only fixture goldens tested")


@pytest.mark.parametrize("kind,name,seed", CASES, ids=[f"{n}-{s}" for _, n, s in CASES])
def test_built_board(built, kind, name, seed):
    g, path = built(kind, name, seed)
    t = time.monotonic()
    res = run_drc(path, path)
    TIMINGS["drc"].append(time.monotonic() - t)
    assert res.errors == [], res.errors[:5]
    assert res.unconnected == 0

    info = boardnet.board_info(path, g.design)
    assert info.partition == D.partition(g.design)
    comps = g.design["components"]
    assert set(info.footprints) == set(comps)
    for ref, c in comps.items():
        assert info.footprints[ref] == c["footprint"]
        assert info.values[ref] == c.get("value", "")
        assert info.pad_fingerprint[ref] == boardnet.library_pad_fingerprint(c["footprint"])
    assert info.zone_count == 0 and info.marker_count == 0 and info.exclusion_count == 0

    # outline
    x0, y0 = ORIGIN
    b = boardnet.load_board(path)
    bb = b.GetBoardEdgesBoundingBox()
    assert abs(bb.GetWidth() / MM - g.board_w_mm) < 0.1 and abs(bb.GetHeight() / MM - g.board_h_mm) < 0.1
    assert abs(bb.GetLeft() / MM - x0) < 0.1 and abs(bb.GetTop() / MM - y0) < 0.1

    # power net widths (nets with >= 2 pins must be routed at >= required width)
    for net, w in g.power_nets.items():
        if len(g.design["nets"].get(net, [])) >= 2:
            assert info.track_widths.get(net, 0) >= w - 1e-6, (net, info.track_widths.get(net), w)
    for net, mw in info.track_widths.items():
        assert mw >= RULES["track_min"] - 1e-6

    # decoupling: every pad of the cap within max_mm of the IC pin
    for dc in g.decoupling:
        ref, pin = dc["ic_pin"].split(".", 1)
        ix, iy = boardnet.pad_position(b, ref, pin, g.design)
        for cpin in ("1", "2"):
            cx, cy = boardnet.pad_position(b, dc["cap"], cpin, g.design)
            assert math.hypot(cx - ix, cy - iy) <= dc["max_mm"], (dc, cpin)
        # RT31: the cap is wired to the pin through a short copper path
        from pcbenv import layout
        path_mm = layout.decoupling_path_mm(b, dc["cap"], dc["ic_pin"], {r: c["part"] for r, c in g.design["components"].items()})
        assert path_mm is not None and path_mm <= layout.max_path_mm(dc), (dc, path_mm)


def test_deterministic(tmp_path):
    g = FIXTURES["fx_mesh"](1)
    a, b = str(tmp_path / "a.kicad_pcb"), str(tmp_path / "b.kicad_pcb")
    build_board(g, a, 3)
    build_board(g, b, 3)
    assert open(a, "rb").read() == open(b, "rb").read()
    c = str(tmp_path / "c.kicad_pcb")
    build_board(g, c, 4)
    ia, ic = boardnet.board_info(a, g.design), boardnet.board_info(c, g.design)
    assert ia.partition == ic.partition
    assert ia.positions != ic.positions  # another seed gives another layout


def test_timings_reported(built):
    # make sure at least one board was built, then print the timing summary
    built("fixture", "fx_rc", 0)
    bt, dt = TIMINGS["build"], TIMINGS["drc"] or [0.0]
    print(f"\nbuild: n={len(bt)} median={statistics.median(bt):.2f}s max={max(bt):.2f}s; "
          f"drc: median={statistics.median(dt):.2f}s max={max(dt):.2f}s")
    assert max(bt) < 60


# ------------------------------------------------------------ DRC catches faults
@pytest.fixture(scope="module")
def base_board(tmp_path_factory):
    g = FIXTURES["fx_rc"](0)
    path = str(tmp_path_factory.mktemp("base") / "board.kicad_pcb")
    build_board(g, path, 0)
    return g, path


def _mutate(base: str, out: str, fn) -> str:
    b = boardnet.load_board(base)
    fn(b)
    assert pcbnew.SaveBoard(out, b, True)
    return out


def _v(x, y):
    return pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM)))


def _track(b, net, x1, y1, x2, y2, w=0.25, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(_v(x1, y1)); t.SetEnd(_v(x2, y2)); t.SetWidth(int(w * MM)); t.SetLayer(layer)
    t.SetNet(b.FindNet(net))
    b.Add(t)
    return t


def _via(b, net, x, y, d=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(_v(x, y)); v.SetWidth(int(d * MM)); v.SetDrill(int(drill * MM))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(b.FindNet(net))
    b.Add(v)


def _types(res) -> set[str]:
    return {e["type"] for e in res.errors}


def test_drc_clean_base(base_board):
    _, path = base_board
    res = run_drc(path, path)
    assert res.errors == [] and res.unconnected == 0


def test_drc_track_clearance(base_board, tmp_path):
    _, path = base_board
    y = ORIGIN[1] + 1.5
    def f(b):
        _track(b, "N1", ORIGIN[0] + 2, y, ORIGIN[0] + 6, y, layer=pcbnew.B_Cu)
        _track(b, "OUT", ORIGIN[0] + 2, y + 0.35, ORIGIN[0] + 6, y + 0.35, layer=pcbnew.B_Cu)
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert "clearance" in _types(res)


def test_drc_short(base_board, tmp_path):
    g, path = base_board
    def f(b):
        p1 = boardnet.pad_position(b, "R1", "1", g.design)   # VIN
        p2 = boardnet.pad_position(b, "R1", "2", g.design)   # N1
        _track(b, "VIN", p1[0], p1[1], p2[0], p2[1])
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert "shorting_items" in _types(res) or "clearance" in _types(res)


def test_drc_unconnected(base_board, tmp_path):
    _, path = base_board
    def f(b):
        for t in list(b.GetTracks()):
            if t.GetNetname() == "OUT":
                b.Remove(t)
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert res.unconnected > 0


def test_drc_copper_edge(base_board, tmp_path):
    _, path = base_board
    def f(b):
        _track(b, "N1", ORIGIN[0] + 0.1, ORIGIN[1] + 3, ORIGIN[0] + 0.1, ORIGIN[1] + 6, layer=pcbnew.B_Cu)
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert "copper_edge_clearance" in _types(res)


def test_drc_track_width(base_board, tmp_path):
    _, path = base_board
    def f(b):
        _track(b, "N1", ORIGIN[0] + 2, ORIGIN[1] + 2, ORIGIN[0] + 4, ORIGIN[1] + 2, w=0.1, layer=pcbnew.B_Cu)
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert "track_width" in _types(res)


def test_drc_courtyard_overlap(base_board, tmp_path):
    _, path = base_board
    def f(b):
        a, c = b.FindFootprintByReference("R1"), b.FindFootprintByReference("R2")
        c.SetPosition(a.GetPosition() + _v(0.6, 0.6))
    res = run_drc(_mutate(path, str(tmp_path / "m.kicad_pcb"), f), path)
    assert "courtyards_overlap" in _types(res)


def test_drc_holes(base_board, tmp_path):
    _, path = base_board
    x, y = ORIGIN[0] + 3, ORIGIN[1] + 3
    def small(b):
        _via(b, "N1", x, y, d=0.5, drill=0.2)
    res = run_drc(_mutate(path, str(tmp_path / "a.kicad_pcb"), small), path)
    assert "drill_out_of_range" in _types(res) or "via_diameter" in _types(res)
    def near(b):
        _via(b, "N1", x, y)
        _via(b, "N1", x + 0.4, y)
    res = run_drc(_mutate(path, str(tmp_path / "b.kicad_pcb"), near), path)
    assert "hole_near_hole" in _types(res)


def test_drc_ignores_sidecar_rules(base_board, tmp_path):
    """A loosening .kicad_pro / .kicad_dru next to the candidate must have no effect."""
    _, path = base_board
    d = tmp_path / "w"
    d.mkdir()
    y = ORIGIN[1] + 1.5
    def f(b):
        _track(b, "N1", ORIGIN[0] + 2, y, ORIGIN[0] + 6, y, layer=pcbnew.B_Cu)
        _track(b, "OUT", ORIGIN[0] + 2, y + 0.3, ORIGIN[0] + 6, y + 0.3, layer=pcbnew.B_Cu)
    cand = _mutate(path, str(d / "board.kicad_pcb"), f)
    (d / "board.kicad_dru").write_text(
        '(version 1)\n(rule loose (constraint clearance (min 0mm)))\n')
    (d / "board.kicad_pro").write_text(
        '{"board": {"design_settings": {"rules": {"min_clearance": 0.0}, '
        '"rule_severities": {"clearance": "ignore"}}}, '
        '"net_settings": {"classes": [{"name": "Default", "clearance": 0.0}]}}')
    res = run_drc(cand, path)
    assert "clearance" in _types(res)


def test_drc_ignores_cwd_rules(base_board, tmp_path, monkeypatch):
    """KiCad resolves <name>.kicad_dru against the default project (= CWD) if the board has
    no project; run_drc sandboxes the board with its own project so this cannot apply."""
    _, path = base_board
    y = ORIGIN[1] + 1.5
    def f(b):
        _track(b, "N1", ORIGIN[0] + 2, y, ORIGIN[0] + 6, y, layer=pcbnew.B_Cu)
        _track(b, "OUT", ORIGIN[0] + 2, y + 0.3, ORIGIN[0] + 6, y + 0.3, layer=pcbnew.B_Cu)
    cand = _mutate(path, str(tmp_path / "board.kicad_pcb"), f)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "board.kicad_dru").write_text('(version 1)\n(rule loose (constraint clearance (min 0mm)))\n')
    monkeypatch.chdir(cwd)
    assert "clearance" in _types(run_drc(cand, path))


def test_drc_repeatable(base_board, tmp_path):
    """Regression for the KiCad 7 uninitialised m_DRCMaxClearance bug (see drc.py)."""
    g, path = base_board
    def f(b):
        ts = sorted((t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"), key=lambda t: -t.GetLength())
        for t in ts[:3]:
            t.Move(_v(0, 0.45))
    cand = _mutate(path, str(tmp_path / "m.kicad_pcb"), f)
    runs = [tuple(sorted((e["type"], e["pos"]) for e in run_drc(cand, path).errors)) for _ in range(25)]
    assert len(set(runs)) == 1 and runs[0]


# ------------------------------------------------------------- fingerprints etc
def test_pad_fingerprint(base_board, tmp_path):
    g, path = base_board
    info = boardnet.board_info(path, g.design)
    for ref, c in g.design["components"].items():
        assert info.pad_fingerprint[ref] == boardnet.library_pad_fingerprint(c["footprint"])

    def moved(b):  # move + rotate + flip: fingerprint unchanged
        fp = b.FindFootprintByReference("C1")
        fp.SetPosition(fp.GetPosition() + _v(1.3, -0.7))
        fp.SetOrientationDegrees(37)
        fp.Flip(fp.GetPosition(), True)
    i2 = boardnet.board_info(_mutate(path, str(tmp_path / "a.kicad_pcb"), moved), g.design)
    assert i2.pad_fingerprint["C1"] == info.pad_fingerprint["C1"]
    assert i2.positions["C1"] != info.positions["C1"] and i2.sides["C1"] == "B"

    def grown(b):
        pad = b.FindFootprintByReference("C1").Pads()[0]
        pad.SetSize(pad.GetSize() + _v(0.2, 0.0))
    i3 = boardnet.board_info(_mutate(path, str(tmp_path / "b.kicad_pcb"), grown), g.design)
    assert i3.pad_fingerprint["C1"] != info.pad_fingerprint["C1"]
    assert i3.pad_fingerprint["R1"] == info.pad_fingerprint["R1"]

    def clr(b):
        b.FindFootprintByReference("R1").Pads()[0].SetLocalClearance(int(0.05 * MM))
    i4 = boardnet.board_info(_mutate(path, str(tmp_path / "c.kicad_pcb"), clr), g.design)
    assert i4.pad_fingerprint["R1"] != info.pad_fingerprint["R1"]


def test_outline_and_netinfo(base_board, tmp_path):
    g, path = base_board
    info = boardnet.board_info(path, g.design)
    assert info.net_pins == {n: set(p) for n, p in g.design["nets"].items() if p}
    assert boardnet.board_partition(path, g.design) == D.partition(g.design)

    def edge(b):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(_v(ORIGIN[0] + 1, ORIGIN[1] + 1)); s.SetEnd(_v(ORIGIN[0] + 2, ORIGIN[1] + 1))
        b.Add(s)
    i2 = boardnet.board_info(_mutate(path, str(tmp_path / "a.kicad_pcb"), edge), g.design)
    assert i2.outline_fingerprint != info.outline_fingerprint

    def swap(b):  # swap the nets of R1's pads -> partition changes
        fp = b.FindFootprintByReference("R1")
        p1, p2 = fp.Pads()[0], fp.Pads()[1]
        n1, n2 = p1.GetNet(), p2.GetNet()
        p1.SetNet(n2); p2.SetNet(n1)
    i3 = boardnet.board_info(_mutate(path, str(tmp_path / "b.kicad_pcb"), swap), g.design)
    assert i3.partition != info.partition

    def zone(b):
        z = pcbnew.ZONE(b)
        z.SetLayer(pcbnew.F_Cu)
        z.AppendCorner(_v(ORIGIN[0] + 1, ORIGIN[1] + 1), -1)
        z.AppendCorner(_v(ORIGIN[0] + 3, ORIGIN[1] + 1), -1)
        z.AppendCorner(_v(ORIGIN[0] + 3, ORIGIN[1] + 3), -1)
        b.Add(z)
    i4 = boardnet.board_info(_mutate(path, str(tmp_path / "c.kicad_pcb"), zone), g.design)
    assert i4.zone_count == 1
