"""v2 red-team fixes: value grammar (RT32/RT33/RT59), net-tie fingerprint (RT30), decoupling copper
path (RT31), neutral net names (RT34), hard-tier latent evidence (fairness)."""
from __future__ import annotations

import json
import math

import pytest

from pcbenv import boardnet, layout, netnames
from pcbenv import design as D
from pcbenv.board import build_board
from pcbenv.families import FAMILIES
from pcbenv.parts import parse_value, values_equal


@pytest.mark.parametrize("value,part,expected", [
    ("10k", "R", 1e4), (" 10k ", "R", 1e4), ("1.000000e+04", "R", 1e4), ("10kΩ", "R", 1e4), ("10kohm", "R", 1e4),
    ("10R", "R", 10.0), ("100nF", "C", 1e-7), ("4.7μ", "C", 4.7e-6), ("4.7µ", "C", 4.7e-6), ("1meg", "R", 1e6),
    ("1MEG", "R", 1e6), ("8MHz", "XTAL", 8e6), ("10uH", "L", 1e-5), (".5", "R", 0.5), ("1K", "R", 1e3),
])
def test_value_grammar_accepts(value, part, expected):
    assert parse_value(value, part) == pytest.approx(expected)


@pytest.mark.parametrize("value,part", [
    ("100nH", "C"), ("10kF", "R"), ("6.8n\n", "C"), ("1e3k", "R"), ("1 k", "R"), ("1f", "C"), ("1e999", "R"),
    ("4k7", "R"), ("+1k", "R"), ("1_000", "R"), ("8MHzz", "XTAL"), ("1k\t", "R"), ("", "R"), ("10V", "R"),
])
def test_value_grammar_rejects(value, part):
    with pytest.raises(ValueError):
        parse_value(value, part)


def test_values_compared_numerically():
    assert values_equal("1000", "1k", "R") and values_equal("100n", "0.1u", "C") and values_equal("", "", "LED_RED")
    assert not values_equal("1k", "1.1k", "R") and not values_equal("1k\n", "1k", "R")


def test_design_rejects_control_characters():
    g = FAMILIES["rc_lowpass"].generate(1)
    d = json.loads(json.dumps(g.design))
    ref = next(r for r, c in d["components"].items() if c["part"] == "C")
    d["components"][ref]["value"] += "\n"
    with pytest.raises(D.DesignError):
        D.validate(d)
    d = json.loads(json.dumps(g.design))
    d["components"]["J1"]["value"] = "x\x07"
    with pytest.raises(D.DesignError):
        D.validate(d)


def test_nettie_changes_fingerprint():
    fp = boardnet.library_footprint("Resistor_SMD:R_0805_2012Metric")
    assert boardnet.net_tie_groups(fp) == [False]
    fp.AddNetTiePadGroup("1, 2")
    assert boardnet.net_tie_groups(fp) == [True, ("1", "2")]
    assert boardnet.footprint_fingerprint(fp) != boardnet.library_pad_fingerprint("Resistor_SMD:R_0805_2012Metric")


@pytest.mark.parametrize("fam", ["ldo_reg", "mcu_i2c", "sys_sensor_node"])
def test_decoupling_copper_path(fam, tmp_path):
    g = FAMILIES[fam].generate(5)
    p = str(tmp_path / "b.kicad_pcb")
    build_board(g, p, 0)
    b = boardnet.load_board(p)
    rp = {r: c["part"] for r, c in g.design["components"].items()}
    for dc in g.decoupling:
        assert "max_path_mm" in dc
        path = layout.decoupling_path_mm(b, dc["cap"], dc["ic_pin"], rp)
        ref, pin = dc["ic_pin"].split(".", 1)
        ip = boardnet.pad_position(b, ref, pin, parts=rp)
        straight = min(math.hypot(x - ip[0], y - ip[1]) for x, y in
                       (boardnet.pad_position(b, dc["cap"], q, parts=rp) for q in ("1", "2")))
        assert straight - 1e-6 <= path <= layout.max_path_mm(dc), (dc, path, straight)
    # tracks of the decoupled net removed -> no copper path -> layout issue
    dc = g.decoupling[0]
    net = D.net_of(g.design, dc["ic_pin"])
    for t in list(b.GetTracks()):
        if t.GetNetname() == net:
            b.Delete(t)
    assert layout.decoupling_path_mm(b, dc["cap"], dc["ic_pin"], rp) is None


def test_netnames_rename_only_unreferenced():
    d = {"schema": D.SCHEMA, "components": {"R1": {"part": "R", "value": "1k", "footprint": ""},
                                           "R2": {"part": "R", "value": "1k", "footprint": ""},
                                           "J1": {"part": "CONN2", "value": "", "footprint": ""}},
         "nets": {"FB": ["R1.2", "R2.1"], "VIN": ["J1.1", "R1.1"], "GND": ["J1.2", "R2.2"], "EMPTY": []}}
    texts = ["Power enters on VIN; U1.FB is the feedback pin; GND"]
    m = netnames.rename_map(d, {}, texts)
    assert m == {"FB": "Net-(R1-Pad2)"}
    out = netnames.apply_to_design(d, m)
    assert set(out["nets"]) == {"Net-(R1-Pad2)", "VIN", "GND"}
