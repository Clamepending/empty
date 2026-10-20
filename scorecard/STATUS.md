# Scorecard status

Updated by the orchestrator after re-running each acceptance command itself.

| Goal | Status | Evidence |
|---|---|---|
| G0 orchestrator | in progress | — |
| G1 circuits | ✅ verified | `pytest tests/test_families.py tests/test_sim.py` → 84 passed (19 s) |
| G2 board | ✅ verified | `pytest tests/` → 209 passed (46 s); 400-board stress run DRC-clean |
| G3 verifier/harness | ✅ verified | `pytest tests/` → 472 passed; verify median 0.54 s, p99 0.65 s |
| G4 faults + tasks | ✅ verified | 818 tasks (654 train/164 holdout), 19 fault types, 100 % valid/detected; orchestrator spot-check 30/30 faulted=0, restored=1; invisible share 81 %; 577 tests pass |
| G5 red team | 🟡 round 2 done; round 3 on v2 pending | round 1+2: 3200 scripted + 124 agent attempts, 0 hacks; open expert-disagrees/leaks RT30–RT37, RT59 → being fixed in v2 integration |
| G6 calibration | ❌ v1 saturated; superseded by G12 | v1: 0/50 in band. v2 hard: sonnet 57 % in band, best model 100 % |
| G7 baseline report | ✅ verified | `python3 reports/make_baseline.py --check` reproduces exactly from committed rollouts; reports/INTERPRETATION.md |
| G8 packaging | ✅ verified | onboarding passes C (1.7 min) and D (2.8 min) back-to-back from README only, no code reading, 20 tasks each incl. hard tier + custom policy; earlier A/B failures fixed (split aliasing, bounded demo, docs) |
| G9 QA packets | 🟡 packets ✅, human sign-off pending (founder) | 100 packets in qa/; agent pre-screen found F1 (pull-up bounds tighter than datasheet), F3/F4 prompt text bugs, F5 unenforced 1206 rule → queued for v2 fix |
| G10 refresh engine | ✅ verified | refresh run seeds 100000+: 118 new gated, deduped tasks |
| G12 hard tier | ❌ not met after 3 rounds (documented) | v2 hard: haiku 100 %, sonnet 57 % (63 % of its failures fixed at effort=high), opus 95 %; hard_layout: haiku 74 %, sonnet 19 %, opus 95 %. Repair against fully-stated rules saturates for careful agents; frontier-hard needs open-ended design tasks (reports/INTERPRETATION.md) |
| G11 buyer signal | 🟡 materials ready (gtm/), sending/pricing/licence = founder | — |
