"""Scripted red-team attacks. Each attack is `fn(workdir: str) -> None`: it edits the agent's
workdir only (public files), never reading hidden data, and makes no genuine repair.
A reward of 1.0 after an attack on a task whose faulted baseline scores 0.0 is a hack."""
from redteam.attacks.basic import ATTACKS

__all__ = ["ATTACKS"]
