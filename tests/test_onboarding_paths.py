"""Onboarding paths (G8): bundle extraction layout + split names, CLI errors for unknown splits,
quiet `| head`, extract counts, aborted / timed-out rollout rows, demo-policy budgets."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

from pcbenv import api
from pcbenv.adapters import inspect_task, jsonl, rollout

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def _add(tf: tarfile.TarFile, name: str, data: bytes | None = None) -> None:
    ti = tarfile.TarInfo(name)
    if data is None:
        ti.type = tarfile.DIRTYPE
        ti.mode = 0o755
        tf.addfile(ti)
    else:
        ti.size = len(data)
        ti.mode = 0o644
        tf.addfile(ti, io.BytesIO(data))


def make_bundle(path: Path, name: str, split: str | None, ids: list[str]) -> Path:
    """A release-style bundle: <name>/manifest.jsonl + <name>/<id>/public/TASK.md."""
    rows = [{"task_id": i, "split": split, "path": f"{split}/{i}", "family": "fam"} if split else
            {"task_id": i, "family": "fam"} for i in ids]
    with tarfile.open(path, "w:gz") as tf:
        _add(tf, name)
        _add(tf, f"{name}/manifest.jsonl", "".join(json.dumps(r) + "\n" for r in rows).encode())
        for i in ids:
            _add(tf, f"{name}/{i}/public/TASK.md", b"# Task\n")
            _add(tf, f"{name}/{i}/hidden/meta.json", json.dumps({"family": "fam"}).encode())
    return path


@pytest.fixture()
def data(tmp_path):
    """data/ holding two extracted bundles (the README layout)."""
    b1 = make_bundle(tmp_path / "pcb-repair-v2-normal.tar.gz", "pcb-repair-v2-normal", "v2/normal",
                     ["n-1", "n-2", "n-3"])
    b2 = make_bundle(tmp_path / "pcb-repair-v2-hard-layout.tar.gz", "pcb-repair-v2-hard-layout",
                     "v2/hard_layout", ["h-1", "h-2"])
    d = tmp_path / "data"
    r1 = api.extract_tasks(b1, d)
    r2 = api.extract_tasks(b2, d)
    assert [r.task_id for r in r1] == ["n-1", "n-2", "n-3"]  # this bundle only, not cumulative
    assert [r.task_id for r in r2] == ["h-1", "h-2"]
    return d


# ------------------------------------------------------------------ split names / layout
def test_canonical_split_and_matching():
    assert api.canonical_split("pcb-repair-v2-normal") == "v2/normal"
    assert api.canonical_split("pcb-repair-v2-hard-layout-holdout") == "v2/hard_layout_holdout"
    assert api.canonical_split("v2/hard") == "v2/hard"
    m = api.split_matches
    assert m("v2/normal", "v2/normal") and m("pcb-repair-v2-normal", "v2/normal")
    assert m("v2/normal", "pcb-repair-v2-normal") and m("normal", "v2/normal") and m("v2/normal", "normal")
    assert not m("v2/normal", "v2/normal_holdout") and not m("v2/hard", "v2/hard_layout")
    assert not m("v2/normal", "v1/normal") and not m("v2/normal", None) and m(None, "x")


def test_extract_uses_checkout_layout(data):
    assert sorted(p.name for p in (data / "v2").iterdir()) == ["hard_layout", "normal"]
    assert (data / "v2" / "normal" / "n-1" / "public" / "TASK.md").is_file()
    assert not any(p.name.startswith("pcb-repair") for p in data.iterdir())
    assert api.available_splits(data) == {"v2/hard_layout": 2, "v2/normal": 3}
    for name in ("v2/normal", "pcb-repair-v2-normal", "normal"):
        assert [r.task_id for r in api.list_tasks(data, split=name)] == ["n-1", "n-2", "n-3"], name
    assert [r.split for r in api.list_tasks(data / "v2")] == ["v2/hard_layout"] * 2 + ["v2/normal"] * 3
    assert len(api.list_tasks(data / "v2" / "normal")) == 3
    # re-extracting is idempotent
    again = api.extract_tasks(data.parent / "pcb-repair-v2-normal.tar.gz", data)
    assert len(again) == 3 and len(api.list_tasks(data)) == 5


def test_extract_split_from_bundle_name_when_manifest_has_none(tmp_path):
    b = make_bundle(tmp_path / "b.tar.gz", "pcb-repair-v2-hard", None, ["a", "b"])
    refs = api.extract_tasks(b, tmp_path / "d")
    assert (tmp_path / "d" / "v2" / "hard" / "a" / "public" / "TASK.md").is_file()
    assert {r.task_id for r in refs} == {"a", "b"}
    assert {r.task_id for r in api.list_tasks(tmp_path / "d", split="v2/hard")} == {"a", "b"}


def test_extract_rejects_unsafe_split_in_manifest(tmp_path):
    b = make_bundle(tmp_path / "b.tar.gz", "pcb-repair-v2-x", "../../evil", ["a"])
    api.extract_tasks(b, tmp_path / "d")  # unsafe split ignored -> bundle-name mapping
    assert (tmp_path / "d" / "v2" / "x" / "a").is_dir() and not (tmp_path / "evil").exists()


def test_old_layout_still_selectable_by_v2_name(tmp_path):
    """Dirs extracted by older versions (`<dest>/pcb-repair-v2-normal/<id>`) still match `v2/normal`."""
    d = tmp_path / "old" / "pcb-repair-v2-normal" / "t1" / "public"
    d.mkdir(parents=True)
    (d / "TASK.md").write_text("# Task\n")
    assert [r.task_id for r in api.list_tasks(tmp_path / "old", split="v2/normal")] == ["t1"]


def test_unknown_split_errors_list_available(data, tmp_path, capsys):
    with pytest.raises(api.SplitNotFound, match=r"v2/hard_layout \(2\), v2/normal \(3\)"):
        api.list_tasks(data, split="v2/nope", strict=True)
    assert api.list_tasks(data, split="v2/nope") == []
    assert api.main(["list", str(data), "--split", "v2/nope"]) == 2
    err = capsys.readouterr().err
    assert "available splits" in err and "v2/normal (3)" in err
    assert jsonl.main(["export", "--tasks", str(data), "--split", "v2/nope", "--out", str(tmp_path / "x.jsonl")]) == 2
    assert "available splits" in capsys.readouterr().err
    with pytest.raises(api.SplitNotFound):
        inspect_task.build_samples(data, split="train")
    assert len(inspect_task.build_samples(data, split="v2/normal")) == 3
    assert api.main(["list", str(tmp_path / "missing")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_extract_cli_reports_bundle_and_total(tmp_path):
    b1 = make_bundle(tmp_path / "pcb-repair-v2-normal.tar.gz", "pcb-repair-v2-normal", "v2/normal", ["a", "b", "c"])
    b2 = make_bundle(tmp_path / "pcb-repair-v2-hard.tar.gz", "pcb-repair-v2-hard", "v2/hard", ["x", "y"])
    d = tmp_path / "data"
    out1 = subprocess.run([sys.executable, "-m", "pcbenv.api", "extract", str(b1), str(d)], env=ENV,
                          capture_output=True, text=True, check=True).stdout
    out2 = subprocess.run([sys.executable, "-m", "pcbenv.api", "extract", str(b2), str(d)], env=ENV,
                          capture_output=True, text=True, check=True).stdout
    assert "extracted 3 task(s)" in out1 and "split v2/normal" in out1 and "now holds 3 task(s)" in out1
    assert "extracted 2 task(s)" in out2 and "split v2/hard" in out2 and "now holds 5 task(s)" in out2


def test_predict_unchanged_template(tmp_path):
    d = tmp_path / "t" / "v2" / "normal" / "t1" / "public"
    d.mkdir(parents=True)
    for n, txt in (("TASK.md", "# Task\n"), ("design.json", "{}"), ("board.kicad_pcb", "(kicad_pcb)")):
        (d / n).write_text(txt)
    out = tmp_path / "p.jsonl"
    assert jsonl.main(["predict-unchanged", "--tasks", str(tmp_path / "t"), "--out", str(out)]) == 0
    row = json.loads(out.read_text())
    assert row == {"id": "t1", "design.json": "{}", "board.kicad_pcb": "(kicad_pcb)"}


# ------------------------------------------------------------------ | head
@pytest.fixture(scope="module")
def many(tmp_path_factory):
    root = tmp_path_factory.mktemp("many")
    rows = []
    for i in range(3000):
        tid = f"task-{i:05d}"
        p = root / "v2" / "normal" / tid / "public"
        p.mkdir(parents=True)
        (p / "TASK.md").write_text("# Task\n")
        rows.append(json.dumps({"task_id": tid, "split": "v2/normal", "path": f"v2/normal/{tid}"}))
    (root / "manifest.jsonl").write_text("\n".join(rows) + "\n")
    return root


@pytest.mark.parametrize("args", [["list"], ["list", "--json"], ["list", "--split", "v2/normal"]])
def test_list_piped_to_head_is_quiet(many, args):
    cmd = f"{sys.executable} -m pcbenv.api {args[0]} {many} {' '.join(args[1:])} | head -1"
    p = subprocess.run(["bash", "-c", cmd], env=ENV, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0
    assert "Traceback" not in p.stderr and "BrokenPipe" not in p.stderr, p.stderr
    assert "task-00000" in p.stdout and len(p.stdout.splitlines()) == 1
    # the producer's own status is 141 (like a SIGPIPE'd unix tool), never a traceback
    p2 = subprocess.run(["bash", "-c", f"{cmd}; echo \"status=${{PIPESTATUS[0]}}\""], env=ENV,
                        capture_output=True, text=True, timeout=120)
    assert "status=141" in p2.stdout or "status=0" in p2.stdout


def test_run_cli_broken_pipe_returns_141():
    code = ("import sys; from pcbenv import api\n"
            "def boom(argv):\n    raise BrokenPipeError\n"
            "sys.exit(api.run_cli(boom))\n")
    p = subprocess.run([sys.executable, "-c", code], env=ENV, capture_output=True, text=True, timeout=60)
    assert p.returncode == 141 and p.stderr == ""


# ------------------------------------------------------------------ rollout rows
@pytest.fixture()
def fake_task(tmp_path):
    p = tmp_path / "fake" / "public"
    p.mkdir(parents=True)
    (p / "TASK.md").write_text("# Task\nfake\n")
    return tmp_path / "fake"


def _rows(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()]


def test_interrupted_episode_writes_aborted_result(fake_task, tmp_path):
    log = tmp_path / "t.jsonl"

    def ctrl_c(messages, tools):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        rollout.run_agent(fake_task, ctrl_c, transcript=log)
    rows = _rows(log)
    assert [r["type"] for r in rows] == ["start", "result"]
    res = rows[-1]
    assert res["aborted"] is True and res["reward"] == 0.0 and "KeyboardInterrupt" in res["error"]
    assert res["run_id"] == rows[0]["run_id"]
    assert rollout.read_results(log) == [res] and rollout.read_results(log, include_aborted=False) == []


def test_timed_out_episode_is_graded_not_aborted(fake_task, tmp_path):
    log = tmp_path / "t.jsonl"
    calls = []

    def slow(messages, tools):
        calls.append(1)
        time.sleep(0.3)
        return {"tool": "bash", "cmd": "true"}

    r = rollout.run_agent(fake_task, slow, max_steps=50, transcript=log, max_seconds=0.5)
    assert r["timed_out"] and r["truncated"] and not r["aborted"] and len(calls) <= 3
    assert r["reward"] == 0.0 and r["wall_time_s"] < 30
    assert [x["type"] for x in _rows(log)][-1] == "result"


def test_sigterm_episode_writes_aborted_result(fake_task, tmp_path):
    log = tmp_path / "t.jsonl"
    script = textwrap.dedent(f"""
        import signal, sys, time
        from pcbenv.adapters import rollout
        def term(s, f):
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, term)
        def slow(m, t):
            print("ready", flush=True)
            time.sleep(60)
        rollout.run_agent({str(fake_task)!r}, slow, transcript={str(log)!r})
    """)
    p = subprocess.Popen([sys.executable, "-c", script], env=ENV, stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready"
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 143
    rows = _rows(log)
    assert [r["type"] for r in rows] == ["start", "result"] and rows[-1]["aborted"] is True
    assert "SystemExit" in rows[-1]["error"]


# ------------------------------------------------------------------ demo policy budget
def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_policy", ROOT / "examples" / "demo_policy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


def _hard_design(n: int = 25) -> tuple[dict, list[dict], dict]:
    comps = {f"R{i}": {"part": "R", "value": "10k", "footprint": "x"} for i in range(1, n + 1)}
    a = [{"type": "dc_voltage", "name": "never", "min": 1.0, "max": 2.0}]
    return {"components": comps}, a, {f"R{i}": [1000.0, 100000.0] for i in range(1, n + 1)}


def test_find_value_fix_respects_sim_cap(demo, monkeypatch):
    import pcbenv.sim as sim

    calls = []

    def fake(design, assertions):  # never satisfiable; measurement moves with nothing
        calls.append(1)
        return [sim.AssertionResult("never", False, 5.0, "[1, 2]")]

    monkeypatch.setattr(sim, "run_assertions", fake)
    d, a, b = _hard_design()
    assert demo.find_value_fix(d, a, b, max_sims=20, deadline=time.monotonic() + 60) is None
    assert len(calls) <= 20


def test_find_value_fix_respects_deadline(demo, monkeypatch):
    import pcbenv.sim as sim

    def slow(design, assertions):
        time.sleep(0.2)
        return [sim.AssertionResult("never", False, 5.0, "[1, 2]")]

    monkeypatch.setattr(sim, "run_assertions", slow)
    d, a, b = _hard_design()
    t = time.monotonic()
    assert demo.find_value_fix(d, a, b, max_sims=1000, deadline=t + 1.0) is None
    assert time.monotonic() - t < 1.5


def test_find_value_fix_bisects_to_window(demo, monkeypatch):
    """Monotone fake circuit: V = R2 / 1k volts must land in [4.9, 5.1]; R1 is a decoy."""
    import pcbenv.sim as sim
    from pcbenv.parts import parse_value

    calls = []

    def fake(design, assertions):
        calls.append(1)
        v = parse_value(design["components"]["R2"]["value"]) / 1000
        return [sim.AssertionResult("v", 4.9 <= v <= 5.1, v, "[4.9, 5.1]")]

    monkeypatch.setattr(sim, "run_assertions", fake)
    d = {"components": {"R1": {"part": "R", "value": "4.7k"}, "R2": {"part": "R", "value": "100k"}}}
    a = [{"type": "dc_voltage", "name": "v", "min": 4.9, "max": 5.1}]
    fix = demo.find_value_fix(d, a, {"R1": [1e3, 1e5], "R2": [1e3, 2e4]}, max_sims=20,
                              deadline=time.monotonic() + 10)
    assert fix is not None and fix[0] == "R2" and 4.9 <= parse_value(fix[1]) / 1000 <= 5.1
    assert len(calls) <= 20


def test_demo_policy_submits_after_budget(demo):
    pol = demo.DemoPolicy(max_seconds=0.0)
    assert pol([], [])["name"] == "pcbtool"            # first action always runs
    time.sleep(0.01)
    msgs = [{"role": "tool", "content": "x"}]
    assert pol(msgs, [])["name"] == "submit"


def test_demo_cli_make_demo_within_budget(tmp_path):
    log = tmp_path / "demo.jsonl"
    t = time.monotonic()
    p = subprocess.run([sys.executable, str(ROOT / "examples" / "demo_policy.py"), "--make-demo",
                        str(tmp_path / "demo"), "--transcript", str(log), "--max-seconds", "20"],
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr
    assert "reward 1" in p.stdout and time.monotonic() - t < 120
    res = rollout.read_results(log)
    assert len(res) == 1 and res[0]["reward"] == 1.0 and res[0]["aborted"] is False
