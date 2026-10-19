# PCB-Repair — technical spec (v1)

This is the contract between modules. If you need to change it, say so in your report
rather than silently diverging.

## 1. Concepts

- **Design of record** = `design.json` (the "schematic") + `board.kicad_pcb` (KiCad 7 layout).
- **Golden** = a correct design produced by a *family generator* from a seed.
- **Task** = golden + 1–3 injected faults, plus a `TASK.md` prompt. The agent edits the
  two deliverable files in its workdir; the verifier grades them against the hidden golden.
- Component reference designators are **fixed** — faults never add/remove components and
  agents must not either. (A "missing" part is modelled as a part that is disconnected/misconnected.)

## 2. `design.json` (schema `pcbenv/design@1`)

```json
{
  "schema": "pcbenv/design@1",
  "title": "3.3 V LDO regulator",
  "components": {
    "U1": {"part": "LDO_ADJ", "value": "", "footprint": "Package_TO_SOT_SMD:SOT-23-5"},
    "R1": {"part": "R", "value": "31.6k", "footprint": "Resistor_SMD:R_0805_2012Metric"}
  },
  "nets": {
    "VIN":  ["J1.1", "U1.VIN", "U1.EN", "C1.1"],
    "GND":  ["J1.2", "U1.GND", "C1.2"]
  }
}
```
- Pins are `REF.PINNAME`; pin names come from the parts library (`pcbenv/parts.py`).
  Passive two-terminal parts use pins `1`,`2`. Diodes/LEDs use `A`,`K`.
- A pin may appear in at most one net. Pins not listed are unconnected.
- Values: SI strings, `"10k"`, `"4.7u"`, `"100n"`, `"2.2"`, `"1M"`, `"470p"`, `"10m"`
  (m = milli, M = mega). Parsed by `parts.parse_value`. Empty for parts without a value.
- Net names are free text; graders compare **partitions**, never names.

**Partition** of a design = `frozenset` of `frozenset[str]` of `REF.PINNAME`, one inner set per
net with ≥1 pin. `design.partition(d)` and `boardnet.board_partition(path)` must produce the same
type so they can be compared with `==`.

## 3. Parts library (`pcbenv/parts.py`)

`PARTS: dict[str, Part]`. A `Part` has:
- `name`, `description`, `pins: dict[pinname, PinInfo]` where `PinInfo` = `pad` (footprint pad
  number as string) + `etype` (`power_in`, `power_out`, `input`, `output`, `bidir`, `passive`,
  `nc`) + `required: bool` (must be connected) .
- `footprints: list[str]` allowed `"Lib:Footprint"` ids (pad map must be valid for all of them).
- `value_required: bool`, `spice(ref, pins->node, value) -> str` netlist line(s) / subckt use,
  `datasheet: str` — short markdown datasheet the agent can read (pinout, electrical
  characteristics, application notes). These are generic parts (e.g. `LDO_ADJ`, `OPAMP`,
  `MCU8`, `NPN`, `LED_RED`), *not* real part numbers.

## 4. Family generators (`pcbenv/families/<family>.py`)

Each exposes `FAMILY: str` and `generate(seed: int) -> Golden` where `Golden` (in
`pcbenv/golden.py`) is:

```python
@dataclass
class Golden:
    family: str
    seed: int
    design: dict                 # design.json content
    assertions: list[dict]       # spec assertions, see §5
    power_nets: dict[str, float] # net name in golden -> min track width mm
    decoupling: list[dict]       # [{"cap": "C3", "ic_pin": "U1.VDD", "max_mm": 5.0}]
    intent: str                  # markdown: what the circuit is for, how it should be connected
    params: dict                 # sampled parameters (targets etc.)
    board_w_mm: float
    board_h_mm: float
    value_bounds: dict[str, list[float]] = {}  # ref -> [min, max] acceptable value, SI units
```
Deterministic in `seed`. Must pass all its own assertions.

Hard tier (v2): composite multi-rail families (`sys_*`, module attribute `TIER = "hard"`, listed in
`families.HARD_FAMILIES`; `families.V1_FAMILIES` are the others) — 20–40 parts, an LDO rail plus the
input rail, several ICs, 40–90 mm boards; their intent carries connector and MCU pin-assignment
tables (kept in the reduced intent) and `params["roles"]` lists refs per fault role.

`value_bounds` covers **every component with a value** (enforced by `families._common.golden`,
golden values must lie inside). Policy: a value that a spec assertion already pins down gets a
wide sanity range (golden ÷2.5–4 … ×2.5–4, factors drawn per ref so the midpoint does not reveal
the golden; or a datasheet range, e.g. the LDO divider) so alternative E-series repairs pass and
the assertion does the real work; a value no assertion constrains (decoupling/bulk caps,
pull-ups, gate/base resistors, crystal frequency, ...) gets a datasheet / engineering range,
which the family also states in `intent`. v2 (QA F1): a bound is never tighter than a limit the
public datasheets imply (e.g. I²C pull-up ≥ (VDD−0.4 V)/3 mA and ≤ tr/(0.8473·Cbus), LED ≤ 25 mA,
GPIO ≤ 8 mA): the sanity range is widened to contain it, and the limits used are recorded in
`params["datasheet_limits"]`. Bounds are requirements, not secrets: they are
published in `public/spec.json` and listed in TASK.md. Old goldens without the field load with `{}`.

## 5. Spec assertions (`pcbenv/sim.py`)

`run_assertions(design: dict, assertions: list[dict]) -> list[AssertionResult]`
(`AssertionResult(name, passed: bool, measured, expected, detail)`). Types:

| type | fields | meaning |
|---|---|---|
| `dc_voltage` | `net_pin` (a `REF.PIN` on the net), `min`, `max` | DC op-point voltage vs GND |
| `dc_current` | `element` (`REF`), `min`, `max` | DC current through a 2-terminal part (abs) |
| `ac_gain` | `in_pin`, `out_pin`, `freq`, `min`, `max` | |Vout/Vin| linear at freq |
| `cutoff` | `in_pin`, `out_pin`, `min`, `max` | −3 dB frequency (Hz) |
| `rise_time` | `net_pin`, `min`, `max`, optional `levels` | transition time between `levels` = [lo, hi] fractions of the swing after a step (s); default [0.1, 0.9]; I²C rise times use [0.3, 0.7] (UM10204) |
| `analytic` | `check`, params | non-SPICE check, e.g. crystal load capacitance |

Nodes are resolved through the design's nets (assertions reference pins, not net names, so
renaming nets cannot break or game them). Ground reference = net containing the pin named in
the golden's `"ground_pin"` key of the assertion set (default: the net containing a pin named
`GND` of the first IC, or `J1.2`). Simulation uses `ngspice -b` in a temp dir with a timeout.
DC operating points must be converged Newton solutions: if ngspice falls back to its "transient op"
guess (or an `op` node voltage lies outside the span of the stimulus voltages), the point is
re-derived (more gmin/source steps; pseudo-transient power-up -> full `.nodeset` -> Newton) and
the analysis re-run from it; failing that, the assertion fails with detail
`simulation did not converge` (measured = null) — never a fabricated measurement (v2).
Stimulus sources (supply, signal) are added by the assertion runner from assertion fields
`supply: {"pin": "J1.1", "volts": 5.0}` and `source: {"pin": ..., "ac": 1}` — they are part of the
golden assertion, never read from the agent's files.

## 6. Board (`pcbenv/board.py`, `pcbenv/router.py`, `pcbenv/drc.py`, `pcbenv/boardnet.py`)

- `build_board(golden: Golden, out_path: str, seed: int) -> None`: rectangular Edge.Cuts outline
  (`board_w_mm` × `board_h_mm`), 2 copper layers, footprints from `/usr/share/kicad/footprints`
  with reference = design ref, value = design value, pad nets = design nets via the parts pad map,
  deterministic placement, **fully routed** (no unconnected pads), DRC clean under the standard rules:
  clearance 0.2 mm, min track 0.2 mm, via 0.6/0.3 mm, power nets routed at
  `power_nets[net]` width. Decoupling caps placed within their `max_mm`.
- `run_drc(board_path, rules_board_path) -> DrcResult(errors: list[dict], unconnected: int)`.
  Loads the candidate, **overwrites its design settings with those of `rules_board_path`**
  (the golden), runs `pcbnew.WriteDRCReport`, parses it. Warnings ignored; only severity error.
- `board_info(board_path) -> BoardInfo` with: `partition` (in `REF.PINNAME` form, via the parts
  pad map), `footprints: {ref: "Lib:Name"}`, `values`, `positions: {ref: (x,y,rot)}`,
  `pad_fingerprint: {ref: hash of pad shapes/sizes/offsets}`, `outline_fingerprint`,
  `track_widths: {netname: min width mm}` and `net_pins: {netname: set(REF.PIN)}`,
  `zone_count`, `marker/exclusion count`.

## 7. Verifier (`pcbenv/verify.py`)

`verify(workdir: str, task_dir: str) -> VerifyResult(reward: float, gates: dict, checks: dict, detail)`.
Reads ONLY `workdir/design.json` and `workdir/board.kicad_pcb` (regular files, no symlinks,
size ≤ 5 MB), copies them to a fresh temp dir first. Hidden data from `task_dir/hidden/`.

Hard gates (all must pass, else reward 0):
1. `parse` — both files load; design validates against the schema & parts library.
2. `components` — same ref set as golden; each `part` equals golden; footprint in the part's allowed list
   and board footprint id == design footprint; pad fingerprint matches the library footprint.
3. `topology` — `partition(design) == partition(golden)` (or ∈ `hidden/meta.json:"alt_partitions"`).
4. `consistency` — board partition == design partition; board values == design values.
5. `integrity` — outline fingerprint == golden; no DRC exclusions/markers; no zones unless golden has them.

Checks (all must pass for reward 1.0):
6. `drc` — zero errors and zero unconnected under golden rules.
7. `erc` — `pcbenv/erc.py` finds no errors (required pins connected, no output-output conflicts,
   no single-pin nets, power_in pins on a net with a power_out/supply connector pin, ...).
8. `spec` — all golden assertions pass on the candidate design (values matter here).
9. `values` — every ref in `hidden/meta.json:"value_bounds"` has a design value that parses to a
   finite number in [min, max] (inclusive). Tasks without `value_bounds` skip it (passes).
10. `layout` — power nets (matched to golden by pin set) have min track width ≥ required; decoupling
   caps within max distance of their IC pin.

**Reward is binary**: 1.0 iff all gates and checks pass, else 0.0. `checks` carries the per-check
breakdown for diagnostics only.

## 8. Tasks on disk

```
tasks/<split>/<task_id>/
  public/   design.json  board.kicad_pcb  TASK.md  parts/<PART>.md
  hidden/   golden_design.json  golden_board.kicad_pcb  meta.json
```
`meta.json`: `task_id, family, seed, params, faults: [{type, detail}], assertions, power_nets,
decoupling, value_bounds, alt_partitions, difficulty (measured|predicted)`. `public/spec.json`:
`title, assertions, power_nets (net, anchor_pin, min_width_mm), decoupling, value_bounds`. Splits: `train`, `holdout`.

## 9. Agent-facing tool (`pcbtool`, `pcbenv/tool.py`)

Run inside the workdir. Read-only: `show`, `netlist`, `drc`, `erc`, `sim` (runs the assertions
listed in TASK.md — these are public — and the
`value_bounds` of spec.json; `check` reports both), `parts <PART>`. Mutating (keeps design.json and board in
sync): `set-value REF VAL`, `set-footprint REF FP`, `connect REF.PIN NET`, `disconnect REF.PIN`,
`move REF X Y ROT`, `route NET [--width W]`, `unroute NET`, `sync`. Agents may also edit files directly.
