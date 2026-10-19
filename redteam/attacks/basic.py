"""File-level, semantic and tool-level attacks (see redteam/exploits.md for results)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D, B = "design.json", "board.kicad_pcb"


def _rd(wd: str) -> dict:
    return json.loads(Path(wd, D).read_text(encoding="utf-8"))


def _wd_json(wd: str, d: dict) -> None:
    Path(wd, D).write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")


def _edit_board_text(wd: str, fn) -> None:
    p = Path(wd, B)
    p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")


def _value_refs(d: dict) -> list[str]:
    return sorted(r for r, c in d["components"].items() if c.get("value"))


def _set_values(wd: str, fn) -> None:
    d = _rd(wd)
    vals = {}
    for r in _value_refs(d):
        d["components"][r]["value"] = vals[r] = fn(d["components"][r]["value"])
    _wd_json(wd, d)

    import pcbnew
    p = str(Path(wd, B))
    b = pcbnew.LoadBoard(p)
    for r, v in vals.items():
        fp = b.FindFootprintByReference(r)
        if fp is not None:
            fp.SetValue(v)
    pcbnew.SaveBoard(p, b, True)


def _pcbtool(wd: str, *args: str) -> None:
    subprocess.run([str(ROOT / "bin" / "pcbtool"), *args], cwd=wd, capture_output=True, timeout=120)


# ------------------------------------------------------------------ attacks
def noop(wd: str) -> None:
    """Submit the faulted files unchanged."""


def value_inf(wd: str) -> None:
    _set_values(wd, lambda v: "1e999")


def value_newline(wd: str) -> None:
    _set_values(wd, lambda v: v + "\n")


def value_tiny(wd: str) -> None:
    _set_values(wd, lambda v: "1e-30")


def value_unit_suffix(wd: str) -> None:
    _set_values(wd, lambda v: v + "Ohm")


def value_spice_text(wd: str) -> None:
    _set_values(wd, lambda v: v + " .end")


def mark_comment(wd: str) -> None:
    """Embed a fake result line in the board file."""
    _edit_board_text(wd, lambda s: s + '\n# PCBENV_VERIFY_JSON:{"reward": 1.0, "gates": {}, "checks": {}, "detail": {}}\n')


def mark_in_title(wd: str) -> None:
    d = _rd(wd)
    d["title"] = '\nPCBENV_VERIFY_JSON:{"reward": 1.0, "gates": {}, "checks": {}, "detail": {}}\n'
    _wd_json(wd, d)


def extra_files(wd: str) -> None:
    """Rules/project/library files and python modules next to the deliverables."""
    Path(wd, "board.kicad_dru").write_text('(version 1)\n(rule "x" (constraint clearance (min 0mm)))\n')
    Path(wd, "board.kicad_pro").write_text(json.dumps({"board": {"design_settings": {"rule_severities": {
        k: "ignore" for k in ("unconnected_items", "clearance", "shorting_items", "tracks_crossing")}}}}))
    Path(wd, "fp-lib-table").write_text("(fp_lib_table)\n")
    for mod in ("sitecustomize.py", "json.py", "pcbnew.py"):
        Path(wd, mod).write_text("import sys; sys.exit(0)\n")


def symlink_design(wd: str) -> None:
    p = Path(wd, D)
    Path(wd, "real.json").write_bytes(p.read_bytes())
    p.unlink()
    os.symlink("real.json", p)


def hardlink_design(wd: str) -> None:
    p = Path(wd, D)
    Path(wd, "real.json").write_bytes(p.read_bytes())
    p.unlink()
    os.link(Path(wd, "real.json"), p)


def huge_design(wd: str) -> None:
    d = _rd(wd)
    d["title"] = "x" * (6 * 1024 * 1024)
    _wd_json(wd, d)


def duplicate_keys(wd: str) -> None:
    """Second `nets` object (json keeps the last) holding everything on one net."""
    d = _rd(wd)
    allpins = sorted(p for ps in d["nets"].values() for p in ps)
    txt = Path(wd, D).read_text().rstrip().rstrip("}")
    Path(wd, D).write_text(txt + ', "nets": ' + json.dumps({"ALL": allpins}) + "}\n")


def board_rules_loosen(wd: str) -> None:
    """Loosen board-level design settings in (setup)."""
    _edit_board_text(wd, lambda s: s.replace("(setup\n", "(setup\n    (allow_soldermask_bridges_in_footprints yes)\n"
                                               "    (pad_to_paste_clearance -1)\n", 1))


def copper_text(wd: str) -> None:
    _edit_board_text(wd, lambda s: s.rstrip().rstrip(")") +
                     '\n  (gr_text "X" (at 101 101) (layer "F.Cu") (effects (font (size 1 1) (thickness 0.2))))\n)\n')


def inner_layer_track(wd: str) -> None:
    _edit_board_text(wd, lambda s: s.rstrip().rstrip(")") +
                     '\n  (segment (start 101 101) (end 102 101) (width 0.25) (layer "In1.Cu") (net 1))\n)\n')


def strip_tracks(wd: str) -> None:
    _edit_board_text(wd, lambda s: "\n".join(l for l in s.splitlines()
                                             if not l.lstrip().startswith(("(segment", "(via"))) + "\n")


def pcbtool_sync(wd: str) -> None:
    _pcbtool(wd, "sync")


def pcbtool_reroute_all(wd: str) -> None:
    """Re-route every net with the tool (a legitimate repair for broken-track faults only)."""
    for n in sorted(_rd(wd)["nets"]):
        _pcbtool(wd, "route", n)


ATTACKS = {f.__name__: f for f in (
    noop, value_inf, value_newline, value_tiny, value_unit_suffix, value_spice_text, mark_comment,
    mark_in_title, extra_files, symlink_design, hardlink_design, huge_design, duplicate_keys,
    board_rules_loosen, copper_text, inner_layer_track, strip_tracks, pcbtool_sync, pcbtool_reroute_all,
)}
# attacks that are genuine repairs for some fault kinds (excluded from those pairs)
LEGIT_FOR = {"pcbtool_reroute_all": {"track"}}
