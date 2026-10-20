"""G9 QA packets (v2): deterministic build, train-only sampling, tier mix, verbatim TASK.md,
hard-tier reviewer sections, parseable forms (incl. v2 fields), tally."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from pcbenv import qa

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tasks" / "manifest.jsonl"
TASKS = ROOT / "tasks"
N_BUILD = 10

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="no shipped tasks")


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def _holdout_ids() -> set[str]:
    return {json.loads(line)["id"] for line in MANIFEST.read_text().splitlines()
            if line.strip() and qa.is_holdout_row(json.loads(line))}


@pytest.fixture(scope="module")
def rows_metas():
    rows = qa.load_train_rows(MANIFEST, TASKS)
    metas = {r["id"]: json.loads((qa.task_dir_of(TASKS, r) / "hidden" / "meta.json").read_text()) for r in rows}
    pub = {r["id"]: qa.public_text(qa.task_dir_of(TASKS, r)) for r in rows}
    return rows, metas, pub


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("qa_a")
    b = tmp_path_factory.mktemp("qa_b")
    sa = qa.build(N_BUILD, a / "packets", 3, MANIFEST, TASKS, workers=2)
    sb = qa.build(N_BUILD, b / "packets", 3, MANIFEST, TASKS, workers=1)
    return a, b, sa, sb


def test_build_deterministic(built):
    a, b, sa, sb = built
    assert [s["id"] for s in sa] == [s["id"] for s in sb]
    ta, tb = _tree(a), _tree(b)
    assert ta.keys() == tb.keys()
    diff = [k for k in ta if ta[k] != tb[k]]
    assert not diff, diff


def test_tier_mix_honored_in_build(built):
    _, _, sa, _ = built
    want = qa.tier_quotas(N_BUILD, qa.parse_mix(qa.DEFAULT_MIX))
    assert want == {"normal": 6, "hard": 3, "hard_layout": 1}
    assert Counter(s["tier"] for s in sa) == Counter(want)


def test_never_holdout(built):
    a, _, sa, _ = built
    holdout = _holdout_ids()
    assert holdout, "manifest has holdout tasks to exclude"
    assert not {s["id"] for s in sa} & holdout
    rows = qa.load_train_rows(MANIFEST, TASKS)
    assert not {r["id"] for r in rows} & holdout
    assert all(qa.task_dir_of(TASKS, r).is_dir() and "holdout" not in r["split"] for r in rows)
    text = "".join(p.read_text() for p in (a / "packets").rglob("README.md"))
    assert "holdout/" not in text and not any(h in text for h in holdout)
    with pytest.raises(ValueError):
        qa.parse_mix("normal=50,normal_holdout=50")


def test_build_packet_refuses_holdout(tmp_path):
    fake = tmp_path / "tasks" / "v2" / "normal_holdout" / "pcbr2-normal-00000000"  # never the real holdout split
    fake.mkdir(parents=True)
    with pytest.raises(ValueError):
        qa.build_packet({"id": fake.name, "family": "x", "faults": []}, fake, tmp_path / "out", 1, [])


def test_readme_contains_task_md_verbatim_and_verdicts(built):
    a, _, sa, _ = built
    rows = {r["id"]: r for r in qa.load_train_rows(MANIFEST, TASKS)}
    for s in sa:
        p = a / "packets" / s["packet"]
        readme = (p / "README.md").read_text(encoding="utf-8")
        td = qa.task_dir_of(TASKS, rows[s["id"]])
        task_md = (td / "public" / "TASK.md").read_text(encoding="utf-8")
        meta = json.loads((td / "hidden" / "meta.json").read_text())
        assert task_md.rstrip("\n") in readme
        assert "Reviewer-only" in readme and "### 2.3 Verifier verdicts" in readme
        assert s["faulted_reward"] == 0.0 and s["golden_reward"] == 1.0
        for svg in ("schematic_faulted.svg", "schematic_golden.svg", "board_faulted.svg", "board_golden.svg"):
            txt = (p / svg).read_text(encoding="utf-8")
            assert txt.startswith("<svg") and txt.rstrip().endswith("</svg>")
        if s["tier"] in ("hard", "hard_layout"):
            assert "### 2.7 Latent faults and their public evidence" in readme
            assert "### 2.8 Design rules" in readme and "| rules | check |" in readme
            assert "NOT FOUND in the public material" not in readme
        if s["tier"] == "hard_layout":
            assert "### 2.9 Layout rules" in readme and "| layout_rules | check |" in readme
            gsvg = (p / "board_golden.svg").read_text(encoding="utf-8")
            assert "layout rules: purple fill" in gsvg
            if meta["layout_rules"].get("switch_loop"):
                assert "switching-loop polygon" in gsvg and "switching-loop area" in readme
    index = (a / "INDEX.md").read_text(encoding="utf-8")
    assert all(s["packet"] in index for s in sa)
    assert "| tool mode | normal | hard | hard_layout | total |" in index


def test_review_yaml_parses(built):
    a, _, sa, _ = built
    assert {"rule_stated_clearly", "layout_rule_reasonable"} <= set(qa.REVIEW_FIELDS)
    for s in sa:
        d = yaml.safe_load((a / "packets" / s["packet"] / "review.yaml").read_text())
        assert set(qa.REVIEW_FIELDS) <= set(d) and "notes" in d
        assert qa.review_status(d) == "pending"
    assert qa.review_status(yaml.safe_load((a / "review_template.yaml").read_text())) == "pending"
    # the new fields parse from YAML as written by a reviewer (unquoted yes / no / n/a)
    filled = yaml.safe_load("rule_stated_clearly: no\nlayout_rule_reasonable: n/a\n")
    assert qa._norm(filled["rule_stated_clearly"]) == "no" and qa._norm(filled["layout_rule_reasonable"]) == "n/a"


FULL = {"reviewer": "AB", "task_fair": "yes", "solvable_from_public_material": "yes",
        "reference_fix_correct": "yes", "verifier_verdict_agrees": "yes",
        "alternative_valid_fixes_rejected": "none", "severity_if_wrong": "low",
        "rule_stated_clearly": "yes", "layout_rule_reasonable": "n/a", "notes": ""}


def test_tally_pending_partial_complete(built, tmp_path):
    a, _, sa, _ = built
    pk = tmp_path / "packets"
    shutil.copytree(a / "packets", pk)
    t = qa.tally(pk)
    assert t["packets"] == len(sa) and len(t["pending_packets"]) == len(sa) and not t["accepted"]
    p0, p1, p2, p3 = (pk / s["packet"] for s in sa[:4])
    (p0 / "review.yaml").write_text(yaml.safe_dump(FULL))
    (p0 / "review-cd.yaml").write_text(yaml.safe_dump({**FULL, "reviewer": "CD", "verifier_verdict_agrees": "no",
                                                       "notes": "golden decap too far"}))
    (p1 / "review.yaml").write_text(yaml.safe_dump({"reviewer": "AB", "task_fair": "unsure"}))  # partial
    (p2 / "review.yaml").write_text("task_fair: [unclosed\n")  # broken YAML
    (p3 / "review.yaml").write_text(yaml.safe_dump({**FULL, "rule_stated_clearly": "no",
                                                   "layout_rule_reasonable": "no"}))
    t = qa.tally(pk)
    assert t["forms"].get("complete") == 3 and t["forms"].get("partial") == 1 and t["forms"].get("invalid") == 1
    assert len(t["pending_packets"]) == len(sa) - 3
    disputed = {p for p, _ in t["disputed"]}
    assert {p0.name, p1.name, p2.name, p3.name} <= disputed
    assert any("reviewers disagree" in why for p, why in t["disputed"] if p == p0.name)
    assert any("rule_stated_clearly=no" in why for p, why in t["disputed"] if p == p3.name)
    assert any("layout_rule_reasonable=no" in why for p, why in t["disputed"] if p == p3.name)
    assert t["fields"]["layout_rule_reasonable"] == {"n/a": 2, "no": 1}
    assert t["reviewers"]["AB"]["rate"] == 1.0 and t["reviewers"]["CD"]["rate"] == 0.0
    assert not t["accepted"]
    (p3 / "review.yaml").write_text(yaml.safe_dump({**FULL, "layout_rule_reasonable": "maybe"}))
    assert qa.review_status(yaml.safe_load((p3 / "review.yaml").read_text())) == "invalid"


def test_selection_mixed_stratified_and_overweights_ambiguity(rows_metas):
    rows, metas, pub = rows_metas
    mix = qa.parse_mix(qa.DEFAULT_MIX)
    ch = qa.select_tasks(rows, metas, 100, 7, mix, pub)
    assert len({r["id"] for r in ch}) == 100
    assert Counter(qa.tier_of(r) for r in ch) == Counter({"normal": 60, "hard": 25, "hard_layout": 15})
    assert not {r["id"] for r in ch} & _holdout_ids()
    for tier in qa.TIERS:
        pool = [r for r in rows if qa.tier_of(r) == tier]
        got = [r for r in ch if qa.tier_of(r) == tier]
        assert {r["family"] for r in got} == {r["family"] for r in pool}, tier
        assert {r["hint_level"] for r in got} == {r["hint_level"] for r in pool}, tier
        assert {r.get("tools_mode") for r in got} == {r.get("tools_mode") for r in pool}, tier
    # every fault type, incl. every latent and layout-latent type, is covered
    assert {f["type"] for r in ch for f in r["faults"]} == {f["type"] for r in rows for f in r["faults"]}
    latent = {f["type"] for r in rows for f in r["faults"] if f["category"] == "latent"}
    assert set(qa.LAYOUT_LATENT) <= latent
    assert latent <= {f["type"] for r in ch for f in r["faults"]}
    for tier in qa.TIERS:
        sub = [r for r in rows if qa.tier_of(r) == tier]
        pick = [r for r in ch if qa.tier_of(r) == tier]
        score = lambda rs: sum(qa.task_features(r, metas[r["id"]], pub[r["id"]])["score"] for r in rs) / len(rs)  # noqa: E731
        assert score(pick) > score(sub), tier
    assert [r["id"] for r in ch] == [r["id"] for r in qa.select_tasks(rows, metas, 100, 7, mix, pub)]


def test_mix_quotas():
    assert qa.tier_quotas(100, qa.parse_mix("normal=60,hard=25,hard_layout=15")) == \
        {"normal": 60, "hard": 25, "hard_layout": 15}
    assert qa.tier_quotas(7, qa.parse_mix("hard=1,hard_layout=1")) == {"hard": 4, "hard_layout": 3}
    assert qa.tier_quotas(10, {"normal": 1, "hard": 1}, {"normal": 2, "hard": 100}) == {"normal": 2, "hard": 8}
    with pytest.raises(ValueError):
        qa.parse_mix("v1=100")
