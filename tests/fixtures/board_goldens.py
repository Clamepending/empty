"""Fixture goldens for board tests, built only from parts in pcbenv/parts.py (R, C, CONN2)."""
from __future__ import annotations

import random

from pcbenv.golden import Golden

R0805 = "Resistor_SMD:R_0805_2012Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"


def _golden(name: str, seed: int, comps: dict, nets: dict, w: float, h: float,
            power: dict | None = None, decoupling: list | None = None) -> Golden:
    return Golden(family=name, seed=seed,
                  design={"schema": "pcbenv/design@1", "title": name, "components": comps, "nets": nets},
                  assertions=[], power_nets=power or {}, decoupling=decoupling or [],
                  intent="", params={}, board_w_mm=w, board_h_mm=h)


def rc_filter(seed: int = 0) -> Golden:
    comps = {
        "J1": {"part": "CONN2", "value": "", "footprint": HDR},
        "J2": {"part": "CONN2", "value": "", "footprint": HDR},
        "R1": {"part": "R", "value": "10k", "footprint": R0805},
        "R2": {"part": "R", "value": "4.7k", "footprint": R0603},
        "C1": {"part": "C", "value": "100n", "footprint": C0805},
        "C2": {"part": "C", "value": "10n", "footprint": C0805},
        "C3": {"part": "C", "value": "1u", "footprint": C1206},
    }
    nets = {
        "VIN": ["J1.1", "R1.1", "C3.1"],
        "GND": ["J1.2", "C1.2", "C2.2", "J2.2", "C3.2"],
        "N1": ["R1.2", "C1.1", "R2.1"],
        "OUT": ["R2.2", "C2.1", "J2.1"],
    }
    return _golden("fx_rc", seed, comps, nets, 22.0, 16.0, power={"VIN": 0.5, "GND": 0.5},
                   decoupling=[{"cap": "C3", "ic_pin": "J1.1", "max_mm": 6.0}])


def ladder(seed: int = 0, n: int = 6) -> Golden:
    """n-stage RC ladder: 2n passives + 2 connectors."""
    comps = {"J1": {"part": "CONN2", "value": "", "footprint": HDR},
             "J2": {"part": "CONN2", "value": "", "footprint": HDR}}
    nets: dict[str, list[str]] = {"GND": ["J1.2", "J2.2"], "N0": ["J1.1"]}
    for i in range(1, n + 1):
        comps[f"R{i}"] = {"part": "R", "value": "1k", "footprint": R0805 if i % 2 else R0603}
        comps[f"C{i}"] = {"part": "C", "value": "100n", "footprint": C0805}
        nets[f"N{i - 1}"].append(f"R{i}.1")
        nets[f"N{i}"] = [f"R{i}.2", f"C{i}.1"]
        nets["GND"].append(f"C{i}.2")
    nets[f"N{n}"].append("J2.1")
    return _golden("fx_ladder", seed, comps, nets, 30.0, 22.0, power={"GND": 0.4, "N0": 0.4})


def random_mesh(seed: int) -> Golden:
    """~16-20 passives with random 2..4-pin nets; a stress fixture."""
    rng = random.Random(seed)
    comps = {"J1": {"part": "CONN2", "value": "", "footprint": HDR}}
    n = rng.randint(14, 18)
    for i in range(1, n + 1):
        if rng.random() < 0.5:
            comps[f"R{i}"] = {"part": "R", "value": "1k", "footprint": rng.choice([R0603, R0805])}
        else:
            comps[f"C{i}"] = {"part": "C", "value": "1n", "footprint": rng.choice([C0805, C1206])}
    pins = [f"{r}.{p}" for r in sorted(comps) for p in ("1", "2")]
    rng.shuffle(pins)
    nets: dict[str, list[str]] = {}
    k = 0
    while pins:
        m = min(len(pins), rng.choice([2, 2, 3, 3, 4]))
        if len(pins) - m == 1:
            m += 1
        nets[f"N{k}"] = pins[:m]
        pins = pins[m:]
        k += 1
    gnd = max(nets, key=lambda x: len(nets[x]))
    return _golden("fx_mesh", seed, comps, nets, 34.0, 26.0, power={gnd: 0.5})


FIXTURES = {"fx_rc": rc_filter, "fx_ladder": ladder, "fx_mesh": random_mesh}
