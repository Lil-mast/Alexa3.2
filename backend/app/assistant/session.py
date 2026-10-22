"""Per-subject pending confirmations for the assistant.

A medium or high risk tool returns a preview and a single-use token. Alexa+ keeps
that token in its own conversation state. The assistant keeps it here so the
next spoken "yes" can complete the same flow without the browser holding a
capability it does not need.

The store is in memory and scoped by subject, like the adapters and the real
confirmation service. A restart drops every pending action, which is safe: the
user is asked again.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.assistant.models import PendingView
from app.models import Preview


@dataclass
class PendingConfirmation:
    """One preview waiting for a decision.

    `params` are stored because the confirmed call must resend exactly the values
    that were hashed into the token. They are never logged and never written to
    the audit row, which keeps the same privacy property as a direct MCP call.
    """

    subject: str
    tool: str
    params: dict[str, Any]
    token: str
    preview: Preview
    effect: str
    created_at: float
    expires_at: float
    ttl_seconds: int

    def expired(self, now: float) -> bool:
        return now >= self.expires_at

    def view(self) -> PendingView:
        return PendingView(
            tool=self.tool,
            effect=self.effect,
            preview=self.preview,
            expires_at=datetime.fromtimestamp(self.expires_at, UTC).isoformat(timespec="seconds"),
            ttl_seconds=self.ttl_seconds,
        )


class SessionStore:
    """At most one pending confirmation per subject, with a hard cap.

    One pending action per household is a product choice: it makes "yes" and
    "no" unambiguous. A new preview replaces the old one, which is the same
    behavior a person expects when they change their mind before answering.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        now: Callable[[], float] | None = None,
        max_pending: int = 512,
    ) -> None:
        self._ttl = ttl_seconds
        self._now = now or time.time
        self._max_pending = max_pending
        self._pending: dict[str, PendingConfirmation] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def put(self, pending: PendingConfirmation) -> None:
        # Replace first so re-previewing does not evict the caller's own slot.
        self._pending.pop(pending.subject, None)
        self._prune()
        while len(self._pending) >= self._max_pending:
            oldest = min(self._pending, key=lambda subject: self._pending[subject].expires_at)
            del self._pending[oldest]
        self._pending[pending.subject] = pending

    def get(self, subject: str) -> PendingConfirmation | None:
        pending = self._pending.get(subject)
        if pending is None:
            return None
        if pending.expired(self._now()):
            del self._pending[subject]
            return None
        return pending

    def clear(self, subject: str) -> bool:
        return self._pending.pop(subject, None) is not None

    def pending_count(self) -> int:
        self._prune()
        return len(self._pending)

    def _prune(self) -> None:
        now = self._now()
        expired = [subject for subject, pending in self._pending.items() if pending.expired(now)]
        for subject in expired:
            del self._pending[subject]


__all__ = ["PendingConfirmation", "SessionStore"]
