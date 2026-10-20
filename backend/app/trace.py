"""In-memory trace ring buffer for the console. The hash-chained audit log lands on Day 3."""

from __future__ import annotations

import secrets
from collections import deque
from datetime import UTC, datetime
from typing import Literal

from app.models import TraceEvent


class TraceBuffer:
    """Newest-first list of recent calls for the console.

    This is observability, not the audit log. It is not hash-chained, it is lost
    on restart, and it keeps only summaries. Day 3 adds the audit table beside it.
    """

    def __init__(self, capacity: int = 200) -> None:
        # deque with maxlen drops the oldest entry on append, no cleanup task.
        self._events: deque[TraceEvent] = deque(maxlen=capacity)

    def record(
        self,
        *,
        subject: str,
        tool: str,
        service: str,
        params_hash: str,
        status: Literal["ok", "confirmation_required", "error"],
        decision: Literal["executed", "previewed", "refused", "no_change"],
        ms: int,
        speech: str,
    ) -> TraceEvent:
        event = TraceEvent(
            id=f"t_{secrets.token_hex(5)}",
            ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
            subject=subject,
            tool=tool,
            service=service,
            params_hash=params_hash,
            status=status,
            decision=decision,
            ok=status == "ok",
            ms=ms,
            speech=speech,
        )
        self._events.append(event)
        return event

    def snapshot(self) -> list[TraceEvent]:
        """Newest first, so the console can render without sorting."""
        return list(reversed(self._events))
