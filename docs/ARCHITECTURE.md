# Architecture

```
families/<f>.generate(seed) ─▶ Golden (design.json dict, assertions, power nets, decoupling, intent)
        │                         │
        │                  board.build_board ─▶ golden board.kicad_pcb (placement + router.py, DRC-clean)
        ▼                         │
faults/ inject 1–3 faults ─▶ taskio.write_task ─▶ tasks/<split>/<id>/{public,hidden}
                                                        │
              agent (PcbRepairEnv / rollout / Inspect) ─┤ edits public copies via bash + pcbtool
                                                        ▼
                                   verify.verify(workdir, task_dir) ─▶ reward ∈ {0, 1}
```

## Module map (`pcbenv/`)

| Module | Role |
|---|---|
| `parts.py`, `parts_lib.py` | Generic parts library: pins (pad, electrical type, required), allowed footprints, SPICE model, datasheet text; `parse_value`/`format_value` |
| `design.py` | `design.json` schema `pcbenv/design@1`: load, validate, `partition()` |
| `golden.py` | `Golden` dataclass |
| `families/` | 10 circuit family generators, `FAMILIES[name].generate(seed)` |
| `sim.py`, `checks.py` | Spec assertions: ngspice decks (op, ac, tran) and analytic checks (crystal load) |
| `board.py`, `router.py` | Deterministic placement and a grid maze router producing DRC-clean 2-layer boards |
| `boardnet.py` | Board → `BoardInfo` (partition via the pad map, footprints, values, pad and outline fingerprints, track widths, zones, markers) |
| `drc.py` | KiCad 7 DRC wrapper with canonical rules; `run_drc(board, rules_board)` |
| `erc.py` | Name-insensitive electrical rule check on design.json |
| `layout.py` | Power-net width / decoupling checks; `same_topology` (symmetric-part pin swaps) |
| `faults/` | Fault injector (G4; owned by builder-faults) |
| `taskio.py` | Task directory layout, TASK.md / spec.json writer, `make_golden_task` |
| `verify.py` | The grader: 5 gates + 4 checks, binary reward, `verify_isolated` subprocess |
| `tool.py` (`bin/pcbtool`) | Agent CLI: show / netlist / drc / erc / sim / parts / check + mutating edits that keep both files consistent |
| `harness.py` | `PcbRepairEnv` (reset / step / reward), `run_task_with_policy` |
| `api.py` | Stable public API + `python3 -m pcbenv.api {list,extract,verify}` |
| `adapters/gym_like.py` | Action JSON schema, OpenAI/Anthropic tool definitions, tool-call → action |
| `adapters/rollout.py` | Reference agent loop, JSONL transcripts (calibration log format) |
| `adapters/jsonl.py` | HF-style JSONL export of public files; batch scoring of predictions |
| `adapters/inspect_task.py` | Inspect `Task` (lazy `inspect_ai` import), host-side scorer |

## Other directories

| Path | Contents |
|---|---|
| `bin/pcbtool` | Shell wrapper: `python3 -P -m pcbenv.tool` with the repo on `PYTHONPATH` |
| `Dockerfile`, `docker/` | `agent` and `grader` image targets, entrypoints, `run_episode.sh`, Inspect compose file |
| `examples/` | `demo_policy.py` (scripted value-fault solver), `run_with_claude.py` (Anthropic API loop) |
| `tests/` | pytest suites per goal (`python3 -m pytest -q tests/`) |
| `tasks/`, `dist/` | Generated task sets / release bundles |
| `redteam/` | Red-team attacks and regression tests (G5) |
| `reports/`, `scorecard/` | Evidence and goal status |

## Data flow per episode

1. **Reset.** `PcbRepairEnv.reset` copies `public/` into a fresh temp workdir.
2. **Act.** Each `step` runs `bash` or `pcbtool` in that workdir with a timeout, truncating the
   output.
3. **Grade.** `submit` (or hitting the step or time limit) calls `verify_isolated(workdir,
   task_dir)`. This runs a fresh `python3 -I` process that copies the two deliverables into its
   own temp dir and compares them with `hidden/`.
4. **Close.** `close()` deletes the episode dir.
