"""Frozen records returned by the account store.

The persistence layer never hands ORM or SQLAlchemy row objects to route
handlers. These small immutable records can be used after the transaction has
closed, and they keep internal columns out of the wire models by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UserRecord:
    id: int
    subject: str
    email: str
    display_name: str
    email_verified: bool
    provider: str
    created_at: datetime
    last_login_at: datetime


@dataclass(frozen=True)
class SessionRecord:
    session_id: int
    expires_at: datetime
    user: UserRecord


@dataclass(frozen=True)
class OAuthStateRecord:
    provider: str
    code_verifier: str
    redirect_after: str


__all__ = ["OAuthStateRecord", "SessionRecord", "UserRecord"]
