# PCB-Repair — RL environment for PCB fault repair

MISSION: Ship "PCB-Repair", an RL environment + eval where an agent repairs small
PCB designs (schematic-of-record `design.json` + KiCad 7 `board.kicad_pcb`) that
contain injected faults, graded by a deterministic verifier. A lab engineer must
be able to run it in <30 min and trust that reward == correctness.

Read `SPEC.md` (formats + interfaces) and `GOALS.md` (goals + acceptance tests)
before writing code.

## Environment facts
- Ubuntu 24.04, system `python3` (3.13) has `import pcbnew` (KiCad 7.0.11). Use system python3, no venv.
- `kicad-cli` 7 has NO drc/erc subcommands. DRC = `pcbnew.WriteDRCReport(...)`. ERC is ours (`pcbenv/erc.py`).
- `ngspice` 42 is installed (batch mode: `ngspice -b deck.cir`).
- KiCad libraries: `/usr/share/kicad/footprints/*.pretty`, `/usr/share/kicad/symbols`.
- No Freerouting, no Docker Hub (rate limited). Router is ours (`pcbenv/router.py`).
- Run tests: `python3 -m pytest -q tests/`

## Rules
1. Builders never edit `thresholds.yaml`, `scorecard/`, `redteam/attacks/`, `tasks/holdout/`.
   Those belong to the orchestrator / red-team / evaluator roles.
2. Every claim in a report is backed by a command anyone can rerun; commit its output.
3. Determinism: same input -> same reward, every time. Generators take explicit seeds.
   Non-determinism is a P0 bug.
4. The verifier never trusts anything in the agent's workdir except the two deliverable
   files (`design.json`, `board.kicad_pcb`). Rules, goldens, and parts data come from
   the hidden task dir / package.
5. Stay inside your assigned files/directories when working in parallel with other agents.
6. Stuck >2 iterations on the same failure: write a short diagnosis in your report and stop.
7. Done = the goal's acceptance command passes, run fresh.
8. Code style: plain, small modules, type hints, docstrings only where non-obvious. No
   frameworks beyond stdlib + numpy + pyyaml + pytest.
