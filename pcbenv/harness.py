"""Gym-like episode runner for PCB-Repair tasks.

```python
env = PcbRepairEnv(max_steps=40)
obs = env.reset("tasks/train/<id>")        # {"task_md", "files", "workdir"}
obs, reward, terminated, truncated, info = env.step({"tool": "pcbtool", "args": ["check"]})
obs, reward, terminated, truncated, info = env.step({"tool": "bash", "cmd": "cat design.json"})
obs, reward, terminated, truncated, info = env.step({"tool": "submit"})   # grades, ends the episode
env.close()
```
Actions: `{"tool": "bash", "cmd": str}`, `{"tool": "pcbtool", "args": [str, ...]}`,
`{"tool": "submit"}`. Each command runs in the workdir with a timeout; combined
stdout+stderr is truncated to `output_limit` bytes. `PATH` starts with the repo's `bin/`, so
`pcbtool` is available to bash commands. Reward (binary, `verify_isolated`) is returned on
submit or when the step/time limit ends the episode; `reward()` grades the current state.

SECURITY BOUNDARY: `bash` here is NOT a sandbox -- commands run as the calling user on the
host, can read the hidden task dir and modify the repo. This is fine for scripted policies and
local development only. Production RL / evaluation must run the agent's commands inside a
container that holds only the public task files (workdir), and run `pcbenv.verify` OUTSIDE
that container on copies of the two deliverables with `hidden/` never mounted into it.
The verifier itself is written for that model: it reads only design.json and
board.kicad_pcb (regular files, <= 5 MB, no symlinks) and takes all reference data from
`hidden/`.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pcbenv import taskio
from pcbenv.verify import VerifyResult, verify_isolated

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"


@dataclass
class EpisodeLog:
    task_dir: str
    steps: list[dict] = field(default_factory=list)
    result: VerifyResult | None = None
    seconds: float = 0.0


class PcbRepairEnv:
    def __init__(self, max_steps: int = 50, time_limit_s: float = 1800.0, cmd_timeout_s: float = 120.0,
                 output_limit: int = 16 * 1024, verify_timeout_s: float = 120.0):
        self.max_steps = max_steps
        self.time_limit_s = time_limit_s
        self.cmd_timeout_s = cmd_timeout_s
        self.output_limit = output_limit
        self.verify_timeout_s = verify_timeout_s
        self.task_dir: str | None = None
        self.workdir: str | None = None
        self._tmp: str | None = None
        self.steps = 0
        self.t0 = 0.0
        self.done = False
        self.result: VerifyResult | None = None

    # ------------------------------------------------------------- lifecycle
    def reset(self, task_dir: str) -> dict:
        self.close()
        self.task_dir = os.path.abspath(task_dir)
        self._tmp = tempfile.mkdtemp(prefix="pcbepisode_")
        self.workdir = os.path.join(self._tmp, "work")
        taskio.copy_public(self.task_dir, self.workdir)
        self.steps, self.t0, self.done, self.result = 0, time.monotonic(), False, None
        task_md = Path(self.workdir, "TASK.md").read_text(encoding="utf-8")
        files = sorted(str(p.relative_to(self.workdir)) for p in Path(self.workdir).rglob("*") if p.is_file())
        return {"task_md": task_md, "files": files, "workdir": self.workdir}

    def close(self) -> None:
        if self._tmp and os.path.isdir(self._tmp):
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._tmp = self.workdir = None

    def __enter__(self) -> "PcbRepairEnv":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------- stepping
    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PATH"] = f"{BIN}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}"
        env["HOME"] = env.get("HOME", self._tmp or "/tmp")
        return env

    def _run(self, argv: list[str]) -> dict:
        t = time.monotonic()
        proc = subprocess.Popen(argv, cwd=self.workdir, env=self._env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=self.cmd_timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = proc.communicate()
        text = out.decode("utf-8", errors="replace")
        if len(text.encode()) > self.output_limit:
            half = self.output_limit // 2
            text = text[:half] + f"\n... [output truncated to {self.output_limit} bytes] ...\n" + text[-half:]
        if timed_out:
            text += f"\n[command timed out after {self.cmd_timeout_s} s]"
        return {"output": text, "exit_code": -9 if timed_out else proc.returncode,
                "seconds": round(time.monotonic() - t, 3)}

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        """Returns (obs, reward, terminated, truncated, info). Reward is 0 until the episode ends."""
        if self.workdir is None:
            raise RuntimeError("call reset() first")
        if self.done:
            raise RuntimeError("episode is over; call reset()")
        tool = action.get("tool")
        self.steps += 1
        if tool == "submit":
            return self._finish({"output": "submitted", "exit_code": 0}, truncated=False)
        if tool == "bash":
            obs = self._run(["bash", "-c", str(action.get("cmd", ""))])
        elif tool == "pcbtool":
            args = action.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                obs = {"output": "error: pcbtool args must be a list of strings", "exit_code": 2}
            else:
                obs = self._run([str(BIN / "pcbtool"), *args])
        else:
            obs = {"output": f"error: unknown tool {tool!r} (use bash, pcbtool or submit)", "exit_code": 2}
        if self.steps >= self.max_steps or time.monotonic() - self.t0 > self.time_limit_s:
            return self._finish(obs, truncated=True)
        return obs, 0.0, False, False, {"steps": self.steps}

    def _finish(self, obs: dict, truncated: bool) -> tuple[dict, float, bool, bool, dict]:
        self.result = self.reward()
        self.done = True
        return obs, self.result.reward, not truncated, truncated, {"steps": self.steps, "verify": self.result}

    def reward(self) -> VerifyResult:
        """Grade the current workdir (fresh subprocess)."""
        if self.workdir is None or self.task_dir is None:
            raise RuntimeError("call reset() first")
        return verify_isolated(self.workdir, self.task_dir, timeout=self.verify_timeout_s)


Policy = Callable[[dict, list[dict]], "dict | None"]


def run_task_with_policy(task_dir: str, policy_fn: Policy, max_steps: int = 30, **env_kw) -> EpisodeLog:
    """Run a scripted policy. `policy_fn(first_obs, history)` returns the next action, or None
    to submit. `history` is a list of {"action", "obs"} dicts."""
    t0 = time.monotonic()
    log = EpisodeLog(task_dir=str(task_dir))
    with PcbRepairEnv(max_steps=max_steps, **env_kw) as env:
        first = env.reset(task_dir)
        while True:
            action = policy_fn(first, log.steps) or {"tool": "submit"}
            obs, reward, term, trunc, info = env.step(action)
            log.steps.append({"action": action, "obs": obs})
            if term or trunc:
                log.result = info["verify"]
                break
    log.seconds = time.monotonic() - t0
    return log
