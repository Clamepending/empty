"""The grader's DRC uses the published rules (TASK.md / pcbtool), not KiCad's built-in defaults."""
import pcbnew

from pcbenv import drc


def _board_with_track_near_edge(tmp_path, gap_mm: float) -> str:
    b = pcbnew.BOARD()
    pts = [(100, 100), (130, 100), (130, 120), (100, 120)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(pcbnew.VECTOR2I_MM(x1, y1))
        s.SetEnd(pcbnew.VECTOR2I_MM(x2, y2))
        b.Add(s)
    t = pcbnew.PCB_TRACK(b)
    w = 0.25
    y = 100 + gap_mm + w / 2  # track edge sits `gap_mm` from the board edge
    t.SetStart(pcbnew.VECTOR2I_MM(110, y))
    t.SetEnd(pcbnew.VECTOR2I_MM(120, y))
    t.SetWidth(pcbnew.FromMM(w))
    t.SetLayer(pcbnew.F_Cu)
    b.Add(t)
    p = str(tmp_path / f"edge_{gap_mm}.kicad_pcb")
    pcbnew.SaveBoard(p, b)
    return p


def _edge_errors(path: str, rules: str | None) -> int:
    res = drc.run_drc(path, rules)
    return sum(e["type"] == "copper_edge_clearance" for e in res.errors)


def test_published_edge_clearance_is_what_grading_enforces(tmp_path):
    ok = _board_with_track_near_edge(tmp_path, 0.4)    # legal under the published 0.3 mm
    bad = _board_with_track_near_edge(tmp_path, 0.2)   # illegal
    assert drc.RULES["copper_edge_clearance"] == 0.3
    # Graded with a project-less "golden" board (carries KiCad defaults, 0.5 mm edge clearance):
    assert _edge_errors(ok, ok) == 0
    assert _edge_errors(bad, ok) > 0
    # Same verdicts without a rules board (what pcbtool drc does).
    assert _edge_errors(ok, None) == 0
    assert _edge_errors(bad, None) > 0
