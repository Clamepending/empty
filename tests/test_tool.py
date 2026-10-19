"""pcbtool: every command works and mutating commands keep design.json and the board consistent."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pcbenv import boardnet
from pcbenv import design as D
from pcbenv.drc import run_drc
from pcbenv.parts import PARTS
from pcbenv.verify import verify
from tests.fixtures.verify_tasks import build_task, workdir

ROOT = Path(__file__).resolve().parent.parent
PCBTOOL = str(ROOT / "bin" / "pcbtool")


def run(wd, *args, ok=True) -> subprocess.CompletedProcess:
    p = subprocess.run([PCBTOOL, *args], cwd=wd, capture_output=True, text=True, timeout=300)
    if ok is True:
        assert p.returncode == 0, (args, p.stdout, p.stderr)
    elif ok is False:
        assert p.returncode != 0, (args, p.stdout, p.stderr)
    return p


@pytest.fixture(scope="module")
def tasks(tmp_path_factory):
    root = tmp_path_factory.mktemp("tooltasks")
    return {f: build_task(root, f, 0) for f in ("ldo_reg", "mcu_i2c", "led_driver", "xtal_osc")}


def _consistent(wd) -> bool:
    d = D.load(Path(wd, "design.json"))
    info = boardnet.board_info(str(Path(wd, "board.kicad_pcb")), design=d)
    return info.partition == D.partition(d) and all(
        info.values[r] == c["value"] and info.footprints[r] == c["footprint"] for r, c in d["components"].items())


def test_readonly_commands(tasks, tmp_path):
    wd = workdir(tasks["ldo_reg"], tmp_path / "w")
    before = {p: Path(wd, p).read_bytes() for p in ("design.json", "board.kicad_pcb")}
    assert "LDO_ADJ" in run(wd, "show").stdout
    assert "none: board connectivity matches" in run(wd, "netlist").stdout
    assert "DRC clean" in run(wd, "drc").stdout
    assert "ERC clean" in run(wd, "erc").stdout
    out = run(wd, "sim").stdout
    assert "PASS vout_loaded" in out and "FAIL" not in out
    assert "LDO_ADJ" in run(wd, "parts").stdout
    assert "VREF" in run(wd, "parts", "LDO_ADJ").stdout
    assert "all local checks pass" in run(wd, "check").stdout
    run(wd, "parts", "NOPE", ok=False)
    after = {p: Path(wd, p).read_bytes() for p in before}
    assert before == after


def test_cwd_cannot_shadow_pcbenv(tasks, tmp_path):
    wd = workdir(tasks["ldo_reg"], tmp_path / "w")
    Path(wd, "pcbenv").mkdir()
    Path(wd, "pcbenv", "__init__.py").write_text("raise SystemExit('shadowed')\n")
    assert "ERC clean" in run(wd, "erc").stdout


def test_set_value(tasks, tmp_path):
    td = tasks["ldo_reg"]
    wd = workdir(td, tmp_path / "w")
    orig = D.load(Path(wd, "design.json"))["components"]["R1"]["value"]
    run(wd, "set-value", "R1", "1k")
    assert _consistent(wd)
    r = verify(wd, td)
    assert r.gates["consistency"] and not r.checks["spec"] and r.reward == 0.0
    assert "FAIL" in run(wd, "sim", ok=False).stdout
    run(wd, "set-value", "R1", orig)
    assert verify(wd, td).reward == 1.0
    run(wd, "set-value", "R1", "banana", ok=False)
    run(wd, "set-value", "R77", "1k", ok=False)
    assert verify(wd, td).reward == 1.0  # failed commands change nothing


def test_connect_disconnect_roundtrip(tasks, tmp_path):
    td = tasks["ldo_reg"]
    wd = workdir(td, tmp_path / "w")
    d0 = D.load(Path(wd, "design.json"))
    net = next(n for n, p in d0["nets"].items() if "U1.EN" in p)
    run(wd, "disconnect", "U1.EN")
    assert _consistent(wd)
    r = verify(wd, td)
    assert r.gates["consistency"] and not r.gates["topology"] and not r.checks["erc"]
    assert "unconnected_required" in run(wd, "erc", ok=False).stdout
    run(wd, "connect", "U1.EN", net)
    assert _consistent(wd)
    assert D.partition(D.load(Path(wd, "design.json"))) == D.partition(d0)
    assert verify(wd, td).reward == 1.0
    # connect to a new net, then back
    run(wd, "connect", "U1.EN", "NEWNET")
    assert _consistent(wd)
    run(wd, "connect", "U1.EN", net)
    assert verify(wd, td).reward == 1.0
    run(wd, "connect", "U1.NOPE", net, ok=False)


@pytest.mark.parametrize("family", ["ldo_reg", "mcu_i2c", "led_driver", "xtal_osc"])
def test_unroute_route_every_net(tasks, tmp_path, family):
    td = tasks[family]
    wd = workdir(td, tmp_path / "w")
    d = D.load(Path(wd, "design.json"))
    for net in sorted(n for n, p in d["nets"].items() if len(p) >= 2):
        run(wd, "unroute", net)
        assert run_drc(str(Path(wd, "board.kicad_pcb"))).unconnected > 0, net
        run(wd, "route", net)
        assert "DRC clean" in run(wd, "drc").stdout, net
    r = verify(wd, td)
    assert r.reward == 1.0, (r.gates, r.checks, r.detail)


def test_route_width_option(tasks, tmp_path):
    td = tasks["ldo_reg"]
    wd = workdir(td, tmp_path / "w")
    run(wd, "route", "VIN", "--width", "0.2")
    info = boardnet.board_info(str(Path(wd, "board.kicad_pcb")))
    assert abs(info.track_widths["VIN"] - 0.2) < 1e-6
    r = verify(wd, td)
    assert not r.checks["layout"] and r.checks["drc"]
    run(wd, "route", "VIN")  # default = the spec's power width
    assert verify(wd, td).reward == 1.0


def test_set_footprint_and_move(tasks, tmp_path):
    td = tasks["ldo_reg"]
    wd = workdir(td, tmp_path / "w")
    d = D.load(Path(wd, "design.json"))
    cur = d["components"]["R2"]["footprint"]
    alt = next(f for f in PARTS["R"].footprints if f != cur)
    run(wd, "set-footprint", "R2", alt)
    assert _consistent(wd)
    r = verify(wd, td)
    assert r.gates["components"] and r.gates["consistency"] and r.gates["topology"]
    run(wd, "set-footprint", "R2", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", ok=False)
    run(wd, "set-footprint", "R2", cur)
    pos0 = boardnet.board_info(str(Path(wd, "board.kicad_pcb"))).positions["R2"]
    run(wd, "move", "R2", str(pos0[0] + 0.5), str(pos0[1]), "90")
    info = boardnet.board_info(str(Path(wd, "board.kicad_pcb")))
    assert info.positions["R2"] == (pos0[0] + 0.5, pos0[1], 90.0)
    assert _consistent(wd)


def test_sync(tasks, tmp_path):
    td = tasks["ldo_reg"]
    wd = workdir(td, tmp_path / "w")
    p = Path(wd, "design.json")
    d = json.loads(p.read_text())
    orig_val = d["components"]["R1"]["value"]
    d["components"]["R1"]["value"] = "47k"
    gnd = next(n for n, pins in d["nets"].items() if "U1.GND" in pins)
    vin = next(n for n, pins in d["nets"].items() if "U1.VIN" in pins)
    d["nets"][vin].remove("U1.EN")
    d["nets"][gnd].append("U1.EN")
    p.write_text(json.dumps(d))
    assert not _consistent(wd)
    out = run(wd, "sync").stdout
    assert "R1: value -> 47k" in out and "U1 pad 3" in out
    assert _consistent(wd)
    assert "already in sync" in run(wd, "sync").stdout
    d["components"]["R1"]["value"] = orig_val
    d["nets"][gnd].remove("U1.EN")
    d["nets"][vin].append("U1.EN")
    p.write_text(json.dumps(d))
    run(wd, "sync")
    assert verify(wd, td).reward == 1.0


def test_broken_files_reported(tasks, tmp_path):
    wd = workdir(tasks["ldo_reg"], tmp_path / "w")
    Path(wd, "design.json").write_text("{")
    p = run(wd, "show", ok=False)
    assert "cannot read design.json" in p.stderr
