"""Alt-fix probe: golden board of a Kelvin task with the sense track and the load track both
extended to the shunt pad centre (the default way to route to a pad). Graded with the verifier."""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/user/empty")
import pcbnew
from pcbenv import boardnet
from pcbenv import layout_rules as LR
from pcbenv.verify import verify
tid = sys.argv[1]
td = Path("/home/user/empty/tasks/v2/hard_layout") / tid
meta = json.loads((td / "hidden" / "meta.json").read_text()); rp = meta["ref_parts"]
k = meta["layout_rules"]["kelvin"][0]
with tempfile.TemporaryDirectory() as tmp:
    wd = Path(tmp)
    shutil.copy(td / "hidden" / "golden_design.json", wd / "design.json")
    shutil.copy(td / "hidden" / "golden_board.kicad_pcb", wd / "board.kicad_pcb")
    b = pcbnew.LoadBoard(str(wd / "board.kicad_pcb"))
    sh = LR._pad(b, k["shunt_pin"], rp); c = sh.GetPosition()
    n = 0
    for t in b.GetTracks():
        if t.GetNetCode() != sh.GetNetCode() or t.GetClass() == "PCB_VIA":
            continue
        for get, set_ in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
            p = get()
            if sh.HitTest(p) and p != c:
                set_(pcbnew.VECTOR2I(c.x, c.y)); n += 1
    b.Save(str(wd / "board.kicad_pcb"))
    print(f"{tid}: moved {n} track end(s) onto the shunt pad centre")
    print("kelvin_ok:", LR.kelvin_ok(str(wd / "board.kicad_pcb"), k, rp))
    r = verify(str(wd), str(td))
    print("VERIFY reward", r.reward, {k2: v for k2, v in r.checks.items() if not v}, r.detail.get("layout_rules"))
