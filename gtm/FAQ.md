# PCB-Repair FAQ (buyer-facing draft)

> **Founder-owned (G11).** Answers about licensing and legal matters are drafts that need
> counsel. Numbers come from `reports/baseline.md` (§ = its sections) and change only when it is
> regenerated.

### What exactly is graded?

Two files: `design.json` and `board.kicad_pcb`. The verifier reads nothing else from the
agent's workdir. All reference data comes from the hidden task directory.

The checks are:
- 5 gates: parse, components, topology vs golden, design/board consistency, and integrity
- 5 checks: KiCad DRC, ERC, SPICE assertions, value bounds, and layout
- `rules` (datasheet design rules), on every v2 task
- `layout_rules` (board geometry), on hard_layout tasks only

The reward is 1 only if all pass. See `docs/REWARD.md`.

### Can the reward be hacked?

No hack is known.
- All 1464 shipped tasks give faulted = 0.0 and oracle = 1.0 (§5).
- Across three red-team rounds, the non-superseded scripted runs made 3500 attack applications,
  and there were 148 agent/hand attempts. 0 of them were successful hacks (§9).
- Five findings where the verifier passed something an expert would reject (crystal frequency,
  decoupling path length, unit letters, control characters, net-tie fingerprint) were fixed and
  re-confirmed in v2 (§9).

Still open:
- Four low-severity information leaks (RT34–36, RT70; e.g. hint text that correlates with fault
  type). None of them lets a policy reach 1.0 without the repair.
- The retry of 64 round-3 applications that errored or timed out.

"0 known hacks" is bounded by what was tried. We disclose new findings, fix them, and version
the verifier (`docs/VERSIONING.md`).

### How hard is it?

See §1 and `reports/INTERPRETATION.md`.
- **Normal tier:** saturated (Haiku 99/100, Sonnet 100/100, Opus 50/50).
- **Hard tiers:**
  - Sonnet: 57 % (hard), 19 % (hard_layout).
  - Opus: 95 % on both.
  - Haiku: 100 % on hard; 73 % on hard_layout, from partial, unaudited data.

Difficulty is driven by diligence: verifying stated rules that the local tool doesn't check.
It is **not** frontier-hard. The strongest model we tested is outside the 10–70 % band, and
goal G12 is not met.

### What's the provenance? Any scraped or customer data?

**100 % synthetic.**
- Circuits come from family generators with keyed seeds.
- Layouts come from our own placer and router.
- Faults come from our injector, and the text comes from templates.
- Parts are generic, with datasheets written for this project.
- No model generated any of the data.
- Footprints are copied unmodified from the KiCad 7.0.11 standard library.

See `docs/DATA_CARD.md`.

### Licensing?

**Dataset licence: TBD, a founder decision.** The KiCad footprints are CC-BY-SA 4.0 with a
KiCad library exception. Our reading is that designs which merely use the footprints are not
Adapted Material, but counsel must confirm this before release. KiCad (GPL) and ngspice are
tools and are not redistributed in the task bundles. The commercial terms are
**[FOUNDER: licence / price]**.

### How often are tasks refreshed?

The refresh engine (`python3 -m pcbenv.generate`) creates new gated tasks from new seeds and
deduplicates them against the shipped set (goal G10, verified). Every refreshed task passes the
same gates: golden 1.0, faulted 0.0, each fault alone 0.0, and oracle 1.0. Cadence: **[FOUNDER:
e.g. per pilot / quarterly]**.

### What's the holdout policy?

20 % of each tier is holdout (§8). Released tasks are immutable; a buggy task is withdrawn,
never edited. For a buyer's held-out evaluation, we recommend a fresh refresh batch generated
for them and graded by us, so that the hidden goldens never leave our side.

### Was any calibration result contaminated?

The transcript audit excluded 4 Sonnet hard_layout rollouts for touching repo paths (§4).
Haiku's hard_layout transcripts are not audited yet, and those rows are flagged as unaudited in
§1. The audit checks file access in actions. It cannot detect what a model already knows.

### What models were tested, and how?

Claude Haiku, Sonnet and Opus (served ids recorded for v2-hard, §6). Settings:
- one attempt per task in v2 (v1: two attempts for Haiku and Sonnet, one for Opus)
- about 40 tasks per tier
- effort = medium
- one shared agent harness
- each agent worked 2–3 tasks in sequence, so within-agent learning is possible

No other vendors' models have been run.

### Known limitations

- Generic parts and behavioural SPICE models. A correct design here is not a sign-off design.
- KiCad 7 file formats and DRC. A port to KiCad 8/9 is planned and mechanical.
- No signal or power integrity, EMI, thermal, DFM or cost checks.
- Small topology space per family. Holdout tasks come from the same families.
- Binary reward against a golden; equivalent alternatives the author did not enumerate fail
  (`docs/REWARD.md`).
- Human EE sign-off of task fairness (G9) is still pending. An agent pre-screen flagged some
  value bounds as arguably too tight (`qa/self_review.md`).
- The calibration numbers come from small samples with wide intervals (§1). See
  `reports/INTERPRETATION.md`.
