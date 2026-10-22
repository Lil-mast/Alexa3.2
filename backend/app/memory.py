"""Per-subject memory of the last few action details.

`tell_me_more` answers from here. The response already withheld the detail in
concise mode, so this is the only copy the client can get without repeating the
action. It is in memory, capped, and cleared when personalization is turned off,
which is the visible meaning of that toggle in this build.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Remembered:
    audit_id: str
    tool: str
    detail: str


class DetailMemory:
    """Newest-first detail history, one small deque per subject."""

    def __init__(self, per_subject: int = 20) -> None:
        self._per_subject = per_subject
        self._entries: dict[str, deque[Remembered]] = {}

    def remember(self, subject: str, entry: Remembered) -> None:
        history = self._entries.setdefault(subject, deque(maxlen=self._per_subject))
        history.append(entry)

    def latest(self, subject: str, audit_id: str | None = None) -> Remembered | None:
        history = self._entries.get(subject)
        if not history:
            return None
        if audit_id is None:
            return history[-1]
        for entry in reversed(history):
            if entry.audit_id == audit_id:
                return entry
        return None

    def clear(self, subject: str) -> None:
        self._entries.pop(subject, None)


__all__ = ["DetailMemory", "Remembered"]
