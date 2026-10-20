"""Tool manifests. Descriptions are part of the product: Alexa+ chooses tools from them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Bounds


class ToolSpec(BaseModel):
    """The manifest contract from STANDARD.md section 2.

    Frozen so a long-running process cannot mutate a manifest under itself. To
    change a tool's behavior, change the code and redeploy.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = "1"
    # Descriptions are tool-selection prompt text for Alexa+. State when to use
    # the tool and, just as important, when not to.
    description: str
    service: str
    scopes: list[str]
    risk: Literal["low", "medium", "high"]
    reversible: bool
    # Tool that undoes this one. Day 3 resolves it through the audit log.
    compensator: str | None = None
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    booleans: list[str] = Field(default_factory=list)
    # Declared ranges and enumerations. rules.py enforces them before an adapter
    # runs; they are part of the public contract, not just documentation.
    bounds: dict[str, Bounds] = Field(default_factory=dict)
    enums: dict[str, list[str]] = Field(default_factory=dict)
    # Presentation-only maps: friendlier field names and spoken range text.
    field_labels: dict[str, str] = Field(default_factory=dict)
    bounds_display: dict[str, str] = Field(default_factory=dict)
    confirmation_template: str | None = None
    # Privacy gate for Day 3: external tools are refused when the user turns off
    # third-party sharing.
    external: bool = False
    # High-risk tools stay disabled unless a current certification report exists.
    certified: bool | None = None

    def manifest(self) -> dict[str, Any]:
        """Public metadata for `tools/list` extras, the console, and certification."""
        payload = self.model_dump(mode="json")
        # These two maps only shape spoken error messages. Clients do not need
        # them, and leaving them out keeps the console payload smaller.
        payload.pop("field_labels", None)
        payload.pop("bounds_display", None)
        return payload
