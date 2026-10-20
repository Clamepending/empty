# QA pre-screen (v2 tasks): 15 packets reviewed by the QA agent

**This is not the human EE sign-off.** The QA agent read 15 of the 100 v2 packets as a skeptical EE
would, to catch problems before paying reviewers. The human forms (`packets/*/review.yaml`) are still
blank. Every claim below can be checked by rerunning a command:

```
python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7      # default --mix normal=60,hard=25,hard_layout=15
cd qa/prescreen_v2
python3 evidence_strength.py > evidence_strength.txt   # latent evidence: real statement vs incidental mention (F4)
python3 layout_margins.py    > layout_margins.txt      # layout-rule metric / limit, golden vs faulted (F2, F3)
python3 kelvin_loop.py       > kelvin_loop.txt         # Kelvin sense error estimate; masked loop faults (F1, F6)
python3 kelvin_centre.py pcbr2-hard_layout-5dd2d0dd    # conventional Kelvin layout graded (F1); output in kelvin_centre.txt
python3 pin_swaps.py         > pin_swaps.txt           # pin-swap latent variants and 2-pin load types (F5)
```

All five scripts read the **train splits only** (`qa.load_train_rows`); holdout splits are never opened.

## Automated verdict on the 100 packets

- For all 100 packets, the faulted files score reward 0 and the golden files score reward 1. The build warns
  on any other result, and it printed no warning.
- No latent fault in the train splits lacks its generator evidence text (`evidence_strength.txt`; the
  `missing_evidence` selection signal never fired). See F4 for how weak that gate is.

## Per-packet judgement

| packet | tier | faults (latent in bold) | fair / solvable | ref fix correct | verifier agrees | rule stated clearly | layout rule reasonable | notes |
|---|---|---|---|---|---|---|---|---|
| 018 | normal | bom_mismatch, decap_moved_far, short | yes / yes | yes | yes | yes | n/a | v1 F1 is fixed: the I²C pull-up bounds are now wider than the datasheet range. R2 and R3 have different bounds (340–2.3k vs 280–3.2k) for identical lines (F9) |
| 027 | normal | wrong_pull_resistor (gate 3.9k), short, footprint_swap | yes / yes | yes | yes | yes | n/a | 3.9k is a real fault: `ctrl_current_on` gives 1.26 mA against a 1 mA limit |
| 049 | normal | wrong_filter_cap, narrow_power_trace (GND) | yes / yes | yes | **arguable, for fault 2** | yes | n/a | v1 F3 persists: a 0.3 mm GND width rule on an LC signal filter. It is published, so the task is fair, but it is not physically motivated |
| 061 | hard | **capacitor_underrated**, **decap_wrong_rail**, FB/EN swap, bom, pad swap | yes / yes | yes | yes | yes | n/a | C1 is a 0603 at 9 V against the 8 V design limit. The faulted rule metrics are mostly 0 because the FB/EN swap kills the regulator (expected) |
| 062 | hard | **resistor_underrated**, **led_underrated**, interacting_value, pin_to_wrong_net | yes / yes | yes | yes | yes | n/a | The intent itself says "Resistors dissipating more than ~60 mW use a 1206". R4 360 Ω is 155 mW, 62 % of the 1206 limit. Clean |
| 067 | hard | **capacitor_underrated**, **flyback_misplaced**, transistor_pinout, bom | yes / yes | yes | yes | yes (F7) | n/a | the intent states the diode orientation explicitly |
| 069 | hard | **connector_pin_swap** (relay J2.1/J2.2), **weak_base_drive**, bom | **disputable** / yes | yes | **reason wrong for fault 1** | yes | n/a | forced β 28.8 vs ≤ 20 is a fair rule, and the intent says "forced beta of about 10". The relay-coil pin swap is electrically a no-op, and `rules` reports a physically false flyback violation (F5) |
| 076 | hard | **decap_swapped**, **bias_wrong_rail**, **mcu_pin_swap**, pull, filter cap, Y1 footprint | yes / yes | yes | yes | yes | n/a | full intent. Every latent fault is stated verbatim (C1 VIN / C2 VOUT, "C4 from NRST to GND", the pin table) |
| 077 | hard | **mcu_pin_swap**, **pullup_wrong_rail** (VIN), bom | yes / yes | yes | yes | yes | n/a | with the SDA/SCL swap, the VIN pull-up puts 4.9 V on SDA, a real abs-max violation |
| 085 | hard | **protection_bypassed**, **connector_pin_swap** (I²C 3/4), **bias_wrong_rail**, floating NRST, bom, LED R | yes / yes | yes | yes | yes | n/a | 6 faults, 3 latent, vague hint. Fair, but long (≈ 10 min) |
| 086 | hard_layout | **crystal_via**, **decap_long_path**, **bias_wrong_rail**, bom, broken trace | yes / yes | yes | yes | yes | yes (vias: nit, F3) | C3 path 21.9 mm vs 8 mm (golden 3.6 mm) |
| 087 | hard_layout | **crystal_far**, **decap_long_path**, **bias_wrong_rail**, decap_misconnected, LED R | yes / yes | yes | yes | yes | yes | crystal path 23.8 / 26.9 mm vs 10 mm (golden 6.3 / 7.9 mm), plus 6 vias |
| 092 | hard_layout | **analog_near_switch**, **pullup_wrong_rail** (+12 V), LED reversed, LED R | yes / yes | yes | yes | yes | yes | ADC net 16.9 mm within 1 mm of the switch node (golden 0). Pulling SCL to 12 V on a 5 V MCU is clear-cut |
| 095 | hard_layout | **kelvin_sense_tap**, **switch_loop_spread**, **mcu_pin_swap**, narrow, pad swap, footprint | yes / yes | yes | yes | yes | **disputable (F1)** | loop 220.5 mm² vs 60 (golden 46.2) is unambiguous. The Kelvin rule rejects a conventional layout (F1) |
| 096 | hard_layout | **switch_loop_spread**, **mcu_pin_swap**, pad swap | yes / yes | yes | yes | yes | **borderline (F2)** | loop 84.7 mm² vs 60 mm² (1.41×). Most EEs would ask for a tighter loop, not reject the board |

Summary: 10 of the 15 are clean. 069 will be disputed (F5). 095 and 096 hinge on layout-rule judgement (F1, F2).
049 repeats the v1 power-width complaint.

## Findings (with evidence), most important first

### F1: the Kelvin rule rejects the conventional Kelvin layout (severity: high, systematic, hard_layout)

- TASK.md defines Kelvin as follows: delete the shunt pad, and the sense pin's copper island must not contain the load pin. It also says
  "the sense trace and the load-current copper may meet only through the shunt pad, never by touching each
  other (not even inside the pad)". Goldens comply by ending the two tracks just inside *opposite edges* of the
  shunt pad. For 095 (`pcbr2-hard_layout-5dd2d0dd`), the pad is 117.5 ± 0.875 mm, and the tracks end at x = 116.7 and 118.3.
- Most EEs, and any hand router, would end both tracks at the pad centre, with the sense trace leaving the
  pad on its own trace. That is a textbook Kelvin connection, and it scores **0**. `kelvin_centre.txt`: the golden board of
  095, with only the two track ends moved onto the pad centre, fails nothing except `layout_rules`:
  ```
  VERIFY reward 0.0 {'layout_rules': False} ['kelvin_sense: sense connection R8.1 shares copper with the load-current path from Q1.S ...']
  ```
  The result is the same on `pcbr2-hard_layout-f7d8d9c0`.
- The rule is stated, so `rule_stated_clearly` is yes. But an expert would dispute it (`layout_rule_reasonable: no`), and it
  rewards reading the fine print over engineering. **Proposed fix (layout_rules owner):** treat overlap *inside the
  shunt pad* as allowed. Only copper outside the pad outline may not be shared. Alternatively, grade the Kelvin error
  as I·R_shared against a stated fraction of the sense tolerance.
- Related, and lower severity: the functional impact of the injected Kelvin faults is small. `kelvin_loop.txt` (b), using an upper
  bound with the tap at Q1.S on 1 oz copper, gives a worst-case sense error of 0.9–3.8 % for 30 of the 36 train faults, against a ±7 % spec.
  Only 3 exceed 7 % (16–18 mm shared paths, 7.8–15.6 %). The injected faults are best-practice violations, not functional failures.
  That is defensible for a "design review" tier, but reviewers should be told.

### F2: switching-loop limit (60 mm²): the limit is defensible, but some faults are only just over it (severity: med)

- Physics: the loop legs C_bulk.+ → D.K, D.A → Q.D, Q.S → R_shunt → C_bulk.− are the true commutation (hot) loop of
  a low-side switch with a freewheel diode. The definition is right.
- Goldens use 0.26–0.80 of the limit (`layout_margins.txt`), so the limit is achievable with these packages. As an absolute number,
  60 mm² (about 6 × 10 mm) is a reasonable "tight" target for a 0.5–1 A brushed-motor PWM stage. No standard
  imposes it, so it is a house rule.
- Injected faults: faulted/limit = 1.27, 1.27, 1.30, 1.31, 1.32, 1.41, … (median 1.79; `kelvin_loop.txt` (c)).
  A loop at 76 mm² instead of 60 mm² changes loop inductance by ~25 %. An EE would comment on it, but not reject the board.
  **Proposed fix (fault injector):** require faulted area ≥ 1.5× the limit (≥ 2× would make it unambiguous).
  This drops 6 of the 25 measurable train faults.

### F3: the other layout limits are defensible. Two are lenient, and one rule has a loophole (severity: low–med)

| rule | limit | goldens (metric/limit) | injected faults (metric/limit) | verdict |
|---|---|---|---|---|
| crystal copper path | 10 mm | 0.33–0.80 | 1.83–3.38 (min 18.3 mm) | defensible. App-note guidance is "as short as possible, ~1 cm". The faults are unambiguous |
| crystal vias | 0 | 0 | 2–4 vias | standard advice (no layer changes on XIN/XOUT). Two vias at 24 MHz do little functional harm, so an EE may call it a nit, but it is stated |
| analog/switch separation | ≤ 3 mm within 1 mm (centreline) | 0–0.50 | 2.14–8.18 (min 6.4 mm) | the faults are unambiguous. The rule is *lenient*: with 0.4 mm tracks, 1 mm centreline spacing is a 0.6 mm edge gap. **Loophole:** only same-layer copper counts (`layout_rules.py:491`, `if la != lay: continue`), so an ADC trace running 20 mm directly over the switch node on the other layer (broadside, the worst coupling) passes, and reward 1 would be given to a bad layout |
| decoupling copper path | 8 mm (composites) / 6 mm | 0.27–0.87 | 1.38–6.02 (min 11.0 mm) | lenient compared with practice (≤ 2–3 mm). Never unfair to the agent. The 11 mm case is mild but still poor practice |
| decoupling straight line | 5 mm | 0.50–0.84 | — | fine |

### F4: the latent-evidence fairness gate is much weaker than it looks (severity: med, robustness)

- `latent.evidence_groups` passes if *any* alternative string appears *anywhere* in TASK.md + spec.json +
  parts/*.md. Two examples from the packets:
  - `connector_pin_swap` accepts the bare pin name `J2.1`. Every task's spec assertion lines already contain it
    (e.g. "load R=150 L=0.01 from J2.1 to J2.2"). In packet 069 the gate matched exactly that assertion line
    (README 2.7). It did not match the real pinout statement, "J2 (pin 1 = supply, pin 2 = switched side …)", which the gate's
    strings (`J2 pin 1`, `| J2 | 1 |`) do not recognise.
  - `resistor_underrated` accepts `| 0805 |` from **any** datasheet. In packet 062 it matched the LED table in
    `parts/LED_GREEN.md`, not the resistor table in `parts/R.md`.
- Population check (`evidence_strength.txt`): for 16 of the 141 train `connector_pin_swap` faults, the gate is satisfied
  *only* by assertion lines or spec.json. I read all 16 TASK.md files: each one does state the pinout in prose
  ("J2 (pin 1 = supply, …)" or "J2 (pin 1 = VDD, …, pin 4 = SCL)"), so **no current task is unfair**. However,
  the gate would also have passed a reduced intent with no pinout at all.
  **Proposed fix (latent.py owner):** drop the bare `REF.PIN` alternative, add the `REF (pin n =` phrasing, and require
  the footprint-size row to come from the part's own datasheet.
- The packet README now quotes the matched line and every file that contains it (section 2.7), so human
  reviewers can judge the evidence themselves.

### F5: 2-pin coil connector swaps are electrically no-ops, and the `rules` message for them is false (severity: med)

- `pin_swaps.txt`: 22 train tasks swap J2 pins 1/2 of a 2-pin load connector. In 16 of them the load is a relay coil (npn) or
  a solenoid (nmos). A non-polar coil sits between the same two nets either way, and D1 is still across it with
  the correct orientation. Only the 6 motor cases change behaviour (direction).
- The grader fails these tasks on `topology`, which is legitimate because the intent fixes the pinout, *and* on `rules`
  with "inductive load J2.1-J2.2 has no flyback diode across it" (packet 069, 2.3). That message is physically
  false: the flyback rule is keyed to connector pins, not to the load. An EE will mark
  `verifier_verdict_agrees: no` (wrong reason) and may argue the fault is not a defect.
  **Proposed fix:** restrict `connector_pin_swap` on 2-pin coil connectors to polarised loads (motor), or state in the
  intent why polarity matters (e.g. a relay module with an internal suppression diode).

### F6: some layout-latent faults cannot be seen on the faulted board (severity: low, reviewer guidance)

- In 6 of the 31 train `switch_loop_spread` tasks, a co-injected `transistor_pinout` or broken connection disconnects a loop leg. The faulted
  board's loop area then reads "Q1.S and R7.1 are not connected by copper" (`kelvin_loop.txt` (a)). Packets
  093 and 094 are such cases. Each fault is still detected *alone* (2.1, "verifier, this fault alone"). The agent
  sees the loop problem only after fixing the pinout, which is fair but makes the task harder than the fault list suggests.

### F7: the capacitor-voltage-by-footprint rule is a stated fiction (severity: low–med, EE realism)

- `parts/C.md` says the "X7R series used on this board" is rated 10/25/50 V for 0603/0805/1206. Real MLCC series offer
  0603 at 16–50 V, so a real EE would pick a higher-voltage part number, not a bigger footprint. It is stated
  explicitly, so it is fair (`rule_stated_clearly: yes`), but expect "unrealistic" comments on every
  `capacitor_underrated` packet (6 in the sample). The 80 % voltage derating is lenient compared with the common 50 % for X7R
  DC bias, which is never unfair to agents.

### F8: TASK.md has two `## Spec` headings in the hard tiers (severity: low, cosmetic)

- 307 of 362 hard and 154 of 154 hard_layout TASK.md files contain `## Spec` twice: the design-intent "Spec" paragraph section and
  the assertion list. The normal tier has 0 of 655. Command:
  `for f in tasks/v2/hard_layout/*/public/TASK.md; do grep -c '^## Spec$' $f; done | sort | uniq -c`.

### F9: inconsistent I²C pull-up bounds (severity: low)

- In packet 018, R2 (SDA) has the range 340 Ω–2.3 kΩ and R3 (SCL) has 280 Ω–3.2 kΩ, for identical lines (same 300 pF, same 3 mA
  spec). Both ranges are wider than the stated datasheet range, 700 Ω–1.16 kΩ, so the assertions are what actually constrains
  the values. This is harmless for grading (v1 F1, bounds rejecting valid pull-ups, is fixed), but an EE will ask why the ranges differ.

## What reviewers should look at first

1. hard_layout packets with `kelvin_sense_tap` (095, 098): F1.
2. `switch_loop_spread` packets (093–098): check the faulted area against 60 mm² in 2.9 (F2), and note F6 for 093/094.
3. `connector_pin_swap` on 2-pin coil connectors (069, 070, 071, 066): F5.
4. Every hard packet's 2.7: is the quoted line real evidence? (F4)
