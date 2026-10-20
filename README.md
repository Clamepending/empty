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

## Quickstart (Ubuntu 24.04, about 10 min)

Run every command from the repo root, in order. Each one was timed on a 4-core host (see
`docs/ONBOARDING.md` for the measured times). Nothing here needs network access or Docker.

### 0. Preflight

```bash
python3 -c "import pcbnew, numpy, yaml; print('ok', pcbnew.Version())" && ngspice --version | grep -m1 ngspice
```

This must print `ok 7.0.11` and an `ngspice-42` line. If it does not:

- **KiCad 7.0.11 and ngspice** come from apt: `sudo apt-get install -y kicad=7.0.11* kicad-footprints=7.0.11* ngspice`.
  The `pcbnew` module lands in `/usr/lib/python3/dist-packages`. It works with whichever `python3` the
  apt KiCad build supports. On the reference host that is Python 3.13. `pcbnew` is not on PyPI.
- **numpy, pyyaml and pytest** come from pip for that same `python3`:
  `python3 -m pip install numpy pyyaml pytest`.
  On a stock Ubuntu 24.04 python (3.12, "externally managed") you need either `--break-system-packages`
  or the apt packages `python3-numpy python3-yaml python3-pytest`.
  The apt packages are built for the distro python only. If your `python3` is a different version
  (as on the reference host, 3.13), they are invisible to it and you must use pip.
- Alternatively, use a venv that can see `pcbnew`:
  `python3 -m venv --system-site-packages .venv && . .venv/bin/activate && pip install -e .`
  This was tested: it also puts `pcbtool` on PATH and makes `import pcbenv` work from any directory.

### 1. Get tasks

The bundles in `dist/` are extracted into `data/v2/<split>/<task_id>/`. That is the same layout as
`tasks/v2/` in a git checkout, so split names such as `v2/normal` work on both. Extract into a
separate directory (`data/`), not into the checkout's `tasks/`.

```bash
export PATH="$PWD/bin:$PATH"                                            # puts pcbtool on PATH
python3 -m pcbenv.api extract dist/pcb-repair-v2.1-normal.tar.gz data       # 655 tasks -> data/v2/normal/
python3 -m pcbenv.api extract dist/pcb-repair-v2.1-hard.tar.gz data         # 362 tasks -> data/v2/hard/
python3 -m pcbenv.api splits data                                         # v2/hard 362, v2/normal 655
```

Other bundles:

- `pcb-repair-v2.1-hard-layout.tar.gz` gives `v2/hard_layout`.
- `-normal-holdout`, `-hard-holdout` and `-hard-layout-holdout` give the `*_holdout` splits. Keep these out of training.

In a git checkout, `tasks/` already holds every split, so `tasks` can replace `data` in every
command below.

A `--split` that matches nothing prints the splits that do exist and exits 2. Bundle names
(`pcb-repair-v2.1-normal`) and bare names (`normal`) are accepted as aliases.

### 2. List tasks (normal and hard tier)

```bash
python3 -m pcbenv.api list data --split v2/normal | head -3               # split  task_id  family  path
python3 -m pcbenv.api list data --split v2/hard   | head -3               # the hard tier
```

### 3. Scripted demo policy: one task, then 20 tasks

```bash
python3 examples/demo_policy.py --make-demo runs/pcb_demo --transcript runs/demo.jsonl          # reward 1, ~2 s
python3 examples/demo_policy.py --tasks data --split v2/normal --split v2/hard --limit 10 \
    --workers 4 --max-seconds 20 --transcript runs/demo20.jsonl                                  # 10 normal + 10 hard, ~30 s
```

The demo policy only solves **single wrong-value faults**, so its mean reward on real tasks is low
(1/20 = 0.05 on the 20 tasks above). It reads `design.json` and `spec.json`, runs at most 20 local
simulations, then calls `set-value`, `check` and `submit`. It is a plumbing demo, not a baseline.

Its limits:

- `--max-seconds` (default 20) caps each episode's acting time. Grading adds about 1–5 s on top.
- `--max-sims` (default 20) caps its simulations.

Each line it prints is one episode.

`runs/demo20.jsonl` is the transcript, with `start`, `step` and `result` rows. Every `start` row
has a matching `result` row. If an episode is interrupted (Ctrl-C, SIGTERM), its `result` row has
`"aborted": true` and reward 0. If it hits `--max-seconds`, the row has `"timed_out": true` and the
files are graded as they are.

### 4. Work one task by hand

```bash
T=$(python3 -m pcbenv.api list data --split v2/normal --json | head -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')
rm -rf runs/work && mkdir -p runs/work && cp -r "$T/public/." runs/work/   # PUBLIC files only; safe to rerun
(cd runs/work && pcbtool check)                                            # exit 1: this task is faulty
python3 -m pcbenv.api verify runs/work "$T"                                # gates/checks JSON; exit 1 here (reward 0 until fixed)
```

`pcbtool --help` lists the inspect and edit commands (`show`, `sim`, `drc`, `set-value`, `connect`,
`route`, ...). TASK.md in the workdir is the problem statement.

### 5. Batch: JSONL export and scoring predictions

```bash
python3 -m pcbenv.adapters.jsonl export --tasks data --split v2/normal --out runs/train.jsonl     # 655 rows, public files only
python3 -m pcbenv.adapters.jsonl predict-unchanged --tasks data --split v2/normal --limit 5 --out runs/preds.jsonl
python3 -m pcbenv.adapters.jsonl score --tasks data --predictions runs/preds.jsonl --out runs/scores.jsonl --workers 4
```

A predictions file has one JSON object per line. Each line holds the task id and the full text of
the two deliverables, and any other key is ignored:

```json
{"id": "pcbr2-normal-0076521e", "design.json": "{\"components\": {...}, ...}", "board.kicad_pcb": "(kicad_pcb (version 20221018) ..."}
```

`predict-unchanged` writes exactly this format with the unmodified public files. It is a template,
and it scores 0 on every task. `score` prints `{"n", "mean_reward"}`. Its `--out` file has one row
per prediction, in input order: `{"id", "reward", "gates", "checks", "failed", "error"}`.

Rows in the export's `{"files": {"design.json": {"encoding", "content"}}}` form are accepted too.
Load the export with `datasets.load_dataset("json", data_files="runs/train.jsonl")`.

### 6. Tests

```bash
python3 -m pytest -q tests/test_v2_hardening.py tests/test_harness.py tests/test_adapters.py tests/test_onboarding_paths.py   # ~1 min
python3 -m pytest -q tests/                                                                     # full suite, ~15 min
```

## Plug in your own policy or model

`run_agent(task_dir, call_model, ...)` runs one episode, grades it, and appends a transcript. You
supply `call_model(messages, tools) -> reply`.

- **`messages`** is a provider-neutral list:
  - `{"role": "system"|"user", "content": str}`
  - `{"role": "assistant", "content", "tool_calls", "raw"}`
  - `{"role": "tool", "tool_call_id", "name", "content"}`
- **`tools`** are the three tool definitions: `bash {cmd}`, `pcbtool {args: [...]}` and `submit {}`.
- **The reply** is `{"tool_calls": [{"name", "input"}, ...], "text": ...}`, or a single
  `{"name", "input"}`. `None` (no tool calls) submits.

Save this as `my_policy.py` in the repo root and run `python3 my_policy.py` (saved anywhere else, run it as `PYTHONPATH=/path/to/repo python3 my_policy.py`, or use the editable install above):

```python
from pcbenv import api
from pcbenv.adapters.rollout import run_agent

def call_model(messages, tools):
    n = sum(m["role"] == "tool" for m in messages)     # tool results seen so far
    if n == 0:
        return {"tool_calls": [{"name": "pcbtool", "input": {"args": ["sim"]}}], "text": "check the spec"}
    if n == 1:
        return {"name": "bash", "input": {"cmd": "head -c 400 design.json"}}
    return None                                         # no tool call -> submit and grade

ref = api.list_tasks("data", split="v2/normal")[0]
row = run_agent(ref.path, call_model, max_steps=10, max_seconds=60, model="my-policy",
                transcript="runs/my_policy.jsonl")
print(ref.task_id, row["reward"], row["failed"])
```

`tool_style="anthropic"` or `"openai"` passes the tool definitions in that provider's schema
(`gym_like.anthropic_style_tools()` / `openai_style_tools()`). Exceptions raised by `call_model` end
the episode with `error` set, and the files are still graded.

**Anthropic models:** `pip install anthropic`, then run
`python3 examples/run_with_claude.py MODEL_ID --tasks data --split v2/normal --limit 5`.
This needs network access and an API key.

**Inspect (UK AISI)** is optional and not part of the timed path above. It needs network access
(`pip install inspect-ai`) and a running Docker daemon (the sandbox image is built with
`docker build --target agent -t pcb-repair-agent .`). The task reads `tasks/` by default, so pass
`-T tasks_root=data` for extracted bundles:

```bash
inspect eval pcbenv/adapters/inspect_task.py@pcb_repair -T tasks_root=data -T split=v2/normal -T limit=5 --model anthropic/<model-id>
```

Without `inspect_ai` installed, `pcb_repair()` raises an ImportError with this install hint.
`inspect_task.build_samples("data", split="v2/normal", limit=3)` works without it.

## Python API

Run Python from the repo root, or set `export PYTHONPATH=/path/to/repo`, or use the `pip install -e .`
venv from the preflight section.

```python
from pcbenv import api
tasks = api.list_tasks("data", split="v2/normal")          # [TaskRef(task_id, path, split, family, difficulty)]
hard = api.list_tasks("data", split="v2/hard")             # hard tier; api.available_splits("data") lists all
task = api.load_task(tasks[0].path)                         # TASK.md, spec, public file list (no hidden data)
with api.PcbRepairEnv(max_steps=40) as env:                 # gym-like: reset / step / reward
    obs = env.reset(task.path)                              # {"task_md", "files", "workdir"}
    obs, reward, terminated, truncated, info = env.step({"tool": "pcbtool", "args": ["check"]})
    obs, reward, terminated, truncated, info = env.step({"tool": "submit"})   # reward is 0.0 or 1.0
res = api.verify(task.public_dir, task.path)                # VerifyResult; isolated subprocess; never raises
print(res.reward, res.gates, res.checks)                    # dataclass: res.to_json() / dataclasses.asdict(res)
```

| Module | What it is for |
|---|---|
| `pcbenv.api` | stable surface: `list_tasks`, `available_splits`, `load_task`, `verify`, `extract_tasks`, `PcbRepairEnv` |
| `pcbenv.adapters.gym_like` | action JSON schema, `openai_style_tools()`, `anthropic_style_tools()`, `tool_call_to_action()` |
| `pcbenv.adapters.rollout` | `run_agent(task_dir, call_model, max_steps, max_seconds=...)`, which writes a JSONL transcript (the calibration log format) |
| `pcbenv.adapters.jsonl` | `export_jsonl` (HF-datasets style rows) and `score_jsonl(predictions)` (batch, parallel, isolated) |
| `pcbenv.adapters.inspect_task` | UK AISI Inspect `Task`: sandboxed `bash` + `pcbtool`, with a host-side verifier scorer |

A task directory looks like this (`tasks/` in a checkout, `data/` after `extract`):

```
<root>/v2/<split>/<task_id>/
  public/  TASK.md  design.json  board.kicad_pcb  spec.json  parts/<PART>.md  [tools.json]  <- the agent sees only this
  hidden/  golden_design.json  golden_board.kicad_pcb  meta.json                <- the grader reads only this
```

`tasks/manifest.jsonl` (checkout) or `data/v2/<split>/manifest.jsonl` (extracted) lists the tasks.
The splits are `v2/normal`, `v2/normal_holdout`, `v2/hard`, `v2/hard_holdout`, and the layout-rules
sub-tier `v2/hard_layout` and `v2/hard_layout_holdout`. Task ids are opaque
(`pcbr2-<tier>-<hash>`); see [reports/v2_generation.md](reports/v2_generation.md).

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
[docs/VERSIONING.md](docs/VERSIONING.md) · [docs/ONBOARDING.md](docs/ONBOARDING.md) (README dry run + timings) · Licence: **LICENSE-TBD (founder decision)**.
