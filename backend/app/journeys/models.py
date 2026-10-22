"""Journey schema: a reviewed sequence of utterances and expected outcomes.

A journey is data, not code. It names the sentence, the tool the deterministic
parser should choose, the status the router should return, and the audit decision
that should follow. The runner compares all of them and fails on the first
mismatch, which is what makes these claims testable.

`extra="forbid"` is deliberate. A typo such as `expected:` instead of `expect:`
would otherwise leave a step with no assertions and pass silently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JourneyStatus = Literal["ok", "confirmation_required", "error", "clarification", "cancelled"]
AuditDecision = Literal["executed", "previewed", "refused", "no_change"]


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    status: JourneyStatus | None = None
    speech: str | None = None
    error_code: str | None = None
    audit_decision: AuditDecision | None = None
    detail_available: bool | None = None
    pending: bool | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    say: str = Field(min_length=1, max_length=500)
    expect: Expectation = Field(default_factory=Expectation)


class Journey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=80)
    description: str = ""
    steps: list[Step] = Field(min_length=1)


class StepResult(BaseModel):
    index: int
    say: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    tool: str | None = None
    status: str
    speech: str
    error_code: str | None = None
    audit_id: str | None = None
    audit_decision: str | None = None


class JourneyResult(BaseModel):
    name: str
    title: str
    passed: bool
    steps: list[StepResult]
    audit_ok: bool
    audit_rows: int
    notes: list[str] = Field(default_factory=list)


__all__ = ["Expectation", "Journey", "JourneyResult", "Step", "StepResult"]
