"""Load, validate and analyse `design.json` (schema pcbenv/design@1)."""
from __future__ import annotations

import json
from pathlib import Path

from pcbenv.parts import PARTS, parse_value

SCHEMA = "pcbenv/design@1"

Partition = frozenset  # frozenset[frozenset[str]]


class DesignError(ValueError):
    pass


def load(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    validate(d)
    return d


def save(d: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate(d: dict) -> None:
    """Raise DesignError if `d` is not a well-formed design."""
    if not isinstance(d, dict) or d.get("schema") != SCHEMA:
        raise DesignError("missing/unknown schema")
    comps = d.get("components")
    nets = d.get("nets")
    if not isinstance(comps, dict) or not isinstance(nets, dict):
        raise DesignError("components/nets must be objects")
    for ref, c in comps.items():
        if not isinstance(c, dict):
            raise DesignError(f"{ref}: component must be an object")
        part = PARTS.get(c.get("part"))
        if part is None:
            raise DesignError(f"{ref}: unknown part {c.get('part')!r}")
        if not isinstance(c.get("footprint"), str):
            raise DesignError(f"{ref}: footprint must be a string")
        value = c.get("value", "")
        if not isinstance(value, str):
            raise DesignError(f"{ref}: value must be a string")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            raise DesignError(f"{ref}: value contains control characters")
        if part.value_required:
            try:
                if parse_value(value, c["part"]) <= 0:
                    raise DesignError(f"{ref}: value must be positive")
            except ValueError as e:
                raise DesignError(f"{ref}: {e}") from None
    seen: set[str] = set()
    for name, pins in nets.items():
        if not isinstance(name, str) or not isinstance(pins, list):
            raise DesignError(f"net {name!r}: must map a name to a list of pins")
        for p in pins:
            if not isinstance(p, str) or "." not in p:
                raise DesignError(f"net {name}: bad pin {p!r}")
            ref, pin = p.split(".", 1)
            if ref not in comps:
                raise DesignError(f"net {name}: unknown ref {ref}")
            if pin not in PARTS[comps[ref]["part"]].pins:
                raise DesignError(f"net {name}: {ref} has no pin {pin}")
            if p in seen:
                raise DesignError(f"pin {p} is on more than one net")
            seen.add(p)


def partition(d: dict) -> Partition:
    """Name-insensitive connectivity: set of pin-sets, one per non-empty net."""
    return frozenset(frozenset(pins) for pins in d["nets"].values() if pins)


def net_of(d: dict, pin: str) -> str | None:
    for name, pins in d["nets"].items():
        if pin in pins:
            return name
    return None
