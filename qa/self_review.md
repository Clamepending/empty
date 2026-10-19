# QA pre-screen: 15 packets reviewed by the packaging agent

**This is not the human EE sign-off.** The packaging agent (builder-packaging) reviewed these packets
as a skeptical EE would, to catch obvious problems before paying reviewers. The human forms
(`packets/*/review.yaml`) are still blank. Every claim below can be checked by rerunning a command:

```
python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7      # packets; prints verdict anomalies if any (none)
python3 qa/prescreen/analyses.py > qa/prescreen/analyses.txt      # population analyses A-H (train split only)
sh qa/prescreen/alt_fix.sh TASK_ID golden "pcbtool ..." ...      # grade an alternative repair; outputs in alt_fixes.txt
```

`qa/prescreen/alt_fixes.txt` and `qa/prescreen/analyses.txt` hold the outputs these findings quote.

## Verdict on the 100 packets (automated)

- All 100 packets: the verifier gives the faulted files reward 0 and the golden files reward 1. The build
  prints a warning on any other result, and it printed none.
- Every packet's golden reward is 1.0, with no gate or check messages.

## Per-packet judgement (15 packets, all 10 families)

| packet | family | faults | fair / solvable | ref fix correct | verifier agrees | alternative fixes | notes |
|---|---|---|---|---|---|---|---|
| 002 | divider_adc | bom_mismatch, broken_trace (vague) | yes / yes | yes | yes | adopting the board value 24.9k breaks the ratio and is correctly rejected (X2) | `pcbtool check` shows the BOM mismatch and the unconnected item |
| 011 | ldo_reg | FB/EN swapped, R2 15.4k, +2V5–GND short (vague) | yes / yes | yes (0.8·(1+24.3/11.5)=2.49 V) | yes | keeping R2=15.4k and scaling R1 to 32.4k is accepted (X4) | the LDO datasheet states that EN goes to VIN and FB to the divider |
| 018 | ldo_reg | decap_moved_far (vague) | yes / yes (5 mm rule published) | yes | yes | another spot within 5 mm is accepted, and an overlapping spot is correctly rejected (X3) | the distance rule is a proxy: loop area and return path are not checked (documented limitation) |
| 024 | led_driver | D4 reversed, R1 75 Ω, D6 footprint (vague) | yes / yes | yes | yes | keeping the 0603 LED and re-routing is accepted (X1) | the reduced intent does not give the LED order in each string. The minimal repair is unique, but equivalent rewirings are rejected (F6) |
| 033 | mcu_i2c | R3 2.2k, bom R1, decap far (symptom) | **disputable** / yes | yes | **no, for fault 1** | R3 = 1.53k–2.8k is valid under the datasheet and the stated spec but is rejected (F1) | R3=2.2k passes the sink-current spec (2.09 mA ≤ 3 mA) and the rise-time spec (169 ns). Only the bound 2.8k–25k fails it |
| 034 | mcu_i2c | NRST tied to GND (vague) | yes / yes | yes | yes | — | ERC, spec and topology all flag it |
| 046 | nmos_switch | G/S swapped, R2 3.3k, D1 footprint (explicit) | yes / yes | yes | yes | keeping the SOD-123 footprint and re-routing is accepted (X1). Both footprints are allowed and the part rating (1 A) is footprint-independent | R2=3.3k fails `ctrl_current_on` (1.48 mA > 1 mA), so this is a real fault. The layout message `power_net_missing` is a side effect of the swap (F9) |
| 052 | npn_switch | B/C swapped, R4 3.9k, clearance (symptom) | yes (bound published) / yes | yes | **arguable, for fault 2** | — | a 3.9k base pull-down still saturates Q1 and holds the load off. It is caught only by the published range 4.7k–220k ("datasheet 10k–100k"), so an EE may not call it a defect (F2) |
| 053 | npn_switch | R1 20 Ω, bom R3, R2 footprint (explicit) | yes / yes | yes (forced β≈9.4, 15 mA) | yes | keeping the 0805 footprint for R2 and re-routing is accepted (X1). The golden's 1206 for a 1.6 mA base resistor is arbitrary | the 20 Ω NRST pull-up is a real fault, but only the `values` check sees it |
| 061 | opamp_inv | IN+/IN- swapped (explicit) | yes / yes | yes (gain −4.98, fc 114 Hz) | yes | — | TASK.md calls the AC input stimulus "dc source" (F4) |
| 069 | opamp_inv | R1/R2 values swapped (vague) | yes / yes | yes | yes | — | spec and values both fail. Clear-cut |
| 079 | opamp_noninv | IN- floating, R1 54.9k, decap far (vague) | yes / yes | yes | yes | keeping R1=54.9k and setting R2=6.04k is accepted (X4) | — |
| 087 | rc_lowpass | C2 6.8p, GND 0.2 mm, broken trace (symptom) | yes / yes | **poor practice** (F7) | **arguable, for fault 2** | — | a 0.3 mm rule on the GND of a µA signal filter, with the symptom "runs hot at full load", is physically false (F3). The 10 pF/130 kΩ second stage is unloaded in the spec |
| 090 | xtal_osc | LED D1 reversed (vague) | yes / yes (thin) | yes | yes | — | the reduced intent never mentions D1 or R2. Only the `led_current` assertion and the datasheets reveal the LED (F10) |
| 094 | xtal_osc | VDD/GND swapped, bom C3, Y1 footprint (vague) | yes / yes | yes (CL_eff 18.0 pF) | yes | adopting the board's C3=47n (in range) is accepted (X2). Keeping the 2012 crystal and re-routing is accepted (X1) | — |

Summary: 13 of the 15 are clean. Packet 033 (one fault) is likely to be disputed by an EE. In packets 052 and 087,
one fault each is arguable as an engineering defect: it is detectable only through a published rule
(a range or a width), not a functional failure.

## Findings (with evidence)

### F1: value bounds reject I²C pull-ups that the datasheet and the task's own spec accept (severity: med-high, systematic)

- Packet 033 (`pcbr-mcu_i2c-153-bfc3eb79`). The injected `wrong_pull_resistor` sets R3 to 2.2 kΩ, with 5 V pull-ups.
  The MCU8 datasheet in `parts/MCU8.md` states `Rp ≥ (VDD - 0.4 V) / 3 mA`, which is 1.53 kΩ. The task's spec also
  passes: `scl_sink_current` is 2.09 mA (≤ 3 mA) and `scl_rise_time` is 169 ns (≤ 1 µs). Only `values` fails,
  because the bound is 2.8k–25k:
  ```
  $ sh qa/prescreen/alt_fix.sh pcbr-mcu_i2c-153-bfc3eb79 golden "set-value R3 2.2k" "sim"
  PASS scl_rise_time: measured 1.69182e-07, expected [0.0, 1e-06]
  PASS scl_sink_current: measured 0.00209091, expected [0.0, 0.003]
  VERIFY reward 0.0 failing ['values'] {"values": ["R3: value '2.2k' outside acceptable range [2800, 25000]"]}
  ```
- Across the population (`analyses.txt` §B), **43 of the 126** SDA/SCL pull-up bounds have a minimum above the datasheet minimum.
  The cause is SPEC §4's "golden ÷2.5–4" sanity range, applied to a value that the spec pins on only one side.
  Another shipped case is `pcbr-mcu_i2c-633-a24fc751`: R3 = 470 Ω on a 1.8 V bus, where the datasheet minimum is 467 Ω and the
  measured sink current is 2.98 mA ≤ 3 mA. Only `values` (bound 840 Ω) rejects it.
- The bound is published, so an agent can comply and the task is mechanically fair. But the "fault" is not a fault
  by the task's own datasheet, and an EE will answer `verifier_verdict_agrees: no`.
- **Fix (owner: builder-circuits / builder-faults):** for pull-ups, set the bound minimum to the datasheet formula.
  Regenerate the tasks whose `wrong_pull_resistor` value meets the datasheet rule.

### F2: 38 of the 271 value faults are caught only by `values`, and some are defensible designs (severity: med)

`analyses.txt` §A lists all 38. Most are unambiguous defects: a 20 Ω NRST pull-up, 100 pF decoupling, a 4.7 mF
"bulk" cap, a 24 MΩ pull-up, or a 10k–24k gate resistor where the published range is 4.7–220 Ω. The
`wrong_pull_resistor` cases are different. They are 270k, 330k, 390k, 560k and 1.2M gate pull-downs (nmos_switch, bound ≤ 220k, intent
"datasheet: 10k–100k") and 1.2k–3.9k base pull-downs (npn_switch, bound ≥ 4.7k). All of them pass the functional spec,
including the stated "1 MΩ / 10 MΩ leakage keeps the load off" tests. Practising EEs routinely use 100k–1M gate
pull-downs, so these faults rest only on a published range, not on any misbehaviour. Expect disputes on
packets such as 052 (`pcbr-npn_switch-185-e13e0b22`, R4 = 3.9k). **Suggestion:** inject `wrong_pull_resistor`
only at values at least 3× outside the datasheet range, or add the assertion that motivates the range (for example,
GPIO current budget or gate turn-off time).

### F3: `narrow_power_trace` on signal-level nets, with a false symptom text (severity: low-med)

28 train tasks narrow the GND of rc_lowpass (17) or divider_adc (11) (`analyses.txt` §C). These nets carry µA, so
0.2 mm vs 0.3 mm is a published-rule violation, not an electrical defect. At the symptom level, TASK.md says *"a supply
trace is narrower than its required width (it runs hot at full load)"* (packet 087, `pcbenv/prompts.py:139`),
which is physically false for these circuits. **Suggestion:** inject this fault only on nets that carry real load
current, and make the symptom text neutral ("violates the layout rule for net X").

### F4: TASK.md calls AC stimuli "dc source" (severity: low, 259 of 654 train tasks)

`taskio.describe_assertion` defaults `kind` to `"dc"`. As a result, every `cutoff`/`ac_gain` assertion whose source is
`{"ac": 1.0, ...}` reads "dc source on J1.1" (`analyses.txt` §D: 259/259). `spec.json` is correct, so a careful
agent can recover. An EE reading packet 061 or 087 will flag it. **Fix:** describe `ac`/`dc` from the source keys.

### F5: the led_driver "> 60 mW → 1206" requirement is stated but not graded (severity: med, verifier leniency)

The led_driver TASK.md says *"Resistors dissipating more than ~60 mW use a 1206 footprint."* In
`pcbr-led_driver-112-138ee0cb`, R1 (360 Ω, 78 mW, golden 1206) was moved to 0805 and re-routed, and the change scored **1.0**:
```
$ sh qa/prescreen/alt_fix.sh pcbr-led_driver-112-138ee0cb golden "set-footprint R1 Resistor_SMD:R_0805_2012Metric" "route CH1_0" "route VS" "route CH2_1" "drc"
DRC clean: 0 errors, 0 unconnected
VERIFY reward 1.0 failing [] {}
```
No shipped faulted task depends on this rule today: 0 of 29 hot resistors are off 1206 in a faulted design (§G). So
no shipped verdict is wrong. However, a repair that violates a stated requirement passes. **Fix (owner: builder-verifier):**
add a footprint-power check from simulated dissipation, or drop the sentence from the intent.

### F6: the topology gate rejects electrically equivalent rewirings (severity: low, documented limitation)

Two rewirings of `pcbr-led_driver-312-8e5d8552` (packet 024) pass every spec assertion but fail topology (`analyses.txt` §H):
moving a channel's resistor to the low side, and swapping two identical LED_RED parts in a string. Vague
led_driver tasks do not state the string order. Because faults move one pin, the minimal repair is unique, so the
risk is low. Reviewers may still log this under `alternative_valid_fixes_rejected`.

### F7: rc_lowpass golden with 10 pF / 130 kΩ and no output load (severity: low)

The packet 087 golden is R1=13k, C1=100p, R2=130k, C2=10p, and the spec assertions apply no load to J2. Any ADC
input or probe (5–15 pF) would move the corner a long way. The golden is correct per the stated spec, but 4 of the 68
rc_lowpass goldens use a cap < 22 pF. An EE may answer `reference_fix_correct: no (poor practice)`.
**Suggestion:** a minimum cap of about 100 pF, or a stated and simulated output load.

### F8: "standard-mode I²C" uses a 10–90 % rise time (severity: low)

The mcu_i2c spec uses a 10–90 % rise time ≤ 1000 ns (`sim._transition_time`, datasheet `Rp ≤ tr/(2.2·Cbus)`). UM10204
defines tr from 30 % to 70 %, which equals 0.85·RC, so this spec is about 2.6× stricter than the I²C standard it names.
The task is self-consistent and fair as stated, but EEs will notice. **Suggestion:** call it "10–90 % rise
time" rather than "standard-mode", or use 30–70 %.

### F9: misleading layout diagnostic on connectivity faults (severity: info)

When a connectivity fault touches a power net, `layout` reports `power_net_missing: no board net has the pins of
golden net GND` (packets 046, 090, 094). The verdict is right, because topology also fails, but the message points to
the wrong cause. It may skew the G6 failure taxonomy.

### F10: reduced intent can omit whole sub-circuits (severity: info)

In packet 090 (`pcbr-xtal_osc-109-c298a4ec`, vague), the intent describes only the MCU, the crystal and power. LED D1 and
R2 appear only through the `led_current` assertion and `parts/LED_GREEN.md`. The task is still solvable (the
reversed LED gives 8.7 µA against a 2–6 mA requirement), but the information is thin.

### Checked and fine

- **Valid alternatives are accepted.** These were tried: keeping a swapped allowed footprint and re-routing (4 tasks, X1);
  adopting an in-range board value for a `bom_mismatch` (X2); a different decap position within the limit (X3); and
  fixing a ratio on the other resistor (X4, 2 tasks). The verifier also correctly rejects the invalid
  variants: a board value that breaks the divider (X2), and an overlapping courtyard (X3). Outputs are in `alt_fixes.txt`.
- **No value fault is marginal.** Applied alone, every spec-detected value fault misses its window by at least
  8.4 % (`analyses.txt` §E: 0 faults in 0–5 %, 8 in 5–15 %).
- **E-series repairs.** For 244 of 252 single-ref value faults, one of the two nearest E24 values to the golden passes.
  The 8 exceptions are ±2 % divider/gain windows, where 5 % E24 steps are too coarse and E96 is needed (§F). That is
  reasonable, since the windows are published.
- **Every injected fault is visible to the agent's tools.** `pcbtool check` exposes BOM mismatches, DRC, ERC, spec and
  value ranges. The only exceptions are the topology-only swaps, and their pinout is stated in the intent (for
  example, the SDA/SCL header pinout).
