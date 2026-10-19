"""G12 latent faults (`pcbenv/faults/latent.py`), tool mode, hard-tier generator, v1 verdicts.

Per latent type: the injection is valid, every pcbtool check passes on the faulted files (checked
with the real `pcbtool check` too), the verifier fails it only through `rules` / `topology`, and
pcbtool commands (full mode) repair it to 1.0."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pcbenv import design as D
from pcbenv import rules as R
from pcbenv import taskio
from pcbenv.board import build_board
from pcbenv.faults.latent import LATENT_TYPES, apply_latent, still_present, visible_failures
from pcbenv.families import FAMILIES
from pcbenv.verify import verify

ROOT = str(Path(__file__).resolve().parent.parent)
WHERE = {  # families to search for an applicable instance of each type
    "resistor_underrated": ["led_driver"], "capacitor_underrated": ["nmos_switch", "ldo_reg"],
    "led_underrated": ["led_driver", "npn_switch"], "weak_base_drive": ["npn_switch"],
    "flyback_misplaced": ["nmos_switch", "npn_switch"], "connector_pin_swap": ["mcu_i2c", "nmos_switch"],
    "mcu_pin_swap": ["mcu_i2c"], "decap_swapped": ["ldo_reg"], "bias_wrong_rail": ["opamp_inv", "opamp_noninv"],
}


def _pcbtool(wd: str, *args: str) -> subprocess.CompletedProcess:
    code = f"import sys; sys.path.insert(0, {ROOT!r}); from pcbenv.tool import main; sys.exit(main())"
    return subprocess.run([sys.executable, "-c", code, *args], cwd=wd, capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def latent_cases(tmp_path_factory):
    """type -> (task_dir, golden, record): a hard-style task with that one latent fault."""
    root = tmp_path_factory.mktemp("latent")
    out = {}
    boards: dict = {}
    for t, fams in WHERE.items():
        found = None
        for fam in fams:
            for s in range(12):
                key = (fam, s)
                if key not in boards:
                    g, _ = R.harden(FAMILIES[fam].generate(s))
                    gb = str(root / f"{fam}_{s}.kicad_pcb")
                    build_board(g, gb, 0)
                    boards[key] = (g, gb)
                g, gb = boards[key]
                d = json.loads(json.dumps(g.design))
                b = str(root / f"{t}.kicad_pcb")
                shutil.copyfile(gb, b)
                rec = apply_latent(t, g, d, b, random.Random(f"test:{t}"), salt=t)
                if rec is not None:
                    found = (g, gb, d, b, rec)
                    break
            if found:
                break
        assert found, f"no applicable instance of {t}"
        g, gb, d, b, rec = found
        td = root / f"task_{t}"
        taskio.write_task(td, g, gb, public_design=d, public_board=b, faults=[rec.to_dict()],
                          extra_meta={"tier": "hard", "rules": R.rules_context(g)})
        (td / "public" / "tools.json").write_text(json.dumps({"mode": "full"}))
        out[t] = (str(td), g, rec)
    return out


@pytest.mark.parametrize("ftype", sorted(LATENT_TYPES))
def test_latent_valid_invisible_detected(latent_cases, ftype, tmp_path):
    td, g, rec = latent_cases[ftype]
    pub = os.path.join(td, "public")
    d = D.load(os.path.join(pub, "design.json"))  # validates
    assert rec.category == "latent" and rec.data["latent"] and rec.data["evidence"]
    assert still_present(rec.to_dict(), d, os.path.join(pub, "board.kicad_pcb"), g)
    assert visible_failures(g, d, os.path.join(pub, "board.kicad_pcb")) == []
    wd = str(tmp_path / "wd")
    shutil.copytree(pub, wd)
    p = _pcbtool(wd, "check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "all local checks pass" in p.stdout
    r = verify(wd, td)
    failing = {k for k, v in {**r.gates, **r.checks}.items() if not v}
    assert r.reward == 0.0 and failing and failing <= {"rules", "topology"}, (failing, r.detail)
    if "rules" in rec.data["detected_by"]:
        assert "rules" in failing
    if "topology" in rec.data["detected_by"]:
        assert "topology" in failing


def _repair_with_pcbtool(wd: str, golden: dict, rec) -> None:
    """Undo the fault using only pcbtool commands (full mode): footprints, values, then every
    moved pin back to its original net, re-routing the affected nets."""
    d = json.loads(Path(wd, "design.json").read_text())
    touched: set[str] = set()
    for ref, c in sorted(golden["components"].items()):
        cur = d["components"][ref]
        if cur["footprint"] != c["footprint"]:
            assert _pcbtool(wd, "set-footprint", ref, c["footprint"]).returncode == 0
            touched |= {n for n, ps in d["nets"].items() if any(p.startswith(ref + ".") for p in ps)}
        if cur["value"] != c["value"]:
            assert _pcbtool(wd, "set-value", ref, c["value"]).returncode == 0
    for pin, (old, new) in sorted(rec.data.get("moves", {}).items()):
        assert _pcbtool(wd, "connect", pin, old).returncode == 0
        touched |= {old, new} - {None}
    for n in sorted(touched):
        _pcbtool(wd, "unroute", n)
    for n in sorted(touched):
        if n in json.loads(Path(wd, "design.json").read_text())["nets"]:
            p = _pcbtool(wd, "route", n)
            assert p.returncode == 0, p.stderr


@pytest.mark.parametrize("ftype", sorted(LATENT_TYPES))
def test_latent_repairable_with_pcbtool(latent_cases, ftype, tmp_path):
    td, g, rec = latent_cases[ftype]
    wd = str(tmp_path / "wd")
    shutil.copytree(os.path.join(td, "public"), wd)
    _repair_with_pcbtool(wd, g.design, rec)
    r = verify(wd, td)
    assert r.reward == 1.0, ({**r.gates, **r.checks}, r.detail)


# ------------------------------------------------------------------ tool mode
def test_no_autoroute_blocks_route_and_sync(latent_cases, tmp_path):
    td, _, _ = latent_cases["decap_swapped"]
    wd = str(tmp_path / "wd")
    shutil.copytree(os.path.join(td, "public"), wd)
    Path(wd, "tools.json").write_text(json.dumps({"mode": "no_autoroute"}))
    before = Path(wd, "board.kicad_pcb").read_bytes()
    for args in (("route", "GND"), ("sync",)):
        p = _pcbtool(wd, *args)
        assert p.returncode == 2 and "no_autoroute" in p.stderr
    assert Path(wd, "board.kicad_pcb").read_bytes() == before
    assert _pcbtool(wd, "show").returncode == 0
    Path(wd, "tools.json").write_text(json.dumps({"mode": "full"}))
    assert _pcbtool(wd, "route", "GND").returncode == 0
    os.remove(os.path.join(wd, "tools.json"))
    assert _pcbtool(wd, "sync").returncode == 0


def test_parts_prints_task_datasheet(latent_cases, tmp_path):
    td, _, _ = latent_cases["capacitor_underrated"]
    wd = str(tmp_path / "wd")
    shutil.copytree(os.path.join(td, "public"), wd)
    Path(wd, "parts", "C.md").write_text(R.hard_datasheet("C"))
    assert "80 %" in _pcbtool(wd, "parts", "C").stdout


# ------------------------------------------------------------------ hard generator
def test_hard_generator_gates(tmp_path):
    from pcbenv.generate_hard import generate_hard
    st = generate_hard(str(tmp_path / "hard"), str(tmp_path / "hold"), 200000, 6, 0.2, workers=2,
                       log=lambda *_: None)
    assert st["accepted"] >= 4
    from pcbenv.generate import load_manifest
    for e in load_manifest(tmp_path / "hard" / "manifest.jsonl"):
        g = e["gates"]
        assert g["golden"] == 1.0 and g["faulted"] == 0.0 and g["oracle_repair"] == 1.0 and g["all_faults_present"]
        assert g["each_fault_detected"] == [0.0] * e["n_faults"]
        assert 2 <= e["n_faults"] <= 4 and e["n_latent"] >= 1
        assert e["hint_level"] in ("symptom", "vague") and e["tools_mode"] in ("full", "no_autoroute")
        for a in e["alone"]:
            if a.get("latent"):
                assert a["tool_visible"] == [] and set(a["failing"]) <= {"rules", "topology"}
        tdir = tmp_path / e["path"]
        meta = taskio.load_meta(tdir)
        assert meta["tier"] == "hard" and meta["rules"]["scenarios"]
        assert json.loads((tdir / "public" / "tools.json").read_text())["mode"] == e["tools_mode"]
        md = (tdir / "public" / "TASK.md").read_text()
        assert "## Design rules" in md and "does not check" in md
        for f in meta["faults"]:  # no fault names / details leak into the public prompt
            assert f["type"] not in md and f["detail"] not in md
    # deterministic: same seeds, different worker count -> byte-identical task trees
    generate_hard(str(tmp_path / "hard2"), str(tmp_path / "hold2"), 200000, 6, 0.2, workers=1, log=lambda *_: None)

    def tree(*roots):
        return {f"{r.name}/{p.relative_to(r)}": p.read_bytes() for r in roots for p in sorted(r.rglob("*"))
                if p.is_file() and p.name not in ("generation_stats.json", "manifest.jsonl")}
    a = tree(tmp_path / "hard", tmp_path / "hold")
    b = {k.replace("hard2/", "hard/").replace("hold2/", "hold/"): v for k, v in tree(tmp_path / "hard2", tmp_path / "hold2").items()}
    assert a == b


# ------------------------------------------------------------------ v1 verdicts unchanged
def _v1_sample(n: int = 50) -> list[Path]:
    root = Path(ROOT) / "tasks" / "train"
    if not root.is_dir():
        return []
    ids = sorted(p.name for p in root.iterdir() if (p / "hidden" / "meta.json").exists())
    return [root / i for i in random.Random(12).sample(ids, min(n, len(ids)))]


@pytest.mark.parametrize("td", _v1_sample(), ids=lambda p: p.name)
def test_v1_task_verdicts_unchanged(td, tmp_path):
    meta = taskio.load_meta(td)
    assert "rules" not in meta and "tier" not in meta
    r = verify(str(td / "public"), str(td))
    assert r.reward == 0.0 and "rules" not in r.checks
    wd = tmp_path / "oracle"
    taskio.copy_public(td, wd)
    shutil.copyfile(td / "hidden" / "golden_design.json", wd / "design.json")
    shutil.copyfile(td / "hidden" / "golden_board.kicad_pcb", wd / "board.kicad_pcb")
    assert verify(str(wd), str(td)).reward == 1.0
