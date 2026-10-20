"""Canonical JSON and hashes.

The same canonicalisation feeds the confirmation tokens and the audit chain, so
a parameter hash computed here is stable across processes and restarts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def params_hash(params: dict[str, Any]) -> str:
    """Hash only the parameters that were actually supplied and are non-null.

    Dropping nulls keeps the hash stable whether a client omits an optional
    field or sends it as null. Confirmation tokens compare this hash.
    """
    clean = {key: value for key, value in params.items() if value is not None}
    return sha256_hex(canonical_json(clean))
