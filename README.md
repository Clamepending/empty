# PCB-Repair

PCB-Repair is a reinforcement-learning environment and evaluation in which an agent repairs small
printed-circuit-board designs. Each design has a schematic of record (`design.json`) and a KiCad 7
layout (`board.kicad_pcb`). Each normal-tier task contains 1–3 injected faults: wrong component
values, broken or swapped connections, wrong footprints, undersized power tracks, misplaced
decoupling capacitors, and so on. Hard-tier tasks (mostly 20–27-part multi-rail boards) contain
3–6 faults, at least two of them *latent*: invisible to every `pcbtool` check but deducible from the
datasheets, the design intent and the stated design rules. The agent works with ordinary shell commands plus a domain CLI (`pcbtool`). A
deterministic verifier then grades the two deliverable files against a hidden golden reference.
The verifier applies structural gates and also runs KiCad DRC, an ERC, SPICE spec assertions
(ngspice) and layout checks. The reward is binary: it is 1 only if every gate and check passes.
Because the reward is checked rather than judged by a model, it equals correctness. Every task is
procedurally generated, so the generator can produce fresh, uncontaminated tasks on demand.

## Quickstart (Ubuntu 24.04, ≤ 30 min)

```bash
# 1. system deps: KiCad 7.0.11 (provides the `pcbnew` Python module) + ngspice
sudo apt-get install -y kicad=7.0.11* kicad-footprints=7.0.11* ngspice python3-numpy python3-pytest
# 2. from the repo root: put pcbtool on PATH (or `pip install -e .` into a --system-site-packages venv)
export PATH="$PWD/bin:$PATH"
# 3. get tasks: extract a released bundle (path traversal / links are rejected) ...
python3 -m pcbenv.api extract dist/pcb-repair-v2-normal.tar.gz tasks   # also -hard, -normal-holdout, -hard-holdout
#    ... or generate fresh ones: python3 -m pcbenv.generate --tier normal --out /tmp/t/normal --count 20 --secret default
# 4. list them
python3 -m pcbenv.api list tasks | head
# 5. run the scripted demo policy (builds its own wrong-value task, fixes it with pcbtool, reward 1)
python3 examples/demo_policy.py --make-demo /tmp/pcb_demo --transcript runs/demo.jsonl
# 6. work a task by hand: copy the PUBLIC files only, then inspect / edit with pcbtool
T=$(python3 -m pcbenv.api list tasks --json | head -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])'); cp -r "$T/public" /tmp/work && (cd /tmp/work && pcbtool check)
# 7. grade a workdir (prints gates/checks; exit 0 iff reward 1)
python3 -m pcbenv.api verify /tmp/work "$T"
# 8. JSONL export for HF datasets (public files only) -- score predictions with `... jsonl score`
python3 -m pcbenv.adapters.jsonl export --tasks tasks --split v2/normal --out train.jsonl
# 9. Inspect (optional: pip install inspect-ai; docker build --target agent -t pcb-repair-agent .)
inspect eval pcbenv/adapters/inspect_task.py@pcb_repair -T split=v2/normal -T limit=5 --model anthropic/<model-id>
# 10. tests (~15 min)
python3 -m pytest -q tests/
```

In a git checkout the shipped task dirs are already under `tasks/v2/` (regenerated, or extracted from
`dist/`); `tasks/manifest.jsonl` lists all v2 splits (`v2/normal`, `v2/normal_holdout`, `v2/hard`,
`v2/hard_holdout`, and the layout-rules sub-tier `v2/hard_layout`, `v2/hard_layout_holdout`). Task ids are opaque (`pcbr2-<tier>-<hash>`); see [reports/v2_generation.md](reports/v2_generation.md).

Any LLM: `examples/run_with_claude.py MODEL_ID --tasks tasks --limit 5` is a reference loop for the
Anthropic Messages API (`pip install anthropic`). For other providers, write a
`call_model(messages, tools)` and use `pcbenv.adapters.rollout.run_agent`, with
`gym_like.openai_style_tools()` or `anthropic_style_tools()` as the tool definitions.

## Python API

```python
from pcbenv import api
tasks = api.list_tasks("tasks", split="v2/normal")         # [TaskRef(task_id, path, split, family, difficulty)]
task = api.load_task(tasks[0].path)                         # TASK.md, spec, public file list (no hidden data)
with api.PcbRepairEnv(max_steps=40) as env:                 # gym-like: reset / step / reward
    obs = env.reset(task.path)                              # {"task_md", "files", "workdir"}
    obs, reward, terminated, truncated, info = env.step({"tool": "pcbtool", "args": ["check"]})
    obs, reward, terminated, truncated, info = env.step({"tool": "submit"})   # reward is 0.0 or 1.0
res = api.verify(workdir, task.path)                        # isolated subprocess; never raises
```

| Module | What it is for |
|---|---|
| `pcbenv.api` | stable surface: `list_tasks`, `load_task`, `verify`, `extract_tasks`, `PcbRepairEnv` |
| `pcbenv.adapters.gym_like` | action JSON schema, `openai_style_tools()`, `anthropic_style_tools()`, `tool_call_to_action()` |
| `pcbenv.adapters.rollout` | `run_agent(task_dir, call_model, max_steps)`, which writes a JSONL transcript (the calibration log format) |
| `pcbenv.adapters.jsonl` | `export_jsonl` (HF-datasets style rows) and `score_jsonl(predictions)` (batch, parallel, isolated) |
| `pcbenv.adapters.inspect_task` | UK AISI Inspect `Task`: sandboxed `bash` + `pcbtool`, with a host-side verifier scorer |

A task directory looks like this:

```
tasks/v2/<split>/<task_id>/
  public/  TASK.md  design.json  board.kicad_pcb  spec.json  parts/<PART>.md  [tools.json]  <- the agent sees only this
  hidden/  golden_design.json  golden_board.kicad_pcb  meta.json                <- the grader reads only this
```

## How reward works

The verifier is `pcbenv/verify.py`. It reads only `design.json` and `board.kicad_pcb` from the
workdir. Each must be a regular file of at most 5 MB, and symlinks are refused. All reference data
comes from `hidden/`.

| Stage | Name | Passes when |
|---|---|---|
| gate | `parse` | both files load; design.json validates against the schema and the parts library |
| gate | `components` | same refs and parts as the golden; each footprint is in the part's allowed list, matches the board, and has library-identical pads |
| gate | `topology` | connectivity partition == golden (net names ignored; symmetric 2-pin parts may be flipped) |
| gate | `consistency` | board connectivity and values == design.json |
| gate | `integrity` | outline unchanged; no DRC exclusions or markers, added zones, copper graphics or inner-layer tracks |
| check | `drc` | KiCad DRC under the canonical rules: 0 errors, 0 unconnected |
| check | `erc` | no ERC errors (unconnected required pins, driver conflicts, missing supply, shorts, ...) |
| check | `spec` | every golden SPICE / analytic assertion passes on the candidate design |
| check | `values` | every component value inside its published range (`value_bounds`) |
| check | `layout` | power-net track widths ≥ required; each decoupling cap within its straight-line distance and copper-path length of its IC pin |
| check | `rules` | only for tasks with a rule context (all v2 tasks: resistor power; hard tier: all datasheet design rules) — not run by `pcbtool` |
| check | `layout_rules` | only for `hard_layout` tasks: board-geometry rules stated in TASK.md "Layout rules" / `spec.json:layout_rules` (Kelvin sense, switching-loop area, crystal traces, analog/switching separation) — not run by `pcbtool` |

**Reward = 1.0 if and only if all 5 gates and all checks (5, plus `rules` / `layout_rules` where present) pass, otherwise 0.0.** The per-gate and
per-check booleans are returned for diagnostics only. [docs/REWARD.md](docs/REWARD.md) covers what
each stage catches and its known limitations.

## Security boundary

`PcbRepairEnv` runs `bash` commands on the host as your user. **This is not a sandbox**: an agent
could read `hidden/` from there. That is fine for scripted policies and local development. For
evaluating or training untrusted models, use the two-image setup instead. The `agent` image
(`docker build --target agent`) holds the public files and the `pcbtool` code only, with no family
generators and no network. The `grader` image runs `pcbenv.verify` outside the agent container on
copies of the two deliverables. `docker/run_episode.sh` and the Inspect adapter both implement this
split. See [docs/SECURITY.md](docs/SECURITY.md).

## Task families & fault types

From [reports/v2_generation.md](reports/v2_generation.md) (train / holdout):

| Tier | Families | Faults per task | # tasks |
|---|---|---|---|
| normal | 10 v1 families: `ldo_reg`, `led_driver`, `npn_switch`, `nmos_switch`, `opamp_noninv`, `opamp_inv`, `rc_lowpass`, `divider_adc`, `mcu_i2c`, `xtal_osc` | 1–3 of 19 types (wrong values, swapped / floating pins, reversed polarity, decap misconnected or moved, broken / narrow / shorted traces, clearance, footprint and board-pad swaps, BOM mismatch) | 655 / 164 |
| hard | 4 composite boards (`sys_sensor_node`, `sys_motor_ctrl`, `sys_clocked_mcu`, `sys_analog_frontend`, 84 %) + 5 v1 families | 3–6, ≥ 2 latent (12 types: underrated parts, weak base drive, misplaced flyback, connector / MCU pin swaps, decap on the wrong rail, bias or pull-up to the wrong rail, bypassed protection diode), interacting value faults, 39 % no_autoroute | 362 / 90 |

## Limitations

- **Generic parts.** Parts such as `LDO_ADJ`, `OPAMP`, `MCU8` and `NPN` are synthetic generics with
  self-contained datasheets, not manufacturer part numbers.
- **SPICE models are behavioural approximations.** They are good enough to tell a correct design
  from a faulted one, but they are not sign-off models.
- **KiCad 7 only.** The `.kicad_pcb` files are KiCad 7.0.11 format; ports to KiCad 8/9 are not done.
- **Small boards.** Boards are 2-layer, about 6–16 components (hard-tier composites 20–27), using SMD/THT library footprints. The
  in-house maze router is simple: it is enough to make goldens DRC-clean, but it is not a
  production router.
- **Not checked:** signal or power integrity, EMI, thermal behaviour, manufacturability (beyond
  DRC), BOM cost or part availability.
- **One task kind: repair.** A golden plus injected faults (1–3 normal, 3–6 hard), with reference designators
  fixed. Open-ended design from a spec is planned for v2.
- **Binary reward.** Partial progress is visible in `gates`/`checks`, but the reward does not
  credit it. A design that differs from the golden yet is equally correct (for example, a different
  but valid resistor pair) passes only if it keeps the golden's topology and meets the same
  assertions.

## More

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (module map) · [docs/REWARD.md](docs/REWARD.md) ·
[docs/SECURITY.md](docs/SECURITY.md) · [docs/DATA_CARD.md](docs/DATA_CARD.md) ·
[docs/VERSIONING.md](docs/VERSIONING.md) · Licence: **LICENSE-TBD (founder decision)**.
