"""`pcbtool`: the agent-facing CLI (SPEC §9). Run inside a task workdir.

Read-only: show, netlist, drc, erc, sim, parts [PART], check.
Mutating (update design.json AND board.kicad_pcb, each saved atomically via temp file +
rename): set-value, set-footprint, connect, disconnect, move, unroute, route, sync.

Exit status: 0 = ok / clean, 1 = the check found problems or the command failed, 2 = usage.
The tool only helps; grading is done by `pcbenv.verify` against hidden golden data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from types import SimpleNamespace

DESIGN = "design.json"
BOARD = "board.kicad_pcb"
SPEC = "spec.json"


class ToolError(RuntimeError):
    pass


# ------------------------------------------------------------------ file access
def _wd() -> str:
    return os.getcwd()


def load_design() -> dict:
    from pcbenv import design as D
    try:
        with open(os.path.join(_wd(), DESIGN), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise ToolError(f"cannot read {DESIGN}: {e}") from None
    try:
        D.validate(d)
    except D.DesignError as e:
        raise ToolError(f"{DESIGN} is invalid: {e}") from None
    return d


def load_board():
    from pcbenv import boardnet
    path = os.path.join(_wd(), BOARD)
    if not os.path.isfile(path):
        raise ToolError(f"{BOARD} not found")
    try:
        b = boardnet.load_board(path)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"cannot load {BOARD}: {e}") from None
    if b is None:
        raise ToolError(f"cannot load {BOARD}")
    return b


def load_spec() -> dict:
    try:
        with open(os.path.join(_wd(), SPEC), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"assertions": [], "power_nets": [], "decoupling": []}


def save_design(d: dict) -> None:
    from pcbenv import design as D
    D.validate(d)
    tmp = os.path.join(_wd(), f".{DESIGN}.tmp")
    D.save(d, tmp)
    os.replace(tmp, os.path.join(_wd(), DESIGN))


def save_board(board) -> None:
    import pcbnew
    tmp = os.path.join(_wd(), ".board.tmp.kicad_pcb")
    if not pcbnew.SaveBoard(tmp, board, True):
        raise ToolError("SaveBoard failed")
    os.replace(tmp, os.path.join(_wd(), BOARD))


def save_both(d: dict, board) -> None:
    save_board(board)
    save_design(d)


def part_map(d: dict) -> dict[str, str]:
    return {ref: c["part"] for ref, c in d["components"].items()}


def _split_pin(d: dict, pin: str) -> tuple[str, str, str]:
    from pcbenv.parts import PARTS
    if "." not in pin:
        raise ToolError(f"pin must be REF.PIN, got {pin!r}")
    ref, name = pin.split(".", 1)
    if ref not in d["components"]:
        raise ToolError(f"unknown component {ref}")
    part = PARTS[d["components"][ref]["part"]]
    if name not in part.pins:
        raise ToolError(f"{ref} ({part.name}) has no pin {name}; pins: {', '.join(part.pins)}")
    return ref, name, part.pins[name].pad


def _footprint(board, ref: str):
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        raise ToolError(f"{ref} not found on the board")
    return fp


def _net(board, name: str):
    import pcbnew
    ni = board.FindNet(name)
    if ni is None:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
    return ni


# ------------------------------------------------------------------ read-only
def cmd_show(a) -> int:
    from pcbenv import boardnet
    d = load_design()
    info = boardnet.board_info(load_board(), design=d)
    print(f"# {d.get('title', '')}\n\n## Components (design.json | board)")
    for ref in sorted(d["components"]):
        c = d["components"][ref]
        pos = info.positions.get(ref)
        where = f"at ({pos[0]:.2f}, {pos[1]:.2f}) rot {pos[2]:g} side {info.sides[ref]}" if pos else "NOT ON BOARD"
        bval = info.values.get(ref)
        extra = "" if bval is None or bval == c.get("value", "") else f"  [board value {bval!r}]"
        bfp = info.footprints.get(ref)
        extra += "" if bfp is None or bfp == c["footprint"] else f"  [board footprint {bfp}]"
        print(f"{ref:5s} {c['part']:10s} {c.get('value', '') or '-':8s} {c['footprint']}  {where}{extra}")
    for ref in sorted(set(info.footprints) - set(d["components"])):
        print(f"{ref:5s} (board only) {info.footprints[ref]}")
    print("\n## Nets (design.json)")
    for name, pins in sorted(d["nets"].items()):
        w = info.track_widths.get(name)
        ws = f"  [min track {w:.3f} mm]" if w is not None else ""
        print(f"{name}: {' '.join(sorted(pins))}{ws}")
    return 0


def _consistency(d: dict, info) -> list[str]:
    from pcbenv import boardnet
    from pcbenv import design as D
    out = []
    dpart = D.partition(d)
    if info.partition != dpart:
        dnet = {p: n for n, pins in d["nets"].items() for p in pins}
        bnet = {p: n for n, pins in info.net_pins.items() for p in pins}
        for p in sorted(set(dnet) | set(bnet)):
            # report a pin when its set of net-mates differs
            dm = frozenset(d["nets"][dnet[p]]) if p in dnet else frozenset({p})
            bm = frozenset(info.net_pins[bnet[p]]) if p in bnet else frozenset({p})
            if dm != bm:
                out.append(f"connectivity: {p}: design net {dnet.get(p, '-')} {sorted(dm)} vs board net "
                           f"{bnet.get(p, '-')} {sorted(bm)}")
    for ref, c in sorted(d["components"].items()):
        if ref not in info.footprints:
            out.append(f"{ref}: missing on board")
            continue
        if info.values[ref] != c.get("value", ""):
            out.append(f"{ref}: value design {c.get('value', '')!r} vs board {info.values[ref]!r}")
        if info.footprints[ref] != c["footprint"]:
            out.append(f"{ref}: footprint design {c['footprint']} vs board {info.footprints[ref]}")
        elif info.pad_fingerprint[ref] != boardnet.library_pad_fingerprint(c["footprint"]):
            out.append(f"{ref}: board footprint differs from the library footprint")
    for ref in sorted(set(info.footprints) - set(d["components"])):
        out.append(f"{ref}: on board but not in design")
    if info.duplicate_refs:
        out.append(f"duplicate refs on board: {info.duplicate_refs}")
    return out


def cmd_netlist(a) -> int:
    from pcbenv import boardnet
    d = load_design()
    info = boardnet.board_info(load_board(), design=d)
    print("## design.json nets")
    for name, pins in sorted(d["nets"].items()):
        print(f"{name}: {' '.join(sorted(pins))}")
    print("\n## board pad nets")
    for name, pins in sorted(info.net_pins.items()):
        print(f"{name}: {' '.join(sorted(pins))}")
    diffs = [m for m in _consistency(d, info) if m.startswith("connectivity")]
    print("\n## differences")
    print("\n".join(diffs) if diffs else "none: board connectivity matches design.json")
    return 1 if diffs else 0


def _drc_lines() -> list[str]:
    from pcbenv import drc
    r = drc.run_drc(os.path.join(_wd(), BOARD))
    out = [f"{e['type']}: {e['description']} @ {e['pos']} {'; '.join(e['items'][:2])}" for e in r.errors]
    if r.unconnected:
        out.append(f"{r.unconnected} unconnected items (pads/tracks of a net not joined by copper)")
    return out


def cmd_drc(a) -> int:
    lines = _drc_lines()
    print("\n".join(lines) if lines else "DRC clean: 0 errors, 0 unconnected")
    return 1 if lines else 0


def _erc_lines(d: dict) -> tuple[list[str], list[str]]:
    from pcbenv import erc
    iss = erc.run_erc(d)
    return ([f"error {i.code}: {i.detail}" for i in iss if i.severity == "error"],
            [f"warning {i.code}: {i.detail}" for i in iss if i.severity != "error"])


def cmd_erc(a) -> int:
    errs, warns = _erc_lines(load_design())
    print("\n".join(errs + warns) if errs or warns else "ERC clean")
    return 1 if errs else 0


def _sim_lines(d: dict) -> tuple[list[str], int]:
    from pcbenv import sim
    res = sim.run_assertions(d, load_spec().get("assertions", []))
    lines = []
    for r in res:
        m = "n/a" if r.measured is None else f"{r.measured:.6g}"
        lines.append(f"{'PASS' if r.passed else 'FAIL'} {r.name}: measured {m}, expected {r.expected} {r.detail}".rstrip())
    return lines, sum(not r.passed for r in res)


def _value_lines(d: dict) -> list[str]:
    """Component values outside spec.json `value_bounds`."""
    from pcbenv.checks import value_violations
    return value_violations(d, load_spec().get("value_bounds") or {})


def cmd_sim(a) -> int:
    d = load_design()
    lines, nfail = _sim_lines(d)
    vlines = _value_lines(d)
    print("\n".join(lines) if lines else "no assertions in spec.json")
    if load_spec().get("value_bounds"):
        print("\n".join(f"FAIL value {s}" for s in vlines) if vlines else "PASS values: all within value_bounds")
    return 1 if nfail or vlines else 0


def cmd_parts(a) -> int:
    from pcbenv.parts import PARTS
    if a.part:
        p = PARTS.get(a.part)
        if p is None:
            print(f"unknown part {a.part}; known: {', '.join(sorted(PARTS))}")
            return 1
        print(p.datasheet.rstrip())
        print("\n## Pins (pcbenv)\n| Pin | Pad | Type | Required |\n|---|---|---|---|")
        for n, i in p.pins.items():
            print(f"| {n} | {i.pad} | {i.etype} | {'yes' if i.required else 'no'} |")
        print("\n## Allowed footprints\n" + "\n".join(f"- {f}" for f in p.footprints))
        return 0
    used = set()
    try:
        used = {c["part"] for c in load_design()["components"].values()}
    except ToolError:
        pass
    for name in sorted(PARTS):
        print(f"{'*' if name in used else ' '} {name:12s} {PARTS[name].description}")
    print("\n(* = used in design.json)  `pcbtool parts PART` prints the datasheet.")
    return 0


def _layout_lines(d: dict, board, info) -> list[str]:
    from pcbenv import layout
    spec = load_spec()
    net_of = {p: n for n, pins in d["nets"].items() for p in pins}
    meta = {"power_nets": {}, "power_net_pins": {}, "decoupling": spec.get("decoupling", [])}
    out = []
    for pn in spec.get("power_nets", []):
        net = net_of.get(pn.get("anchor_pin", "")) or (pn["net"] if pn.get("net") in d["nets"] else None)
        if net is None:
            out.append(f"power net {pn.get('net')}: anchor pin {pn.get('anchor_pin')} is not connected")
            continue
        meta["power_nets"][net] = pn["min_width_mm"]
        meta["power_net_pins"][net] = sorted(d["nets"][net])
    out += [f"{i.code}: {i.detail}" for i in layout.run_layout_checks(info, meta, board=board, ref_parts=part_map(d))]
    return out


def cmd_check(a) -> int:
    from pcbenv import boardnet
    d = load_design()
    board = load_board()
    info = boardnet.board_info(board, design=d)
    sections = [("consistency (design.json vs board)", _consistency(d, info)), ("drc", _drc_lines()),
                ("erc", _erc_lines(d)[0])]
    sim_lines, nfail = _sim_lines(d)
    sections.append(("spec (sim)", [s for s in sim_lines if s.startswith("FAIL")]))
    sections.append(("component values (value_bounds)", _value_lines(d)))
    sections.append(("layout", _layout_lines(d, board, info)))
    bad = 0
    for title, lines in sections:
        print(f"[{'FAIL' if lines else 'ok'}] {title}")
        for s in lines[:30]:
            print(f"    {s}")
        bad += bool(lines)
    print("\nall local checks pass" if not bad else f"\n{bad} section(s) failing")
    print("(the grader also compares against the hidden golden: same components/parts, intended "
          "connectivity, unchanged outline)")
    return 1 if bad else 0


# ------------------------------------------------------------------ mutating
def cmd_set_value(a) -> int:
    d = load_design()
    if a.ref not in d["components"]:
        raise ToolError(f"unknown component {a.ref}")
    d["components"][a.ref]["value"] = a.value
    from pcbenv import design as D
    try:
        D.validate(d)
    except D.DesignError as e:
        raise ToolError(str(e)) from None
    board = load_board()
    _footprint(board, a.ref).SetValue(a.value)
    save_both(d, board)
    print(f"{a.ref} value = {a.value}")
    return 0


def _replace_footprint(board, ref: str, fpid: str, value: str) -> None:
    import pcbnew

    from pcbenv import boardnet
    old = _footprint(board, ref)
    new = boardnet.library_footprint(fpid)
    if new is None:
        raise ToolError(f"library footprint {fpid} not found")
    nets = {p.GetNumber(): p.GetNetname() for p in old.Pads() if p.GetNetCode() > 0}
    pos, rot, flipped = old.GetPosition(), old.GetOrientationDegrees(), old.IsFlipped()
    board.Delete(old)
    new.SetReference(ref)
    new.SetValue(value)
    board.Add(new)
    new.SetPosition(pcbnew.VECTOR2I(pos.x, pos.y))
    new.SetOrientationDegrees(rot)
    if flipped:
        new.Flip(new.GetPosition(), True)
    for pad in new.Pads():
        n = nets.get(pad.GetNumber())
        if n:
            pad.SetNet(_net(board, n))


def cmd_set_footprint(a) -> int:
    from pcbenv.parts import PARTS
    d = load_design()
    c = d["components"].get(a.ref)
    if c is None:
        raise ToolError(f"unknown component {a.ref}")
    allowed = PARTS[c["part"]].footprints
    if a.footprint not in allowed:
        raise ToolError(f"{a.footprint} is not allowed for part {c['part']}; allowed: {', '.join(allowed)}")
    board = load_board()
    _replace_footprint(board, a.ref, a.footprint, c.get("value", ""))
    c["footprint"] = a.footprint
    save_both(d, board)
    print(f"{a.ref} footprint = {a.footprint} (same position; check tracks with `pcbtool drc`)")
    return 0


def _set_pad_net(board, ref: str, pad: str, net: str | None) -> None:
    fp = _footprint(board, ref)
    pads = [p for p in fp.Pads() if p.GetNumber() == pad]
    if not pads:
        raise ToolError(f"{ref} has no pad {pad} on the board")
    for p in pads:
        if net is None:
            p.SetNetCode(0)
        else:
            p.SetNet(_net(board, net))


def _remove_pin(d: dict, pin: str) -> None:
    for name in list(d["nets"]):
        if pin in d["nets"][name]:
            d["nets"][name] = [p for p in d["nets"][name] if p != pin]
            if not d["nets"][name]:
                del d["nets"][name]


def cmd_connect(a) -> int:
    d = load_design()
    ref, _, pad = _split_pin(d, a.pin)
    if not a.net:
        raise ToolError("net name must not be empty")
    _remove_pin(d, a.pin)
    d["nets"].setdefault(a.net, []).append(a.pin)
    board = load_board()
    _set_pad_net(board, ref, pad, a.net)
    save_both(d, board)
    print(f"{a.pin} -> net {a.net} (route it with `pcbtool route {a.net}`)")
    return 0


def cmd_disconnect(a) -> int:
    d = load_design()
    ref, _, pad = _split_pin(d, a.pin)
    _remove_pin(d, a.pin)
    board = load_board()
    _set_pad_net(board, ref, pad, None)
    save_both(d, board)
    print(f"{a.pin} disconnected (tracks still touching the pad remain; see `pcbtool drc`)")
    return 0


def cmd_move(a) -> int:
    import pcbnew
    d = load_design()
    if a.ref not in d["components"]:
        raise ToolError(f"unknown component {a.ref}")
    board = load_board()
    fp = _footprint(board, a.ref)
    fp.SetPosition(pcbnew.VECTOR2I(int(round(a.x * 1e6)), int(round(a.y * 1e6))))
    fp.SetOrientationDegrees(a.rot)
    save_both(d, board)
    print(f"{a.ref} at ({a.x}, {a.y}) rot {a.rot} (tracks did not move; re-route its nets)")
    return 0


def _unroute(board, net: str) -> int:
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() == net:
            board.Delete(t)  # Remove() leaves a dangling item that crashes KiCad at exit
            n += 1
    return n


def cmd_unroute(a) -> int:
    d = load_design()
    board = load_board()
    n = _unroute(board, a.net)
    save_both(d, board)
    print(f"removed {n} tracks/vias of net {a.net}")
    return 0


def _outline(board) -> tuple[float, float, float, float]:
    import pcbnew
    xs, ys = [], []
    for g in board.GetDrawings():
        if g.GetLayer() == pcbnew.Edge_Cuts and isinstance(g, pcbnew.PCB_SHAPE):
            for p in (g.GetStart(), g.GetEnd()):
                xs.append(p.x / 1e6)
                ys.append(p.y / 1e6)
    if not xs:
        raise ToolError("board has no Edge.Cuts outline")
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _default_width(d: dict, net: str) -> float:
    from pcbenv import drc
    for pn in load_spec().get("power_nets", []):
        if pn.get("anchor_pin") in d["nets"].get(net, []) or (pn.get("net") == net and net in d["nets"]):
            return float(pn["min_width_mm"])
    return drc.RULES["default_track_width"]


def route_net(board, net: str, width: float) -> tuple[int, int]:
    """Rip up `net` and route it among all other copper. Returns (segments, vias) added."""
    import pcbnew

    from pcbenv import board as B
    from pcbenv import drc
    from pcbenv.router import Router, RouteError, Rules, Seg, Via
    ni = board.FindNet(net)
    if ni is None or ni.GetNetCode() <= 0:
        raise ToolError(f"net {net} not on the board")
    code = ni.GetNetCode()
    _unroute(board, net)
    x0, y0, w, h = _outline(board)
    R = drc.RULES
    router = Router(x0, y0, w, h, 0.1, Rules(clearance=R["clearance"], edge_clearance=R["copper_edge_clearance"],
                                             hole_clearance=R["hole_clearance"], hole_to_hole=R["hole_to_hole"],
                                             via_d=R["via_diameter"], via_drill=R["via_drill"]))
    mine: list[int] = []
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        for pad in sorted(fp.Pads(), key=lambda p: (p.GetNumber(), p.GetPosition().x, p.GetPosition().y)):
            try:
                g = B.pad_geom(pad, f"{fp.GetReference()}.{pad.GetNumber()}")
            except B.BuildError as e:
                raise ToolError(str(e)) from None
            router.pads.append(g)
            if g.net == code and (g.layers[0] or g.layers[1]):
                mine.append(len(router.pads) - 1)
    layer_idx = {pcbnew.F_Cu: 0, pcbnew.B_Cu: 1}
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            router.vias.append(Via(t.GetNetCode(), p.x / 1e6, p.y / 1e6, t.GetWidth() / 1e6, t.GetDrillValue() / 1e6))
        elif t.GetLayer() in layer_idx:
            s, e = t.GetStart(), t.GetEnd()
            router.segs.append(Seg(t.GetNetCode(), layer_idx[t.GetLayer()], s.x / 1e6, s.y / 1e6,
                                   e.x / 1e6, e.y / 1e6, t.GetWidth() / 1e6))
    if len(mine) < 2:
        return 0, 0
    try:
        res = router.route_net(code, mine, max(width, R["track_min"]))
    except RouteError as e:
        raise ToolError(f"routing failed: {e} (move parts or unroute blocking nets, then retry)") from None
    B.add_copper(board, SimpleNamespace(segs=res.segs, vias=res.vias))
    return len(res.segs), len(res.vias)


def cmd_route(a) -> int:
    d = load_design()
    board = load_board()
    width = a.width if a.width is not None else _default_width(d, a.net)
    ns, nv = route_net(board, a.net, width)
    save_both(d, board)
    print(f"routed net {a.net} at {width} mm: {ns} segments, {nv} vias")
    return 0


def cmd_sync(a) -> int:
    from pcbenv import board as B
    d = load_design()
    board = load_board()
    padnets = B.design_pad_nets(d)
    changed = []
    for ref, c in sorted(d["components"].items()):
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            changed.append(f"{ref}: not on board (cannot add components)")
            continue
        if str(fp.GetFPID().GetUniStringLibId()) != c["footprint"]:
            _replace_footprint(board, ref, c["footprint"], c.get("value", ""))
            fp = _footprint(board, ref)
            changed.append(f"{ref}: footprint -> {c['footprint']}")
        if fp.GetValue() != c.get("value", ""):
            fp.SetValue(c.get("value", ""))
            changed.append(f"{ref}: value -> {c.get('value', '')}")
        for pad in fp.Pads():
            want = padnets[ref].get(pad.GetNumber())
            have = pad.GetNetname() if pad.GetNetCode() > 0 else None
            if want != have:
                if want is None:
                    pad.SetNetCode(0)
                else:
                    pad.SetNet(_net(board, want))
                changed.append(f"{ref} pad {pad.GetNumber()}: {have or '-'} -> {want or '-'}")
    save_both(d, board)
    print("\n".join(changed) if changed else "board already in sync with design.json")
    return 0


# ------------------------------------------------------------------ CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pcbtool", description="Inspect and edit a PCB-Repair workdir.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, hlp in (("show", cmd_show, "components, values, footprints, nets"),
                          ("netlist", cmd_netlist, "design vs board connectivity"),
                          ("drc", cmd_drc, "design rule check (canonical rules)"),
                          ("erc", cmd_erc, "electrical rule check"),
                          ("sim", cmd_sim, "run the spec assertions"),
                          ("check", cmd_check, "all checks"),
                          ("sync", cmd_sync, "push design.json onto the board")):
        sp.add_parser(name, help=hlp).set_defaults(fn=fn)
    p = sp.add_parser("parts", help="list parts or show a datasheet")
    p.add_argument("part", nargs="?")
    p.set_defaults(fn=cmd_parts)
    p = sp.add_parser("set-value")
    p.add_argument("ref"); p.add_argument("value"); p.set_defaults(fn=cmd_set_value)
    p = sp.add_parser("set-footprint")
    p.add_argument("ref"); p.add_argument("footprint"); p.set_defaults(fn=cmd_set_footprint)
    p = sp.add_parser("connect")
    p.add_argument("pin"); p.add_argument("net"); p.set_defaults(fn=cmd_connect)
    p = sp.add_parser("disconnect")
    p.add_argument("pin"); p.set_defaults(fn=cmd_disconnect)
    p = sp.add_parser("move")
    p.add_argument("ref"); p.add_argument("x", type=float); p.add_argument("y", type=float)
    p.add_argument("rot", type=float); p.set_defaults(fn=cmd_move)
    p = sp.add_parser("unroute")
    p.add_argument("net"); p.set_defaults(fn=cmd_unroute)
    p = sp.add_parser("route")
    p.add_argument("net"); p.add_argument("--width", type=float); p.set_defaults(fn=cmd_route)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
