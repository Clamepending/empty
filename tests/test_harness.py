"""Harness: reset / step / reward round trips with scripted policies."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pcbnew
import pytest

from pcbenv import boardnet, taskio
from pcbenv.families import FAMILIES
from pcbenv.harness import PcbRepairEnv, run_task_with_policy
from tests.fixtures.verify_tasks import build_task


@pytest.fixture(scope="module")
def tasks(tmp_path_factory):
    """An unfaulted golden task and a value-fault task derived from it (R1 value wrong)."""
    root = tmp_path_factory.mktemp("harness")
    golden_td = build_task(root, "ldo_reg", 0)
    g = FAMILIES["ldo_reg"].generate(0)
    good = g.design["components"]["R1"]["value"]
    bad_design = copy.deepcopy(g.design)
    bad_design["components"]["R1"]["value"] = "10k"
    bad_board = str(root / "bad.kicad_pcb")
    b = boardnet.load_board(taskio.golden_board_path(golden_td))
    b.FindFootprintByReference("R1").SetValue("10k")
    assert pcbnew.SaveBoard(bad_board, b, True)
    fault_td = taskio.write_task(root / "ldo_value_fault", g, taskio.golden_board_path(golden_td),
                                 public_design=bad_design, public_board=bad_board,
                                 faults=[{"type": "wrong_value", "detail": {"ref": "R1", "golden": good, "faulted": "10k"}}],
                                 problem="The output voltage measures about 1.4 V instead of 3.3 V.")
    return {"golden": golden_td, "fault": str(fault_td), "good": good}


def test_reset_observation(tasks):
    with PcbRepairEnv() as env:
        obs = env.reset(tasks["fault"])
        assert "1.4 V" in obs["task_md"] and "pcbtool" in obs["task_md"]
        assert {"design.json", "board.kicad_pcb", "TASK.md", "spec.json", "parts/LDO_ADJ.md"} <= set(obs["files"])
        assert not any(f.startswith("hidden") or "golden" in f for f in obs["files"])
        wd = obs["workdir"]
        assert os.path.isdir(wd) and Path(wd).resolve() != Path(tasks["fault"], "public").resolve()
    assert not os.path.exists(wd)  # close() removes the episode dir


def test_value_fault_fixed_by_scripted_policy(tasks):
    good = tasks["good"]
    script = [{"tool": "pcbtool", "args": ["sim"]},
              {"tool": "bash", "cmd": "pcbtool show | grep R1"},
              {"tool": "pcbtool", "args": ["set-value", "R1", good]},
              {"tool": "pcbtool", "args": ["check"]}]

    def policy(first, history):
        return script[len(history)] if len(history) < len(script) else None

    log = run_task_with_policy(tasks["fault"], policy, max_steps=10)
    assert "FAIL vout_loaded" in log.steps[0]["obs"]["output"]
    assert "10k" in log.steps[1]["obs"]["output"]
    assert "all local checks pass" in log.steps[3]["obs"]["output"]
    assert log.result.reward == 1.0, (log.result.gates, log.result.checks, log.result.detail)
    assert len(log.steps) == 5  # 4 actions + submit


def test_unfixed_fault_scores_zero_and_golden_scores_one(tasks):
    log = run_task_with_policy(tasks["fault"], lambda f, h: None)
    assert log.result.reward == 0.0 and log.result.checks["spec"] is False
    log = run_task_with_policy(tasks["golden"], lambda f, h: None)
    assert log.result.reward == 1.0


def test_step_limit_truncates_and_grades(tasks):
    with PcbRepairEnv(max_steps=2) as env:
        env.reset(tasks["golden"])
        _, r, term, trunc, _ = env.step({"tool": "bash", "cmd": "true"})
        assert (r, term, trunc) == (0.0, False, False)
        _, r, term, trunc, info = env.step({"tool": "bash", "cmd": "true"})
        assert trunc and not term and r == 1.0 and info["verify"].reward == 1.0
        with pytest.raises(RuntimeError):
            env.step({"tool": "bash", "cmd": "true"})


def test_bash_timeout_truncation_and_bad_actions(tasks):
    with PcbRepairEnv(cmd_timeout_s=2, output_limit=1000) as env:
        env.reset(tasks["golden"])
        obs, *_ = env.step({"tool": "bash", "cmd": "sleep 30"})
        assert obs["exit_code"] == -9 and "timed out" in obs["output"]
        obs, *_ = env.step({"tool": "bash", "cmd": "yes x | head -c 100000"})
        assert "truncated" in obs["output"] and len(obs["output"]) < 1200
        obs, *_ = env.step({"tool": "bash", "cmd": "pwd; ls"})
        assert obs["output"].startswith(env.workdir) and "design.json" in obs["output"]
        obs, *_ = env.step({"tool": "rm -rf"})
        assert obs["exit_code"] == 2
        obs, *_ = env.step({"tool": "pcbtool", "args": "drc"})
        assert obs["exit_code"] == 2
        # the agent wrecking its files gives reward 0, never an exception
        env.step({"tool": "bash", "cmd": "rm board.kicad_pcb && ln -s /etc/passwd board.kicad_pcb"})
        res = env.reward()
        assert res.reward == 0.0 and res.gates["parse"] is False
