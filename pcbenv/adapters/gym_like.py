"""Function-calling glue for `PcbRepairEnv` (pure dicts, no SDK imports).

The environment's action space is three tools:

| tool      | input                         | effect                                         |
|-----------|-------------------------------|------------------------------------------------|
| `bash`    | `{"cmd": str}`                | run a shell command in the task workdir        |
| `pcbtool` | `{"args": [str, ...]}`        | run `pcbtool <args>` (see TASK.md for commands) |
| `submit`  | `{}`                          | end the episode and grade it (reward 0 or 1)   |

Typical loop with a function-calling LLM:

```python
from pcbenv.harness import PcbRepairEnv
from pcbenv.adapters.gym_like import anthropic_style_tools, tool_call_to_action, format_observation

tools = anthropic_style_tools()                       # or openai_style_tools()
with PcbRepairEnv(max_steps=40) as env:
    obs = env.reset("tasks/v2/normal/<task_id>")
    prompt = obs["task_md"]                           # first user message
    done = False
    while not done:
        name, args = my_llm(prompt, tools)            # your model call -> one tool call
        obs, reward, terminated, truncated, info = env.step(tool_call_to_action(name, args))
        prompt = format_observation(obs)              # becomes the tool result
        done = terminated or truncated
    print("reward", reward, info["verify"].checks)
```
`pcbenv.adapters.rollout.run_agent` is a complete version of this loop with logging.
"""
from __future__ import annotations

import json

TOOL_SPECS: list[dict] = [
    {
        "name": "bash",
        "description": ("Run a bash command in the task working directory (which holds TASK.md, design.json, "
                        "board.kicad_pcb, spec.json and parts/). `pcbtool` is on PATH. Returns combined "
                        "stdout+stderr (truncated) and the exit code."),
        "parameters": {
            "type": "object",
            "properties": {"cmd": {"type": "string", "description": "The bash command to run."}},
            "required": ["cmd"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pcbtool",
        "description": ("Run the PCB-Repair CLI: `pcbtool <args...>`. Read-only commands: show, netlist, drc, erc, "
                        "sim, parts [PART], check. Mutating commands (keep design.json and the board in sync): "
                        "set-value REF VALUE, set-footprint REF LIB:FP, connect REF.PIN NET, disconnect REF.PIN, "
                        "move REF X Y ROT, unroute NET, route NET [--width W], sync."),
        "parameters": {
            "type": "object",
            "properties": {"args": {"type": "array", "items": {"type": "string"},
                                    "description": "Arguments, e.g. [\"set-value\", \"R1\", \"10k\"]."}},
            "required": ["args"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit",
        "description": ("Finish the episode. The two deliverables (design.json, board.kicad_pcb) are graded "
                        "pass/fail against the hidden reference. Call this once, when you are done."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

# JSON schema of a raw `PcbRepairEnv.step` action (the harness's native format).
ACTION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PcbRepairEnv action",
    "oneOf": [
        {"type": "object", "properties": {"tool": {"const": "bash"}, "cmd": {"type": "string"}},
         "required": ["tool", "cmd"], "additionalProperties": False},
        {"type": "object", "properties": {"tool": {"const": "pcbtool"},
                                          "args": {"type": "array", "items": {"type": "string"}}},
         "required": ["tool", "args"], "additionalProperties": False},
        {"type": "object", "properties": {"tool": {"const": "submit"}},
         "required": ["tool"], "additionalProperties": False},
    ],
}

TOOL_NAMES = tuple(t["name"] for t in TOOL_SPECS)


def openai_style_tools() -> list[dict]:
    """Chat Completions-style `tools=[{"type": "function", "function": {...}}]`."""
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": json.loads(json.dumps(t["parameters"]))}}
            for t in TOOL_SPECS]


def anthropic_style_tools() -> list[dict]:
    """Anthropic Messages API `tools=[{"name", "description", "input_schema"}]`."""
    return [{"name": t["name"], "description": t["description"],
             "input_schema": json.loads(json.dumps(t["parameters"]))} for t in TOOL_SPECS]


def tool_call_to_action(name: str, arguments: dict | str | None) -> dict:
    """Map a model tool call to a `PcbRepairEnv.step` action. `arguments` may be a dict or a JSON
    string (OpenAI style). Bad input becomes an action the env rejects with exit code 2, so the
    model sees the error instead of the episode crashing."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return {"tool": "invalid", "error": "arguments are not valid JSON"}
    args = arguments if isinstance(arguments, dict) else {}
    if name == "bash":
        return {"tool": "bash", "cmd": str(args.get("cmd", ""))}
    if name == "pcbtool":
        a = args.get("args", [])
        if isinstance(a, str):
            a = a.split()
        return {"tool": "pcbtool", "args": a}
    if name == "submit":
        return {"tool": "submit"}
    return {"tool": str(name)}


def format_observation(obs: dict) -> str:
    """Text shown to the model as the tool result."""
    out = obs.get("output", "")
    return f"{out}\n[exit code {obs.get('exit_code')}]" if "exit_code" in obs else out
