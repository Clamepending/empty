"""The Golden dataclass: a known-correct design produced by a family generator."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields


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
    # ref -> [min, max] acceptable value (SI units, parsed with parts.parse_value). Public
    # requirement (spec.json) and graded by the verifier's `values` check. Empty = no check.
    value_bounds: dict[str, list[float]] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Golden":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
