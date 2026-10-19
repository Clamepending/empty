"""G4/G10 task generator: gates, determinism, dedupe, splits, TASK.md hint levels, packing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbenv import generate as G
from pcbenv import prompts
from pcbenv.faults import FAULT_TYPES
from pcbenv.families import FAMILIES

START, COUNT = 40, 10


def _tree_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.name != "generation_stats.json"}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("gen")
    a = G.generate(str(root / "a"), START, COUNT, 0.2, workers=4, log=lambda *_: None)
    b = G.generate(str(root / "b"), START, COUNT, 0.2, workers=2, log=lambda *_: None)
    return root, a, b


def test_generation_gated(runs):
    root, a, _ = runs
    entries = G.load_manifest(root / "a" / "manifest.jsonl")
    assert len(entries) == a["accepted"] >= COUNT - 1
    for e in entries:
        g = e["gates"]
        assert g["golden"] == 1.0 and g["faulted"] == 0.0 and g["oracle_repair"] == 1.0
        assert g["each_fault_detected"] == [0.0] * e["n_faults"] and g["all_faults_present"]
        assert 1 <= e["n_faults"] <= 3
        assert e["id"].startswith(f"pcbr-{e['family']}-{e['seed']}-") and len(e["id"].rsplit("-", 1)[1]) == 8
        td = root / "a" / e["split"] / e["id"]
        meta = json.loads((td / "hidden" / "meta.json").read_text())
        assert meta["task_id"] == e["id"] and len(meta["faults"]) == e["n_faults"]
        assert meta["hint_level"] == e["hint_level"]
        assert (td / "public" / "TASK.md").exists() and (td / "public" / "board.kicad_pcb").exists()
    assert {e["split"] for e in entries} == {"train", "holdout"}
    assert sum(e["split"] == "holdout" for e in entries) == round(0.2 * len(entries))


def test_generation_deterministic(runs):
    root, _, _ = runs
    assert _tree_hashes(root / "a") == _tree_hashes(root / "b")


def test_dedupe_against_manifest(runs, tmp_path):
    root, a, _ = runs
    st = G.generate(str(tmp_path / "again"), START, 3, 0.0, workers=2,
                    dedupe_against=[str(root / "a" / "manifest.jsonl")], log=lambda *_: None)
    assert st["accepted"] == 0 and st["drop_reasons"].get("duplicate", 0) >= 2
    entries = G.load_manifest(root / "a" / "manifest.jsonl")
    assert len({(e["golden_design_hash"], e["fault_set"]) for e in entries}) == len(entries)
    assert len({e["faulted_design_hash"] for e in entries}) == len(entries)


def _fault_words() -> list[str]:
    words = set(FAULT_TYPES)
    words |= {n.replace("_", " ") for n in FAULT_TYPES}
    return sorted(words)


def test_prompts_do_not_leak_fault_types(runs):
    root, _, _ = runs
    for e in G.load_manifest(root / "a" / "manifest.jsonl"):
        md = (root / "a" / e["split"] / e["id"] / "public" / "TASK.md").read_text()
        assert "## Deliverable" in md and "## Tools" in md and "pcbtool route" in md
        if e["hint_level"] in ("symptom", "vague"):
            low = md.lower()
            assert not [w for w in _fault_words() if w in low], (e["id"], e["hint_level"])
            for f in e["faults"]:
                assert f["detail"] not in md
        if e["hint_level"] == "vague":
            assert "Observations" not in md


def test_reduced_intent_drops_connection_bullets():
    for fam in sorted(FAMILIES):
        g = FAMILIES[fam].generate(3)
        red = prompts.reduce_intent(g.intent)
        assert "Spec" in red and prompts.REDUCED_NOTE in red
        assert not any(line.startswith("- ") for line in red.splitlines())
        assert len(red) < len(g.intent) + len(prompts.REDUCED_NOTE) + 10


def test_hint_levels_render():
    g = FAMILIES["ldo_reg"].generate(1)
    rec = {"type": "wrong_feedback_resistor", "category": "value", "detail": "R1 is 1k, should be 2k",
           "data": {"ref": "R1", "golden_value": "2k", "value": "1k"}}
    ex = prompts.render(g, "explicit", [rec], ["Bench: J2.1 reads 4 V"])
    sy = prompts.render(g, "symptom", [rec], ["Bench: J2.1 reads 4 V"])
    va = prompts.render(g, "vague", [rec], [])
    bullet = next(line for line in g.intent.splitlines() if line.startswith("- "))
    assert "the value of R1" in ex and bullet in ex
    assert "the value of R1" not in sy and bullet not in sy and "J2.1 reads 4 V" in sy and prompts.REDUCED_NOTE in sy
    assert "fail bring-up" in va and "J2.1 reads 4 V" not in va


def test_pack_deterministic(runs, tmp_path):
    root, _, _ = runs
    G.pack(root / "a" / "train", tmp_path / "x.tar.gz", "train")
    G.pack(root / "b" / "train", tmp_path / "y.tar.gz", "train")
    assert (tmp_path / "x.tar.gz").read_bytes() == (tmp_path / "y.tar.gz").read_bytes()
