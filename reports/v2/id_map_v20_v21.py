"""v2.0 -> v2.1 task id map (same tier + generator index, so the same golden; faults may differ).
Reads the private manifests (tasks/v2.0_archive/private, tasks/private); prints only ids and splits.

    python3 reports/v2/id_map_v20_v21.py > reports/v2/id_map_v20_v21.tsv
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tasks"


def load(d: Path) -> dict:
    out = {}
    for f in sorted(d.glob("*.jsonl")):
        for x in f.read_text().splitlines():
            if x.strip():
                r = json.loads(x)
                if "id" in r:   # dropped indices carry no id
                    out[(f.stem, r["index"])] = r
    return out


old, new = load(ROOT / "v2.0_archive" / "private"), load(ROOT / "private")
print("manifest\tv2.0_id\tv2.0_split\tv2.1_id\tv2.1_split\tsame_id")
for k in sorted(set(old) | set(new), key=lambda k: (k[0], k[1])):
    a, b = old.get(k), new.get(k)
    print("\t".join([k[0], a["id"] if a else "-", a["split"] if a else "-", b["id"] if b else "-",
                     b["split"] if b else "-", str(bool(a and b and a["id"] == b["id"]))]))
