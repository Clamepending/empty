# Outreach drafts

> **Founder-owned (G11). Do not send from an agent.** Only a human sends these. Fill every
> `[PLACEHOLDER]`. Every number comes from `reports/baseline.md`. Re-run
> `python3 reports/make_baseline.py --check` before sending, and update the numbers if the
> report has changed. We have no customers or design partners to name. Do not imply that we do.

---

## A. Lab RL-environments lead

**Subject:** A verifiable PCB-repair RL environment (binary reward, 0 known hacks)

Hi [FIRST_NAME],

I'm [FOUNDER_NAME] from [COMPANY]. We built **PCB-Repair**, an RL environment where agents
repair faulted circuit-board designs (a schematic plus a KiCad 7 layout) using a shell and a
domain CLI. A deterministic verifier grades the result with DRC, ERC, SPICE assertions,
datasheet rules and layout-geometry rules against a hidden golden. There is no LLM judge.

Why it might be useful to [LAB]:

- **The reward equals correctness, and we can show it.** All 1464 shipped tasks score 0 when
  faulted and 1 when the oracle repair is applied. Our red team logged 0 successful hacks across
  3500 scripted attack applications and 148 agent attempts.
- **It targets verification behaviour.** On the hard tiers, a mid-tier Claude model passed 57 %
  and 19 %, and every one of its failures was a stated requirement that the local tool doesn't
  check. A careful smaller model did better.
- **Fresh tasks on demand.** The tasks are fully synthetic, with keyed seeds and opaque ids, and
  a refresh engine produces new gated, deduplicated tasks.

To be straight about the limits: the strongest model we tested scores about 95 % on the hard
tiers. This is a diligence environment, not a frontier-capability benchmark. Our calibration
covers Claude models only, with about 40 tasks per tier and one attempt each.

Would a 2–4 week pilot be useful, with your models on our tiers plus a fresh holdout batch? I'm
happy to send the one-pager and the baseline report.

[FOUNDER_NAME]
[TITLE], [COMPANY] · [EMAIL]

---

## B. Data vendor / environment marketplace

**Subject:** Licensing a verifiable hardware-engineering RL environment

Hi [FIRST_NAME],

[COMPANY] has an RL environment for **PCB repair**: agents fix faulted KiCad 7 boards and
schematics, and a deterministic verifier (DRC, ERC, SPICE, design rules, no model judge) assigns
the reward. It ships with:

- 1464 gated tasks in three tiers (normal, hard, hard_layout), with a 20 % holdout per tier
- a refresh engine for new, deduplicated tasks
- Inspect, JSONL and gym-style adapters
- a data card, a red-team log (0 known hacks), and graded calibration rollouts for three Claude
  models

All data is 100 % procedurally generated, with no scraped or customer designs. Footprints come
from the KiCad standard library; licence details are in our FAQ.

We're exploring [FOUNDER: resale / co-distribution / white-label] arrangements. Would a short
call make sense?

[FOUNDER_NAME] · [COMPANY] · [EMAIL]
