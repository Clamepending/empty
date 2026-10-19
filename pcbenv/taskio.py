"""On-disk task layout (SPEC §8): writing and reading task directories.

```
<task_dir>/
  public/   design.json  board.kicad_pcb  TASK.md  spec.json  parts/<PART>.md
  hidden/   golden_design.json  golden_board.kicad_pcb  meta.json
```
`public/spec.json` holds what the agent is allowed to know about the spec: the assertions
(they are spec, not secret), the required power-net widths, the decoupling rules and the
acceptable value range of every valued component (`value_bounds`: ref -> [min, max], SI units).
`hidden/meta.json` is what the grader trusts: task_id, family, seed, board_seed, params,
faults, assertions, power_nets, power_net_pins, decoupling, value_bounds, alt_partitions, ref_parts
(golden ref -> part name, used to name board pads), difficulty.

`write_task` is the generic writer (the fault injector passes a faulted public design/board);
`make_golden_task` writes an unfaulted golden task.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from pcbenv import design as D
from pcbenv.golden import Golden
from pcbenv.parts import PARTS

PUBLIC_FILES = ("design.json", "board.kicad_pcb")
TOOLS_TEXT = """\
## Tools

Run `pcbtool <command>` inside this directory (you may also edit the two files directly).

Read-only:
- `pcbtool show` — components, values, footprints, positions and nets
- `pcbtool netlist` — design nets vs. board pad nets, with differences highlighted
- `pcbtool drc` — KiCad DRC under the canonical rules (the same rules the grader uses)
- `pcbtool erc` — electrical rule check of design.json
- `pcbtool sim` — run the spec assertions (spec.json) on design.json
- `pcbtool parts [PART]` — list parts / print a part's datasheet (also in `parts/`)
- `pcbtool check` — all of the above in one summary

Mutating (each keeps design.json and board.kicad_pcb consistent and saves both):
- `pcbtool set-value REF VALUE`
- `pcbtool set-footprint REF LIB:FOOTPRINT`
- `pcbtool connect REF.PIN NET` / `pcbtool disconnect REF.PIN`
- `pcbtool move REF X Y ROT` (absolute mm, degrees; tracks do not follow)
- `pcbtool unroute NET` / `pcbtool route NET [--width W]` (re-routes the whole net)
- `pcbtool sync` — push design.json connectivity and values onto the board pads
"""


def _fmt(x: float, unit: str) -> str:
    """4-significant-digit SI string, e.g. 3.201 V, 19 mA, 10.55 kHz."""
    x = float(x)
    if x == 0:
        return f"0 {unit}".strip()
    for suffix, mult in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(x) >= mult * 0.99995:
            return f"{x / mult:.4g} {suffix}{unit}".strip()
    return f"{x:.4g} {unit}".strip()


_UNITS = {"dc_voltage": "V", "dc_current": "A", "ac_gain": "", "cutoff": "Hz", "rise_time": "s"}


def _source_kind(s: dict) -> str:
    """Plain-English stimulus kind from the source's keys (QA F4: AC sources are not "dc")."""
    kind = s.get("kind", "dc")
    if kind == "release":
        return "open-drain driver releasing the line"
    if kind == "step":
        return f"step {s.get('v0', 0)} V -> {s.get('v1')} V source"
    ac, dc = s.get("ac"), s.get("dc")
    if ac and dc:
        return f"{dc} V DC + {ac} V AC source"
    if ac:
        return f"{ac} V AC source"
    return f"{dc if dc is not None else 0} V DC source"


def describe_assertion(a: dict) -> str:
    """One plain-English line for a spec assertion."""
    t = a.get("type")
    u = _UNITS.get(t, "")
    rng = f"between {_fmt(a['min'], u)} and {_fmt(a['max'], u)}" if "min" in a and "max" in a else ""
    if t == "dc_voltage":
        what = f"DC voltage at {a['net_pin']}" + (f" relative to {a['ref_pin']}" if a.get("ref_pin") else "")
    elif t == "dc_current":
        what = f"DC current through {a['element']}"
    elif t == "ac_gain":
        what = f"AC gain |V({a['out_pin']})/V({a['in_pin']})| at {_fmt(a['freq'], 'Hz')}"
    elif t == "cutoff":
        what = f"-3 dB frequency from {a['in_pin']} to {a['out_pin']}"
    elif t == "rise_time":
        what = f"10-90 % transition time at {a['net_pin']}"
    elif t == "analytic" and a.get("check") == "xtal_load":
        return (f"- `{a.get('name')}`: crystal {a['xtal']} effective load capacitance within "
                f"±{a.get('tol', 0.1) * 100:.0f} % of its rated CL (stray {_fmt(a.get('cstray', 0), 'F')})")
    else:
        what = f"{t} check"
    cond = []
    for s in (a.get("supply") if isinstance(a.get("supply"), list) else [a["supply"]] if a.get("supply") else []):
        cond.append(f"{s['pin']} supplied with {s['volts']} V")
    for s in (a.get("source") if isinstance(a.get("source"), list) else [a["source"]] if a.get("source") else []):
        cond.append(f"{_source_kind(s)} on {s['pin']}")
    for ld in a.get("loads") or []:
        parts = [f"{k.upper()}={ld[k]:g}" for k in ("r", "l", "c") if ld.get(k) is not None]
        cond.append(f"load {' '.join(parts)} from {ld['pin']} to {ld.get('to', 'ground')}")
    if a.get("ground_pin"):
        cond.append(f"ground = {a['ground_pin']}")
    tail = f" ({'; '.join(cond)})" if cond else ""
    return f"- `{a.get('name')}`: {what} {rng}{tail}".rstrip()


def anchor_pin(pins: list[str]) -> str:
    """A representative pin of a golden net (first connector pin, else first pin) that names
    the net publicly without revealing its full pin set."""
    pins = sorted(pins)
    conn = [p for p in pins if p.startswith("J")]
    return (conn or pins or [""])[0]


def public_spec(golden: Golden) -> dict:
    nets = golden.design["nets"]
    return {
        "title": golden.design.get("title", ""),
        "assertions": golden.assertions,
        "power_nets": [{"net": n, "anchor_pin": anchor_pin(nets.get(n, [])), "min_width_mm": w}
                       for n, w in sorted(golden.power_nets.items())],
        "decoupling": golden.decoupling,
        "value_bounds": golden.value_bounds,
    }


_VALUE_UNITS = {"R": "Ω", "C": "F", "L": "H"}


def value_bound_lines(design: dict, bounds: dict) -> list[str]:
    """`- R1 (R): 3.3 kΩ … 30 kΩ` lines for TASK.md."""
    out = []
    for ref, (lo, hi) in sorted(bounds.items()):
        part = design["components"].get(ref, {}).get("part", "")
        unit = _VALUE_UNITS.get(part, "Hz" if part.startswith("XTAL") else "")
        out.append(f"- {ref} ({part}): {_fmt(lo, unit)} … {_fmt(hi, unit)}")
    return out


def render_task_md(golden: Golden, problem: str | None = None) -> str:
    """TASK.md text. `problem` (markdown) describes the reported symptoms of a faulted task."""
    spec = public_spec(golden)
    lines = [f"# Task: {golden.design.get('title', golden.family)}", ""]
    if problem:
        lines += ["## Problem report", "", problem.strip(), ""]
    else:
        lines += ["## Problem report", "",
                  "This board was submitted for review. Check it against the spec below and fix anything "
                  "that is wrong (it may already be correct).", ""]
    lines += ["## Design intent", "", golden.intent.strip(), "",
              "## Spec", "",
              "The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in "
              "`spec.json`):", ""]
    lines += [describe_assertion(a) for a in spec["assertions"]]
    if spec["power_nets"]:
        lines += ["", "Layout: every track of these nets must be at least the given width:", ""]
        lines += [f"- {p['net']} (the net of {p['anchor_pin']}): ≥ {p['min_width_mm']} mm" for p in spec["power_nets"]]
    if spec["decoupling"]:
        lines += ["", "Decoupling: every pad of each capacitor within the given distance of the IC pin's pad:", ""]
        lines += [f"- {d['cap']} within {d['max_mm']} mm of {d['ic_pin']}" for d in spec["decoupling"]]
    if spec["value_bounds"]:
        lines += ["", "Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in "
                  "`spec.json`). Ranges come from the datasheets and the design intent; values the assertions "
                  "already pin down get a wide sanity range, and the assertions still apply:", ""]
        lines += value_bound_lines(golden.design, spec["value_bounds"])
    lines += ["", "Board rules: 2 copper layers, clearance 0.2 mm, min track 0.2 mm, vias 0.6/0.3 mm, "
              "copper-to-edge 0.3 mm. DRC must be clean with no unconnected items.", "",
              "## Deliverable", "",
              "- Edit only `design.json` (the schematic of record) and `board.kicad_pcb` (the layout).",
              "- Do not add, remove or rename components; keep each component's part.",
              "- Keep the two files consistent: same connectivity, values and footprints on both.",
              "- Do not change the board outline, add zones, or add DRC exclusions.",
              "- Footprints must be unmodified library footprints from the part's allowed list "
              "(see `parts/<PART>.md`).",
              "- Grading is pass/fail: topology, consistency, DRC, ERC, spec, component values and layout "
              "must all pass.", "",
              TOOLS_TEXT]
    return "\n".join(lines)


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_task(task_dir: str | os.PathLike, golden: Golden, golden_board: str,
               public_design: dict | None = None, public_board: str | None = None,
               faults: list[dict] | None = None, task_id: str | None = None, board_seed: int = 0,
               alt_partitions: list | None = None, difficulty: dict | None = None,
               problem: str | None = None, extra_meta: dict | None = None) -> Path:
    """Write a complete task dir. Public design/board default to the golden ones."""
    root = Path(task_dir)
    pub, hid = root / "public", root / "hidden"
    if root.exists():
        shutil.rmtree(root)
    (pub / "parts").mkdir(parents=True)
    hid.mkdir(parents=True)
    pd = public_design if public_design is not None else golden.design
    D.save(pd, pub / "design.json")
    shutil.copyfile(public_board or golden_board, pub / "board.kicad_pcb")
    (pub / "TASK.md").write_text(render_task_md(golden, problem), encoding="utf-8")
    _write_json(pub / "spec.json", public_spec(golden))
    used = sorted({c["part"] for c in golden.design["components"].values()} |
                  {c["part"] for c in pd["components"].values() if c.get("part") in PARTS})
    for p in used:
        (pub / "parts" / f"{p}.md").write_text(PARTS[p].datasheet, encoding="utf-8")
    D.save(golden.design, hid / "golden_design.json")
    shutil.copyfile(golden_board, hid / "golden_board.kicad_pcb")
    meta = {
        "task_id": task_id or root.name,
        "family": golden.family, "seed": golden.seed, "board_seed": board_seed,
        "params": golden.params, "faults": faults or [],
        "assertions": golden.assertions, "power_nets": golden.power_nets,
        "power_net_pins": {n: sorted(golden.design["nets"].get(n, [])) for n in golden.power_nets},
        "decoupling": golden.decoupling, "value_bounds": golden.value_bounds,
        "alt_partitions": alt_partitions or [],
        "ref_parts": {ref: c["part"] for ref, c in sorted(golden.design["components"].items())},
        "board_w_mm": golden.board_w_mm, "board_h_mm": golden.board_h_mm,
        "difficulty": difficulty or {"measured": None, "predicted": None},
    }
    meta.update(extra_meta or {})
    _write_json(hid / "meta.json", meta)
    return root


def make_golden_task(golden: Golden, task_dir: str | os.PathLike, board_seed: int = 0,
                     task_id: str | None = None) -> Path:
    """Build the golden board and write an unfaulted task (public == golden)."""
    from pcbenv.board import build_board
    with tempfile.TemporaryDirectory(prefix="pcbtask_") as td:
        bpath = os.path.join(td, "board.kicad_pcb")
        build_board(golden, bpath, board_seed)
        return write_task(task_dir, golden, bpath, task_id=task_id, board_seed=board_seed)


# ------------------------------------------------------------------ reading
def load_meta(task_dir: str | os.PathLike) -> dict:
    return json.loads((Path(task_dir) / "hidden" / "meta.json").read_text(encoding="utf-8"))


def load_golden_design(task_dir: str | os.PathLike) -> dict:
    return json.loads((Path(task_dir) / "hidden" / "golden_design.json").read_text(encoding="utf-8"))


def golden_board_path(task_dir: str | os.PathLike) -> str:
    return str(Path(task_dir) / "hidden" / "golden_board.kicad_pcb")


def copy_public(task_dir: str | os.PathLike, workdir: str | os.PathLike) -> None:
    """Copy public/ into `workdir` (created if needed)."""
    shutil.copytree(Path(task_dir) / "public", workdir, dirs_exist_ok=True)
