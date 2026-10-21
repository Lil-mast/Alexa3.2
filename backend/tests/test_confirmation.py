from __future__ import annotations

from app.confirm import ConfirmationService, TokenStatus


class Clock:
    """A hand-cranked clock so expiry tests do not sleep."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _service(ttl_seconds: int = 300) -> tuple[ConfirmationService, Clock]:
    clock = Clock()
    return ConfirmationService(ttl_seconds=ttl_seconds, now=clock), clock


def _issue(service: ConfirmationService, **overrides):
    fields = {
        "subject": "alice",
        "tool": "book_room",
        "params_hash": "a" * 64,
        **overrides,
    }
    return service.issue(**fields)


def test_token_is_single_use():
    service, _ = _service()
    record = _issue(service)

    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.OK
    assert service.consume(record.token) is True
    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.CONSUMED
    # A second consume is refused, so two racing confirmations cannot both win.
    assert service.consume(record.token) is False


def test_token_expires_after_ttl():
    service, clock = _service(ttl_seconds=300)
    record = _issue(service)

    clock.advance(299)
    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.OK
    clock.advance(1)
    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.EXPIRED


def test_consumed_reports_consumed_even_after_expiry():
    # The more useful reason wins: a replay is still a replay after five minutes.
    service, clock = _service(ttl_seconds=300)
    record = _issue(service)
    service.consume(record.token)

    clock.advance(301)
    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.CONSUMED


def test_token_is_bound_to_parameters():
    service, _ = _service()
    record = _issue(service)

    assert service.verify(record.token, subject="alice", tool="book_room", params_hash="b" * 64) is TokenStatus.MISMATCH
    assert (
        service.verify(record.token, subject="alice", tool="lights_set", params_hash="a" * 64) is TokenStatus.MISMATCH
    )


def test_token_is_bound_to_subject():
    service, _ = _service()
    record = _issue(service)

    # Another user's token reads as expired, not "someone else's token".
    assert service.verify(record.token, subject="bob", tool="book_room", params_hash="a" * 64) is TokenStatus.EXPIRED


def test_unknown_token_is_expired():
    service, _ = _service()
    assert service.verify("not-a-token", subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.EXPIRED


def test_pending_table_is_bounded():
    service = ConfirmationService(ttl_seconds=300, max_pending=2)
    first = _issue(service, params_hash="a" * 64)
    _issue(service, params_hash="b" * 64)
    third = _issue(service, params_hash="c" * 64)

    # The oldest pending token is evicted rather than growing memory forever.
    assert service.pending_count() == 2
    assert service.verify(first.token, subject="alice", tool="book_room", params_hash="a" * 64) is TokenStatus.EXPIRED
    assert service.verify(third.token, subject="alice", tool="book_room", params_hash="c" * 64) is TokenStatus.OK
