"""Train-split pin-swap latent faults: variants, and for 2-pin load connectors the load type
(a relay / solenoid coil is non-polar: swapping its two pins changes nothing electrically)."""
import json, re, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/home/user/empty")
from pcbenv import qa
T = Path("/home/user/empty/tasks")
c = Counter()
for r in qa.load_train_rows(T / "manifest.jsonl", T):
    td = qa.task_dir_of(T, r)
    m = json.loads((td / "hidden" / "meta.json").read_text())
    for f in m["faults"]:
        if f["type"] not in ("mcu_pin_swap", "connector_pin_swap"):
            continue
        pins = tuple(sorted(p.split(".")[1] for p in f["data"]["pins"]))
        c[(f["type"], r["family"], pins)] += 1
        if f["type"] == "connector_pin_swap" and pins == ("1", "2"):
            md = (td / "public" / "TASK.md").read_text()
            load = re.search(r"The load is ([^.]*)\.|off-board (relay coil[^)]*\))|(brushed DC motor)", md)
            al = next(a for a in r["alone"] if a["type"] == "connector_pin_swap")
            print(f"2-pin swap {r['id']} {r['family']}: load = {load.group(0)[:70] if load else '?'}; "
                  f"alone fails {al['failing']}")
print("\nvariants (type, family, swapped pins): count")
for k, v in sorted(c.items()):
    print(f"  {v:3d} {k}")
