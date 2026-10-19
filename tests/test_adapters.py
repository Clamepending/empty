"""Public API + adapters: list/load/verify, JSONL export/score, safe extraction, tool schemas,
rollout logging, Inspect helpers (without inspect_ai)."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from pcbenv import api
from pcbenv.adapters import gym_like, inspect_task, jsonl, rollout
from tests.fixtures.verify_tasks import build_task

ROOT = Path(__file__).resolve().parent.parent


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_policy", ROOT / "examples" / "demo_policy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def troot(tmp_path_factory, demo):
    """tasks root: train/{ldo golden, ldo value fault}, holdout/{rc_lowpass golden}."""
    base = tmp_path_factory.mktemp("adapters")
    root = base / "tasks"
    build = base / "build"
    (root / "train").mkdir(parents=True)
    (root / "holdout").mkdir(parents=True)
    g1 = build_task(build, "ldo_reg", 0)
    g2 = build_task(build, "rc_lowpass", 0)
    shutil.copytree(g1, root / "train" / "ldo_golden")
    shutil.copytree(g2, root / "holdout" / "rc_golden")
    fault = demo.make_demo_task(str(build / "demo"))
    shutil.copytree(fault, root / "train" / "ldo_value_fault")
    return root


def _public(td: Path, name: str) -> bytes:
    return (Path(td) / "public" / name).read_bytes()


# ------------------------------------------------------------------ api
def test_list_tasks_scan_and_split(troot):
    refs = api.list_tasks(troot)
    assert [(r.split, r.task_id) for r in refs] == [("holdout", "rc_golden"), ("train", "ldo_golden"),
                                                    ("train", "ldo_value_fault")]
    assert {r.family for r in refs} == {"ldo_reg", "rc_lowpass"}
    assert [r.task_id for r in api.list_tasks(troot, split="holdout")] == ["rc_golden"]
    assert [r.task_id for r in api.list_tasks(troot / "train")] == ["ldo_golden", "ldo_value_fault"]
    assert [r.task_id for r in api.list_tasks(troot / "train" / "ldo_golden")] == ["ldo_golden"]
    assert api.list_tasks(troot / "nope") == []


def test_list_tasks_manifest(troot, tmp_path):
    root = tmp_path / "t"
    shutil.copytree(troot, root)
    rows = [{"task_id": "ldo_golden", "split": "train", "family": "ldo_reg", "difficulty": "easy", "n_faults": 0},
            {"task_id": "rc_golden", "split": "holdout", "path": "holdout/rc_golden"},
            {"task_id": "ghost", "split": "train"}]
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    refs = api.list_tasks(root)
    assert [r.task_id for r in refs] == ["rc_golden", "ldo_golden"]  # ghost skipped, not in manifest = absent
    ldo = next(r for r in refs if r.task_id == "ldo_golden")
    assert ldo.difficulty == "easy" and ldo.extra == {"n_faults": 0} and Path(ldo.path).is_dir()
    assert [r.task_id for r in api.list_tasks(root, split="train")] == ["ldo_golden"]


def test_load_task(troot):
    t = api.load_task(troot / "train" / "ldo_value_fault")
    assert t.task_id == "ldo_value_fault" and t.meta is None
    assert "pcbtool" in t.task_md and t.spec["assertions"]
    assert {"design.json", "board.kicad_pcb", "TASK.md", "spec.json"} <= set(t.public_files)
    assert not any("golden" in f or f.startswith("hidden") for f in t.public_files)
    th = api.load_task(troot / "train" / "ldo_value_fault", include_hidden=True)
    assert th.meta["faults"][0]["type"] == "wrong_value"
    with pytest.raises(FileNotFoundError):
        api.load_task(troot / "train")


def test_verify_api(troot):
    g = troot / "train" / "ldo_golden"
    f = troot / "train" / "ldo_value_fault"
    assert api.verify(g / "public", g).reward == 1.0
    assert api.verify(g / "public", g, isolated=False).reward == 1.0
    r = api.verify(f / "public", f)
    assert r.reward == 0.0 and r.checks["spec"] is False and set(r.gates) == set(api.GATES)


# ------------------------------------------------------------------ extraction
def _tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _file(name: str, data: bytes = b"x") -> tuple[tarfile.TarInfo, bytes]:
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    return ti, data


def test_extract_tasks_roundtrip(troot, tmp_path):
    tb = tmp_path / "bundle.tar.gz"
    with tarfile.open(tb, "w:gz") as tf:
        tf.add(troot, arcname="pcb-repair-v1/tasks")
    refs = api.extract_tasks(tb, tmp_path / "out")
    assert sorted(r.task_id for r in refs) == ["ldo_golden", "ldo_value_fault", "rc_golden"]
    g = next(r for r in refs if r.task_id == "ldo_golden")
    assert api.verify(Path(g.path) / "public", g.path).reward == 1.0


@pytest.mark.parametrize("kind", ["dotdot", "abs", "symlink", "hardlink", "fifo", "nested_dotdot"])
def test_extract_tasks_rejects_unsafe(tmp_path, kind):
    good = _file("tasks/train/a/public/TASK.md", b"# ok")
    if kind == "dotdot":
        bad = _file("../evil.txt")
    elif kind == "nested_dotdot":
        bad = _file("tasks/../../evil.txt")
    elif kind == "abs":
        bad = _file(str(tmp_path / "evil.txt"))
    elif kind in ("symlink", "hardlink"):
        ti = tarfile.TarInfo("tasks/train/a/public/design.json")
        ti.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
        ti.linkname = "/etc/passwd"
        bad = (ti, None)
    else:
        ti = tarfile.TarInfo("tasks/fifo")
        ti.type = tarfile.FIFOTYPE
        bad = (ti, None)
    tb = _tar(tmp_path / "bad.tar.gz", [good, bad])
    dest = tmp_path / "dest"
    with pytest.raises(api.UnsafeArchive):
        api.extract_tasks(tb, dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not any(p.is_file() for p in dest.rglob("*"))  # nothing extracted before the check


# ------------------------------------------------------------------ jsonl
def test_jsonl_export_has_no_hidden_data(troot, tmp_path):
    out = tmp_path / "train.jsonl"
    assert jsonl.export_jsonl(troot, out, split="train") == 2
    text = out.read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["id"] for r in rows] == ["ldo_golden", "ldo_value_fault"]
    fault_td = troot / "train" / "ldo_value_fault"
    golden_design = (fault_td / "hidden" / "golden_design.json").read_text()
    golden_board = (fault_td / "hidden" / "golden_board.kicad_pcb").read_bytes()
    meta = json.loads((fault_td / "hidden" / "meta.json").read_text())
    # (the unfaulted ldo_golden task's PUBLIC design legitimately equals this golden; check this row)
    ftext = text.splitlines()[1]
    assert json.loads(ftext)["id"] == "ldo_value_fault"
    assert golden_design not in ftext and json.dumps(golden_design) not in ftext
    assert base64.b64encode(golden_board).decode() not in ftext
    assert "wrong_value" not in text and "faulted" not in text and "golden_design" not in text
    row = rows[1]
    assert row["prompt"] == (fault_td / "public" / "TASK.md").read_text()
    assert not any(k.startswith("hidden") or "golden" in k for k in row["files"])
    assert set(row["metadata"]) == {"task_id", "split", "family", "difficulty", "title", "n_assertions"}
    assert row["metadata"]["family"] == "ldo_reg" and str(meta["seed"]) != row["metadata"].get("seed")
    assert row["files"]["board.kicad_pcb"]["encoding"] == "base64"
    assert jsonl.decode_file(row["files"]["board.kicad_pcb"]) == _public(fault_td, "board.kicad_pcb")
    assert jsonl.decode_file(row["files"]["design.json"]) == _public(fault_td, "design.json")
    assert jsonl.main(["export", "--tasks", str(troot), "--out", str(tmp_path / "all.jsonl")]) == 0
    assert len((tmp_path / "all.jsonl").read_text().splitlines()) == 3


def test_score_jsonl_roundtrip(troot, tmp_path):
    g = troot / "train" / "ldo_golden"
    f = troot / "train" / "ldo_value_fault"
    rc = troot / "holdout" / "rc_golden"
    export_row = jsonl.task_row(api.TaskRef("rc_golden", str(rc)))
    preds = [
        {"id": "ldo_golden", "design.json": _public(g, "design.json").decode(),
         "board.kicad_pcb": _public(g, "board.kicad_pcb").decode()},
        {"id": "ldo_golden", "design.json": "{not json", "board.kicad_pcb": "garbage"},
        {"id": "ldo_value_fault", "design.json": _public(f, "design.json").decode(),
         "board.kicad_pcb": _public(f, "board.kicad_pcb").decode()},
        {"id": "rc_golden", "files": export_row["files"]},          # export format round trip
        {"id": "no_such_task", "design.json": "", "board.kicad_pcb": ""},
        {"id": "rc_golden", "files": {"board.kicad_pcb": {"encoding": "base64", "content": "!!notb64"}}},
    ]
    p = tmp_path / "preds.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in preds))
    scores = jsonl.score_jsonl(p, troot, workers=4, out_path=tmp_path / "scores.jsonl")
    assert [s["reward"] for s in scores] == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    assert [s["id"] for s in scores] == [r["id"] for r in preds]
    assert scores[1]["gates"]["parse"] is False
    assert scores[2]["checks"]["spec"] is False and scores[2]["gates"]["topology"] is True
    assert scores[4]["error"] == "unknown task id" and "bad row" in scores[5]["error"]
    assert len((tmp_path / "scores.jsonl").read_text().splitlines()) == 6


# ------------------------------------------------------------------ tool schemas
def _check_schema(s: dict) -> None:
    assert s["type"] == "object" and isinstance(s["properties"], dict)
    assert set(s.get("required", [])) <= set(s["properties"])
    for prop in s["properties"].values():
        assert prop["type"] in ("string", "array") and (prop["type"] != "array" or "items" in prop)


def test_tool_schemas():
    oa, an = gym_like.openai_style_tools(), gym_like.anthropic_style_tools()
    assert [t["function"]["name"] for t in oa] == [t["name"] for t in an] == ["bash", "pcbtool", "submit"]
    for t in oa:
        assert t["type"] == "function" and t["function"]["description"]
        _check_schema(t["function"]["parameters"])
    for t in an:
        assert set(t) == {"name", "description", "input_schema"}
        _check_schema(t["input_schema"])
    json.dumps([oa, an, gym_like.ACTION_SCHEMA])  # pure JSON
    an[0]["input_schema"]["properties"]["cmd"]["type"] = "mutated"   # copies, not shared state
    assert gym_like.anthropic_style_tools()[0]["input_schema"]["properties"]["cmd"]["type"] == "string"
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(gym_like.ACTION_SCHEMA)
        for t in gym_like.anthropic_style_tools():
            jsonschema.Draft202012Validator.check_schema(t["input_schema"])
        v = jsonschema.Draft202012Validator(gym_like.ACTION_SCHEMA)
        assert v.is_valid({"tool": "pcbtool", "args": ["drc"]}) and v.is_valid({"tool": "submit"})
        assert not v.is_valid({"tool": "pcbtool", "args": "drc"}) and not v.is_valid({"tool": "rm"})
    c2a = gym_like.tool_call_to_action
    assert c2a("bash", {"cmd": "ls"}) == {"tool": "bash", "cmd": "ls"}
    assert c2a("pcbtool", '{"args": ["set-value", "R1", "10k"]}') == {"tool": "pcbtool", "args": ["set-value", "R1", "10k"]}
    assert c2a("pcbtool", {"args": "drc"}) == {"tool": "pcbtool", "args": ["drc"]}
    assert c2a("submit", None) == {"tool": "submit"}
    assert c2a("bash", "{bad json")["tool"] == "invalid"
    assert c2a("rm", {}) == {"tool": "rm"}


# ------------------------------------------------------------------ rollout
def test_rollout_scripted_fix_and_transcript(troot, demo, tmp_path):
    td = troot / "train" / "ldo_value_fault"
    good = api.load_task(td, include_hidden=True).meta["faults"][0]["detail"]["golden"]
    seen_tools = []

    def call_model(messages, tools):
        seen_tools.append(tools)
        n = sum(m["role"] == "tool" for m in messages)
        assert messages[0]["role"] == "system" and messages[1]["content"].startswith("# Task")
        if n == 0:   # two tool calls in one turn (parallel tool use)
            return {"tool_calls": [{"name": "pcbtool", "input": {"args": ["sim"]}},
                                   {"name": "bash", "input": {"cmd": "ls ..; cat design.json | head -3"}}],
                    "text": "look first", "model": "fake-1", "usage": {"input_tokens": 10, "output_tokens": 5}}
        if n == 2:
            assert "FAIL" in messages[-2]["content"] and messages[-1]["tool_call_id"]
            return {"tool": "pcbtool", "args": ["set-value", "R1", good]}
        if n == 3:
            return {"name": "pcbtool", "input": {"args": ["check"]}}
        return None  # stop talking -> auto submit

    log = tmp_path / "runs" / "t.jsonl"
    res = rollout.run_agent(td, call_model, max_steps=10, model="fake", transcript=log, tool_style="anthropic")
    assert res["reward"] == 1.0, res
    assert res["n_tool_calls"] == 4 and res["steps"] == 5 and res["n_model_calls"] == 4
    assert res["submitted"] and not res["truncated"] and res["error"] is None
    assert res["served_models"] == ["fake-1"] and res["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert "input_schema" in seen_tools[0][0]
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert [r["type"] for r in rows] == ["start"] + ["step"] * 5 + ["result"]
    assert all(r["task_id"] == "ldo_value_fault" and r["model"] == "fake" for r in rows)
    for k in ("task_id", "model", "steps", "reward", "wall_time_s", "n_tool_calls"):
        assert k in rows[-1]
    assert rollout.read_results([log]) == [res]

    # demo policy through the same loop, appended to the same transcript
    r2 = rollout.run_agent(td, demo.DemoPolicy(), max_steps=12, model="scripted-demo", transcript=log)
    assert r2["reward"] == 1.0 and len(rollout.read_results(log)) == 2


def test_rollout_errors_and_limits(troot, tmp_path):
    td = troot / "train" / "ldo_value_fault"

    def boom(messages, tools):
        raise ConnectionError("api down")

    r = rollout.run_agent(td, boom, model="x", transcript=tmp_path / "e.jsonl")
    assert r["reward"] == 0.0 and "api down" in r["error"] and r["n_tool_calls"] == 0

    r = rollout.run_agent(td, lambda m, t: {"tool": "bash", "cmd": "true"}, max_steps=3)
    assert r["truncated"] and not r["submitted"] and r["steps"] == 3 and r["reward"] == 0.0

    r = rollout.run_agent(troot / "train" / "ldo_golden", lambda m, t: None)
    assert r["reward"] == 1.0 and r["n_tool_calls"] == 0 and r["submitted"]


# ------------------------------------------------------------------ inspect (no inspect_ai needed)
def test_inspect_samples_and_scorer(troot):
    samples = inspect_task.build_samples(troot, split="train")
    assert [s["id"] for s in samples] == ["ldo_golden", "ldo_value_fault"]
    for s in samples:
        assert s["input"].startswith("# Task")
        assert all(os.sep + "public" + os.sep in p and os.path.isfile(p) for p in s["files"].values())
        assert not any("hidden" in k or "golden" in k for k in s["files"])
        assert Path(s["metadata"]["task_dir"]).is_dir()
    g = troot / "train" / "ldo_golden"
    ok = inspect_task.score_deliverables(str(g), {n: _public(g, n) for n in ("design.json", "board.kicad_pcb")})
    assert ok["value"] == 1.0 and ok["explanation"] == "PASS"
    bad = inspect_task.score_deliverables(str(g), {"design.json": b"{}", "board.kicad_pcb": None})
    assert bad["value"] == 0.0 and "parse" in bad["explanation"]


def test_inspect_task_requires_inspect_ai(troot):
    if importlib.util.find_spec("inspect_ai") is not None:
        pytest.skip("inspect_ai installed")
    with pytest.raises(ImportError, match="pip install inspect-ai"):
        inspect_task.pcb_repair(tasks_root=str(troot))


def test_api_cli(troot, tmp_path, capsys):
    assert api.main(["list", str(troot), "--split", "train"]) == 0
    out = capsys.readouterr().out
    assert "ldo_golden" in out and "rc_golden" not in out
    g = troot / "train" / "ldo_golden"
    assert api.main(["verify", str(g / "public"), str(g)]) == 0
    assert json.loads(capsys.readouterr().out)["reward"] == 1.0
    f = troot / "train" / "ldo_value_fault"
    assert api.main(["verify", str(f / "public"), str(f)]) == 1
