"""Append-only, hash-chained audit log.

Every decision the router makes appends one row: executed, previewed, refused,
or no_change. Each row carries the hash of the row before it, so removing,
reordering, or editing a row breaks the chain and `verify()` reports the first
broken link by id.

The chain is deliberately separate from the trace ring buffer. The trace drops
old entries and is a debugging view; this log is the record. It lives in memory
and is seeded from `audit_seed.json` at startup so a redeploy reads
as an intentional reset rather than lost data (BUILD_PLAN.md section 4).

What a row stores, and what it refuses to store:

- the subject pseudonym, tool, tool version, rules version, and service
- the scopes the action relied on
- the parameter hash, never the raw parameters
- the decision, status, and error code
- the minimal inverse needed to compensate the action, for undo
- `compensator_of`, which links an undo row to the action it reversed

The inverse is device state, not user speech: a light that was off at 40 percent
or a thermostat that was at 21 degrees. Undo needs it after a restart, and it is
the reason `compensation` is allowed here and not in the trace.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.canonical import canonical_json, sha256_hex

# The hash before the first row. Any fixed value works as long as every verifier
# agrees on it; 64 zeroes are easy to recognise in a report.
GENESIS = "0" * 64

# The fields that are hashed, in a fixed order. `prev_hash` and `row_hash` are
# not part of their own payload: the previous hash is concatenated after it.
CANONICAL_FIELDS: tuple[str, ...] = (
    "id",
    "seq",
    "ts",
    "subject",
    "tool",
    "tool_version",
    "rules_version",
    "service",
    "scopes_used",
    "params_hash",
    "decision",
    "status",
    "error_code",
    "compensator_of",
    "result_ref",
    "compensation",
    "tombstone",
)

SEED_PATH = Path(__file__).with_name("audit_seed.json")

Decision = Literal["executed", "previewed", "refused", "no_change"]
Status = Literal["ok", "confirmation_required", "error"]


class AuditRow(BaseModel):
    """One audit entry. Frozen to stop reassignment, and every field is covered
    by `row_hash`, so even an in-place edit to a list or dict is caught by
    `verify()`.
    """

    # extra="forbid" makes a seed file with a typo fail at startup instead of
    # silently dropping the field, which would change the seeded hashes.
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    seq: int
    ts: str
    subject: str
    tool: str
    tool_version: str
    rules_version: str
    service: str
    scopes_used: list[str]
    params_hash: str
    decision: Decision
    status: Status
    error_code: str | None = None
    # The audit id this row compensates, set only by an undo tool.
    compensator_of: str | None = None
    # A stable adapter reference such as `timer_7f3a` or `booking_1c2d`.
    result_ref: str | None = None
    # The minimal previous state needed to reverse the action.
    compensation: dict[str, Any] | None = None
    # True once retention blanked the row. The hashes stay, so the chain links.
    tombstone: bool = False
    prev_hash: str
    row_hash: str


class AuditReport(BaseModel):
    ok: bool
    rows: int
    head: str
    first_bad: str | None = None
    reason: str | None = None


def _payload(row: AuditRow) -> dict[str, Any]:
    return {name: getattr(row, name) for name in CANONICAL_FIELDS}


def chain_hash(row: AuditRow, prev_hash: str) -> str:
    """SHA-256(canonical_json(row_fields) + prev_hash) from BUILD_PLAN.md."""
    return sha256_hex(canonical_json(_payload(row)) + prev_hash)


class AuditLog:
    """In-memory append-only chain with an injectable clock.

    Unbounded on purpose: retention, not a ring buffer, decides how
    long a row stays. A production store would be a table with the same columns
    and the same hash rule.
    """

    def __init__(
        self,
        *,
        seed_path: Path | None = SEED_PATH,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._rows: list[AuditRow] = []
        self._by_id: dict[str, AuditRow] = {}
        self._seed_marker: dict[str, Any] | None = None
        if seed_path is not None and Path(seed_path).is_file():
            self._seed(Path(seed_path))

    @property
    def seed_marker(self) -> dict[str, Any] | None:
        """Present after startup seeding, so a reset is visible, not silent."""
        return self._seed_marker

    def __len__(self) -> int:
        return len(self._rows)

    def append(
        self,
        *,
        subject: str,
        tool: str,
        tool_version: str,
        rules_version: str,
        service: str,
        scopes_used: Iterable[str],
        params_hash: str,
        decision: Decision,
        status: Status,
        error_code: str | None = None,
        compensator_of: str | None = None,
        result_ref: str | None = None,
        compensation: dict[str, Any] | None = None,
    ) -> AuditRow:
        return self._append_row(
            ts=self._now().isoformat(timespec="milliseconds"),
            subject=subject,
            tool=tool,
            tool_version=tool_version,
            rules_version=rules_version,
            service=service,
            scopes_used=list(scopes_used),
            params_hash=params_hash,
            decision=decision,
            status=status,
            error_code=error_code,
            compensator_of=compensator_of,
            result_ref=result_ref,
            compensation=compensation,
        )

    def get(self, audit_id: str) -> AuditRow | None:
        return self._by_id.get(audit_id)

    def rows_for(self, subject: str) -> list[AuditRow]:
        """Oldest first. Tombstones are omitted: they exist to hold the chain."""
        return [row for row in self._rows if row.subject == subject and not row.tombstone]

    def snapshot(self, *, limit: int | None = None) -> list[AuditRow]:
        """Newest first for the console."""
        rows = list(reversed(self._rows))
        return rows if limit is None else rows[:limit]

    def compensated_ids(self) -> set[str]:
        """Audit ids that an undo row already points at.

        Undo history is derived from the log itself rather than a mutable flag on
        the original row. Editing a row would break the chain, so the link lives
        on the newer row.
        """
        return {row.compensator_of for row in self._rows if row.compensator_of is not None}

    def last_executed(self, subject: str) -> AuditRow | None:
        """Newest row for this subject where an action actually ran.

        Reads report `no_change`, and previews and refusals never reached an
        adapter, so all three are skipped. The caller decides whether the row is
        reversible; this method only answers "what did the user just do".
        """
        for row in reversed(self._rows):
            if row.subject != subject or row.tombstone:
                continue
            if row.decision == "executed":
                return row
        return None

    def prune(self, subject: str, retention_days: int) -> int:
        """Blank rows older than the user's retention window.

        The tombstone keeps the id, timestamp, tool, decision, and both hashes.
        Everything that identifies the request or the user is gone. A tombstone
        cannot be recomputed from its contents, so `verify()` checks its link to
        the previous row and then continues from its stored hash.
        """
        cutoff = self._now() - timedelta(days=retention_days)
        pruned = 0
        for index, row in enumerate(self._rows):
            if row.tombstone or row.subject != subject:
                continue
            if datetime.fromisoformat(row.ts) >= cutoff:
                continue
            # Both hashes are kept as they were, so the links on either side
            # still point at a value that never changed.
            tombstone = AuditRow(
                id=row.id,
                seq=row.seq,
                ts=row.ts,
                subject="",
                tool=row.tool,
                tool_version="",
                rules_version="",
                service="",
                scopes_used=[],
                params_hash="",
                decision=row.decision,
                status=row.status,
                prev_hash=row.prev_hash,
                row_hash=row.row_hash,
                tombstone=True,
            )
            self._rows[index] = tombstone
            self._by_id[row.id] = tombstone
            pruned += 1
        return pruned

    def verify(self) -> AuditReport:
        """Walk the chain and report the first row that does not hold up."""
        previous = GENESIS
        for row in self._rows:
            if row.prev_hash != previous:
                return AuditReport(
                    ok=False,
                    rows=len(self._rows),
                    head=previous,
                    first_bad=row.id,
                    reason=f"row {row.id} does not link to the row before it",
                )
            if not row.tombstone and chain_hash(row, previous) != row.row_hash:
                return AuditReport(
                    ok=False,
                    rows=len(self._rows),
                    head=previous,
                    first_bad=row.id,
                    reason=f"row {row.id} does not match its own hash",
                )
            previous = row.row_hash
        return AuditReport(ok=True, rows=len(self._rows), head=previous)

    def _append_row(self, *, ts: str, **fields: Any) -> AuditRow:
        seq = len(self._rows) + 1
        prev_hash = self._rows[-1].row_hash if self._rows else GENESIS
        draft = AuditRow(id=f"a_{seq:06d}", seq=seq, ts=ts, prev_hash=prev_hash, row_hash=GENESIS, **fields)
        # The draft's placeholder row_hash is not part of the payload, so it
        # cannot influence the real hash.
        row = draft.model_copy(update={"row_hash": chain_hash(draft, prev_hash)})
        self._rows.append(row)
        self._by_id[row.id] = row
        return row

    def _seed(self, path: Path) -> None:
        """Load the fixture, then let `_append_row` compute the hashes.

        Fixing the timestamps and order in the file makes the seeded chain
        byte-for-byte reproducible, so a reviewer can verify it independently.
        A malformed fixture is a startup failure, not a silent empty log.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read audit seed {path}") from exc
        rows = raw.get("rows") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"audit seed {path} must contain a rows list")
        for index, entry in enumerate(rows, start=1):
            if not isinstance(entry, dict):
                raise RuntimeError(f"audit seed {path} row {index} is not an object")
            try:
                self._append_row(**entry)
            except (TypeError, ValidationError) as exc:
                raise RuntimeError(f"audit seed {path} row {index} is invalid: {exc}") from exc
        self._seed_marker = {
            "fixture": path.name,
            "rows": len(rows),
            "seeded": True,
        }


__all__ = [
    "CANONICAL_FIELDS",
    "GENESIS",
    "SEED_PATH",
    "AuditLog",
    "AuditReport",
    "AuditRow",
    "chain_hash",
]
