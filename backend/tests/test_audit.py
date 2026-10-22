from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.audit import GENESIS, AuditLog, AuditRow
from app.auth import Principal
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


class Clock:
    """Advanceable clock so retention and timestamps are deterministic."""

    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def _principal(subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(ALL_SCOPES))


def _append(log: AuditLog, **overrides) -> AuditRow:
    fields = {
        "subject": "test-user",
        "tool": "timer_set",
        "tool_version": "1",
        "rules_version": "3",
        "service": "timers",
        "scopes_used": ["home:timers:write"],
        "params_hash": "a" * 64,
        "decision": "executed",
        "status": "ok",
    }
    return log.append(**{**fields, **overrides})


def test_empty_chain_verifies_from_genesis():
    log = AuditLog(seed_path=None)

    report = log.verify()

    assert report.ok is True
    assert report.rows == 0
    assert report.head == GENESIS


def test_appended_rows_link_and_verify():
    log = AuditLog(seed_path=None)
    first = _append(log)
    second = _append(log, tool="lights_set", decision="refused", status="error", error_code="OUT_OF_BOUNDS")

    assert first.prev_hash == GENESIS
    assert second.prev_hash == first.row_hash
    assert first.row_hash != second.row_hash
    assert log.verify().ok is True
    assert log.verify().head == second.row_hash


def test_editing_a_row_breaks_the_chain_at_that_row():
    log = AuditLog(seed_path=None)
    _append(log)
    target = _append(log, decision="refused", status="error", error_code="OUT_OF_BOUNDS")
    _append(log)

    # A mutable store would allow this. The chain makes it detectable instead of
    # silent, which is the only reason to keep it.
    log._rows[1] = target.model_copy(update={"decision": "executed", "error_code": None})

    report = log.verify()

    assert report.ok is False
    assert report.first_bad == target.id
    assert "does not match its own hash" in (report.reason or "")


def test_removing_a_row_breaks_the_next_link():
    log = AuditLog(seed_path=None)
    _append(log)
    _append(log)
    third = _append(log)

    del log._rows[1]

    report = log.verify()

    assert report.ok is False
    assert report.first_bad == third.id
    assert "does not link" in (report.reason or "")


def test_startup_seed_is_deterministic_and_verifies():
    first = AuditLog()
    second = AuditLog()

    assert first.seed_marker is not None
    assert first.seed_marker["rows"] == 3
    assert first.seed_marker["seeded"] is True
    # Fixed timestamps and order mean two boots rebuild the same chain, so a
    # reviewer can verify the fixture independently.
    assert first.verify().head == second.verify().head
    assert first.verify().ok is True


def test_seed_rows_belong_to_the_demo_user_and_are_not_undoable():
    log = AuditLog()

    rows = log.rows_for("demo-user")

    assert len(rows) == 3
    assert {row.decision for row in rows} == {"executed", "previewed", "refused"}
    assert all(row.compensation is None for row in rows)
    # Seeded history is evidence, not a reversible action: the newest executed
    # row is the seeded timer, and it carries no compensation.
    latest = log.last_executed("demo-user")
    assert latest is not None
    assert latest.tool == "timer_set"
    assert latest.compensation is None


def test_retention_tombstones_old_rows_and_keeps_the_chain_intact():
    clock = Clock(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
    log = AuditLog(seed_path=None, now=clock)
    old = _append(log, subject="test-user")
    _append(log, subject="other-user")
    clock.advance(days=10)
    recent = _append(log, subject="test-user", tool="lights_set")

    pruned = log.prune("test-user", retention_days=7)

    assert pruned == 1
    # The tombstone keeps position and hashes, so verification still passes.
    assert log.verify().ok is True
    assert old.id not in {row.id for row in log.rows_for("test-user")}
    assert [row.id for row in log.rows_for("test-user")] == [recent.id]
    # Another subject's rows are untouched.
    assert len(log.rows_for("other-user")) == 1


def test_a_tombstone_keeps_only_the_chain_fields():
    clock = Clock(datetime(2026, 10, 1, tzinfo=UTC))
    log = AuditLog(seed_path=None, now=clock)
    _append(log, subject="test-user", result_ref="timer_1234", compensation={"timer_id": "timer_1234"})
    clock.advance(days=1)
    log.prune("test-user", retention_days=0)

    tombstone = log.snapshot()[0]
    assert tombstone.tombstone is True
    assert tombstone.subject == ""
    assert tombstone.params_hash == ""
    assert tombstone.compensation is None
    assert tombstone.tool == "timer_set"
    assert tombstone.decision == "executed"
    assert log.verify().ok is True


def test_router_audits_executed_previewed_and_refused_calls():
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))
    router = Router(state)
    principal = _principal()

    executed = router.execute("timer_set", {"duration_seconds": 600}, principal)
    previewed = router.execute("book_room", {"date": "2099-01-04"}, principal)
    refused = router.execute("thermostat_set", {"zone": "office", "target_c": 35}, principal)

    assert executed.audit_id == "a_000001"
    assert previewed.audit_id == "a_000002"
    assert refused.audit_id == "a_000003"
    rows = state.audit.rows_for("test-user")
    assert [row.decision for row in rows] == ["executed", "previewed", "refused"]
    assert [row.status for row in rows] == ["ok", "confirmation_required", "error"]
    assert rows[2].error_code == "OUT_OF_BOUNDS"
    assert all(row.rules_version == "3" for row in rows)
    assert all(len(row.params_hash) == 64 for row in rows)
    assert state.audit.verify().ok is True


def test_router_audits_an_unauthenticated_refusal_as_anonymous():
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))

    response = Router(state).execute("timer_set", {"duration_seconds": 60}, None)

    assert response.audit_id is not None
    rows = state.audit.snapshot()
    assert rows[0].subject == "anonymous"
    assert rows[0].decision == "refused"
    assert rows[0].error_code == "AUTH_REQUIRED"


def test_audit_row_holds_no_raw_parameters():
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))
    Router(state).execute(
        "timer_set",
        {"duration_seconds": 600, "label": "pasta water"},
        _principal(),
    )

    row = state.audit.snapshot()[0].model_dump(mode="json")

    assert "pasta water" not in json.dumps(row)
    assert "duration_seconds" not in row
    assert "params" not in row


def test_unknown_tool_is_not_audited():
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))

    Router(state).execute("door_unlock", {"door": "front"}, _principal())

    assert len(state.audit) == 0


def test_audit_requires_a_non_empty_seed_rows_list(tmp_path):
    fixture = tmp_path / "seed.json"
    fixture.write_text(json.dumps({"rows": "not-a-list"}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="rows list"):
        AuditLog(seed_path=fixture)
