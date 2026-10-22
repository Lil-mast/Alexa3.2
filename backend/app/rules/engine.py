"""Versioned, data-driven parameter rules.

`rules.yaml` beside this module is the reviewed source of truth for what a tool
accepts. Code owns identity, risk, and scopes; the rules own value constraints,
because a reviewer should be able to read the rules without reading Python.

The engine is a pure function of (tool, parameters). It has no I/O after the
YAML is loaded at import time and makes no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models import ErrorCode, RuleViolation, ToolError
from app.speech import human_date, human_time

if TYPE_CHECKING:
    # Imported for typing only. A runtime import would pull in app.tools, which
    # imports app.state, which imports this module: a real cycle at startup.
    from app.tools.specs import ToolSpec

RULES_PATH = Path(__file__).with_name("rules.yaml")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["integer", "number", "string", "boolean"]
    label: str | None = None
    # int | float keeps whole-number YAML values as ints, so `allowed` stays a
    # list of integers on the wire.
    min: int | float | None = None
    max: int | float | None = None
    # Enum values may be strings or integers: `privacy_set.retention_days` is a
    # closed set of day counts, not a numeric range.
    enum: list[str | int] | None = None
    # Spoken names for enum values, used in errors and previews. Never say
    # "living_room" or "oak" to a user when a nicer name is declared.
    enum_labels: dict[str, str] = Field(default_factory=dict)
    max_length: int | None = None
    format: Literal["date", "time"] | None = None
    # A date must not be before the server's current UTC date. This is a rule,
    # so a past date is refused at preview time, before a token is issued.
    not_past: bool = False
    # Spoken range text, for example "between 16 and 28 degrees Celsius".
    display: str | None = None
    # A default is part of the effective action, so it is applied before the
    # parameter hash and shown in the confirmation preview.
    default: Any = None

    @property
    def has_default(self) -> bool:
        # None is a legitimate value in general, so presence is what matters,
        # not truthiness.
        return "default" in self.model_fields_set

    def label_for(self, field: str) -> str:
        return self.label or field.replace("_", " ").capitalize()


class ToolRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: dict[str, FieldRule] = Field(default_factory=dict)


class ConfirmationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ttl_seconds: int = 300


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    confirmation: ConfirmationPolicy = Field(default_factory=ConfirmationPolicy)
    tools: dict[str, ToolRules] = Field(default_factory=dict)

    def for_tool(self, name: str) -> ToolRules:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise LookupError(f"rules.yaml has no entry for tool {name!r}") from exc

    def check_tools(self, specs: Iterable[ToolSpec]) -> None:
        """Fail at startup rather than on the first call if the files drift.

        Every declared parameter needs a rule, every rule needs a declared
        parameter, and every tool entry needs a registered tool. One check
        catches a typo in the YAML and a field added without constraints.
        """
        specs = list(specs)
        names = {spec.name for spec in specs}
        if extra_tools := sorted(set(self.tools) - names):
            raise LookupError(f"rules.yaml declares unknown tools: {extra_tools}")
        for spec in specs:
            tool = self.for_tool(spec.name)
            declared = set(tool.fields)
            listed = set(spec.required) | set(spec.optional)
            if missing := sorted(listed - declared):
                raise LookupError(f"rules.yaml is missing rules for {spec.name}: {missing}")
            if extra := sorted(declared - listed):
                raise LookupError(f"rules.yaml declares unknown fields for {spec.name}: {extra}")

    def display_params(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Resolve enum labels and human-friendly dates and times for a preview."""
        fields = self.for_tool(name).fields
        rendered: dict[str, Any] = {}
        for field, value in params.items():
            rule = fields.get(field)
            if rule is None:
                rendered[field] = value
            elif isinstance(value, str) and value in rule.enum_labels:
                rendered[field] = rule.enum_labels[value]
            elif rule.format == "date" and isinstance(value, str):
                rendered[field] = human_date(value)
            elif rule.format == "time" and isinstance(value, str):
                rendered[field] = human_time(value)
            else:
                rendered[field] = value
        return rendered


@lru_cache(maxsize=8)
def load_rules(path: str | Path = RULES_PATH) -> RuleSet:
    """Read and validate one rules file. Cached, so startup reads it once."""
    file = Path(path)
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"cannot read rules file {file}") from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(f"rules file {file} is not valid YAML") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"rules file {file} must contain a mapping")
    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"rules file {file} is invalid: {exc}") from exc


RULES = load_rules()
RULES_VERSION = RULES.version


def _invalid(field: str, message: str, *, follow_up: str | None = None) -> RuleViolation:
    return RuleViolation(ToolError.of(ErrorCode.INVALID_PARAM, message, field=field, follow_up=follow_up))


def _out_of_bounds(
    field: str,
    message: str,
    *,
    allowed: list[int | float | str] | None = None,
) -> RuleViolation:
    return RuleViolation(ToolError.of(ErrorCode.OUT_OF_BOUNDS, message, field=field, allowed=allowed))


def _check_type(rule: FieldRule, field: str, value: Any) -> None:
    label = rule.label_for(field)
    # bool is a subclass of int in Python. Reject it explicitly, or True would
    # pass as a temperature of 1 degree.
    if rule.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(field, f"{label} must be a whole number.")
    elif rule.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _invalid(field, f"{label} must be a number.")
    elif rule.type == "string":
        if not isinstance(value, str):
            raise _invalid(field, f"{label} must be text.")
    elif rule.type == "boolean" and not isinstance(value, bool):
        raise _invalid(field, f"{label} must be true or false.")


def _check_value(rule: FieldRule, field: str, value: Any) -> None:
    label = rule.label_for(field)
    _check_type(rule, field, value)

    # Enumerations before numeric bounds: a bad room should get a room message,
    # not a generic range message. A declared `display` wins, so a closed set
    # such as retention days can read as a sentence instead of a list.
    if rule.enum is not None and value not in rule.enum:
        if rule.display:
            message = f"{label} must be {rule.display}"
        else:
            spoken = ", ".join(rule.enum_labels.get(str(choice), str(choice).replace("_", " ")) for choice in rule.enum)
            message = f"{label} must be one of: {spoken}."
        raise _out_of_bounds(field, message, allowed=list(rule.enum))

    if rule.type in {"integer", "number"}:
        bounds = [bound for bound in (rule.min, rule.max) if bound is not None]
        if rule.min is not None and value < rule.min:
            message = f"{label} must be {rule.display}" if rule.display else f"{label} must be at least {rule.min}."
            raise _out_of_bounds(field, message, allowed=bounds)
        if rule.max is not None and value > rule.max:
            message = f"{label} must be {rule.display}" if rule.display else f"{label} must be at most {rule.max}."
            raise _out_of_bounds(field, message, allowed=bounds)

    if rule.format == "date" and isinstance(value, str):
        if not DATE_RE.match(value):
            raise _invalid(field, f"{label} must be a date in YYYY-MM-DD format.")
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise _invalid(field, f"{label} must be a real calendar date.") from exc
        if rule.not_past and parsed_date < datetime.now(UTC).date():
            raise _invalid(field, f"{label} must be today or later.")

    if rule.format == "time" and isinstance(value, str):
        if not TIME_RE.match(value):
            raise _invalid(field, f"{label} must be a time in 24-hour HH:MM format.")
        try:
            time.fromisoformat(value)
        except ValueError as exc:
            raise _invalid(field, f"{label} must be a real time of day.") from exc

    if rule.max_length is not None and isinstance(value, str) and len(value) > rule.max_length:
        raise _invalid(field, f"{label} must be {rule.max_length} characters or fewer.")


def validate_params(
    spec: ToolSpec,
    params: dict[str, Any],
    rules: RuleSet | None = None,
) -> dict[str, Any]:
    """Return normalised parameters or raise RuleViolation. Pure function."""
    rule_set = rules or RULES
    tool = rule_set.for_tool(spec.name)

    # An explicit null is the same as an omitted optional field. Normalising once
    # here keeps every later check simple and makes the parameter hash stable.
    clean = {key: value for key, value in params.items() if value is not None}

    # Reject unknown fields before anything else. A typo such as "minutes" should
    # fail loudly instead of being ignored while duration_seconds is missing.
    allowed = set(spec.required) | set(spec.optional) | set(tool.fields)
    for field in clean:
        if field not in allowed:
            matching = tool.fields.get(field)
            label = matching.label_for(field) if matching else field.replace("_", " ").capitalize()
            raise _invalid(field, f"{label} is not a parameter of {spec.name}.")

    # Presence next, because every later check assumes the field can be read.
    for field in spec.required:
        if field not in clean:
            raise _invalid(field, f"{tool.fields[field].label_for(field)} is required.")

    # Defaults are part of the effective action. Apply them before validation so
    # a malformed default fails here, and before hashing so the preview and the
    # confirmation describe the same request.
    for field in spec.optional:
        rule = tool.fields[field]
        if field not in clean and rule.has_default:
            clean[field] = rule.default

    # YAML order is human order: the first failing field is the one to ask about.
    for field, rule in tool.fields.items():
        if field in clean:
            _check_value(rule, field, clean[field])

    return clean


__all__ = [
    "RULES",
    "RULES_PATH",
    "RULES_VERSION",
    "ConfirmationPolicy",
    "FieldRule",
    "RuleSet",
    "ToolRules",
    "load_rules",
    "validate_params",
]
