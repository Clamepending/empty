# Scorecard status

Updated by the orchestrator after re-running each acceptance command itself.

| Goal | Status | Evidence |
|---|---|---|
| G0 orchestrator | in progress | — |
| G1 circuits | ✅ verified | `pytest tests/test_families.py tests/test_sim.py` → 84 passed (19 s) |
| G2 board | ✅ verified | `pytest tests/` → 209 passed (46 s); 400-board stress run DRC-clean |
| G3 verifier/harness | ✅ verified | `pytest tests/` → 472 passed; verify median 0.54 s, p99 0.65 s |
| G4 faults + tasks | 🔄 builder running | — |
| G5 red team | 🔄 red team running | — |
| G6 calibration | ⏳ blocked on G4 | — |
| G7 baseline report | ⏳ blocked on G6 | — |
| G8 packaging | ⏳ blocked on G3 | — |
| G9 QA packets | ⏳ blocked on G4 (human sign-off = founder) | — |
| G10 refresh engine | 🔄 with G4 builder | — |
| G11 buyer signal | founder-owned | — |
