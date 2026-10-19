"""DRC wrapper around KiCad 7 `pcbnew.WriteDRCReport`.

Rules are *canonical*: in KiCad 7 the design rules (clearance, min track, vias,
netclasses, severities, exclusions) live in the `.kicad_pro` project file, not in the
`.kicad_pcb`. The verifier only ever sees `board.kicad_pcb`, so the rules are defined
here (`RULES`) and applied to every board before DRC. `run_drc` additionally copies the
board-file-level settings (solder mask, layer count/enabled layers) from the rules board
(the golden) and takes, for every numeric minimum, max(canonical, rules board) so a rules
board can only tighten the rules, never loosen them.

The candidate is copied into a fresh temp dir next to our own canonical `.kicad_pro` and
`.kicad_dru` before loading, so no project file (severities, exclusions) or custom rules
file next to the candidate -- or in the process CWD, which KiCad would otherwise use for a
board without a project -- can apply. DRC is run twice per load to dodge a KiCad 7.0.11
uninitialised-member bug (see `_CANON_DRU`).

Ignored report items (see `IGNORED_RULES`):
- every item whose severity is not `error` (spec: warnings ignored). With KiCad's default
  severities this drops e.g. `lib_footprint_issues` ("current configuration does not
  include the library ..." -- there is no fp-lib-table in this headless environment),
  `lib_footprint_mismatch`, silk warnings, `track_dangling`, `via_dangling`,
  `isolated_copper`, `missing_courtyard`/`*_inside_courtyard` (ignore by default).
- `lib_footprint_issues`, `lib_footprint_mismatch`: dropped even if reported as error,
  because they depend on the machine's library table, not on the board. Library
  conformance is checked by `boardnet.pad_fingerprint` instead.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

import pcbnew

MM = 1_000_000  # nm per mm

# Canonical rules (mm). Applied to every board before DRC.
RULES = {
    "clearance": 0.2,
    "track_min": 0.2,
    "via_diameter": 0.6,
    "via_drill": 0.3,
    "via_min_diameter": 0.6,
    "via_min_annular": 0.1,
    "min_through_drill": 0.3,
    "copper_edge_clearance": 0.3,
    "hole_clearance": 0.25,
    "hole_to_hole": 0.25,
    "default_track_width": 0.25,
}

IGNORED_RULES = frozenset({"lib_footprint_issues", "lib_footprint_mismatch"})


@dataclass
class DrcResult:
    errors: list[dict] = field(default_factory=list)
    unconnected: int = 0
    raw: str = ""

    @property
    def clean(self) -> bool:
        return not self.errors and self.unconnected == 0


def _nm(mm: float) -> int:
    return int(round(mm * MM))


def apply_rules(board: "pcbnew.BOARD", rules_board: "pcbnew.BOARD | None" = None) -> None:
    """Set the canonical design rules on `board` (optionally tightened by `rules_board`)."""
    ds = board.GetDesignSettings()
    rd = rules_board.GetDesignSettings() if rules_board is not None else None

    def tight(val_mm: float, attr: str) -> int:
        v = _nm(val_mm)
        if rd is not None:
            v = max(v, int(getattr(rd, attr)))
        return v

    ds.m_MinClearance = tight(RULES["clearance"], "m_MinClearance")
    ds.m_TrackMinWidth = tight(RULES["track_min"], "m_TrackMinWidth")
    ds.m_ViasMinSize = tight(RULES["via_min_diameter"], "m_ViasMinSize")
    ds.m_ViasMinAnnularWidth = tight(RULES["via_min_annular"], "m_ViasMinAnnularWidth")
    ds.m_MinThroughDrill = tight(RULES["min_through_drill"], "m_MinThroughDrill")
    ds.m_CopperEdgeClearance = tight(RULES["copper_edge_clearance"], "m_CopperEdgeClearance")
    ds.m_HoleClearance = tight(RULES["hole_clearance"], "m_HoleClearance")
    ds.m_HoleToHoleMin = tight(RULES["hole_to_hole"], "m_HoleToHoleMin")
    nc = ds.m_NetSettings.m_DefaultNetClass
    nc.SetClearance(max(_nm(RULES["clearance"]), int(ds.m_MinClearance)))
    nc.SetTrackWidth(_nm(RULES["default_track_width"]))
    nc.SetViaDiameter(_nm(RULES["via_diameter"]))
    nc.SetViaDrill(_nm(RULES["via_drill"]))
    # No other netclasses: every net uses the default class.
    try:
        ds.m_NetSettings.m_NetClasses.clear()
    except Exception:  # pragma: no cover - binding differences
        pass
    board.SynchronizeNetsAndNetClasses(False)
    if rd is not None:
        ds.m_SolderMaskExpansion = rd.m_SolderMaskExpansion
        ds.m_SolderMaskMinWidth = rd.m_SolderMaskMinWidth
        ds.m_SolderMaskToCopperClearance = rd.m_SolderMaskToCopperClearance
        ds.m_AllowSoldermaskBridgesInFPs = rd.m_AllowSoldermaskBridgesInFPs
        board.SetCopperLayerCount(rules_board.GetCopperLayerCount())
        board.SetEnabledLayers(rules_board.GetEnabledLayers())
    else:
        ds.m_SolderMaskExpansion = 0
        ds.m_SolderMaskMinWidth = 0
        ds.m_SolderMaskToCopperClearance = 0
        ds.m_AllowSoldermaskBridgesInFPs = False
        board.SetCopperLayerCount(2)


_ITEM_RE = re.compile(r"^\[(\w+)\]: (.*)$")
_SEV_RE = re.compile(r"Severity: (\w+)")
_POS_RE = re.compile(r"^\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): (.*)$")
_UNCONN_RE = re.compile(r"\*\* Found (\d+) unconnected pads \*\*")


def parse_report(text: str) -> tuple[list[dict], int]:
    """Parse a WriteDRCReport text into (error items, unconnected count).

    Only the "DRC violations" section is turned into error items; the unconnected
    section is summarised by its count (each of those is an `unconnected_items` error).
    """
    errors: list[dict] = []
    unconnected = 0
    section = ""
    cur: dict | None = None

    def flush() -> None:
        if cur and section == "violations" and cur.get("severity") == "error" \
                and cur["type"] not in IGNORED_RULES:
            errors.append(cur)

    for line in text.splitlines():
        if line.startswith("** Found") and "DRC violations" in line:
            flush(); cur = None; section = "violations"; continue
        m = _UNCONN_RE.search(line)
        if m:
            flush(); cur = None; section = "unconnected"; unconnected = int(m.group(1)); continue
        if line.startswith("** "):
            flush(); cur = None; section = "other"; continue
        m = _ITEM_RE.match(line)
        if m:
            flush()
            cur = {"type": m.group(1), "description": m.group(2), "severity": "", "items": [], "pos": None}
            continue
        if cur is None:
            continue
        m = _SEV_RE.search(line)
        if m:
            cur["severity"] = m.group(1)
            continue
        m = _POS_RE.match(line)
        if m:
            pos = (float(m.group(1)), float(m.group(2)))
            if cur["pos"] is None:
                cur["pos"] = pos
            cur["items"].append(m.group(3).strip())
    flush()
    return errors, unconnected


# KiCad 7.0.11 bug workaround: BOARD::m_DRCMaxClearance is not initialised by the BOARD
# constructor and is only reset by IncrementTimeStamp() when one of the board's expression
# caches is non-empty. With a garbage (huge) value the copper R-tree bounding boxes overflow
# and the copper clearance / short tests silently find nothing (~10 % of runs in a process
# after the first). We therefore (1) give the board a rule whose condition fills
# m_LayerExpressionCache (harmless: silk clearance >= 0) and (2) run DRC twice on the same
# board object, using the second result, whose cache-reset path zeroes the field.
_CANON_DRU = """(version 1)
(rule "pcbenv_cache_init"
  (constraint silk_clearance (min 0mm))
  (condition "A.Layer == 'F.SilkS'"))
"""
_CANON_PRO = '{"meta": {"filename": "board.kicad_pro", "version": 1}}\n'


def _write_report(board: "pcbnew.BOARD", td: str) -> str:
    rpt = os.path.join(td, "drc.rpt")
    if os.path.exists(rpt):
        os.remove(rpt)
    ok = pcbnew.WriteDRCReport(board, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    if not ok or not os.path.exists(rpt):
        raise RuntimeError("WriteDRCReport failed")
    with open(rpt, encoding="utf-8", errors="replace") as f:
        return f.read()


def _load_in_sandbox(path: str, td: str) -> "pcbnew.BOARD":
    """Copy `path` into `td` next to our own canonical .kicad_pro/.kicad_dru and load it.

    The project file matters: without one, KiCad resolves `<name>.kicad_dru` relative to
    the *default project*, i.e. the process CWD, so a rules file in the CWD would apply."""
    with open(os.path.join(td, "board.kicad_pro"), "w", encoding="utf-8") as f:
        f.write(_CANON_PRO)
    with open(os.path.join(td, "board.kicad_dru"), "w", encoding="utf-8") as f:
        f.write(_CANON_DRU)
    dst = os.path.join(td, "board.kicad_pcb")
    shutil.copyfile(path, dst)
    board = pcbnew.LoadBoard(dst)
    if board is None:
        raise RuntimeError(f"cannot load board {path}")
    return board


def _release(board: "pcbnew.BOARD") -> None:
    """Unload the sandbox project (the settings manager otherwise keeps every one)."""
    try:
        prj = board.GetProject()
        board.ClearProject()
        if prj is not None:
            pcbnew.GetSettingsManager().UnloadProject(prj, False)
    except Exception:  # pragma: no cover - best effort
        pass


def run_drc(board_path: str, rules_board_path: str | None = None) -> DrcResult:
    """DRC `board_path` under the canonical rules tightened by `rules_board_path`."""
    with tempfile.TemporaryDirectory(prefix="pcbdrc_") as td:
        cdir, rdir = os.path.join(td, "c"), os.path.join(td, "r")
        os.mkdir(cdir)
        os.mkdir(rdir)
        board = _load_in_sandbox(board_path, cdir)
        rules = _load_in_sandbox(rules_board_path, rdir) if rules_board_path else None
        # The sandbox project holds no exclusions/severity overrides; drop any markers too.
        board.DeleteMARKERs()
        apply_rules(board, rules)
        board.BuildConnectivity()
        _write_report(board, cdir)          # 1st run: fills the expression cache
        text = _write_report(board, cdir)   # 2nd run: reliable (see comment above)
        for b in (board, rules):
            if b is not None:
                _release(b)
    errors, unconnected = parse_report(text)
    return DrcResult(errors=errors, unconnected=unconnected, raw=text)
