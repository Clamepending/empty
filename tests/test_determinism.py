"""build_board / make_golden_task are byte-deterministic regardless of process history.

KiCad hands out UUIDs from a process-global generator, library footprint loads consume draws
(cached ones do not) and boards are saved in UUID order, so before canonicalisation the same
(golden, seed) could give different bytes in a process that had already built other boards.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r"""
import hashlib, json, os, sys, tempfile
from pathlib import Path
from pcbenv.board import build_board
from pcbenv.families import FAMILIES
from pcbenv.taskio import make_golden_task
prior, target, out = json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]
with tempfile.TemporaryDirectory() as td:
    for fam, seed in prior:
        build_board(FAMILIES[fam].generate(seed), os.path.join(td, "prior.kicad_pcb"), 0)
    fam, seed = target
    make_golden_task(FAMILIES[fam].generate(seed), out)
"""


def _task(tmp: Path, name: str, prior: list, target: tuple) -> dict[str, bytes]:
    out = tmp / name
    subprocess.run([sys.executable, "-c", SCRIPT, json.dumps(prior), json.dumps(target), str(out)],
                   cwd=ROOT, check=True, capture_output=True, timeout=600)
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("target", [("mcu_i2c", 3), ("ldo_reg", 1)])
def test_same_bytes_across_process_histories(tmp_path, target):
    fresh = _task(tmp_path, "fresh", [], target)
    busy = _task(tmp_path, "busy", [["xtal_osc", 7], ["opamp_inv", 3], ["divider_adc", 5]], target)
    assert sorted(fresh) == sorted(busy)
    diff = [k for k in fresh if fresh[k] != busy[k]]
    assert not diff, diff
    # the golden board equals the shipped one when the frozen task set is present
    manifest = ROOT / "tasks" / "manifest.jsonl"
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            if (row["family"], row["seed"]) == tuple(target):
                shipped = list((ROOT / "tasks").glob(f"*/{row['id']}/hidden/golden_board.kicad_pcb"))
                if shipped:
                    assert hashlib.sha256(shipped[0].read_bytes()).hexdigest() == \
                        hashlib.sha256(fresh["hidden/golden_board.kicad_pcb"]).hexdigest()


def test_canonical_pass_is_idempotent(tmp_path):
    """The task generator re-canonicalises build_board's output with the same salt: no-op."""
    from pcbenv.board import build_board, canonical_board_file
    from pcbenv.families import FAMILIES
    g = FAMILIES["led_driver"].generate(2)
    p = tmp_path / "b.kicad_pcb"
    build_board(g, str(p), 0)
    before = p.read_bytes()
    canonical_board_file(str(p), f"{g.family}:{g.seed}:0")
    assert p.read_bytes() == before
