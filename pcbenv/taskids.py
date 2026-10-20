"""Opaque task ids and secret-derived generator seeds (RT37).

v1 ids were `pcbr-<family>-<seed>-<hash>`: with the open-source generators, an id that reached a
policy was enough to regenerate the golden. v2:

- task id `pcbr2-<tier>-<hmac8>`, hmac8 = HMAC-SHA256(secret, "id:<tier>:<index>:<content>")[:8];
- generator seed of task index i = int(HMAC-SHA256(secret, "seed:<tier>:<i>")[:12], 16) (48 bit),
  so neither an id nor a public manifest row (which never carries seeds) reveals family + seed.

The secret lives ONLY in a generation-secret file outside every public directory
(`tasks/.secret`, git-ignored; shipped tasks were generated with it and it must be backed up
privately). `secret="default"` selects the documented public default `DEFAULT_SECRET`, used by tests
and reproducibility runs (tasks generated with it are NOT protected against regeneration).
Seeds and indices of shipped tasks are kept in a private manifest under `tasks/private/`
(git-ignored); hidden/meta.json keeps the seed too (grader side only).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets as _secrets
from pathlib import Path

DEFAULT_SECRET = "pcb-repair-v2-public-default-secret (reproducibility runs only)"
DEFAULT_SECRET_FILE = "tasks/.secret"


def load_secret(spec: str | None = None, create: bool = False) -> str:
    """`spec`: "default" (public default), a path to a secret file, or None (= DEFAULT_SECRET_FILE).
    With `create`, a missing secret file is created with 32 random bytes (hex, mode 0600)."""
    if spec == "default":
        return DEFAULT_SECRET
    p = Path(spec or DEFAULT_SECRET_FILE)
    if not p.exists():
        if not create:
            raise FileNotFoundError(f"generation secret {p} not found (pass --secret default for a "
                                    "reproducibility run, or --create-secret)")
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(_secrets.token_hex(32) + "\n")
    s = p.read_text(encoding="utf-8").strip()
    if len(s) < 16:
        raise ValueError(f"generation secret {p} is too short")
    return s


def _mac(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def task_seed(secret: str, tier: str, index: int) -> int:
    return int(_mac(secret, f"seed:{tier}:{index}")[:12], 16)


def task_id(secret: str, tier: str, index: int, content: str) -> str:
    return f"pcbr2-{tier}-{_mac(secret, f'id:{tier}:{index}:{content}')[:8]}"


def secret_fingerprint(secret: str) -> str:
    """Public, non-reversible tag of the secret (lets a reader check which secret a run used)."""
    return _mac(secret, "fingerprint")[:12]
