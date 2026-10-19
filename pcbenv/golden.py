"""The Golden dataclass: a known-correct design produced by a family generator."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class Golden:
    family: str
    seed: int
    design: dict
    assertions: list[dict]
    power_nets: dict[str, float]
    decoupling: list[dict]
    intent: str
    params: dict
    board_w_mm: float
    board_h_mm: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Golden":
        return cls(**d)
