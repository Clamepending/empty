"""TASK.md writer for faulted tasks: bug-report framing at one of three hint levels.

- `explicit`: full design intent + the areas a reviewer narrowed the failure down to
  (component / pin / net names) + measured symptoms.
- `symptom`:  reduced intent (purpose, external interfaces, spec) + the measured misbehaviour,
  computed by simulating, DRC-ing, ERC-ing and layout-checking the faulted files.
- `vague`:    reduced intent + "fails bring-up, find and fix all problems".

Reduced intent drops the golden intent's connection bullets ("R1 from VOUT to FB ...") so the
agent must use the part datasheets in `parts/` for how parts connect. Fault type names and
fault details never appear at the symptom / vague levels.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from pcbenv import boardnet, erc, layout, sim
from pcbenv import design as D
from pcbenv.drc import run_drc
from pcbenv.golden import Golden
from pcbenv.parts import PARTS
from pcbenv.taskio import _UNITS, _fmt, render_task_md

HINT_LEVELS = ("explicit", "symptom", "vague")

REDUCED_NOTE = ("_Connection details are intentionally not repeated here: wire each part as its datasheet in "
                "`parts/` describes (pinout and application notes), so that the circuit does what the purpose, "
                "interfaces and spec above require._")


def reduce_intent(intent: str) -> str:
    """Purpose + external interfaces + spec: drop the per-part connection bullets / topology lines."""
    out: list[str] = []
    in_bullet = False
    for line in intent.splitlines():
        s = line.strip()
        if line.startswith("- "):
            in_bullet = True
            continue
        if in_bullet and line.startswith("  ") and s:
            continue
        in_bullet = False
        if s.startswith("Topology:"):
            continue
        out.append(line)
    text, blank = [], False
    for line in out:
        if not line.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        text.append(line)
    return "\n".join(text).strip() + "\n\n" + REDUCED_NOTE + "\n"


# ------------------------------------------------------------------ symptoms
def _rng_txt(a: dict) -> str:
    u = _UNITS.get(a.get("type"), "")
    return f"{_fmt(a['min'], u)} to {_fmt(a['max'], u)}"


def _is_led(design: dict, ref: str) -> bool:
    c = design["components"].get(ref)
    return bool(c) and c["part"].startswith("LED_")


def sim_symptoms(golden: Golden, design: dict) -> list[str]:
    out = []
    by_name = {sim.assertion_name(a): a for a in golden.assertions}
    for r in sim.run_assertions(design, golden.assertions):
        if r.passed:
            continue
        a = by_name.get(r.name, {})
        t = a.get("type")
        u = _UNITS.get(t, "")
        m = None if r.measured is None else _fmt(r.measured, u)
        if m is None:
            out.append(f"`{r.name}`: no valid measurement — the circuit does not reach a sensible operating point.")
        elif t == "dc_current" and _is_led(design, a.get("element", "")) and abs(r.measured) < 2e-4:
            out.append(f"LED {a['element']} never lights (`{r.name}`: {m}; expected {_rng_txt(a)}).")
        elif t == "dc_current":
            out.append(f"Bench: current through {a['element']} is {m}, expected {_rng_txt(a)} (`{r.name}`).")
        elif t == "dc_voltage":
            out.append(f"Bench: {a['net_pin']} reads {m}, expected {_rng_txt(a)} (`{r.name}`).")
        elif t == "rise_time":
            out.append(f"Scope: the edge on {a['net_pin']} takes {m} (10–90 %), spec allows {_rng_txt(a)} "
                       f"(`{r.name}`).")
        elif t == "ac_gain":
            out.append(f"Network analyser: gain {a['in_pin']} → {a['out_pin']} at {_fmt(a['freq'], 'Hz')} is "
                       f"{r.measured:.4g}, expected {a['min']:.4g} to {a['max']:.4g} (`{r.name}`).")
        elif t == "cutoff":
            out.append(f"Network analyser: −3 dB corner {a['in_pin']} → {a['out_pin']} measured at {m}, "
                       f"expected {_rng_txt(a)} (`{r.name}`).")
        elif t == "analytic" and a.get("check") == "xtal_load":
            out.append(f"The clock runs off-frequency: the crystal's effective load capacitance is "
                       f"{_fmt(r.measured, 'F')} (`{r.name}` fails).")
        else:
            out.append(f"Spec check `{r.name}` fails (measured {m}).")
    return out


def drc_symptoms(board_path: str) -> list[str]:
    r = run_drc(board_path)
    out = []
    if r.errors:
        c = Counter(e["type"] for e in r.errors)
        kinds = ", ".join(f"{n}× {k}" for k, n in sorted(c.items()))
        out.append(f"The fab's DRC run rejects the layout: {len(r.errors)} error(s) ({kinds}).")
    if r.unconnected:
        out.append(f"The fab's DRC run reports {r.unconnected} unconnected item(s).")
    return out


def erc_symptoms(design: dict) -> list[str]:
    errs = erc.errors(erc.run_erc(design))
    if not errs:
        return []
    c = Counter(i.code for i in errs)
    return ["Schematic ERC reports " + ", ".join(f"{n}× {k}" for k, n in sorted(c.items())) + "."]


def board_symptoms(golden: Golden, design: dict, board_path: str) -> list[str]:
    out = []
    rp = {r: c["part"] for r, c in golden.design["components"].items()}
    info = boardnet.board_info(board_path, parts=rp)
    if info.partition != D.partition(design):
        out.append("The assembled board does not behave like the simulated schematic: the layout's netlist "
                   "disagrees with design.json.")
    if any(info.values.get(r) != c.get("value", "") for r, c in design["components"].items() if r in info.values):
        out.append("Incoming inspection: a part value on the layout does not match the design.json BOM.")
    meta = {"power_nets": golden.power_nets,
            "power_net_pins": {n: sorted(golden.design["nets"].get(n, [])) for n in golden.power_nets},
            "decoupling": golden.decoupling}
    codes = {i.code for i in layout.run_layout_checks(info, meta, board=board_path, ref_parts=rp)}
    if "power_width" in codes:
        out.append("Layout review: a track on a net with a required minimum width (see the layout rules) is narrower "
                   "than that width.")
    if "decoupling" in codes:
        out.append("Layout review: a decoupling capacitor sits too far from the IC pin it decouples.")
    return out


SILENT_SYMPTOMS = {
    "decap_misconnected": "Bring-up: an IC supply pin shows large ripple and the board resets intermittently under load.",
    "swapped_ic_pins": "Bring-up: an interface does not work on the real board even though the spec simulation passes.",
    "pin_to_wrong_net": "Bring-up: behaviour is wrong when inputs are left unconnected / at power-up, although the "
                        "spec simulation passes.",
    "transistor_pinout": "Bring-up: the switching stage behaves oddly on the real board.",
    "reversed_polarity": "Bring-up: a diode in the circuit runs hot / does not do its job.",
}
GENERIC_SILENT = ("Design review: at least one part is not connected the way its datasheet requires, "
                  "although the spec simulation passes.")


def silent_symptom(ftype: str) -> str:
    return SILENT_SYMPTOMS.get(ftype, GENERIC_SILENT)


def symptoms(golden: Golden, design: dict, board_path: str, silent_types: list[str]) -> list[str]:
    """Measured symptoms of the faulted files + a bring-up observation for each fault that no
    check except the hidden topology comparison would reveal (`silent_types`)."""
    out = sim_symptoms(golden, design) + erc_symptoms(design) + drc_symptoms(board_path)
    out += board_symptoms(golden, design, board_path)
    for t in silent_types:
        s = silent_symptom(t)
        if s not in out:
            out.append(s)
    return out or [GENERIC_SILENT]


# ------------------------------------------------------------------ explicit areas
def explicit_area(rec: dict) -> str:
    t, d = rec["type"], rec.get("data", {})
    if t == "bom_mismatch":
        return f"the value of {d['ref']} on the board vs. design.json"
    if rec["category"] == "value":
        refs = d.get("refs") or [d["ref"]]
        return "the value" + ("s of " if len(refs) > 1 else " of ") + " and ".join(refs)
    if t == "decap_misconnected":
        return f"how {d['cap']} is connected"
    if rec["category"] == "connectivity":
        pins = d.get("pins") or [d["pin"]]
        return "the connection" + ("s of " if len(pins) > 1 else " of ") + " / ".join(pins)
    if t == "board_pad_swap":
        return f"the board pads of {d['ref']} vs. design.json"
    if t in ("clearance_violation", "short_between_nets"):
        return f"the routing of net {d['net']} near net {d['other_net']}"
    if t in ("broken_trace", "narrow_power_trace"):
        return f"the routing of net {d['net']}"
    if t == "decap_moved_far":
        return f"the placement of {d['cap']}"
    if t == "footprint_swap":
        return f"the footprint of {d['ref']} and its tracks"
    return "the design"


# ------------------------------------------------------------------ TASK.md
def problem_text(level: str, golden: Golden, records: list[dict], symptom_lines: list[str]) -> str:
    if level == "vague":
        return ("The first boards built from these files fail bring-up. Find and fix all problems: the design "
                "must meet its purpose and spec, the layout must match design.json, and DRC/ERC must be clean.")
    lines = ["The first boards built from these files fail bring-up. Observations so far:", ""]
    lines += [f"- {s}" for s in symptom_lines]
    if level == "explicit":
        lines += ["", "A reviewer narrowed the failure down to these areas (each needs a fix):", ""]
        lines += [f"- {explicit_area(r)}" for r in records]
    lines += ["", "Fix every problem (there may be more than the observations show directly)."]
    return "\n".join(lines)


# Topology-only ("silent") faults whose correct wiring follows from the datasheets / interfaces alone.
# A silent fault of another type (e.g. a bias resistor returned to the wrong rail) is only
# recoverable from the full intent, so such tasks keep the full intent at every hint level.
DATASHEET_INFERABLE = frozenset({"reversed_polarity", "transistor_pinout", "swapped_ic_pins",
                                 "decap_misconnected", "floating_pin"})


def needs_full_intent(level: str, silent_types: list[str]) -> bool:
    return level == "explicit" or any(t not in DATASHEET_INFERABLE for t in silent_types)


def render(golden: Golden, level: str, records: list[dict], symptom_lines: list[str],
           full_intent: bool | None = None) -> str:
    if level not in HINT_LEVELS:
        raise ValueError(level)
    full = level == "explicit" if full_intent is None else full_intent
    g = golden if full else replace(golden, intent=reduce_intent(golden.intent))
    return render_task_md(g, problem_text(level, golden, records, symptom_lines))


# ------------------------------------------------------------------ hard tier (G12)
import re as _re  # noqa: E402

_INTERFACE_RE = _re.compile(r"\bJ\d+\b|\bpin \d+ =|\bU\d+\.[A-Z]|\b(PA[0-2]|SDA|SCL|XIN|XOUT)\b|"
                            r"\d(\.\d+)? ?V\b")

HARD_NO_AUTOROUTE_NOTE = """\
**Tool mode for this task: `no_autoroute`** (`tools.json`). `pcbtool route` and `pcbtool sync` are
disabled: after changing connectivity or footprints, edit the tracks (`segment` / `via` items) in
`board.kicad_pcb` yourself, or move parts with `pcbtool move`. All other commands work.
"""


def interface_lines(intent: str) -> list[str]:
    """Intent bullets that state an interface: connector pins, MCU pin assignments, rail voltages."""
    out, cur = [], None
    for line in intent.splitlines() + [""]:
        if line.startswith("- "):
            if cur:
                out.append(cur)
            cur = line
        elif cur is not None and line.startswith("  ") and line.strip():
            cur += " " + line.strip()
        else:
            if cur:
                out.append(cur)
            cur = None
    return [b for b in out if _INTERFACE_RE.search(b)]


def hard_intent(intent: str) -> str:
    """Hard-tier reduced intent: purpose / interfaces / spec, plus every bullet that fixes a
    connector pinout, an MCU pin assignment or a rail voltage (these must never be dropped)."""
    red = reduce_intent(intent)
    keep = interface_lines(intent)
    if not keep:
        return red
    head, _, note = red.rpartition(REDUCED_NOTE)
    return (head.rstrip() + "\n\nInterfaces and pin assignments (fixed):\n\n" + "\n".join(keep) + "\n\n"
            + REDUCED_NOTE + note)


def render_hard(golden: Golden, level: str, symptom_lines: list[str], full_intent: bool, mode: str) -> str:
    """Hard-tier TASK.md: symptom / vague problem report (latent faults have no symptoms by
    construction, so none are listed for them), full or hard-reduced intent, and the "Design
    rules" section stating that pcbtool does not check them."""
    from pcbenv.rules import DESIGN_RULES_MD
    from pcbenv.taskio import TOOLS_TEXT
    if level not in ("symptom", "vague"):
        raise ValueError(level)
    g = golden if full_intent else replace(golden, intent=hard_intent(golden.intent))
    text = render_task_md(g, problem_text(level, golden, [], symptom_lines))
    text = text.replace("\n## Deliverable\n", "\n" + DESIGN_RULES_MD + "\n## Deliverable\n", 1)
    old = "- Grading is pass/fail: topology, consistency, DRC, ERC, spec, component values and layout "
    if old in text:
        text = text.replace(old, "- Grading is pass/fail: topology, consistency, DRC, ERC, spec, component values, "
                                 "layout and the design rules above ", 1)
    if mode == "no_autoroute":
        text = text.replace(TOOLS_TEXT, TOOLS_TEXT.rstrip() + "\n\n" + HARD_NO_AUTOROUTE_NOTE, 1)
    return text


POWER_RULE_NOTE = """\
Resistor power rule: every resistor's continuous dissipation I²·R must stay at or below 50 % of its
footprint's rated power (0603 0.1 W, 0805 0.125 W, 1206 0.5 W; see `parts/R.md`). The grader checks
this under the spec's operating conditions; `pcbtool` does not.
"""


def add_power_rule_note(text: str, golden: Golden) -> str:
    """All-tier TASK.md note for the graded resistor power rule (QA F5)."""
    if not any(c["part"] == "R" for c in golden.design["components"].values()):
        return text
    return text.replace("\nBoard rules: ", "\n" + POWER_RULE_NOTE + "\nBoard rules: ", 1)
