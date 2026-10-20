"""G9 QA packets: deterministic build, train-only sampling, verbatim TASK.md, parseable forms, tally."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pcbenv import qa

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tasks" / "manifest.jsonl"
TASKS = ROOT / "tasks"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="no shipped tasks")


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("qa_a")
    b = tmp_path_factory.mktemp("qa_b")
    sa = qa.build(6, a / "packets", 3, MANIFEST, TASKS, workers=2)
    sb = qa.build(6, b / "packets", 3, MANIFEST, TASKS, workers=1)
    return a, b, sa, sb


def test_build_deterministic(built):
    a, b, sa, sb = built
    assert [s["id"] for s in sa] == [s["id"] for s in sb]
    ta, tb = _tree(a), _tree(b)
    assert ta.keys() == tb.keys()
    diff = [k for k in ta if ta[k] != tb[k]]
    assert not diff, diff


def test_never_holdout(built):
    a, _, sa, _ = built
    holdout = {json.loads(l)["id"] for l in MANIFEST.read_text().splitlines() if l.strip()
               and qa.is_holdout_row(json.loads(l))}
    assert holdout, "manifest has holdout tasks to exclude"
    assert not {s["id"] for s in sa} & holdout
    rows = qa.load_train_rows(MANIFEST, TASKS)
    assert not {r["id"] for r in rows} & holdout
    assert all(qa.task_dir_of(TASKS, r).is_dir() and "holdout" not in r["split"] for r in rows)
    text = "".join(p.read_text() for p in (a / "packets").rglob("README.md"))
    assert "holdout/" not in text and not any(h in text for h in holdout)


def test_build_packet_refuses_holdout(tmp_path):
    fake = tmp_path / "tasks" / "v2" / "normal_holdout" / "pcbr2-normal-00000000"  # never the real holdout split
    fake.mkdir(parents=True)
    with pytest.raises(ValueError):
        qa.build_packet({"id": fake.name, "family": "x", "faults": []}, fake, tmp_path / "out", 1, [])


def test_readme_contains_task_md_verbatim_and_verdicts(built):
    a, _, sa, _ = built
    for s in sa:
        p = a / "packets" / s["packet"]
        readme = (p / "README.md").read_text(encoding="utf-8")
        row = next(r for r in qa.load_train_rows(MANIFEST, TASKS) if r["id"] == s["id"])
        task_md = (qa.task_dir_of(TASKS, row) / "public" / "TASK.md").read_text(encoding="utf-8")
        assert task_md.rstrip("\n") in readme
        assert "Reviewer-only" in readme and "### 2.3 Verifier verdicts" in readme
        assert s["faulted_reward"] == 0.0 and s["golden_reward"] == 1.0
        for svg in ("schematic_faulted.svg", "schematic_golden.svg", "board_faulted.svg", "board_golden.svg"):
            txt = (p / svg).read_text(encoding="utf-8")
            assert txt.startswith("<svg") and txt.rstrip().endswith("</svg>")
    index = (a / "INDEX.md").read_text(encoding="utf-8")
    assert all(s["packet"] in index for s in sa)


def test_review_yaml_parses(built):
    a, _, sa, _ = built
    for s in sa:
        d = yaml.safe_load((a / "packets" / s["packet"] / "review.yaml").read_text())
        assert set(qa.REVIEW_FIELDS) <= set(d) and "notes" in d
        assert qa.review_status(d) == "pending"
    assert qa.review_status(yaml.safe_load((a / "review_template.yaml").read_text())) == "pending"


def test_tally_pending_partial_complete(built, tmp_path):
    import shutil
    a, _, sa, _ = built
    pk = tmp_path / "packets"
    shutil.copytree(a / "packets", pk)
    t = qa.tally(pk)
    assert t["packets"] == len(sa) and len(t["pending_packets"]) == len(sa) and not t["accepted"]
    p0, p1, p2 = (pk / s["packet"] for s in sa[:3])
    full = {"reviewer": "AB", "task_fair": "yes", "solvable_from_public_material": "yes",
            "reference_fix_correct": "yes", "verifier_verdict_agrees": "yes",
            "alternative_valid_fixes_rejected": "none", "severity_if_wrong": "low", "notes": ""}
    (p0 / "review.yaml").write_text(yaml.safe_dump(full))
    (p0 / "review-cd.yaml").write_text(yaml.safe_dump({**full, "reviewer": "CD", "verifier_verdict_agrees": "no",
                                                       "notes": "golden decap too far"}))
    (p1 / "review.yaml").write_text(yaml.safe_dump({"reviewer": "AB", "task_fair": "unsure"}))  # partial
    (p2 / "review.yaml").write_text("task_fair: [unclosed\n")  # broken YAML
    t = qa.tally(pk)
    assert t["forms"].get("complete") == 2 and t["forms"].get("partial") == 1 and t["forms"].get("invalid") == 1
    assert len(t["pending_packets"]) == len(sa) - 2
    disputed = {p for p, _ in t["disputed"]}
    assert {p0.name, p1.name, p2.name} <= disputed
    assert any("reviewers disagree" in why for p, why in t["disputed"] if p == p0.name)
    assert t["reviewers"]["AB"]["rate"] == 1.0 and t["reviewers"]["CD"]["rate"] == 0.0
    assert not t["accepted"]


def test_selection_stratified_and_overweights_ambiguity():
    rows = qa.load_train_rows(MANIFEST, TASKS)
    metas = {r["id"]: json.loads((qa.task_dir_of(TASKS, r) / "hidden" / "meta.json").read_text()) for r in rows}
    ch = qa.select_tasks(rows, metas, 100, 7)
    assert len({r["id"] for r in ch}) == 100
    assert {r["family"] for r in ch} == {r["family"] for r in rows}
    assert {r["hint_level"] for r in ch} == {r["hint_level"] for r in rows}
    assert {f["type"] for r in ch for f in r["faults"]} == {f["type"] for r in rows for f in r["faults"]}
    score = lambda rs: sum(qa.task_features(r, metas[r["id"]])["score"] for r in rs) / len(rs)  # noqa: E731
    assert score(ch) > score(rows)
    assert [r["id"] for r in ch] == [r["id"] for r in qa.select_tasks(rows, metas, 100, 7)]
