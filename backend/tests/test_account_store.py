"""Compatibility checks for the account schema.

`create_all` creates missing tables but never alters an existing one. The first
version of the app had no `last_seen_at` and bound exchange codes to a user.
These tests pin the small startup migration that keeps an existing local or
Render database usable until Alembic lands.
"""

from __future__ import annotations

import sqlite3

from app.accounts.store import AccountStore


def test_store_upgrades_the_first_schema(tmp_path):
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


def test_dev_account_created_under_an_old_subject_moves_to_the_house_subject(tmp_path):
    path = tmp_path / "dev.db"
    store = AccountStore(f"sqlite:///{path}")
    try:
        first = store.find_or_create_dev_user()
        assert first.subject == "house-user"

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE auth_users SET subject = ?, display_name = ? WHERE id = ?",
                ("legacy-subject", "Legacy Name", first.id),
            )

        again = store.find_or_create_dev_user()
        assert again.id == first.id
        assert again.subject == "house-user"
        assert again.display_name == "House Owner"
    finally:
        store.close()


def test_render_postgres_urls_are_mapped_to_the_psycopg_driver():
    from sqlalchemy import create_engine

    from app.accounts.store import normalize_database_url

    assert normalize_database_url("postgres://u:p@db.internal/alexa") == "postgresql+psycopg://u:p@db.internal/alexa"
    assert normalize_database_url("postgresql://u:p@db.internal/alexa") == "postgresql+psycopg://u:p@db.internal/alexa"
    assert normalize_database_url("sqlite:///./data/alexa.db") == "sqlite:///./data/alexa.db"

    # create_engine does not connect, so this checks the driver without a database.
    engine = create_engine(normalize_database_url("postgres://u:p@localhost/alexa"))
    try:
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()
