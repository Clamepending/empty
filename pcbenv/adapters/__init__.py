"""Adapters that plug PCB-Repair into common eval / training stacks.

- `gym_like`     -- action JSON schema + OpenAI / Anthropic tool definitions for PcbRepairEnv
- `rollout`      -- reference agent loop with JSONL transcripts (calibration log format)
- `jsonl`        -- HF-datasets-style JSONL export of public task files + batch scoring
- `inspect_task` -- UK AISI Inspect (`inspect_ai`) Task; inspect_ai is imported lazily

None of these import a model SDK; bring your own client.
"""
