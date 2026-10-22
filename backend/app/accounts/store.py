"""SQLite and Postgres persistence for accounts and browser sessions.

The house, audit chain, and trace stay in memory. This store keeps only the
records that must survive a restart: the account, the opaque session, the
short-lived OAuth state, and the one-time code that hands a session to the SPA.

SQLAlchemy Core is used because the schema is four small tables and every query
is explicit. No plaintext session token, OAuth state, or exchange code is stored;
only its SHA-256 digest is.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.accounts.models import OAuthStateRecord, SessionRecord, UserRecord

SESSION_PREFIX = "sess_"
EXCHANGE_PREFIX = "code_"
STATE_PREFIX = "state_"

_METADATA = MetaData()

_USERS = Table(
    "auth_users",
    _METADATA,
    Column("id", Integer, primary_key=True),
    Column("subject", String(64), nullable=False, unique=True),
    Column("email", String(320), nullable=False),
    Column("display_name", String(80), nullable=False),
    Column("email_verified", Boolean, nullable=False),
    Column("provider", String(32), nullable=False),
    Column("provider_account_id", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("provider", "provider_account_id", name="uq_auth_users_provider_account"),
    Index("ix_auth_users_email", "email"),
)

_SESSIONS = Table(
    "auth_sessions",
    _METADATA,
    Column("id", Integer, primary_key=True),
    Column("user_id", ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index("ix_auth_sessions_user_id", "user_id"),
)

_OAUTH_STATES = Table(
    "auth_oauth_states",
    _METADATA,
    Column("id", Integer, primary_key=True),
    Column("state_hash", String(64), nullable=False, unique=True),
    Column("provider", String(32), nullable=False),
    Column("code_verifier", String(128), nullable=False),
    Column("redirect_after", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Index("ix_auth_oauth_states_expires_at", "expires_at"),
)

_EXCHANGE_CODES = Table(
    "auth_exchange_codes",
    _METADATA,
    Column("id", Integer, primary_key=True),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("session_id", ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
    Index("ix_auth_exchange_codes_expires_at", "expires_at"),
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_database_url(raw: str) -> str:
    """Map the URL forms Render and SQLAlchemy use onto one driver.

    Render exposes `postgres://...` on some plans and `postgresql://...` on
    others. SQLAlchemy 2 needs the driver name, and psycopg is the installed
    driver, so both forms become `postgresql+psycopg://`.
    """
    value = raw.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


def _hash_secret(value: str) -> str:
    # Session tokens, exchange codes, and OAuth states have 256 bits of
    # randomness. A fast hash is enough, and unlike a password hash it can be
    # looked up directly by index.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on round-trip even with timezone=True. Treating a
    # naive stored value as UTC keeps expiry checks correct in both dialects.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _random_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


class AccountStore:
    """The authoritative store for accounts and browser sessions."""

    def __init__(self, database_url: str) -> None:
        self._engine = self._build_engine(database_url)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the tables and carry the two demo schema changes forward.

        `create_all` never alters an existing table. The first deployed version
        of this demo lacked `last_seen_at` and bound exchange codes to a user
        instead of a session. Adding the column and recreating the short-lived
        code table is enough to keep an existing local or Render database
        usable; a real migration tool is still the next step before the schema
        changes again.
        """
        _METADATA.create_all(self._engine)
        inspector = inspect(self._engine)

        session_columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
        if "last_seen_at" not in session_columns:
            with self._engine.begin() as connection:
                connection.execute(text("ALTER TABLE auth_sessions ADD COLUMN last_seen_at TIMESTAMP"))
                connection.execute(
                    text("UPDATE auth_sessions SET last_seen_at = created_at WHERE last_seen_at IS NULL")
                )

        code_columns = {column["name"] for column in inspector.get_columns("auth_exchange_codes")}
        if "session_id" not in code_columns:
            # These codes live for 60 seconds and are already single-use, so
            # dropping them is safer than trying to guess a session for a
            # pre-session-row code.
            _EXCHANGE_CODES.drop(self._engine, checkfirst=True)
            _EXCHANGE_CODES.create(self._engine)

    @staticmethod
    def _build_engine(raw_url: str) -> Engine:
        url = normalize_database_url(raw_url)
        if not url:
            raise ValueError("An auth database URL is required")

        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 5}
            if url in {"sqlite://", "sqlite:///:memory:"}:
                # Every connection would otherwise get its own empty database.
                # StaticPool keeps one connection, which is what tests want.
                kwargs["poolclass"] = StaticPool
            else:
                path = url.removeprefix("sqlite:///")
                if path:
                    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, **kwargs)

    def close(self) -> None:
        self._engine.dispose()

    def prune(self) -> None:
        now = utcnow()
        with self._engine.begin() as connection:
            self._prune(connection, now)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def upsert_google_user(
        self,
        *,
        provider_account_id: str,
        email: str,
        display_name: str,
        email_verified: bool,
    ) -> UserRecord:
        """Create the account on first sign-in, then refresh its profile.

        Google's `sub` is the stable lookup key. The email is descriptive and can
        change; merging accounts on email would let a later address change take
        over an existing household.
        """
        now = utcnow()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(_USERS).where(
                        _USERS.c.provider == "google",
                        _USERS.c.provider_account_id == provider_account_id,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                subject = f"user_{uuid.uuid4().hex}"
                result = connection.execute(
                    insert(_USERS).values(
                        subject=subject,
                        email=email,
                        display_name=display_name,
                        email_verified=email_verified,
                        provider="google",
                        provider_account_id=provider_account_id,
                        created_at=now,
                        last_login_at=now,
                    )
                )
                user_id = int(result.inserted_primary_key[0])
            else:
                user_id = int(row["id"])
                connection.execute(
                    update(_USERS)
                    .where(_USERS.c.id == user_id)
                    .values(
                        email=email,
                        display_name=display_name,
                        email_verified=email_verified,
                        last_login_at=now,
                    )
                )
            row = connection.execute(select(_USERS).where(_USERS.c.id == user_id)).mappings().one()
        return self._user_from_row(row)

    def find_or_create_dev_user(self) -> UserRecord:
        """A local-only account used when Google credentials are not set.

        The subject matches the shipped MCP development token, so local browser
        and CLI sessions see the same simulated house. The endpoint that calls
        this is disabled outside a local origin and behind an explicit flag.
        """
        now = utcnow()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(_USERS).where(
                        _USERS.c.provider == "dev",
                        _USERS.c.provider_account_id == "dev-user",
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                result = connection.execute(
                    insert(_USERS).values(
                        subject="demo-user",
                        email="dev@example.invalid",
                        display_name="Demo User",
                        email_verified=True,
                        provider="dev",
                        provider_account_id="dev-user",
                        created_at=now,
                        last_login_at=now,
                    )
                )
                user_id = int(result.inserted_primary_key[0])
            else:
                user_id = int(row["id"])
                connection.execute(update(_USERS).where(_USERS.c.id == user_id).values(last_login_at=now))
            row = connection.execute(select(_USERS).where(_USERS.c.id == user_id)).mappings().one()
        return self._user_from_row(row)

    def get_user(self, user_id: int) -> UserRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(select(_USERS).where(_USERS.c.id == user_id)).mappings().first()
        return self._user_from_row(row) if row is not None else None

    def update_display_name(self, user_id: int, display_name: str) -> UserRecord:
        with self._engine.begin() as connection:
            connection.execute(update(_USERS).where(_USERS.c.id == user_id).values(display_name=display_name))
            row = connection.execute(select(_USERS).where(_USERS.c.id == user_id)).mappings().one()
        return self._user_from_row(row)

    # ------------------------------------------------------------------
    # OAuth state
    # ------------------------------------------------------------------

    def create_oauth_state(
        self,
        *,
        provider: str,
        code_verifier: str,
        redirect_after: str,
        ttl_seconds: int,
    ) -> str:
        raw_state = _random_token(STATE_PREFIX)
        now = utcnow()
        with self._engine.begin() as connection:
            self._prune(connection, now)
            connection.execute(
                insert(_OAUTH_STATES).values(
                    state_hash=_hash_secret(raw_state),
                    provider=provider,
                    code_verifier=code_verifier,
                    redirect_after=redirect_after,
                    created_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
        return raw_state

    def consume_oauth_state(self, raw_state: str, *, provider: str) -> OAuthStateRecord | None:
        """Return the state once, atomically, or None if it is invalid.

        The conditional update is what makes the state single-use. A duplicate
        callback loses the race and gets None, even if both requests read the
        same row first.
        """
        now = utcnow()
        state_hash = _hash_secret(raw_state)
        with self._engine.begin() as connection:
            row = (
                connection.execute(select(_OAUTH_STATES).where(_OAUTH_STATES.c.state_hash == state_hash))
                .mappings()
                .first()
            )
            if row is None or row["provider"] != provider:
                return None
            if row["consumed_at"] is not None or _as_utc(row["expires_at"]) <= now:
                return None
            result = connection.execute(
                update(_OAUTH_STATES)
                .where(
                    _OAUTH_STATES.c.id == row["id"],
                    _OAUTH_STATES.c.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
            if result.rowcount != 1:
                return None
            return OAuthStateRecord(
                provider=row["provider"],
                code_verifier=row["code_verifier"],
                redirect_after=row["redirect_after"],
            )

    # ------------------------------------------------------------------
    # One-time exchange codes
    # ------------------------------------------------------------------

    def create_exchange_code(self, *, session_id: int, ttl_seconds: int) -> str:
        raw_code = _random_token(EXCHANGE_PREFIX)
        now = utcnow()
        with self._engine.begin() as connection:
            self._prune(connection, now)
            connection.execute(
                insert(_EXCHANGE_CODES).values(
                    code_hash=_hash_secret(raw_code),
                    session_id=session_id,
                    created_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
        return raw_code

    def consume_exchange_code(self, raw_code: str) -> int | None:
        now = utcnow()
        code_hash = _hash_secret(raw_code)
        with self._engine.begin() as connection:
            row = (
                connection.execute(select(_EXCHANGE_CODES).where(_EXCHANGE_CODES.c.code_hash == code_hash))
                .mappings()
                .first()
            )
            if row is None or _as_utc(row["expires_at"]) <= now:
                return None
            result = connection.execute(
                update(_EXCHANGE_CODES)
                .where(
                    _EXCHANGE_CODES.c.id == row["id"],
                    _EXCHANGE_CODES.c.used_at.is_(None),
                )
                .values(used_at=now)
            )
            if result.rowcount != 1:
                return None
            return int(row["session_id"])

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, *, user_id: int, ttl_seconds: int) -> tuple[int, str, datetime]:
        raw_token = _random_token(SESSION_PREFIX)
        now = utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._engine.begin() as connection:
            result = connection.execute(
                insert(_SESSIONS).values(
                    user_id=user_id,
                    token_hash=_hash_secret(raw_token),
                    created_at=now,
                    expires_at=expires_at,
                    last_seen_at=now,
                )
            )
            session_id = int(result.inserted_primary_key[0])
        return session_id, raw_token, expires_at

    def rotate_session(self, session_id: int, *, ttl_seconds: int) -> tuple[str, datetime, UserRecord] | None:
        """Replace a pending session token and return the new bearer.

        The callback creates the session with a token it discards. Redeeming the
        exchange code rotates that hash, so the code is never the bearer and a
        session that is never redeemed has no usable token.
        """
        now = utcnow()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        _SESSIONS.c.id,
                        _SESSIONS.c.expires_at,
                        _SESSIONS.c.revoked_at,
                        _USERS.c.id.label("user_id"),
                        _USERS.c.subject,
                        _USERS.c.email,
                        _USERS.c.display_name,
                        _USERS.c.email_verified,
                        _USERS.c.provider,
                        _USERS.c.created_at.label("user_created_at"),
                        _USERS.c.last_login_at,
                    )
                    .select_from(_SESSIONS.join(_USERS, _SESSIONS.c.user_id == _USERS.c.id))
                    .where(_SESSIONS.c.id == session_id)
                )
                .mappings()
                .first()
            )
            if row is None or row["revoked_at"] is not None or _as_utc(row["expires_at"]) <= now:
                return None

            token = _random_token(SESSION_PREFIX)
            expires_at = now + timedelta(seconds=ttl_seconds)
            connection.execute(
                update(_SESSIONS)
                .where(_SESSIONS.c.id == session_id)
                .values(
                    token_hash=_hash_secret(token),
                    expires_at=expires_at,
                    last_seen_at=now,
                )
            )
        user = UserRecord(
            id=int(row["user_id"]),
            subject=row["subject"],
            email=row["email"],
            display_name=row["display_name"],
            email_verified=bool(row["email_verified"]),
            provider=row["provider"],
            created_at=_as_utc(row["user_created_at"]),
            last_login_at=_as_utc(row["last_login_at"]),
        )
        return token, expires_at, user

    def resolve_session(self, raw_token: str) -> SessionRecord | None:
        if not raw_token.startswith(SESSION_PREFIX):
            return None
        now = utcnow()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        _SESSIONS.c.id.label("session_id"),
                        _SESSIONS.c.expires_at,
                        _SESSIONS.c.last_seen_at,
                        _SESSIONS.c.revoked_at,
                        _USERS.c.id.label("user_id"),
                        _USERS.c.subject,
                        _USERS.c.email,
                        _USERS.c.display_name,
                        _USERS.c.email_verified,
                        _USERS.c.provider,
                        _USERS.c.created_at.label("user_created_at"),
                        _USERS.c.last_login_at,
                    )
                    .select_from(_SESSIONS.join(_USERS, _SESSIONS.c.user_id == _USERS.c.id))
                    .where(_SESSIONS.c.token_hash == _hash_secret(raw_token))
                )
                .mappings()
                .first()
            )
            if row is None or row["revoked_at"] is not None or _as_utc(row["expires_at"]) <= now:
                return None
            # A write on every request would contend with the audit path. One
            # minute of resolution is enough to show recent activity.
            if now - _as_utc(row["last_seen_at"]) >= timedelta(seconds=60):
                connection.execute(
                    update(_SESSIONS).where(_SESSIONS.c.id == row["session_id"]).values(last_seen_at=now)
                )
        user = UserRecord(
            id=int(row["user_id"]),
            subject=row["subject"],
            email=row["email"],
            display_name=row["display_name"],
            email_verified=bool(row["email_verified"]),
            provider=row["provider"],
            created_at=_as_utc(row["user_created_at"]),
            last_login_at=_as_utc(row["last_login_at"]),
        )
        return SessionRecord(
            session_id=int(row["session_id"]),
            expires_at=_as_utc(row["expires_at"]),
            user=user,
        )

    def revoke_session(self, session_id: int) -> bool:
        now = utcnow()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(_SESSIONS)
                .where(_SESSIONS.c.id == session_id, _SESSIONS.c.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        return result.rowcount == 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _prune(self, connection, now: datetime) -> None:
        """Delete expired handshake rows before inserting a new one.

        Sessions are not deleted here: a revoked or expired session is a useful
        audit fact, and the table is tiny for a demo. OAuth states and exchange
        codes have no value after their short TTL, so they are safe to prune.
        """
        connection.execute(_OAUTH_STATES.delete().where(_OAUTH_STATES.c.expires_at < now))
        connection.execute(_EXCHANGE_CODES.delete().where(_EXCHANGE_CODES.c.expires_at < now))

    @staticmethod
    def _user_from_row(row) -> UserRecord:
        return UserRecord(
            id=int(row["id"]),
            subject=row["subject"],
            email=row["email"],
            display_name=row["display_name"],
            email_verified=bool(row["email_verified"]),
            provider=row["provider"],
            created_at=_as_utc(row["created_at"]),
            last_login_at=_as_utc(row["last_login_at"]),
        )


__all__ = [
    "EXCHANGE_PREFIX",
    "SESSION_PREFIX",
    "STATE_PREFIX",
    "AccountStore",
    "normalize_database_url",
    "utcnow",
]
