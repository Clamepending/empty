"""Reference agent loop: `run_agent(task_dir, call_model, max_steps)` with a JSONL transcript.

`call_model(messages, tools) -> reply` is supplied by you. `messages` is a provider-neutral list:

    {"role": "system", "content": str}
    {"role": "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "input"}], "raw": <anything>}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}

(`raw` is whatever your `call_model` returned as `raw`, e.g. the provider's native content blocks,
so you can send them back unchanged; it is never written to the transcript.)
`tools` is `gym_like.TOOL_SPECS` / `openai_style_tools()` / `anthropic_style_tools()` per `tool_style`.

`reply` may be:
- `{"tool_calls": [{"id", "name", "input"}, ...], "text": str, "raw": ..., "model": str,
   "usage": {"input_tokens": int, "output_tokens": int}, "stop_reason": str}` (all but tool_calls optional),
- a single tool call `{"name": ..., "input": {...}}`,
- a native env action `{"tool": "bash", "cmd": ...}`, or
- `None` / no tool calls -> the episode is submitted as-is.

Transcript (one JSON object per line, appended; one file may hold many episodes):
- `{"type": "start", run_id, task_id, model, max_steps, time}`
- `{"type": "step", run_id, task_id, model, step, tool_call, action, output, exit_code, seconds, text}`
- `{"type": "result", run_id, task_id, model, served_models, steps, n_tool_calls, n_model_calls,
   reward, gates, checks, failed, wall_time_s, truncated, submitted, error, usage}`
The `result` row is the calibration-log format (G6/G7): `read_results(paths)` loads them.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable

from pcbenv.adapters import gym_like
from pcbenv.harness import PcbRepairEnv
from pcbenv.verify import VerifyResult

CallModel = Callable[[list[dict], list[dict]], "dict | None"]

SYSTEM_PROMPT = """\
You are an electronics engineer repairing a small two-layer PCB design. The working directory holds
TASK.md (problem report, design intent, spec), design.json (schematic of record), board.kicad_pcb
(KiCad 7 layout), spec.json and parts/<PART>.md datasheets. Use the `pcbtool` tool (or `bash`) to
inspect, diagnose and fix the design so that it meets the spec, keeping design.json and the board
consistent. Grading is pass/fail against a hidden reference. Call `submit` when you are done."""

TRANSCRIPT_OUTPUT_LIMIT = 4000


def _tools(style: str) -> list[dict]:
    if style == "anthropic":
        return gym_like.anthropic_style_tools()
    if style == "openai":
        return gym_like.openai_style_tools()
    return json.loads(json.dumps(gym_like.TOOL_SPECS))


def _normalize(reply, n: int) -> dict:
    """-> {"tool_calls": [...], "text", "raw", "model", "usage", "stop_reason"}"""
    if reply is None:
        return {"tool_calls": []}
    if not isinstance(reply, dict):
        raise TypeError(f"call_model must return a dict or None, got {type(reply).__name__}")
    if "tool_calls" in reply:
        out = dict(reply)
        out["tool_calls"] = [dict(c, id=c.get("id") or f"call_{n}_{i}") for i, c in enumerate(reply["tool_calls"] or [])]
        return out
    if "tool" in reply:  # native env action
        a = dict(reply)
        name = a.pop("tool")
        return {"tool_calls": [{"id": f"call_{n}_0", "name": name, "input": a}]}
    if "name" in reply:
        return {"tool_calls": [{"id": reply.get("id") or f"call_{n}_0", "name": reply["name"],
                                "input": reply.get("input", reply.get("arguments", {}))}]}
    raise ValueError(f"unrecognised call_model reply keys: {sorted(reply)}")


def _write(fh, row: dict) -> None:
    if fh is not None:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        fh.flush()


def _clip(s: str, n: int = TRANSCRIPT_OUTPUT_LIMIT) -> str:
    return s if len(s) <= n else s[: n // 2] + f"\n...[{len(s) - n} chars clipped]...\n" + s[-n // 2:]


def run_agent(task_dir: str | os.PathLike, call_model: CallModel, max_steps: int = 40, *,
              model: str = "unknown", transcript: str | os.PathLike | None = None,
              tool_style: str = "neutral", system_prompt: str = SYSTEM_PROMPT,
              max_model_calls: int | None = None, env_kwargs: dict | None = None) -> dict:
    """Run one episode and return the `result` row (also appended to `transcript`).

    `max_steps` bounds env steps (tool calls incl. submit); `max_model_calls` (default
    `max_steps`) bounds calls to `call_model`. Exceptions from `call_model` end the episode:
    the current files are still graded and the error is recorded in `result["error"]`."""
    task_dir = os.path.abspath(task_dir)
    task_id = Path(task_dir).name
    run_id = uuid.uuid4().hex[:12]
    tools = _tools(tool_style)
    max_model_calls = max_model_calls or max_steps
    t0 = time.monotonic()
    usage = {"input_tokens": 0, "output_tokens": 0}
    served: list[str] = []
    n_calls = n_model = 0
    error = None
    submitted = truncated = False
    res: VerifyResult | None = None
    fh = None
    if transcript is not None:
        Path(transcript).parent.mkdir(parents=True, exist_ok=True)
        fh = open(transcript, "a", encoding="utf-8")
    try:
        _write(fh, {"type": "start", "run_id": run_id, "task_id": task_id, "model": model,
                    "max_steps": max_steps, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with PcbRepairEnv(max_steps=max_steps, **(env_kwargs or {})) as env:
            obs0 = env.reset(task_dir)
            messages: list[dict] = [{"role": "system", "content": system_prompt},
                                    {"role": "user", "content": obs0["task_md"]}]
            while res is None:
                if n_model >= max_model_calls:
                    truncated = True
                    res = env.reward()
                    break
                n_model += 1
                try:
                    reply = _normalize(call_model(messages, tools), n_model)
                except Exception as e:  # noqa: BLE001 - recorded, episode still graded
                    error = f"{type(e).__name__}: {e}"[:2000]
                    res = env.reward()
                    break
                if reply.get("model") and reply["model"] not in served:
                    served.append(reply["model"])
                for k in usage:
                    usage[k] += int((reply.get("usage") or {}).get(k) or 0)
                calls = reply["tool_calls"]
                messages.append({"role": "assistant", "content": reply.get("text") or "",
                                 "tool_calls": calls, "raw": reply.get("raw")})
                if not calls:  # model stopped talking without submitting
                    calls = [{"id": f"call_{n_model}_auto", "name": "submit", "input": {}, "auto": True}]
                for i, call in enumerate(calls):
                    action = gym_like.tool_call_to_action(call["name"], call.get("input"))
                    n_calls += 0 if call.get("auto") else 1
                    obs, reward, term, trunc, info = env.step(action)
                    text = gym_like.format_observation(obs)
                    if not call.get("auto"):
                        messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"],
                                         "content": text})
                    _write(fh, {"type": "step", "run_id": run_id, "task_id": task_id, "model": model,
                                "step": env.steps, "tool_call": {k: call.get(k) for k in ("id", "name", "input")},
                                "action": action, "output": _clip(obs.get("output", "")),
                                "exit_code": obs.get("exit_code"), "seconds": obs.get("seconds"),
                                "text": _clip(reply.get("text") or "") if i == 0 else ""})
                    if term or trunc:
                        res = info["verify"]
                        submitted, truncated = bool(term), bool(trunc)
                        break
            steps = env.steps
    finally:
        result = None
        if res is not None:
            result = {
                "type": "result", "run_id": run_id, "task_id": task_id, "task_dir": task_dir, "model": model,
                "served_models": served, "steps": steps, "n_tool_calls": n_calls, "n_model_calls": n_model,
                "reward": res.reward, "gates": res.gates, "checks": res.checks,
                "failed": sorted([k for k, v in {**res.gates, **res.checks}.items() if not v]),
                "verify_error": res.detail.get("error"),
                "wall_time_s": round(time.monotonic() - t0, 3), "truncated": truncated, "submitted": submitted,
                "error": error, "usage": usage,
            }
            _write(fh, result)
        if fh is not None:
            fh.close()
    return result


def read_results(paths) -> list[dict]:
    """All `result` rows from one or more transcript files."""
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    rows = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("type") == "result":
                    rows.append(row)
    return rows
