#!/usr/bin/env python3
"""Reference loop: a Claude model solves PCB-Repair tasks via the Anthropic Messages API.

    pip install anthropic                     # optional; not a pcbenv dependency
    export ANTHROPIC_API_KEY=...              # or `ant auth login`; never hard-code keys
    python3 examples/run_with_claude.py MODEL_ID --tasks data --split v2/normal --limit 5 \
        --transcript runs/claude.jsonl
    python3 examples/run_with_claude.py MODEL_ID data/v2/normal/<task_id>

Built on `pcbenv.adapters.rollout.run_agent` (episode loop + JSONL calibration log) and
`gym_like.anthropic_style_tools()` (bash / pcbtool / submit tool definitions). The assistant's
native content blocks (incl. thinking blocks) are sent back unchanged on every turn, and all
tool results of one assistant turn go back in a single user message.

Calibration note: no server-side model fallback is configured, so every logged step is from the
requested model; `served_models` in the result row records what the API reported. A refusal or a
`max_tokens` stop ends the episode with `error` set (files are still graded) -- filter on `error`
when computing pass rates.

SECURITY: commands run on this host through PcbRepairEnv (not a sandbox). For untrusted models use
the Docker images (docs/SECURITY.md) or the Inspect adapter.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pcbenv import api  # noqa: E402
from pcbenv.adapters.rollout import run_agent  # noqa: E402


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Neutral rollout messages -> (system, Anthropic `messages`)."""
    system = ""
    out: list[dict] = []
    pending: list[dict] = []

    def flush() -> None:
        if pending:
            out.append({"role": "user", "content": list(pending)})
            pending.clear()

    for m in messages:
        role = m["role"]
        if role == "system":
            system = m["content"]
        elif role == "tool":
            pending.append({"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]})
        else:
            flush()
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m.get("raw") is not None:
                out.append({"role": "assistant", "content": m["raw"]})
            else:
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("input", {})}
                           for c in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks})
    flush()
    return system, out


def make_call_model(model: str, effort: str | None, max_tokens: int):
    try:
        import anthropic
    except ImportError:
        sys.exit("the `anthropic` package is not installed: pip install anthropic")
    client = anthropic.Anthropic(max_retries=5)

    def call_model(messages: list[dict], tools: list[dict]) -> dict:
        system, conv = to_anthropic(messages)
        kw = {"output_config": {"effort": effort}} if effort else {}
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system, tools=tools,
                                      messages=conv, **kw)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"refusal: {getattr(resp, 'stop_details', None)}")
        calls = [{"id": b.id, "name": b.name, "input": b.input} for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason == "max_tokens" and not calls:
            raise RuntimeError("max_tokens reached without a tool call")
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        return {"tool_calls": calls, "text": text, "raw": resp.content, "model": resp.model,
                "stop_reason": resp.stop_reason,
                "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}

    return call_model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model", help="Anthropic model id, e.g. claude-opus-5-5")
    ap.add_argument("task_dirs", nargs="*")
    ap.add_argument("--tasks", help="tasks root (uses manifest.jsonl if present)")
    ap.add_argument("--split", default="v2/normal", help="manifest split, e.g. v2/normal or v2/hard")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-steps", type=int, default=50)
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--effort", default="high", help="output_config.effort; 'none' to omit (older models)")
    ap.add_argument("--transcript", default="runs/claude.jsonl")
    ap.add_argument("--max-seconds", type=float, default=None, help="per-episode wall-clock cap")
    a = ap.parse_args(argv)
    dirs = list(a.task_dirs)
    if a.tasks:
        try:
            dirs += [r.path for r in api.list_tasks(a.tasks, split=a.split, strict=True)[: a.limit]]
        except api.SplitNotFound as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if not dirs:
        ap.error("give task dirs or --tasks ROOT")
    call_model = make_call_model(a.model, None if a.effort == "none" else a.effort, a.max_tokens)
    wins = 0.0
    for td in dirs:
        r = run_agent(td, call_model, max_steps=a.max_steps, model=a.model, tool_style="anthropic",
                      transcript=a.transcript, max_seconds=a.max_seconds)
        wins += r["reward"]
        print(f"{r['task_id']}: reward {r['reward']:.0f} steps {r['steps']} {r['wall_time_s']:.0f}s "
              f"failed={r['failed']} error={r['error']}", flush=True)
    print(f"pass rate {wins / len(dirs):.3f} over {len(dirs)} task(s); transcript {a.transcript}")
    return 0


if __name__ == "__main__":
    sys.exit(api.run_cli(main))
