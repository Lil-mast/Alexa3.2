"""Single-use confirmation tokens for medium and high risk tools.

A token is a capability for exactly one action: one subject, one tool, and one
canonical parameter hash, within a short TTL. It is issued with a preview, never
with execution. The router verifies it, runs the adapter, then consumes it.

Tokens live in memory beside the simulated adapters. A restart invalidates every
pending confirmation, which is safe: the user is asked again.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class TokenStatus(StrEnum):
    OK = "ok"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    MISMATCH = "mismatch"


@dataclass
class Confirmation:
    token: str
    subject: str
    tool: str
    params_hash: str
    expires_at: float
    consumed: bool = False


class ConfirmationService:
    """In-memory token table with an injectable clock for tests."""

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
        self._tokens: dict[str, Confirmation] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def issue(self, *, subject: str, tool: str, params_hash: str) -> Confirmation:
        self._prune()
        # A client that asks for previews repeatedly should not grow the table
        # without bound. Evict the oldest pending token before adding another.
        while len(self._tokens) >= self._max_pending:
            oldest = min(self._tokens, key=lambda token: self._tokens[token].expires_at)
            del self._tokens[oldest]
        record = Confirmation(
            # 32 random bytes make guessing or sharing a token impractical.
            token=secrets.token_urlsafe(32),
            subject=subject,
            tool=tool,
            params_hash=params_hash,
            expires_at=self._now() + self._ttl,
        )
        self._tokens[record.token] = record
        return record

    def verify(
        self,
        token: str,
        *,
        subject: str,
        tool: str,
        params_hash: str,
    ) -> TokenStatus:
        record = self._tokens.get(token)
        # An unknown token and another user's token read the same on purpose:
        # one user must not learn that a token exists for someone else.
        if record is None or record.subject != subject:
            return TokenStatus.EXPIRED
        # Replay is checked before expiry so a reused token reports the useful
        # reason even after its TTL has passed.
        if record.consumed:
            return TokenStatus.CONSUMED
        if record.expires_at <= self._now():
            return TokenStatus.EXPIRED
        if record.tool != tool or record.params_hash != params_hash:
            return TokenStatus.MISMATCH
        return TokenStatus.OK

    def consume(self, token: str) -> bool:
        """Mark a token used. Returns False if it was already used or unknown."""
        record = self._tokens.get(token)
        if record is None or record.consumed:
            return False
        record.consumed = True
        return True

    def pending_count(self) -> int:
        """For tests and the debug console; not part of the tool contract."""
        self._prune()
        return len(self._tokens)

    def _prune(self) -> None:
        now = self._now()
        for token in [token for token, record in self._tokens.items() if record.expires_at <= now]:
            del self._tokens[token]


__all__ = ["Confirmation", "ConfirmationService", "TokenStatus"]
