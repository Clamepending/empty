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
    lt = LATENT_TYPES[name]
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
    rp = {r: c["part"] for r, c in golden.design["components"].items()}
    info = boardnet.board_info(board_path, parts=rp)
    for r, (_, fp) in d.get("footprints", {}).items():
        if design["components"][r]["footprint"] != fp or info.footprints.get(r) != fp:
            return False
    for r, (_, v) in d.get("values", {}).items():
        if design["components"][r]["value"] != v or info.values.get(r) != v:
            return False
    return all(net_of(design, p) == new for p, (_, new) in d.get("moves", {}).items())


__all__ = ["LATENT_TYPES", "LatentType", "apply_latent", "visible_failures", "still_present"]
