"""Shared helpers for family generators: E-series values, a design builder, numeric filters."""
from __future__ import annotations

import cmath
import math
import random

from pcbenv.golden import Golden
from pcbenv.parts import PARTS, format_value, parse_value

E6 = [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
       3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43,
       1.47, 1.50, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10,
       2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09,
       3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53,
       4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
       6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76]


def series_values(series: list[float], lo: float, hi: float) -> list[float]:
    """All values of an E-series within [lo, hi] (rounded to the value string precision)."""
    out = []
    for dec in range(-13, 8):
        for m in series:
            v = parse_value(format_value(m * 10 ** dec))
            if lo * (1 - 1e-9) <= v <= hi * (1 + 1e-9):
                out.append(v)
    return sorted(set(out))


def nearest(series: list[float], x: float) -> float:
    """Nearest E-series value to x (log distance), exactly representable as a value string."""
    dec = math.floor(math.log10(x))
    cands = [m * 10 ** d for d in (dec - 1, dec, dec + 1) for m in series]
    best = min(cands, key=lambda v: abs(math.log(v / x)))
    return parse_value(format_value(best))


def vstr(x: float) -> str:
    return format_value(x)


def pick(rng: random.Random, xs: list):
    return xs[rng.randrange(len(xs))]


class Builder:
    """Accumulates components and nets into a design.json dict."""

    def __init__(self, title: str, rng: random.Random):
        self.title = title
        self.rng = rng
        self.components: dict[str, dict] = {}
        self.nets: dict[str, list[str]] = {}

    def add(self, ref: str, part: str, value: float | str = "", footprint: str | None = None) -> str:
        fps = PARTS[part].footprints
        if footprint is None:
            footprint = fps[0] if len(fps) == 1 else pick(self.rng, fps)
        if not isinstance(value, str):
            value = vstr(value)
        self.components[ref] = {"part": part, "value": value, "footprint": footprint}
        return ref

    def val(self, ref: str) -> float:
        return parse_value(self.components[ref]["value"])

    def net(self, name: str, *pins: str) -> None:
        self.nets.setdefault(name, []).extend(pins)

    def design(self) -> dict:
        return {
            "schema": "pcbenv/design@1",
            "title": self.title,
            "components": {k: dict(v) for k, v in sorted(self.components.items())},
            "nets": {k: list(v) for k, v in sorted(self.nets.items())},
        }


def board_size(n_components: int, big: bool = False) -> tuple[float, float]:
    w = min(50.0, 22.0 + 3.0 * n_components + (6 if big else 0))
    h = min(45.0, 20.0 + 2.2 * n_components + (5 if big else 0))
    return float(round(w)), float(round(h))


# ----------------------------------------------------------------------------- value bounds
# Acceptable component value ranges ([min, max], SI units) graded by the verifier's `values` check
# and published in spec.json / TASK.md. Two kinds:
# - `spec(ref, v)`: the value is already pinned by a spec assertion, so the bound is only a sanity
#   range (golden / 2.5..4 to golden x 2.5..4) that leaves room for alternative E-series repairs. The
#   two factors are drawn per ref from a separate RNG so the range's midpoint does not reveal the
#   golden value (the generator's own RNG stream is untouched).
# - `fixed(ref, lo, hi)`: no assertion constrains the value; the range comes from datasheet /
#   engineering practice and is also stated in the family's intent.
DECOUPLING = (47e-9, 10e-6)      # MCU8 / OPAMP datasheets: 100 nF typical, 47 nF..10 uF acceptable
NRST_PULLUP = (2.2e3, 100e3)     # MCU8 datasheet: 10k typical; 2.2k..100k keeps NRST high, low current
BULK = (1e-6, 22e-6)             # ceramic bulk / LDO caps: >= 1 uF (datasheet), <= 22 uF practical MLCC


def _sig2(x: float) -> float:
    return float(f"{x:.2g}")


class Bounds:
    def __init__(self, family: str, seed: int):
        self.family, self.seed = family, seed
        self.out: dict[str, list[float]] = {}

    def spec(self, ref: str, v: float) -> None:
        r = random.Random(f"value_bounds/{self.family}/{self.seed}/{ref}")
        lo, hi = 2.5 + 1.5 * r.random(), 2.5 + 1.5 * r.random()
        self.out[ref] = [_sig2(v / lo), _sig2(v * hi)]

    def fixed(self, ref: str, lo: float, hi: float) -> None:
        self.out[ref] = [float(lo), float(hi)]

    def exact(self, ref: str, v: float, rel: float) -> None:
        self.out[ref] = [float(f"{v * (1 - rel):.9g}"), float(f"{v * (1 + rel):.9g}")]


def check_bounds(design: dict, bounds: dict[str, list[float]]) -> None:
    """Every component with a value has a bound and its golden value lies inside it."""
    for ref, c in design["components"].items():
        if not c.get("value"):
            continue
        if ref not in bounds:
            raise ValueError(f"no value bound for {ref}")
        lo, hi = bounds[ref]
        if not lo <= parse_value(c["value"]) <= hi:
            raise ValueError(f"golden {ref}={c['value']} outside its bound {bounds[ref]}")


def golden(family: str, seed: int, b: Builder, assertions: list[dict], power_nets: dict[str, float],
           decoupling: list[dict], intent: str, params: dict, big: bool = False,
           value_bounds: dict[str, list[float]] | None = None) -> Golden:
    w, h = board_size(len(b.components), big)
    design = b.design()
    vb = {k: list(v) for k, v in sorted((value_bounds or {}).items())}
    check_bounds(design, vb)
    return Golden(family=family, seed=seed, design=design, assertions=assertions, power_nets=power_nets,
                  decoupling=decoupling, intent=intent.strip() + "\n", params=params, board_w_mm=w, board_h_mm=h,
                  value_bounds=vb)


def rng_range(lo: float, hi: float, slack: float) -> dict:
    """min/max dict around a nominal band, rounded for readability."""
    return {"min": float(f"{lo * (1 - slack):.6g}"), "max": float(f"{hi * (1 + slack):.6g}")}


def band(x: float, rel: float, abs_: float = 0.0) -> dict:
    d = abs(x) * rel + abs_
    return {"min": float(f"{x - d:.6g}"), "max": float(f"{x + d:.6g}")}


# ----------------------------------------------------------------------------- numeric AC

def freq_grid(f1: float = 0.1, f2: float = 1e8, per_dec: int = 400) -> list[float]:
    n = int(round(math.log10(f2 / f1) * per_dec))
    return [f1 * 10 ** (i / per_dec) for i in range(n + 1)]


def cutoff_of(h, edge: str = "high", f1: float = 0.1, f2: float = 1e8) -> float:
    """-3 dB frequency (relative to peak |H|) of transfer function h(s), same rule as sim.py."""
    fs = freq_grid(f1, f2)
    mags = [abs(h(2j * math.pi * f)) for f in fs]
    from pcbenv.sim import _cutoff
    fc = _cutoff(fs, mags, edge)
    if fc is None:
        raise ValueError("no cutoff")
    return fc


def par(*zs: complex) -> complex:
    return 1 / sum(1 / z for z in zs)


def gain_at(h, f: float) -> float:
    return abs(h(2j * math.pi * f))


__all__ = ["E6", "E12", "E24", "E96", "Builder", "Bounds", "DECOUPLING", "NRST_PULLUP", "BULK", "check_bounds", "cmath", "series_values", "nearest", "vstr", "pick",
           "golden", "band", "rng_range", "cutoff_of", "par", "gain_at"]
