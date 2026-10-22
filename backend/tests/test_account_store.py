"""Compatibility checks for the demo account schema.

`create_all` creates missing tables but never alters an existing one. The first
version of the demo had no `last_seen_at` and bound exchange codes to a user.
These tests pin the small startup migration that keeps an existing local or
Render database usable until Alembic lands.
"""

from __future__ import annotations

import sqlite3

from app.accounts.store import AccountStore


def test_store_upgrades_the_first_demo_schema(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE auth_sessions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_hash VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                revoked_at DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE auth_exchange_codes (
                id INTEGER PRIMARY KEY,
                code_hash VARCHAR(64) NOT NULL,
                user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                used_at DATETIME
            )
            """
        )

    store = AccountStore(f"sqlite:///{path}")
    try:
        with sqlite3.connect(path) as connection:
            session_columns = {row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")}
            code_columns = {row[1] for row in connection.execute("PRAGMA table_info(auth_exchange_codes)")}

        assert "last_seen_at" in session_columns
        assert "session_id" in code_columns
        assert "user_id" not in code_columns

        user = store.find_or_create_dev_user()
        _session_id, token, _expires_at = store.create_session(user_id=user.id, ttl_seconds=60)
        session = store.resolve_session(token)
        assert session is not None
        assert session.user.subject == user.subject
    finally:
        store.close()
