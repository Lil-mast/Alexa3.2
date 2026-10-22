from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import AuditLog
from app.auth import Principal
from app.models import ErrorCode
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


class Clock:
    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def _setup(now=None) -> tuple[Router, AppState]:
    state = AppState(
        settings=make_settings(),
        audit=AuditLog(seed_path=None, now=now),
    )
    return Router(state), state


def _principal(subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(ALL_SCOPES))


def _booking_date(days: int = 2) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def test_third_party_sharing_off_blocks_booking():
    router, state = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute("book_room", {"date": _booking_date()}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.PRIVACY_BLOCKED
    assert "third-party sharing" in response.error.message
    # Refused before a preview, so no token was issued and nothing was booked.
    assert response.preview is None
    assert response.confirmation_token is None
    assert state.bookings.list_for("test-user") == []
    assert response.trace[0].decision == "refused"
    row = state.audit.get(response.audit_id or "")
    assert row is not None
    assert row.error_code == "PRIVACY_BLOCKED"


def test_sharing_off_does_not_block_local_tools():
    router, _ = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute("lights_set", {"room": "office", "on": True}, _principal())

    assert response.status == "ok"
    assert response.speech == "Office lights on."


def test_privacy_get_reports_the_current_settings():
    router, _ = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute("privacy_get", {}, _principal())

    assert response.status == "ok"
    assert "Third-party sharing is off" in response.speech
    assert "30 days" in response.speech
    # A read changes nothing, so it is not an undo candidate.
    assert response.trace[0].decision == "no_change"


def test_every_privacy_change_is_audited():
    router, state = _setup()

    response = router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    row = state.audit.get(response.audit_id or "")
    assert row is not None
    assert row.tool == "privacy_set"
    assert row.decision == "executed"
    assert row.scopes_used == ["privacy:settings:write"]


def test_privacy_set_needs_at_least_one_field():
    router, _ = _setup()

    response = router.execute("privacy_set", {}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.INVALID_PARAM
    assert response.error.message == "Say which privacy setting to change."


def test_invalid_retention_is_out_of_bounds():
    router, _ = _setup()

    response = router.execute("privacy_set", {"retention_days": 1}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "0, 7, 30, or 90 days" in response.error.message
    assert response.error.allowed == [0, 7, 30, 90]


def test_invalid_microphone_mode_is_out_of_bounds():
    router, _ = _setup()

    response = router.execute("privacy_set", {"microphone_mode": "always"}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.OUT_OF_BOUNDS
    assert response.error.field == "microphone_mode"


def test_retention_days_prunes_older_rows_for_that_subject_only():
    clock = Clock(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))
    router, state = _setup(now=clock)
    router.execute("timer_set", {"duration_seconds": 60}, _principal())
    router.execute("lights_set", {"room": "office", "on": True}, _principal("other-user"))
    clock.advance(days=10)

    response = router.execute("privacy_set", {"retention_days": 7}, _principal())

    assert response.status == "ok"
    assert state.audit.verify().ok is True
    remaining = [row.tool for row in state.audit.rows_for("test-user")]
    assert remaining == ["privacy_set"]
    # A different subject keeps their rows.
    assert [row.tool for row in state.audit.rows_for("other-user")] == ["lights_set"]


def test_retention_zero_keeps_only_the_change_itself():
    clock = Clock(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))
    router, state = _setup(now=clock)
    router.execute("timer_set", {"duration_seconds": 60}, _principal())
    clock.advance(minutes=1)

    router.execute("privacy_set", {"retention_days": 0}, _principal())

    assert [row.tool for row in state.audit.rows_for("test-user")] == ["privacy_set"]
    assert state.audit.verify().ok is True


def test_settings_are_per_user():
    router, _ = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal("alice"))

    alice = router.execute("book_room", {"date": _booking_date()}, _principal("alice"))
    bob = router.execute("book_room", {"date": _booking_date()}, _principal("bob"))

    assert alice.error is not None
    assert alice.error.code is ErrorCode.PRIVACY_BLOCKED
    assert bob.status == "confirmation_required"


def test_multi_field_change_is_one_audited_call():
    router, state = _setup()

    response = router.execute(
        "privacy_set",
        {"third_party_sharing": False, "concise_mode": False},
        _principal(),
    )

    assert response.speech == "Updated 2 privacy settings."
    assert len(state.audit.rows_for("test-user")) == 1


def test_setting_the_same_value_is_no_change():
    router, state = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    assert response.status == "ok"
    assert response.speech == "Those settings are already in place."
    assert response.trace[0].decision == "no_change"
    assert [row.decision for row in state.audit.rows_for("test-user")] == ["executed", "no_change"]


def test_a_partly_redundant_change_reports_only_what_changed():
    router, _ = _setup()
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute(
        "privacy_set",
        {"third_party_sharing": False, "concise_mode": False},
        _principal(),
    )

    assert response.speech == "Concise mode is off. I will include details."
    assert "Third-party sharing" not in (response.detail or "")
