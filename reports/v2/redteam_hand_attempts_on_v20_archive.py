"""The round-3 hand attempts (redteam/hand_attempts_v2.py) pin v2.0 task ids, which no longer exist in
the v2.1 hard / hard_layout splits (the ids changed; map: reports/v2/id_map_v20_v21.tsv). This runs every
`fake` attempt against the archived v2.0 task dirs (tasks/v2.0_archive) with the CURRENT (v2.1)
verifier, without editing redteam/:

    python3 reports/v2/redteam_hand_attempts_on_v20_archive.py > reports/v2/redteam_hand_attempts_on_v20_archive.txt
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import redteam.hand_attempts_v2 as HV2  # noqa: E402

ARCH = ROOT / "tasks" / "v2.0_archive"


def _td(tid: str) -> str:
    for m in (json.loads(x) for x in open(ARCH / "manifest.jsonl")):
        if m["id"] == tid:
            return str(ARCH / m["path"].split("/", 1)[1])
    raise KeyError(tid)


HV2._td = _td
bad = 0
fakes = [a for a in HV2.ATTEMPTS if a[3] == "fake"]
for a in fakes:
    r = HV2.run_attempt(*a)
    bad += r["reward"] != 0.0
    print(a[0], a[1], "reward", r["reward"])
print(f"{len(fakes)} fake attempts on the v2.0 archive with the v2.1 verifier: {len(fakes) - bad} at 0.0, {bad} above 0")
