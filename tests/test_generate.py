"""G4/G10 task generator: gates, determinism, dedupe, splits, TASK.md hint levels, packing."""
from __future__ import annotations

import hashlib
import json
import re
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
    a = G.generate(str(root / "a"), START, COUNT, 0.2, workers=4, log=lambda *_: None,
                   private=str(root / "private_a.jsonl"))
    b = G.generate(str(root / "b"), START, COUNT, 0.2, workers=2, log=lambda *_: None)
    return root, a, b


def _rows(root: Path, name: str) -> list[dict]:
    """All public manifest rows of a run (train dir + holdout dir)."""
    return G.load_manifest(root / name / "manifest.jsonl") + G.load_manifest(root / f"{name}_holdout" / "manifest.jsonl")


def test_generation_gated(runs):
    root, a, _ = runs
    entries = _rows(root, "a")
    assert len(entries) == a["accepted"] >= COUNT - 1
    from pcbenv.families import V1_FAMILIES
    for e in entries:
        g = e["gates"]
        assert g["golden"] == 1.0 and g["faulted"] == 0.0 and g["oracle_repair"] == 1.0
        assert g["each_fault_detected"] == [0.0] * e["n_faults"] and g["all_faults_present"]
        assert 1 <= e["n_faults"] <= 3
        assert e["family"] in V1_FAMILIES and e["tier"] == "normal"
        # RT37: opaque id, no seed / index in the public manifest
        assert re.fullmatch(r"pcbr2-normal-[0-9a-f]{8}", e["id"]) and "seed" not in e and "index" not in e
        td = root / e["split"] / e["id"]
        assert e["path"] == f"{e['split']}/{e['id']}"
        meta = json.loads((td / "hidden" / "meta.json").read_text())
        assert meta["task_id"] == e["id"] and len(meta["faults"]) == e["n_faults"]
        assert meta["hint_level"] == e["hint_level"]
        assert (td / "public" / "TASK.md").exists() and (td / "public" / "board.kicad_pcb").exists()
        for f in (td / "public").rglob("*"):   # no id / seed in the public files
            if f.is_file():
                txt = f.read_text(encoding="utf-8", errors="replace")
                assert e["id"] not in txt and e["id"].rsplit("-", 1)[1] not in txt
                assert f'"seed": {meta["seed"]}' not in txt and str(meta["seed"]) not in txt
    assert {e["split"] for e in entries} == {"a", "a_holdout"}
    assert sum(e["holdout"] for e in entries) == round(0.2 * len(entries))
    priv = G.load_manifest(root / "private_a.jsonl")
    assert {p["id"] for p in priv if not p.get("dropped")} == {e["id"] for e in entries}
    assert all("seed" in p and "index" in p for p in priv if not p.get("dropped"))


def test_seeds_and_ids_depend_on_the_secret():
    from pcbenv import taskids
    a = taskids.task_seed("secret-a-xxxxxxxxxxxx", "normal", 5)
    assert a == taskids.task_seed("secret-a-xxxxxxxxxxxx", "normal", 5)
    assert a != taskids.task_seed("secret-b-xxxxxxxxxxxx", "normal", 5)
    assert a != taskids.task_seed("secret-a-xxxxxxxxxxxx", "hard", 5)
    i1 = taskids.task_id("secret-a-xxxxxxxxxxxx", "hard", 5, "c")
    assert re.fullmatch(r"pcbr2-hard-[0-9a-f]{8}", i1) and i1 != taskids.task_id("secret-b-xxxxxxxxxxxx", "hard", 5, "c")


def test_public_net_names_neutral(runs):
    """RT34: a public net is either named in TASK.md / spec.json or carries a KiCad-style auto name
    built from its own public pins (never a golden name nobody mentions)."""
    from pcbenv import netnames
    root, _, _ = runs
    for e in _rows(root, "a"):
        td = root / e["split"] / e["id"]
        d = json.loads((td / "public" / "design.json").read_text())
        texts = [(td / "public" / f).read_text() for f in ("TASK.md", "spec.json")]
        for name, pins in d["nets"].items():
            assert pins
            assert netnames.referenced(name, texts) or name == netnames.auto_name(d, pins) \
                or name.startswith(netnames.auto_name(d, pins) + "-"), (e["id"], name)
        renames = json.loads((td / "hidden" / "meta.json").read_text())["public_net_renames"]
        assert not any(netnames.referenced(old, texts) for old in renames)


def test_generation_deterministic(runs):
    root, _, _ = runs
    for x, y in (("a", "b"), ("a_holdout", "b_holdout")):
        ha = {k: v for k, v in _tree_hashes(root / x).items() if k != "manifest.jsonl"}
        hb = {k: v for k, v in _tree_hashes(root / y).items() if k != "manifest.jsonl"}
        assert ha and ha == hb
    norm = [dict(e, split=e["split"].replace("a", "X"), path=e["path"].replace("a", "X", 1)) for e in _rows(root, "a")]
    assert norm == [dict(e, split=e["split"].replace("b", "X"), path=e["path"].replace("b", "X", 1))
                    for e in _rows(root, "b")]


def test_dedupe_against_manifest(runs, tmp_path):
    root, a, _ = runs
    st = G.generate(str(tmp_path / "again"), START, 3, 0.0, workers=2,
                    dedupe_against=[str(root / "a" / "manifest.jsonl"), str(root / "a_holdout" / "manifest.jsonl")],
                    log=lambda *_: None)
    assert st["accepted"] == 0 and st["drop_reasons"].get("duplicate", 0) >= 2
    entries = _rows(root, "a")
    assert len({(e["golden_design_hash"], e["fault_set"]) for e in entries}) == len(entries)
    assert len({e["faulted_design_hash"] for e in entries}) == len(entries)


def _fault_words() -> list[str]:
    words = set(FAULT_TYPES)
    words |= {n.replace("_", " ") for n in FAULT_TYPES}
    return sorted(words)


def test_prompts_do_not_leak_fault_types(runs):
    root, _, _ = runs
    for e in _rows(root, "a"):
        md = (root / e["split"] / e["id"] / "public" / "TASK.md").read_text()
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
    tid = sorted(d.name for d in (root / "a").iterdir() if d.is_dir())[0]   # manifests differ by split name only
    G.pack(root / "a" / tid, tmp_path / "x.tar.gz", "t")
    G.pack(root / "b" / tid, tmp_path / "y.tar.gz", "t")
    assert (tmp_path / "x.tar.gz").read_bytes() == (tmp_path / "y.tar.gz").read_bytes()


def test_v21_holdout_membership_pinned_to_v20():
    """v2.1 regeneration keeps every generator index on the same side of the train / holdout line as
    in v2.0 (`--holdout-pin`): no v2.0 training golden became a v2.1 holdout task or vice versa."""
    import json as _json
    from pathlib import Path as _P
    from pcbenv.generate import holdout_pins
    root = _P(__file__).resolve().parent.parent / "tasks"
    arch = root / "v2.0_archive" / "private"
    if not arch.is_dir() or not (root / "private").is_dir():
        pytest.skip("v2.0 archive / private manifests not present (generation machine only)")
    for tier in ("normal", "hard", "hard_layout"):
        old, new = holdout_pins(str(arch / f"{tier}.jsonl")), holdout_pins(str(root / "private" / f"{tier}.jsonl"))
        both = set(old) & set(new)
        assert len(both) > 100, tier
        assert all(old[i] == new[i] for i in both), tier
        rows = [_json.loads(x) for x in (root / "private" / f"{tier}.jsonl").read_text().splitlines() if x.strip()]
        n = sum("id" in r for r in rows)
        assert abs(sum(new.values()) / n - 0.2) < 0.02, tier
