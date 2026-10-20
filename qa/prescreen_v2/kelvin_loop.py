"""(a) switch_loop_spread faults whose faulted board shows no loop violation (masked by another
fault?); (b) Kelvin faults: shared copper length Q1.S -> shunt pad and the resulting sense error
at the spec current, vs the spec tolerance; (c) loop-fault ratio histogram."""
import json, math, sys
from pathlib import Path
sys.path.insert(0, "/home/user/empty")
from pcbenv import qa, boardnet
from pcbenv import layout as LY
from pcbenv import layout_rules as LR
T = Path("/home/user/empty/tasks")
rows = [r for r in qa.load_train_rows(T / "manifest.jsonl", T) if qa.tier_of(r) == "hard_layout"]
RHO, T_CU = 1.72e-8, 35e-6
ratios = []
for r in rows:
    types = [f["type"] for f in r["faults"]]
    td = qa.task_dir_of(T, r)
    meta = json.loads((td / "hidden" / "meta.json").read_text())
    rp = meta["ref_parts"]
    fb = str(td / "public" / "board.kicad_pcb")
    if "switch_loop_spread" in types:
        rule = meta["layout_rules"]["switch_loop"][0]
        a = LR.loop_area(fb, rule, rp)
        ga = LR.loop_area(str(td / "hidden" / "golden_board.kicad_pcb"), rule, rp)
        al = next(x for x in r["alone"] if x["type"] == "switch_loop_spread")
        if isinstance(a, str) or a <= 60:
            print(f"(a) {r['id']}: faulted loop = {a if isinstance(a, str) else round(a, 1)}; golden {ga:.1f}; "
                  f"fault alone: reward {al['reward']} fails {al['failing']}; other faults {[t for t in types if t != 'switch_loop_spread']}")
        else:
            ratios.append(a / 60)
    if "kelvin_sense_tap" in types:
        k = meta["layout_rules"]["kelvin"][0]
        b = boardnet.load_board(fb)
        qs, sh, se = LR._pad(b, k["load_pins"][0], rp), LR._pad(b, k["shunt_pin"], rp), LR._pad(b, k["sense_pin"], rp)
        L_load = LY.copper_path_mm(b, qs, sh)
        L_sense = LY.copper_path_mm(b, se, sh)
        widths = [t.GetWidth() / 1e6 for t in b.GetTracks() if t.GetNetCode() == sh.GetNetCode() and t.GetClass() != "PCB_VIA"]
        w = min(widths) if widths else 0.4
        # sense current ~0: the sense pin sees the voltage at its tap point; worst case the tap is at Q1.S
        a = next(x for x in meta["assertions"] if x.get("name") == "current_sense_voltage")
        lo, hi = a["min"], a["max"]; nom = (lo + hi) / 2
        I = nom / 0.22 if True else None
        try:
            from pcbenv.parts import parse_value
            rs = parse_value(meta and json.loads((td / "hidden" / "golden_design.json").read_text())["components"][k["shunt"]]["value"])
            I = nom / rs
        except Exception:
            pass
        dv = I * RHO * (L_load * 1e-3) / (w * 1e-3 * T_CU) if L_load else float("nan")
        print(f"(b) {r['id']}: load path Q1.S->shunt {L_load:.2f} mm, w_min {w:.2f} mm -> worst sense error "
              f"{dv * 1e3:.2f} mV = {100 * dv / nom:.1f} % of {nom * 1e3:.0f} mV (spec ±{100 * (hi - lo) / 2 / nom:.0f} %)")
ratios.sort()
print("(c) switch_loop_spread faulted/limit:", [round(x, 2) for x in ratios])
