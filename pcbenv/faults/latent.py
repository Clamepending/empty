"""Latent faults (hard tier, G12): defects that EVERY pcbtool output misses.

A latent fault, applied alone to a (hardened) golden, leaves all tool-visible checks passing:
design.json vs board consistency, DRC, ERC, the spec assertions (`pcbtool sim`), the published
value bounds and the layout rules -- `visible_failures` replicates `pcbtool check` and the
injector asserts it is empty, otherwise the candidate is dropped. It is still caught by the
grader: by the `rules` check (datasheet design rules, `pcbenv/rules.py`) and/or by the hidden
topology gate. Each is deducible from public material: the datasheet addenda in `parts/`,
TASK.md's "Design rules" section, the design intent's interfaces, or spec.json.

Every injector returns a FaultRecord with category "latent" and `data` holding `latent: True`,
`detected_by` (rules / topology / both), `rule_codes` and `evidence` (which public text makes the
defect deducible). Records are hidden (meta.json only).

Types
- resistor_underrated   R footprint downsized; I²R > 50 % of the smaller footprint's rating     [rules]
- capacitor_underrated  C footprint downsized; working V > 80 % of its voltage rating           [rules]
- led_underrated        LED package downsized; IF > 80 % of the smaller package's maximum       [rules]
- weak_base_drive       NPN base resistor raised (inside its value range); still saturates in the
                        sim, but forced beta IC/IB > 20                                          [rules]
- flyback_misplaced     flyback diode moved off the inductive load (anode to GND / across the
                        transistor / both ends on the supply); the on/off DC states are unchanged [rules+topology]
- connector_pin_swap    two pins of an interface connector exchanged (pinout fixed by the intent) [topology]
- mcu_pin_swap          two MCU pin functions exchanged where the circuit still simulates
                        (e.g. SDA <-> SCL)                                                       [topology]
- decap_swapped         two decoupling caps on different rails exchange rails while sitting at
                        their (public) IC pins                                                    [topology]
- bias_wrong_rail       a bias / bypass / reset part returned to the supply instead of GND where
                        DC and AC behaviour do not change (VMID bypass, input bias R, NRST cap,
                        anti-alias cap of an ADC divider)                                        [topology]
- pullup_wrong_rail     an MCU I/O pull-up (I2C) returned to the higher input rail instead of the
                        MCU's rail: the line idles above VDD (abs max)                           [rules+topology]
- decap_wrong_rail      a decoupling cap next to its IC pin but wired to another rail            [topology+layout]
- protection_bypassed   the series reverse-polarity Schottky bypassed (its cathode net merged into
                        the raw input): every on-state sim still passes                          [topology]

Hard tier (v2): the decoupling rules are stated in TASK.md / spec.json `design_rules` but not run
by pcbtool, so `decap_swapped` / `decap_wrong_rail` are graded by the verifier's layout check (copper
path from the cap pad to the named IC pin) and the topology gate. `evidence_groups` lists the
public text that makes each fault deducible; the hard generator drops a task whose public files
miss any of it.
"""
from __future__ import annotations

import math
import os
import random
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable

from pcbenv import boardnet, drc, erc, rules, sim
from pcbenv import design as D
from pcbenv.checks import value_violations
from pcbenv.faults.common import (FaultRecord, NotApplicable, copy_design, design_pad_nets, drc_result, free,
                                  load_board, move_pin, net_of, nets_target, reroute, rewire, save_board, seed_kiid,
                                  set_board_values, swap_pins, topology_differs)
from pcbenv.golden import Golden
from pcbenv.parts import PARTS, format_value, parse_value


# ------------------------------------------------------------------ tool-equivalent checks
def visible_failures(golden: Golden, design: dict, board_path: str) -> list[str]:
    """Everything `pcbtool check` would report for (design, board) in a task made from `golden`
    (spec.json = taskio.public_spec(golden, hard=True)). Empty list = the tool sees nothing wrong."""
    from pcbenv import taskio, tool
    out: list[str] = []
    try:
        D.validate(design)
    except D.DesignError as e:
        return [f"design invalid: {e}"]
    spec = taskio.public_spec(golden, hard=True)
    board = load_board(board_path)
    info = boardnet.board_info(board, design=design)
    out += [f"consistency: {m}" for m in tool._consistency(design, info)]
    r = drc.run_drc(board_path)
    out += [f"drc: {e['type']}: {e['description']}" for e in r.errors]
    if r.unconnected:
        out.append(f"drc: {r.unconnected} unconnected")
    out += [f"erc: {i.code}: {i.detail}" for i in erc.errors(erc.run_erc(design))]
    out += [f"sim: {a.name}" for a in sim.run_assertions(design, spec["assertions"]) if not a.passed]
    out += [f"values: {m}" for m in value_violations(design, spec.get("value_bounds") or {})]
    out += [f"layout: {m}" for m in tool._layout_lines(design, board, info, spec)]
    return out


def _design_visible(golden: Golden, design: dict) -> list[str]:
    """The cheap (design-only) part of `visible_failures`."""
    out = [f"erc: {i.code}" for i in erc.errors(erc.run_erc(design))]
    out += [f"sim: {a.name}" for a in sim.run_assertions(design, golden.assertions) if not a.passed]
    out += [f"values: {m}" for m in value_violations(design, golden.value_bounds or {})]
    return out


# ------------------------------------------------------------------ candidates
@dataclass
class Cand:
    desc: str
    data: dict
    footprints: dict[str, str] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)
    swaps: list[tuple[str, str]] = field(default_factory=list)
    moves: list[tuple[str, str | None]] = field(default_factory=list)

    def apply(self, d: dict) -> None:
        for r, fp in self.footprints.items():
            d["components"][r]["footprint"] = fp
        for r, v in self.values.items():
            d["components"][r]["value"] = v
        for a, b in self.swaps:
            swap_pins(d, a, b)
        for p, n in self.moves:
            move_pin(d, p, n)


@dataclass(frozen=True)
class LatentType:
    name: str
    detected_by: str          # rules | topology | rules+topology
    rule_codes: tuple         # rule codes the fault must trip (rules-detected types)
    evidence: str             # public material that makes the defect deducible
    needs_full_intent: bool   # only the full intent text states the violated requirement
    fn: Callable


def _all_pins(a: dict, b: dict) -> list[str]:
    return sorted({p for d in (a, b) for pins in d["nets"].values() for p in pins})


def _swap_footprints_on_board(golden: Golden, board_path: str, fps: dict[str, str], values: dict[str, str],
                              salt: str) -> None:
    """Replace footprints in place (same position), re-route their nets, save; DRC must not worsen."""
    from pcbenv.tool import _replace_footprint
    before = drc_result(board_path)
    board = load_board(board_path)
    seed_kiid(salt)
    nets: set[str] = set()
    for ref, fpid in sorted(fps.items()):
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise NotApplicable(f"{ref} not on board")
        nets |= {p.GetNetname() for p in fp.Pads() if p.GetNetCode() > 0}
        _replace_footprint(board, ref, fpid, values[ref])
    reroute(board, golden, sorted(nets))
    with tempfile.TemporaryDirectory(prefix="pcblat_") as td:
        tmp = os.path.join(td, "board.kicad_pcb")
        save_board(board, tmp, salt)
        after = drc_result(tmp)
        if len(after.errors) > len(before.errors) or after.unconnected > before.unconnected:
            raise NotApplicable("footprint change leaves DRC errors")
        shutil.copyfile(tmp, board_path)


_WANT: list[str | None] = [None]   # apply_latent(want=...): only the candidate with this description


def _realise(lt: LatentType, golden: Golden, design: dict, board_path: str, rng: random.Random, exclude: set[str],
             salt: str, cands: list[Cand], ctx: dict) -> FaultRecord | None:
    cands = list(cands)
    rng.shuffle(cands)
    if _WANT[0] is not None:
        cands = [c for c in cands if c.desc == _WANT[0]]
    base_rules = {(v.code, v.detail) for v in rules.run_rules(design, ctx)}
    for c in cands:
        d2 = copy_design(design)
        c.apply(d2)
        changed = [p for p in _all_pins(design, d2) if net_of(design, p) != net_of(d2, p)]
        refs = sorted({p.split(".", 1)[0] for p in changed} | set(c.footprints) | set(c.values))
        nets = sorted({n for p in changed for n in (net_of(design, p), net_of(d2, p)) if n})
        if not free(exclude, *refs, *nets_target(*nets)):
            continue
        topo = topology_differs(d2, golden)
        new_rules = [v for v in rules.run_rules(d2, ctx) if (v.code, v.detail) not in base_rules]
        hit = sorted({v.code for v in new_rules if v.code in lt.rule_codes})
        if "rules" in lt.detected_by and not hit:
            continue
        if "topology" in lt.detected_by and not topo:
            continue
        if not topo and not hit:
            continue
        if _design_visible(golden, d2):
            continue
        with tempfile.TemporaryDirectory(prefix="pcblat_") as td:
            b2 = os.path.join(td, "board.kicad_pcb")
            shutil.copyfile(board_path, b2)
            try:
                if c.footprints:
                    _swap_footprints_on_board(golden, b2, c.footprints,
                                              {r: d2["components"][r].get("value", "") for r in c.footprints},
                                              salt + ":fp")
                if changed:
                    rewire(golden, b2, design_pad_nets(d2), salt + ":nets")
                if c.values:
                    set_board_values(b2, c.values, salt + ":val")
            except NotApplicable:
                continue
            vis = visible_failures(golden, d2, b2)
            if vis:
                continue
            shutil.copyfile(b2, board_path)
        data = dict(c.data)
        data.update(latent=True, detected_by=lt.detected_by, rule_codes=hit, evidence=lt.evidence,
                    needs_full_intent=lt.needs_full_intent,
                    moves={p: [net_of(design, p), net_of(d2, p)] for p in changed},
                    footprints={r: [design["components"][r]["footprint"], fp] for r, fp in c.footprints.items()},
                    values={r: [design["components"][r]["value"], v] for r, v in c.values.items()},
                    rule_violations=[f"{v.code}: {v.detail}" for v in new_rules][:10])
        design.clear()
        design.update(d2)
        return FaultRecord(lt.name, "latent", c.desc, True, refs + nets_target(*nets), data)
    return None


def _comps(design: dict, part: str | tuple) -> list[str]:
    pre = (part,) if isinstance(part, str) else part
    return sorted(r for r, c in design["components"].items() if c["part"].startswith(pre))


def _smaller(fp: str, sizes: list[str]) -> list[str]:
    return sizes[:sizes.index(fp)] if fp in sizes else []


# ------------------------------------------------------------------ injectors
def _downsize(kind: str, part: str, sizes: list[str], what: str):
    def fn(lt, golden, design, board_path, rng, exclude, salt, ctx):
        cands = []
        for ref in _comps(design, part):
            if part in ("R", "C") and design["components"][ref]["part"] != part:
                continue
            old = design["components"][ref]["footprint"]
            for fp in _smaller(old, sizes):
                cands.append(Cand(f"{ref} {what} footprint downsized {old.split(':')[1]} -> {fp.split(':')[1]}; "
                                  f"it now exceeds the rating of the smaller part",
                                  {"ref": ref, "footprint": fp, "golden_footprint": old}, footprints={ref: fp}))
        return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)
    return fn


def _weak_base_drive(lt, golden, design, board_path, rng, exclude, salt, ctx):
    cands = []
    for q in _comps(design, "NPN"):
        base = net_of(design, f"{q}.B")
        if base is None:
            continue
        for r in _comps(design, "R"):
            if design["components"][r]["part"] != "R":
                continue
            n1, n2 = net_of(design, f"{r}.1"), net_of(design, f"{r}.2")
            if base not in (n1, n2):
                continue
            other = n2 if n1 == base else n1
            if other is None or not any(p.split(".")[0].startswith("U") for p in design["nets"].get(other, [])):
                continue  # the drive resistor comes from the MCU pin, not the pull-down
            old = parse_value(design["components"][r]["value"])
            lo, hi = (golden.value_bounds or {}).get(r, [0, old * 4])
            for f in (2.7, 3.0, 3.3, 3.6, 3.9):
                v = format_value(float(f"{old * f:.2g}"))
                if parse_value(v) > hi:
                    continue
                cands.append(Cand(f"{r} (base drive of {q}) is {v}, should be ~{design['components'][r]['value']}: "
                                  f"{q} only saturates thanks to typical hFE (forced beta > 20)",
                                  {"ref": r, "value": v, "golden_value": design["components"][r]["value"]},
                                  values={r: v}))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _flyback_misplaced(lt, golden, design, board_path, rng, exclude, salt, ctx):
    gnd = net_of(design, "J1.2")
    cands = []
    for ld in ctx.get("inductive_loads", []):
        ns, nw = net_of(design, ld["supply_pin"]), net_of(design, ld["switched_pin"])
        for d in _comps(design, "D_SCHOTTKY"):
            if net_of(design, f"{d}.K") != ns or net_of(design, f"{d}.A") != nw:
                continue
            if gnd:
                cands.append(Cand(f"{d} anode returned to GND instead of the switched node: it no longer clamps "
                                  "the coil", {"diode": d, "variant": "anode_to_gnd"}, moves=[(f"{d}.A", gnd)]))
                cands.append(Cand(f"{d} placed across the transistor (cathode on the switched node, anode on GND) "
                                  "instead of across the coil", {"diode": d, "variant": "across_switch"},
                                  moves=[(f"{d}.K", nw), (f"{d}.A", gnd)]))
            cands.append(Cand(f"{d} anode on the supply net (both ends on the supply): the clamp is shorted out",
                              {"diode": d, "variant": "both_supply"}, moves=[(f"{d}.A", ns)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _connector_pin_swap(lt, golden, design, board_path, rng, exclude, salt, ctx):
    cands = []
    resistive = [{ld["pin"], ld["to"]} for a in golden.assertions for ld in a.get("loads") or []
                 if ld.get("to") and ld.get("l") is None and ld.get("c") is None]
    for j in _comps(design, "CONN"):
        pins = sorted(PARTS[design["components"][j]["part"]].pins)
        for i, a in enumerate(pins):
            for b in pins[i + 1:]:
                pa, pb = f"{j}.{a}", f"{j}.{b}"
                if net_of(design, pa) == net_of(design, pb) or net_of(design, pa) is None or net_of(design, pb) is None:
                    continue
                if {pa, pb} in resistive:
                    continue  # a plain resistive off-board load (heater) is not polarised: no real defect
                cands.append(Cand(f"connector {j} pins {a} and {b} exchanged (pinout fixed by the intent)",
                                  {"pins": [pa, pb]}, swaps=[(pa, pb)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


MCU_IO = ("NRST", "PA0", "PA1", "PA2", "SDA", "SCL")


def _mcu_pin_swap(lt, golden, design, board_path, rng, exclude, salt, ctx):
    cands = []
    for u in _comps(design, "MCU8"):
        for i, a in enumerate(MCU_IO):
            for b in MCU_IO[i + 1:]:
                pa, pb = f"{u}.{a}", f"{u}.{b}"
                na, nb = net_of(design, pa), net_of(design, pb)
                if na == nb:
                    continue
                if {a, b} == {"PA1", "PA2"}:
                    continue  # XIN/XOUT exchange is equivalent for a 2-pin crystal
                cands.append(Cand(f"{u}.{a} and {u}.{b} functions exchanged (pin assignment fixed by the intent / "
                                  "datasheet)", {"pins": [pa, pb]}, swaps=[(pa, pb)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _decap_swapped(lt, golden, design, board_path, rng, exclude, salt, ctx):
    gnd = net_of(design, "J1.2")
    cands = []
    decs = [d for d in golden.decoupling if d["cap"] in design["components"]]
    for i, a in enumerate(decs):
        for b in decs[i + 1:]:
            ca, cb = a["cap"], b["cap"]
            pa = [f"{ca}.{p}" for p in ("1", "2") if net_of(design, f"{ca}.{p}") not in (None, gnd)]
            pb = [f"{cb}.{p}" for p in ("1", "2") if net_of(design, f"{cb}.{p}") not in (None, gnd)]
            if len(pa) != 1 or len(pb) != 1 or net_of(design, pa[0]) == net_of(design, pb[0]):
                continue
            cands.append(Cand(f"{ca} and {cb} exchange rails: {ca} sits at {a['ic_pin']} but decouples "
                              f"{net_of(design, pb[0])}, {cb} sits at {b['ic_pin']} but decouples {net_of(design, pa[0])}",
                              {"caps": [ca, cb]}, swaps=[(pa[0], pb[0])]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def input_rails(design: dict) -> set[str]:
    """Nets carrying the raw / protected input supply: J1.1's net, the cathode net of a series
    Schottky fed from it (composites: VIN_RAW -> D -> VIN), and every LDO VIN net."""
    gnd = net_of(design, "J1.2")
    raw = net_of(design, "J1.1")
    out = {raw}
    for d in _comps(design, "D_SCHOTTKY"):
        if raw is not None and net_of(design, f"{d}.A") == raw:
            out.add(net_of(design, f"{d}.K"))
    out |= {net_of(design, f"{u}.VIN") for u in _comps(design, "LDO_ADJ")}
    return out - {None, gnd}


def supply_rails(design: dict) -> set[str]:
    """Every supply net: the input rails plus the nets of IC supply pins (LDO VOUT, MCU VDD,
    op-amp V+). J1.1 alone is not "the" supply on composites (VIN_RAW sits before a protection
    diode and the logic runs from an LDO rail)."""
    gnd = net_of(design, "J1.2")
    out = set(input_rails(design))
    for u, pins in (("MCU8", ("VDD",)), ("OPAMP", ("V+",)), ("LDO_ADJ", ("VOUT",))):
        for ref in _comps(design, u):
            out |= {net_of(design, f"{ref}.{p}") for p in pins}
    return out - {None, gnd}


def _bias_wrong_rail(lt, golden, design, board_path, rng, exclude, salt, ctx):
    gnd = net_of(design, "J1.2")
    cands = []
    if gnd is None:
        return None
    rails = supply_rails(design)
    decaps = {d["cap"] for d in golden.decoupling}
    for r in _comps(design, ("R", "C")):
        if design["components"][r]["part"] not in ("R", "C") or r in decaps:
            continue
        n1, n2 = net_of(design, f"{r}.1"), net_of(design, f"{r}.2")
        if gnd not in (n1, n2) or (n1 in rails or n2 in rails):
            continue
        gpin = f"{r}.1" if n1 == gnd else f"{r}.2"
        other = n2 if n1 == gnd else n1
        if other is None:
            continue
        for rail in sorted(rails):
            cands.append(Cand(f"{gpin} returned to {rail} instead of GND", {"pin": gpin, "net": rail,
                                                                           "golden_net": gnd},
                              moves=[(gpin, rail)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _pullup_wrong_rail(lt, golden, design, board_path, rng, exclude, salt, ctx):
    """A pull-up on an MCU I/O line returned to a higher input rail instead of the MCU's own rail
    (the line idles above VDD: abs-max violation, ESD diodes back-power the MCU)."""
    cands = []
    io = ("SDA", "SCL", "NRST", "PA0", "PA1", "PA2")
    higher = input_rails(design)
    for u in _comps(design, "MCU8"):
        vdd = net_of(design, f"{u}.VDD")
        io_nets = {net_of(design, f"{u}.{p}") for p in io} - {None}
        for r in _comps(design, "R"):
            if design["components"][r]["part"] != "R":
                continue
            n1, n2 = net_of(design, f"{r}.1"), net_of(design, f"{r}.2")
            for rp, rail, other in ((f"{r}.1", n1, n2), (f"{r}.2", n2, n1)):
                if rail != vdd or other not in io_nets:
                    continue
                for hi in sorted(higher - {vdd}):
                    cands.append(Cand(f"pull-up {r} on {other} returned to {hi} instead of the MCU rail {vdd}",
                                      {"ref": r, "pin": rp, "net": hi, "golden_net": vdd, "mcu": u},
                                      moves=[(rp, hi)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _decap_wrong_rail(lt, golden, design, board_path, rng, exclude, salt, ctx):
    """A decoupling cap stays next to its IC pin (the public rule names the pin) but its supply pad
    is wired to another rail: the pin is left undecoupled."""
    gnd = net_of(design, "J1.2")
    rails = supply_rails(design)
    cands = []
    for dc in golden.decoupling:
        cap = dc["cap"]
        if cap not in design["components"]:
            continue
        pins = [f"{cap}.{p}" for p in ("1", "2") if net_of(design, f"{cap}.{p}") not in (None, gnd)]
        if len(pins) != 1:
            continue
        own = net_of(design, pins[0])
        for rail in sorted(rails - {own}):
            cands.append(Cand(f"{cap} sits at {dc['ic_pin']} but decouples {rail} instead of {own}",
                              {"cap": cap, "ic_pin": dc["ic_pin"], "pin": pins[0], "net": rail, "golden_net": own},
                              moves=[(pins[0], rail)]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


def _protection_bypassed(lt, golden, design, board_path, rng, exclude, salt, ctx):
    """The series reverse-polarity Schottky is bypassed: everything on its cathode net is wired to
    the raw input (the diode ends up with both pins on one net). All on-state sims still pass
    (more headroom), but a reversed supply now reaches the LDO and the rest of the board."""
    raw = net_of(design, "J1.1")
    cands = []
    for d in _comps(design, "D_SCHOTTKY"):
        if raw is None or net_of(design, f"{d}.A") != raw:
            continue
        k = net_of(design, f"{d}.K")
        if k is None or k == raw:
            continue
        moved = sorted(design["nets"][k])
        cands.append(Cand(f"reverse-polarity diode {d} bypassed: {k} wired straight to the input {raw}",
                          {"diode": d, "net": k, "raw": raw}, moves=[(p, raw) for p in moved]))
    return _realise(lt, golden, design, board_path, rng, exclude, salt, cands, ctx)


LATENT_TYPES: dict[str, LatentType] = {t.name: t for t in (
    LatentType("resistor_underrated", "rules", ("resistor_power",),
               "parts/R.md ratings by footprint + 50 % power derating rule; TASK.md Design rules", False,
               _downsize("R", "R", rules.R_SIZES, "resistor")),
    LatentType("capacitor_underrated", "rules", ("capacitor_voltage",),
               "parts/C.md voltage rating by footprint + 80 % rule; rail voltages in the intent; TASK.md Design rules",
               False, _downsize("C", "C", rules.C_SIZES, "capacitor")),
    LatentType("led_underrated", "rules", ("led_current",),
               "parts/LED_*.md max IF by package + 80 % rule; LED current in the spec; TASK.md Design rules", False,
               _downsize("LED", "LED_", rules.LED_SIZES, "LED")),
    LatentType("weak_base_drive", "rules", ("npn_saturation",),
               "parts/NPN.md forced-beta <= 20 switching rule (and the RB formula); load current in the spec",
               False, _weak_base_drive),
    LatentType("flyback_misplaced", "rules+topology", ("flyback",),
               "parts/D_SCHOTTKY.md and NPN/NMOS application notes: flyback diode across the inductive load, cathode "
               "to supply; TASK.md Design rules", False, _flyback_misplaced),
    LatentType("connector_pin_swap", "topology", (),
               "design intent: connector pinouts (pin n = function), kept at every hint level", False,
               _connector_pin_swap),
    LatentType("mcu_pin_swap", "topology", (),
               "parts/MCU8.md pin functions + intent's MCU pin assignment (e.g. SDA -> J2.3)", False, _mcu_pin_swap),
    LatentType("decap_swapped", "topology", (),
               "spec.json / TASK.md decoupling rules name each cap's IC pin (C1 at U1.VIN, C2 at U1.VOUT)", False,
               _decap_swapped),
    LatentType("bias_wrong_rail", "topology", (),
               "design intent (full text kept): bias / bypass / reset parts returned to GND; MCU8 / OPAMP application "
               "notes", True, _bias_wrong_rail),
    LatentType("pullup_wrong_rail", "rules+topology", ("mcu_abs_max", "mcu_pin_current"),
               "parts/MCU8.md abs-max (no pin above VDD + 0.3 V, e.g. via a pull-up to a higher rail); intent: the "
               "MCU's rail and its pull-ups", False, _pullup_wrong_rail),
    LatentType("decap_wrong_rail", "topology", (),
               "TASK.md Design rules / spec.json design_rules: each decoupling cap is named with its IC pin", False,
               _decap_wrong_rail),
    LatentType("protection_bypassed", "topology", (),
               "design intent: rails line (input -> reverse-polarity diode -> VIN) and the protection bullet", False,
               _protection_bypassed),
)}


# ------------------------------------------------------------------ fairness: public evidence
_ADDENDUM_KEYS = {
    "resistor_underrated": [["the continuous dissipation P = I²·R of every resistor"]],
    "capacitor_underrated": [["the DC working voltage across a capacitor must not exceed 80 %"]],
    "led_underrated": [["the forward current must not exceed 80 % of the package maximum"]],
    "weak_base_drive": [["**Design rule (switching):**"]],
    "flyback_misplaced": [["**Design rule (inductive loads):**"]],
    "pullup_wrong_rail": [["by a pull-up to a higher rail"]],
}


def evidence_groups(rec: dict) -> list[list[str]]:
    """Text that must appear in the task's public material (TASK.md + spec.json + parts/*.md) for
    this latent fault to be deducible: every group needs one alternative present. An alternative
    `line:A&B` needs A and B on one line."""
    t, d = rec["type"], rec.get("data", {})
    groups = [list(g) for g in _ADDENDUM_KEYS.get(t, [])]
    if t in ("resistor_underrated", "capacitor_underrated", "led_underrated"):
        size = d["footprint"].split(":")[1].split("_")[1]
        groups.append([f"| {size} |"])
    if t == "connector_pin_swap" or t == "mcu_pin_swap":
        for pin in d["pins"]:
            ref, p = pin.split(".", 1)
            alts = [f"{ref}.{p}"]
            alts += [f"| {ref} | {p} |", f"{ref} pin {p}"] if t == "connector_pin_swap" else [f"| {p} |"]
            groups.append(alts)
    if t in ("decap_swapped", "decap_wrong_rail"):
        for cap in d.get("caps") or [d["cap"]]:
            groups.append([f"- {cap} within"])
    if t == "decap_wrong_rail":
        groups.append([d["ic_pin"]])
    if t == "bias_wrong_rail":
        groups.append([f"line:{d['pin'].split('.')[0]}&GND"])
    if t == "pullup_wrong_rail":
        groups.append([f"line:{d['ref']}&{d['golden_net']}", f"| VDD | supply, {d['golden_net']} rail |"])
    if t == "protection_bypassed":
        groups.append(["reverse-polarity diode -> VIN", f"Schottky {d['diode']} in series"])
    return groups


def missing_evidence(rec: dict, public_text: str) -> list[list[str]]:
    """Evidence groups of `rec` with no alternative present in `public_text`."""
    import re as _re
    lines = public_text.splitlines()

    def has(alt: str) -> bool:
        if alt.startswith("line:"):
            a, b = alt[5:].split("&", 1)
            pa = _re.compile(r"(?<![A-Za-z0-9])" + _re.escape(a) + r"(?![A-Za-z0-9])")
            return any(pa.search(ln) and b in ln for ln in lines)
        return alt in public_text
    return [g for g in evidence_groups(rec) if not any(has(a) for a in g)]


def apply_latent(name: str, golden: Golden, design: dict, board_path: str, rng: random.Random,
                 exclude: set[str] | frozenset = frozenset(), salt: str = "", ctx: dict | None = None,
                 want: str | None = None) -> FaultRecord | None:
    """Apply latent fault `name` in place (None if not applicable). The input state must itself be
    clean for the tool (the hard generator applies latent faults first, to the golden), and the
    result is asserted to stay clean (`visible_failures` empty). `want`: only the candidate whose
    description is `want` (the hard generator picks each latent fault on the pristine golden and
    then applies exactly that one on top of the others)."""
    lt = LATENT_TYPES[name] if name in LATENT_TYPES else LAYOUT_LATENT_TYPES[name]
    ctx = ctx if ctx is not None else rules.rules_context(golden)
    if _design_visible(golden, design):
        raise NotApplicable("latent faults must be applied to a tool-clean design")
    _WANT[0] = want
    try:
        rec = lt.fn(lt, golden, design, board_path, rng, set(exclude), f"{salt}:{name}", ctx)
    except NotApplicable:
        return None
    finally:
        _WANT[0] = None
    if rec is not None:
        assert not visible_failures(golden, design, board_path), f"latent {name} became visible"
    return rec


def still_present(rec: dict, design: dict, board_path: str, golden: Golden) -> bool:
    """The latent fault's change is still in the (combined) faulted files."""
    d = rec["data"]
    if rec["type"] in LAYOUT_LATENT_TYPES:
        return layout_still_present(rec, golden, board_path)
    rp = {r: c["part"] for r, c in golden.design["components"].items()}
    info = boardnet.board_info(board_path, parts=rp)
    for r, (_, fp) in d.get("footprints", {}).items():
        if design["components"][r]["footprint"] != fp or info.footprints.get(r) != fp:
            return False
    for r, (_, v) in d.get("values", {}).items():
        if design["components"][r]["value"] != v or info.values.get(r) != v:
            return False
    return all(net_of(design, p) == new for p, (_, new) in d.get("moves", {}).items())




# ================================================================== layout-latent faults (hard_layout)
# Board-geometry defects: design.json untouched, connectivity / values / DRC / ERC / sim / bounds all
# still pass (pcbtool sees nothing), but exactly one stated layout rule (`pcbenv/layout_rules.py`, or
# the decoupling copper-path rule) is broken. Each needs the agent to read board coordinates and
# move parts / re-route copper by hand. `autoroute_fixes` tells whether `pcbtool route` on one of
# the fault's nets would repair it (then the task must be no_autoroute).
LAYOUT_MARGIN = 1.25          # a faulted metric exceeds its limit by at least this factor


@dataclass
class GeoCand:
    desc: str
    data: dict
    targets: list[str]
    edit: Callable            # edit(board) -> None (KiCad board, in place); NotApplicable to skip


def _lctx(golden: Golden) -> dict:
    from pcbenv.layout_rules import layout_rules_context
    return layout_rules_context(golden)


def _rp(golden: Golden) -> dict[str, str]:
    return {r: c["part"] for r, c in golden.design["components"].items()}


def _padnum(golden: Golden, pin: str) -> tuple[str, str]:
    ref, name = pin.split(".", 1)
    return ref, PARTS[golden.design["components"][ref]["part"]].pins[name].pad


def _key(golden: Golden, pin: str) -> str:
    ref, num = _padnum(golden, pin)
    return f"{ref}.{num}"


def layout_issues(golden: Golden, board_path: str) -> dict[str, list[str]]:
    """{code: [details]} of the layout rules + the decoupling path rule on a board."""
    from pcbenv import layout
    from pcbenv.layout_rules import run_layout_rules
    rp = _rp(golden)
    out: dict[str, list[str]] = {}
    b = load_board(board_path)
    for v in run_layout_rules(b, _lctx(golden), rp):
        out.setdefault(v.code, []).append(v.detail)
    meta = {"decoupling": golden.decoupling, "power_nets": {}, "power_net_pins": {}}
    info = boardnet.board_info(b, parts=rp)
    for i in layout.run_layout_checks(info, meta, board=b, ref_parts=rp):
        out.setdefault(i.code, []).append(i.detail)
    return out


def _metric(golden: Golden, board_path: str, kind: str, extra: dict) -> float | None:
    """The faulted quantity, for the LAYOUT_MARGIN check."""
    from pcbenv import layout_rules as LR
    b = load_board(board_path)
    rp = _rp(golden)
    lctx = _lctx(golden)
    if kind == "loop":
        a = LR.loop_area(b, lctx["switch_loop"][0], rp)
        return None if isinstance(a, str) else a / lctx["switch_loop"][0]["max_area_mm2"]
    if kind == "xtal":
        r = lctx["crystal"][0]
        ds = [d for _, d, _ in LR.crystal_metrics(b, r, rp)]
        return None if None in ds else max(ds) / r["max_path_mm"]
    if kind == "sep":
        r = lctx["separation"][0]
        s = LR.separation_length(b, r, rp)
        return None if isinstance(s, str) else s / r["max_parallel_mm"]
    if kind == "decap":
        from pcbenv.layout import decoupling_path_mm, max_path_mm
        dc = extra["rule"]
        d = decoupling_path_mm(b, dc["cap"], dc["ic_pin"], rp)
        return None if d is None else d / max_path_mm(dc)
    return math.inf


def _realise_geo(lt: "LatentType", golden: Golden, design: dict, board_path: str, rng: random.Random,
                 exclude: set[str], salt: str, cands: list[GeoCand], metric: str) -> FaultRecord | None:
    cands = list(cands)
    rng.shuffle(cands)
    if _WANT[0] is not None:
        cands = [c for c in cands if c.desc == _WANT[0]]
    base = layout_issues(golden, board_path)
    for c in cands[:12]:
        if not free(exclude, *c.targets):
            continue
        with tempfile.TemporaryDirectory(prefix="pcblay_") as td:
            b2 = os.path.join(td, "board.kicad_pcb")
            board = load_board(board_path)
            seed_kiid(salt)
            try:
                c.edit(board)
            except NotApplicable:
                continue
            save_board(board, b2, salt)
            r = drc.run_drc(b2)
            if r.errors or r.unconnected:
                continue
            now = layout_issues(golden, b2)
            new = {k: [x for x in v if x not in base.get(k, [])] for k, v in now.items()}
            new = {k: v for k, v in new.items() if v}
            if not new or set(new) - set(lt.rule_codes):
                continue
            m = _metric(golden, b2, metric, c.data)
            if m is None or m < LAYOUT_MARGIN:
                continue
            if visible_failures(golden, design, b2):
                continue
            shutil.copyfile(b2, board_path)
        data = dict(c.data)
        data.pop("rule", None)
        data.update(latent=True, layout=True, detected_by=lt.detected_by, rule_codes=sorted(new),
                    evidence=lt.evidence, needs_full_intent=False, moves={}, footprints={}, values={},
                    metric_ratio=round(m, 3), rule_violations=[f"{k}: {x}" for k, v in sorted(new.items()) for x in v][:10])
        return FaultRecord(lt.name, "latent", c.desc, True, sorted(set(c.targets)), data)
    return None


def _net_name(golden: Golden, pin: str) -> str:
    return net_of(golden.design, pin)


def _board_pad(board, golden: Golden, pin: str):
    from pcbenv.faults.geom import find_pad
    ref, num = _padnum(golden, pin)
    return find_pad(board, ref, num)


def _kelvin_sense_tap(lt, golden, design, board_path, rng, exclude, salt, ctx):
    from pcbenv.faults import geom as G
    from pcbenv.faults.common import net_width
    from pcbenv.layout import copper_path
    lctx = _lctx(golden)
    cands = []
    for r in lctx.get("kelvin", []):
        net = _net_name(golden, r["shunt_pin"])
        w = net_width(golden, net)
        sense, shunt, load = r["sense_pin"], r["shunt_pin"], r["load_pins"][0]

        def strip(board, sense=sense, shunt=shunt):
            from pcbenv.layout_rules import island_items
            sp, hp = _board_pad(board, golden, sense), _board_pad(board, golden, shunt)
            code = hp.GetNetCode()
            G.delete_items(board, island_items(board, code, sp, drop_pad=hp))
            return code

        def tap_pad(board, sense=sense, load=load, w=w):
            code = strip(board)
            G.route_branch(board, code, _key(golden, sense), _key(golden, load), w, isolated=False)

        def tap_mid(board, sense=sense, shunt=shunt, load=load, w=w):
            code = strip(board)
            res = copper_path(board, _board_pad(board, golden, load), _board_pad(board, golden, shunt))
            if res is None or res[0] < 1.0:
                raise NotApplicable("power path too short")
            pts, L = res[1], res[0]
            target, acc = L / 2, 0.0
            mid = pts[0]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                s = math.hypot(x2 - x1, y2 - y1)
                if acc + s >= target and s > 0:
                    f = (target - acc) / s
                    mid = (x1 + (x2 - x1) * f, y1 + (y2 - y1) * f)
                    break
                acc += s
            layer = _layer_at(board, code, mid)
            router, idx = G.board_router(board)
            wp = G.waypoint(mid[0], mid[1], layer)
            wp.net = code
            router.pads.append(wp)
            n_s, n_v = len(router.segs), len(router.vias)
            from pcbenv.router import RouteError
            try:
                ia = idx[_key(golden, sense)]
                router.route_net(code, [ia, len(router.pads) - 1], w, [ia, len(router.pads) - 1])
            except RouteError as e:
                raise NotApplicable(str(e)) from None
            router.pads.pop()
            G.add_new_copper(board, router, n_s, n_v)

        tg = [sense.split(".")[0], shunt.split(".")[0], load.split(".")[0], *nets_target(net)]
        cands.append(GeoCand(f"sense connection {sense} re-routed to tap the load-current copper at {load} instead of "
                             f"the shunt pad {shunt}", {"variant": "tap_load_pad", "nets": [net], "rule": r}, tg, tap_pad))
        cands.append(GeoCand(f"sense connection {sense} re-routed to tee into the middle of the {load} -> {shunt} "
                             f"power trace instead of leaving from the shunt pad", {"variant": "tap_mid", "nets": [net],
                                                                                    "rule": r}, tg, tap_mid))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "none")


def pcbnew_layers():
    import pcbnew
    return (pcbnew.F_Cu, pcbnew.B_Cu)


def _layer_at(board, code: int, pt: tuple[float, float]) -> int:
    """Router layer (0/1) of the net's track nearest to `pt`."""
    import pcbnew

    from pcbenv.faults.geom import _pt_seg
    best = None
    for t in board.GetTracks():
        if t.GetNetCode() != code or t.GetClass() == "PCB_VIA":
            continue
        d = _pt_seg(pt[0], pt[1], t)
        if best is None or d < best[0]:
            best = (d, 0 if t.GetLayer() == pcbnew.F_Cu else 1)
    return 0 if best is None else best[1]


def _candidate_spots(board, golden: Golden, ref: str, rng: random.Random, dmin: float, dmax: float,
                     n: int = 40) -> list[tuple[float, float, int]]:
    """Grid positions (1 mm) dmin..dmax mm from the part's current position, shuffled."""
    from pcbenv.faults.geom import board_outline
    fp = board.FindFootprintByReference(ref)
    c = fp.GetPosition()
    cx, cy = c.x / 1e6, c.y / 1e6
    x0, y0, w, h = board_outline(board)
    spots = []
    for i in range(int(w) + 1):
        for j in range(int(h) + 1):
            x, y = x0 + i, y0 + j
            if dmin <= math.hypot(x - cx, y - cy) <= dmax:
                spots.append((float(x), float(y), rng.choice((0, 90, 180, 270))))
    rng.shuffle(spots)
    return spots[: n * 6]


def _move_and_branch(board, golden: Golden, ref: str, spots, legs: list[tuple[str, str]], rng) -> None:
    """Detach `ref`'s copper, move it to the first spot where it fits, route each (pin, partner)
    leg as an isolated branch, then re-join any copper islands the detach split off."""
    from pcbenv.faults import geom as G
    from pcbenv.faults.common import net_width
    fp = board.FindFootprintByReference(ref)
    nets = sorted({p.GetNetCode() for p in fp.Pads() if p.GetNetCode() > 0})
    for p in sorted(fp.Pads(), key=lambda q: q.GetNumber()):
        if p.GetNetCode() > 0:
            G.detach_pad(board, p)
    old = fp.GetPosition(), fp.GetOrientationDegrees()
    for x, y, rot in spots:
        G.move_footprint(fp, x, y, rot)
        if G.placement_ok(board, fp):
            break
    else:
        fp.SetPosition(old[0])
        fp.SetOrientationDegrees(old[1])
        raise NotApplicable("no free spot")
    for pin, partner in legs:
        p = _board_pad(board, golden, pin)
        G.route_branch(board, p.GetNetCode(), _key(golden, pin), _key(golden, partner),
                       net_width(golden, _net_name(golden, pin)), isolated=True)
    for code in nets:
        G.reconnect(board, code, net_width(golden, board.GetNetInfo().GetNetItem(code).GetNetname()))


def _switch_loop_spread(lt, golden, design, board_path, rng, exclude, salt, ctx):
    lctx = _lctx(golden)
    cands = []
    b0 = load_board(board_path)
    for r in lctx.get("switch_loop", []):
        legs = r["legs"]
        pins_of = {}
        for a, c in legs:
            pins_of.setdefault(a.split(".")[0], []).append((a, c))
            pins_of.setdefault(c.split(".")[0], []).append((c, a))
        movable = sorted({ref for ref in pins_of if golden.design["components"][ref]["part"] in ("D_SCHOTTKY", "C")})
        for ref in movable:
            for k in range(3):
                srng = random.Random(f"{salt}:{ref}:{k}")
                spots = _candidate_spots(b0, golden, ref, srng, 9.0 + 4 * k, 16.0 + 6 * k)
                nets = sorted({_net_name(golden, p) for p, _ in pins_of[ref]})

                def edit(board, ref=ref, spots=spots, legs=pins_of[ref], srng=srng):
                    _move_and_branch(board, golden, ref, spots, legs, srng)
                cands.append(GeoCand(f"{ref} moved away from the switching loop (ring {k}) and re-routed: the commutation "
                                     f"loop {' -> '.join(a for a, _ in legs)} encloses too much area",
                                     {"variant": f"move_{golden.design['components'][ref]['part']}", "ref": ref,
                                      "nets": nets, "ring": k}, [ref, *nets_target(*nets)], edit))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "loop")


def _crystal_far(lt, golden, design, board_path, rng, exclude, salt, ctx):
    lctx = _lctx(golden)
    cands = []
    b0 = load_board(board_path)
    for r in lctx.get("crystal", []):
        y = r["xtal"]
        nets = sorted({_net_name(golden, a) for a, _ in r["pairs"]})
        for k in range(3):
            srng = random.Random(f"{salt}:{y}:{k}")
            spots = _candidate_spots(b0, golden, y, srng, 10.0 + 4 * k, 18.0 + 6 * k)

            def edit(board, y=y, spots=spots, pairs=r["pairs"], srng=srng):
                _move_and_branch(board, golden, y, spots, [(yp, mp) for mp, yp in pairs], srng)
            cands.append(GeoCand(f"crystal {y} moved away from {r['mcu']} (ring {k}) and re-routed: XIN/XOUT traces too long",
                                 {"variant": "move_xtal", "ref": y, "nets": nets, "ring": k},
                                 [y, *nets_target(*nets)], edit))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "xtal")


def _crystal_via(lt, golden, design, board_path, rng, exclude, salt, ctx):
    from pcbenv.faults import geom as G
    from pcbenv.faults.common import net_width
    lctx = _lctx(golden)
    cands = []
    for r in lctx.get("crystal", []):
        for mp, yp in r["pairs"]:
            net = _net_name(golden, mp)
            for k, off in enumerate((0.0, 1.5, -1.5)):
                def edit(board, mp=mp, yp=yp, net=net, off=off):
                    p = _board_pad(board, golden, yp)
                    q = _board_pad(board, golden, mp)
                    code = p.GetNetCode()
                    G.detach_pad(board, p)
                    (x1, y1), (x2, y2) = [(t.GetPosition().x / 1e6, t.GetPosition().y / 1e6) for t in (p, q)]
                    L = math.hypot(x2 - x1, y2 - y1) or 1.0
                    nx, ny = -(y2 - y1) / L, (x2 - x1) / L
                    wp = G.waypoint((x1 + x2) / 2 + nx * off, (y1 + y2) / 2 + ny * off, 1)
                    G.route_branch(board, code, _key(golden, yp), _key(golden, mp), net_width(golden, net), [wp],
                                   isolated=True)
                    G.reconnect(board, code, net_width(golden, net))
                cands.append(GeoCand(f"{yp} -> {mp} oscillator trace re-routed through the bottom layer (via pair) "
                                     f"(offset {off:g} mm)", {"variant": "via", "nets": [net], "pins": [mp, yp]},
                                     [r["xtal"], *nets_target(net)], edit))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "none")


def _offset_chains(board, code: int, min_len: float) -> list[tuple[int, list[tuple[float, float]]]]:
    """Polylines (layer, points) of a net's tracks: maximal chains of segments on one layer joined
    end to end, at least `min_len` mm long."""
    import pcbnew
    segs = []
    for t in board.GetTracks():
        if t.GetNetCode() == code and t.GetClass() == "PCB_TRACK":
            s, e = t.GetStart(), t.GetEnd()
            segs.append((0 if t.GetLayer() == pcbnew.F_Cu else 1, (s.x / 1e6, s.y / 1e6), (e.x / 1e6, e.y / 1e6)))
    used = [False] * len(segs)
    out = []
    for i, (lay, a, c) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        chain = [a, c]
        grown = True
        while grown:
            grown = False
            for j, (l2, a2, c2) in enumerate(segs):
                if used[j] or l2 != lay:
                    continue
                if math.dist(a2, chain[-1]) < 1e-4:
                    chain.append(c2)
                elif math.dist(c2, chain[-1]) < 1e-4:
                    chain.append(a2)
                elif math.dist(c2, chain[0]) < 1e-4:
                    chain.insert(0, a2)
                elif math.dist(a2, chain[0]) < 1e-4:
                    chain.insert(0, c2)
                else:
                    continue
                used[j] = True
                grown = True
        L = sum(math.dist(p, q) for p, q in zip(chain, chain[1:]))
        if L >= min_len:
            out.append((lay, chain))
    return out


def _analog_near_switch(lt, golden, design, board_path, rng, exclude, salt, ctx):
    from pcbenv.faults import geom as G
    from pcbenv.faults.common import net_width
    lctx = _lctx(golden)
    cands = []
    b0 = load_board(board_path)
    for r in lctx.get("separation", []):
        vpin, apin = r["victim_pins"][0], r["aggressor_pins"][0]
        vnet, anet = _net_name(golden, vpin), _net_name(golden, apin)
        acode = _board_pad(b0, golden, apin).GetNetCode()
        run = r["max_parallel_mm"] * LAYOUT_MARGIN + 1.5
        chains = _offset_chains(b0, acode, run)
        vpins = sorted(golden.design["nets"][vnet])
        for ci, (lay, chain) in enumerate(chains):
            for side in (1, -1):
                def edit(board, lay=lay, chain=chain, side=side, vpins=vpins, vnet=vnet, anet=anet):
                    vcode = _board_pad(board, golden, vpin).GetNetCode()
                    aw = net_width(golden, anet)
                    vw = net_width(golden, vnet)
                    gap = (aw + vw) / 2 + 0.2 + 0.17
                    wps = _offset_points(chain, side * gap, run)
                    G.delete_items(board, [t for t in board.GetTracks() if t.GetNetCode() == vcode])
                    ends = [p for p in vpins if p != vpin]
                    start = min(ends, key=lambda p: math.dist(_pad_xy_pin(board, golden, p), wps[0]))
                    a, c = (start, vpin)
                    if math.dist(_pad_xy_pin(board, golden, a), wps[0]) > math.dist(_pad_xy_pin(board, golden, a), wps[-1]):
                        wps = wps[::-1]
                    G.route_branch(board, vcode, _key(golden, a), _key(golden, c), vw,
                                   [G.waypoint(x, y, lay) for x, y in wps], isolated=False)
                    G.reconnect(board, vcode, vw)
                cands.append(GeoCand(f"{vnet} trace re-routed alongside the switching node {anet} (chain {ci}, side {side})",
                                     {"variant": "parallel_run", "nets": [vnet], "victim": vpin, "aggressor": apin},
                                     [*nets_target(vnet, anet)], edit))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "sep")


def _pad_xy_pin(board, golden: Golden, pin: str) -> tuple[float, float]:
    p = _board_pad(board, golden, pin)
    c = p.GetPosition()
    return c.x / 1e6, c.y / 1e6


def _offset_points(chain: list[tuple[float, float]], off: float, run: float) -> list[tuple[float, float]]:
    """Points every ~1 mm along the middle `run` mm of polyline `chain`, offset sideways by `off`."""
    L = [math.dist(p, q) for p, q in zip(chain, chain[1:])]
    tot = sum(L)
    s0 = max(0.0, (tot - run) / 2)
    n = max(2, int(math.ceil(run)) + 1)
    out = []
    for k in range(n):
        s = s0 + run * k / (n - 1)
        acc = 0.0
        for (p, q), l in zip(zip(chain, chain[1:]), L):
            if acc + l >= s and l > 0:
                f = (s - acc) / l
                x, y = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
                nx, ny = -(q[1] - p[1]) / l, (q[0] - p[0]) / l
                out.append((round(x + nx * off, 1), round(y + ny * off, 1)))
                break
            acc += l
    dedup = []
    for pt in out:
        if not dedup or pt != dedup[-1]:
            dedup.append(pt)
    return dedup


def _decap_long_path(lt, golden, design, board_path, rng, exclude, salt, ctx):
    from pcbenv.faults import geom as G
    from pcbenv.faults.common import net_width
    from pcbenv.layout import copper_path_mm, max_path_mm
    cands = []
    b0 = load_board(board_path)
    gnd = net_of(golden.design, "J1.2")
    for dc in golden.decoupling:
        cap = dc["cap"]
        net = _net_name(golden, dc["ic_pin"])
        cpin = next((f"{cap}.{p}" for p in ("1", "2") if net_of(golden.design, f"{cap}.{p}") == net), None)
        if cpin is None or net == gnd:
            continue
        ip = _board_pad(b0, golden, dc["ic_pin"])
        far = []
        for pin in sorted(golden.design["nets"][net]):
            if pin in (cpin, dc["ic_pin"]):
                continue
            d = copper_path_mm(b0, ip, _board_pad(b0, golden, pin))
            if d is not None and d >= max_path_mm(dc) * LAYOUT_MARGIN + 1.0:
                far.append((d, pin))
        for d, pin in sorted(far)[:3]:
            def edit(board, cpin=cpin, pin=pin, net=net):
                p = _board_pad(board, golden, cpin)
                code = p.GetNetCode()
                G.detach_pad(board, p)
                G.reconnect(board, code, net_width(golden, net), skip={_key(golden, cpin)})
                G.route_branch(board, code, _key(golden, cpin), _key(golden, pin), net_width(golden, net), isolated=True)
            cands.append(GeoCand(f"{cap} ({dc['ic_pin']} decoupling) re-routed the long way: its pad now joins {net} at "
                                 f"{pin} instead of running to the IC pin", {"variant": "long_way", "cap": cap,
                                                                           "ic_pin": dc["ic_pin"], "via_pin": pin,
                                                                           "nets": [net], "rule": dc},
                                 [cap, *nets_target(net)], edit))
    return _realise_geo(lt, golden, design, board_path, rng, exclude, salt, cands, "decap")


LAYOUT_LATENT_TYPES: dict[str, LatentType] = {t.name: t for t in (
    LatentType("kelvin_sense_tap", "layout_rules", ("kelvin_sense",),
               "TASK.md Layout rules / spec.json layout_rules.kelvin: the sense pin must leave from the shunt pad",
               False, _kelvin_sense_tap),
    LatentType("switch_loop_spread", "layout_rules", ("switch_loop_area",),
               "TASK.md Layout rules / spec.json layout_rules.switch_loop: commutation-loop area limit + formula",
               False, _switch_loop_spread),
    LatentType("crystal_far", "layout_rules", ("crystal_trace", "crystal_via"),
               "TASK.md Layout rules / spec.json layout_rules.crystal: oscillator trace length limit", False,
               _crystal_far),
    LatentType("crystal_via", "layout_rules", ("crystal_trace", "crystal_via"),
               "TASK.md Layout rules / spec.json layout_rules.crystal: no vias on XIN/XOUT", False, _crystal_via),
    LatentType("analog_near_switch", "layout_rules", ("analog_separation",),
               "TASK.md Layout rules / spec.json layout_rules.separation: gap / parallel-run limit", False,
               _analog_near_switch),
    LatentType("decap_long_path", "layout", ("decoupling",),
               "TASK.md Design rules / spec.json design_rules.decoupling: copper-path limit cap -> IC pin", False,
               _decap_long_path),
)}


def autoroute_fixes(golden: Golden, design: dict, board_path: str, rec: dict) -> bool:
    """Would `pcbtool route NET` (full tool mode) on one of the fault's nets -- or on all of them --
    repair this layout fault? (Then it may only ship in no_autoroute tasks.)"""
    from pcbenv.tool import ToolError, route_net
    from pcbenv.faults.common import net_width
    nets = rec["data"].get("nets") or []
    trials = [[n] for n in nets] + ([nets] if len(nets) > 1 else [])
    for group in trials:
        with tempfile.TemporaryDirectory(prefix="pcbauto_") as td:
            b2 = os.path.join(td, "board.kicad_pcb")
            board = load_board(board_path)
            try:
                for n in group:
                    route_net(board, n, net_width(golden, n), golden.decoupling, _rp(golden))
            except ToolError:
                continue
            save_board(board, b2, "autoroute")
            if not layout_still_present(rec, golden, b2):
                return True
    return False


def layout_still_present(rec: dict, golden: Golden, board_path: str) -> bool:
    d = rec["data"]
    issues = layout_issues(golden, board_path)
    if rec["type"] == "decap_long_path":
        return any(x.startswith(f"{d['cap']} ") for x in issues.get("decoupling", []))
    return any(c in issues for c in LAYOUT_LATENT_TYPES[rec["type"]].rule_codes)


__all__ = ["LATENT_TYPES", "LAYOUT_LATENT_TYPES", "LatentType", "apply_latent", "visible_failures", "still_present",
           "autoroute_fixes", "layout_still_present"]
