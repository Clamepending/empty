# Reward

The verifier is `pcbenv/verify.py`: `verify(workdir, task_dir) -> VerifyResult(reward, gates, checks, detail)`.
`verify_isolated` runs the same function in a fresh `python3 -I` subprocess, and is the default
used by `pcbenv.api.verify`, the harness and the adapters.

**Reward is binary: 1.0 if and only if all 5 gates and all checks pass** (5 checks, plus `rules` for tasks with a rule context: every v2 task has at least the resistor-power rule). The per-stage
booleans and the `detail` messages are diagnostics. They are useful for failure taxonomies and
reward shaping experiments, but they are not part of the reward. Any exception inside the
verifier gives reward 0, with the message in `detail.error`. The verifier is deterministic: in
G3, 10 reruns of the same input produced identical results (`reports/g3_verify_run.txt`).

## Inputs

- **From the workdir:** only `design.json` and `board.kicad_pcb`. Each must be a regular file,
  not a symlink (it is opened with `O_NOFOLLOW`), no larger than 5 MB, and is copied into a fresh
  temp dir before parsing.
- **From `task_dir/hidden/`:** `golden_design.json`, `golden_board.kicad_pcb` and `meta.json`
  (assertions, power nets and their golden pin sets, decoupling rules, alternative partitions,
  and the golden ref→part map).
- **Canonical DRC rules come from `pcbenv/drc.py`, never from the candidate:** clearance 0.2 mm,
  minimum track 0.2 mm, via 0.6/0.3 mm, annular ring 0.1 mm, copper-to-edge 0.3 mm, hole clearance
  0.25 mm. The golden board can only tighten these.

## Gates (any failure means reward 0)

| Gate | What it checks | What it catches |
|---|---|---|
| `parse` | both files load; design.json has schema `pcbenv/design@1`; parts, pins and values are valid (v2 value grammar: `<number><SI prefix><unit>`, unit letters must match the part, no control characters or inner whitespace; see SPEC §2); no pin appears on two nets | corrupted or truncated files, invented parts or pins, malformed values, `100nH` on a capacitor, values with a trailing newline (RT32/RT59) |
| `components` | ref set == golden; `part` == golden part per ref; footprint is in the part's allowed list; board footprint id == design footprint; pad fingerprint (shapes, sizes, offsets, net-tie pad groups, copper-graphic shapes) and copper graphics == the library footprint; net-tie information that cannot be read fails closed (v2, RT30) | adding, removing or renaming parts; swapping in a different part; shrinking or moving pads to dodge DRC; hand-edited footprints |
| `topology` | `partition(design)` == golden partition, or one of `meta.alt_partitions`. Net names are ignored, and the two pins of symmetric parts (R, C, L, crystals) may be swapped | wrong, missing or extra connections; shorts; opens; pins swapped on polarised or multi-pin parts |
| `consistency` | board pad connectivity == design.json partition; board values == design values, compared as numbers (`1k` == `1000`, v2 RT33) | fixing only one of the two files; a schematic that disagrees with the layout |
| `integrity` | Edge.Cuts outline fingerprint == golden; no DRC markers or exclusions; no zones beyond the golden's; same copper layer count; no tracks on inner layers; no added copper drawings or text | enlarging the board to make room; silencing DRC; flooding copper to "connect" nets; drawing copper shapes to fake connectivity |

## Checks (all must pass for reward 1)

| Check | What it checks | What it catches |
|---|---|---|
| `drc` | `pcbnew.WriteDRCReport` under the canonical rules: zero errors and zero unconnected items. Warnings are ignored, as are `lib_footprint_*` items, which depend on the host's library table | clearance violations, shorts, unrouted nets, tracks that are too thin, copper too close to the edge, overlapping courtyards (when KiCad reports them with severity error) |
| `erc` | `pcbenv/erc.py` on design.json: unconnected required pins, single-pin nets, driver conflicts, `power_in` without a source, supply or output shorted to ground, nets of inputs only | floating enables or feedback pins, regulator outputs tied together, missing supply connections |
| `spec` | every golden assertion (`dc_voltage`, `dc_current`, `ac_gain`, `cutoff`, `rise_time`, `analytic` crystal load) passes when the candidate design is simulated with ngspice. Stimuli and loads come from the hidden assertion, never from the agent's files | wrong component values, wrong value magnitude (k vs M), wrong crystal load caps. This is the main detector for faults that DRC and ERC cannot see |
| `values` | every component listed in `meta.value_bounds` (ref → [min, max], SI units; also public in `spec.json` and TASK.md) has a design value inside its range. Values that assertions pin down get a wide sanity range; values no assertion sees get a datasheet range (decoupling 47 nF–10 µF, NRST pull-up 2.2k–100k, gate/base pull-downs, bulk caps, crystal frequency ±0.1 %, ...). Tasks without `value_bounds` pass trivially | values the spec cannot see: a crystal at the wrong frequency (RT01), a decoupling cap ×100, a 430 Ω gate resistor, a pull-down that no longer holds the switch off; absurd R-vs-C rescaling that keeps a corner frequency |
| `layout` | each golden power net, identified on the board by its pin set and never by name, has every track ≥ the required width; each decoupling cap's pad on the IC pin's net reaches the pin through at most `max_path_mm` of copper (shortest path over the net's tracks, vias and pads; v2, RT31) and every cap pad is within `max_mm` of the pin in a straight line | undersized power traces; decoupling caps moved away from the IC; a cap left next to the pin but wired to it the long way round (via the connector), or wired to another rail |

## Design rules (`rules`, hard tier and resistor power)

Tasks whose `hidden/meta.json` carries a rule context get a sixth check, `rules`
(`pcbenv/rules.py`): datasheet design rules that `pcbtool` deliberately does **not** run. The
candidate design is DC-simulated under every stimulus condition of the golden's assertions and
checked against absolute-maximum ratings (MCU pins within -0.3 V…VDD+0.3 V, op-amp inputs within the
rails, LDO EN ≤ VIN, NMOS |VGS| ≤ 12 V, ...), current limits (MCU pins, LED IF by package, NPN IC/IB,
forced beta ≤ 20 for a saturated switch), resistor power (I²R ≤ 50 % of the footprint rating:
0603 0.1 W, 0805 0.125 W, 1206 0.5 W), capacitor voltage (≤ 80 % of 10/25/50 V for 0603/0805/1206)
and flyback-diode orientation across inductive loads (v2.1: a Schottky with one pin on each of the load's
two nets, cathode on the side at the higher potential while the load is energised -- judged by the load's
terminals, so a non-polar coil plugged in with connector pins 1/2 exchanged is still clamped; the pin swap
itself is the topology gate's business when the intent fixes the pinout). Every rule is stated in the task's
`parts/<PART>.md` and TASK.md.

- `meta["rules"]` (hard tier, `tier: "hard"`, `python3 -m pcbenv.generate --tier hard`): all rules.
- `meta["rules_power"]` (all tiers from v2 on): the resistor power rule only.
- Tasks without either key (all v1 shipped tasks) are graded exactly as before; `checks` has no `rules` entry.

Hard-tier tasks state the decoupling rules in TASK.md's "Design rules" section and in
`spec.json:design_rules.decoupling` (`spec.json:decoupling` is empty, so `pcbtool check` does not run
them); the verifier's `layout` check grades them exactly as above. Hard-tier tasks also carry `public/tools.json` (`{"mode": "full" | "no_autoroute"}`); in
`no_autoroute` mode `pcbtool route` / `sync` exit 2. This is a task knob, not a security boundary:
the grader only sees the two deliverable files.

When the topology gate fails, a golden power net that cannot be found by its pin set is reported
under `detail["layout_skipped"]` instead of failing `layout` (the connectivity error is the
topology gate's finding).

## Known limitations

- **The spec check is only as strong as the golden assertions.** A value change that stays inside
  every assertion's tolerance window, and inside its `value_bounds` range, passes. That is intended (any in-spec value is correct), but
  it means a fault can only be detected if it moves a measured quantity outside its window. The
  fault injector (G4) keeps only faults the verifier detects (≥ 99 % per type).
- **SPICE models are behavioural.** The op-amp, LDO, MCU and transistor models are simplified
  generics, so a design that is "correct" under these models may not be correct for a real
  device.
- **Topology is compared against the golden** (plus explicit `alt_partitions`). An electrically
  equivalent but structurally different repair, such as two resistors in series instead of one,
  is impossible anyway because refs are fixed. A valid alternative that the task author did not
  enumerate, however, fails.
- **DRC is KiCad 7.0.11's.** Its quirks are inherited. `drc.py` documents a workaround: DRC runs
  twice per load because of an uninitialised-member bug. Only items KiCad reports with severity
  `error` count; items that KiCad's default severities leave at warning or ignore (silkscreen,
  dangling tracks, missing courtyards, ...) are not graded.
- **Layout covers only power-net widths and decoupling distance / copper path length** (plus, in the hard_layout
  sub-tier, the `layout_rules` check: Kelvin sense, switching-loop area, crystal traces, analog/switching
  separation; see SPEC §7 item 12 and the task's TASK.md for the exact definitions). No signal integrity, return
  paths, thermal, EMI or manufacturability (DFM) checks are performed.
- **Binary reward hides partial progress.** Use `gates`/`checks` for diagnostics; they are not a
  calibrated partial-credit signal.
- **The adversarial robustness claim is bounded by red-team coverage** (G5, `redteam/`): zero
  known successful hacks does not prove that no hack exists.
