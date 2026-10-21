"""Tool manifests. Descriptions are part of the product: Alexa+ chooses tools from them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolSpec(BaseModel):
    """The manifest contract from STANDARD.md section 2.

    Frozen so a long-running process cannot mutate a manifest under itself. To
    change a tool's behavior, change the code and redeploy.

    Value constraints (types, bounds, enums, defaults) live in the versioned
    `app/rules/rules.yaml`, not here. This object says what the tool is and who
    may call it; the rules file says which values are acceptable.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    # Human-readable title for clients that render a tool picker. Kept beside
    # the name so the MCP annotation and the console manifest cannot drift.
    title: str
    version: str = "1"
    # Descriptions are tool-selection prompt text for Alexa+. State when to use
    # the tool and, just as important, when not to.
    description: str
    service: str
    scopes: list[str]
    risk: Literal["low", "medium", "high"]
    reversible: bool
    # True when repeating the same call with the same parameters leaves the
    # same state. MCP clients use this hint when deciding whether a retry is
    # safe after a timeout.
    idempotent: bool = False
    # Tool that undoes this one. Day 3 resolves it through the audit log.
    compensator: str | None = None
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    confirmation_template: str | None = None
    # Privacy gate for Day 3: external tools are refused when the user turns off
    # third-party sharing.
    external: bool = False
    # High-risk tools stay disabled unless a current certification report exists.
    certified: bool | None = None

    def manifest(self) -> dict[str, Any]:
        """Public metadata for `tools/list` extras, the console, and certification."""
        return self.model_dump(mode="json")
