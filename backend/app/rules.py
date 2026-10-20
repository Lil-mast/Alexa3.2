"""Deterministic parameter validation.

Day 1 covers required fields, types, enumerations, and numeric bounds. Day 2
turns this module into the versioned YAML rules engine; the decisions and error
codes below are already the ones the tools return to Alexa+.
"""

from __future__ import annotations

from typing import Any

from app.models import ErrorCode, RuleViolation, ToolError
from app.tools.specs import ToolSpec

RULES_VERSION = "1"
"""Bumped when a rule changes. Day 3 records this string in each audit entry."""


def field_label(spec: ToolSpec, field: str) -> str:
    # Spoken messages use a friendly label; the wire uses the field name.
    return spec.field_labels.get(field, field.replace("_", " ").capitalize())


def _invalid(spec: ToolSpec, field: str, message: str) -> RuleViolation:
    return RuleViolation(ToolError.of(ErrorCode.INVALID_PARAM, message, field=field))


def validate_params(spec: ToolSpec, params: dict[str, Any]) -> dict[str, Any]:
    """Return normalised parameters or raise RuleViolation. Pure function."""
    # An explicit null is the same as an omitted optional field. Normalising once
    # here keeps every later check simple and makes the parameter hash stable.
    clean = {key: value for key, value in params.items() if value is not None}

    # Reject unknown fields before anything else. A typo such as "minutes" should
    # fail loudly instead of being ignored while duration_seconds is missing.
    allowed_fields = set(spec.required) | set(spec.optional) | set(spec.bounds) | set(spec.enums)
    for field in clean:
        if field not in allowed_fields:
            raise _invalid(spec, field, f"{field_label(spec, field)} is not a parameter of {spec.name}.")

    # Presence next, because every later check assumes the field can be read.
    for field in spec.required:
        if field not in clean:
            raise _invalid(spec, field, f"{field_label(spec, field)} is required.")

    # Enumerations before numeric bounds: a bad room should get a room message,
    # not a generic range message.
    for field, choices in spec.enums.items():
        if field in clean and clean[field] not in choices:
            spoken = ", ".join(choice.replace("_", " ") for choice in choices)
            raise RuleViolation(
                ToolError.of(
                    ErrorCode.OUT_OF_BOUNDS,
                    f"{field_label(spec, field)} must be one of: {spoken}.",
                    field=field,
                    allowed=list(choices),
                )
            )

    for field, bound in spec.bounds.items():
        if field not in clean:
            continue
        value = clean[field]
        # bool is a subclass of int in Python. Reject it explicitly, otherwise
        # True would pass as a duration of 1 second.
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(spec, field, f"{field_label(spec, field)} must be a whole number.")
        if not bound.min <= value <= bound.max:
            # bounds_display lets a manifest say "between 1 second and 24 hours"
            # for speech while the wire keeps the numeric min and max.
            display = spec.bounds_display.get(field)
            message = (
                f"{field_label(spec, field)} must be {display}."
                if display
                else f"{field_label(spec, field)} must be between {bound.min} and {bound.max}."
            )
            raise RuleViolation(
                ToolError.of(
                    ErrorCode.OUT_OF_BOUNDS,
                    message,
                    field=field,
                    allowed=[bound.min, bound.max],
                )
            )

    for field in spec.booleans:
        if field in clean and not isinstance(clean[field], bool):
            raise _invalid(spec, field, f"{field_label(spec, field)} must be true or false.")

    # Optional fields are text unless the manifest already typed them above.
    for field in spec.optional:
        if field in spec.bounds or field in spec.enums or field in spec.booleans:
            continue
        if field in clean and not isinstance(clean[field], str):
            raise _invalid(spec, field, f"{field_label(spec, field)} must be text.")

    # Bound free text so a runaway model cannot fill speech or logs with a
    # kilobyte of label. The limit is per manifest, not per adapter.
    label = clean.get("label")
    if isinstance(label, str) and len(label) > 64:
        raise _invalid(spec, "label", "Label must be 64 characters or fewer.")

    return clean


__all__ = ["RULES_VERSION", "validate_params"]
