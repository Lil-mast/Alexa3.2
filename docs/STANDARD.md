# Alexa Developer Standard

This document defines the interoperability and safety requirements for tools exposed by Alexa's MCP server. It is the contract for tool authors, the server, and the journey and certification runners.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative requirements.

## 1. Trust boundary

The language model interprets requests and proposes tool calls. It MUST NOT receive device credentials or call device and service adapters directly. The server MUST validate every call against its tool schema, permission scope, privacy policy, and deterministic rules before invoking an adapter. An adapter MUST only receive validated, authorized parameters.

Tools SHOULD be deterministic: the same validated inputs and state should produce the same decision and effect. No LLM call may run in the tool execution path.

## 2. Tool manifest

Every exposed tool MUST have a manifest entry containing:

| Field | Requirement |
|---|---|
| `name` | Stable, unique identifier, such as `thermostat_set`. |
| `description` | State when the tool should be used and when it should not. |
| `scopes` | Minimum permission scopes required for the action. |
| `risk` | `low`, `medium`, or `high`. |
| `reversible` | Whether a compensating action can restore the prior state. |
| `compensator` | Required for reversible actions; names the undo tool. |
| `params_schema` | Machine-readable parameter schema used for validation. |
| `bounds` | Declared ranges or enumerations enforced by the rules engine. |
| `confirmation_template` | Human-readable summary used to preview a consequential action. |
| `external` | Whether results are shared with a third-party service; required for privacy enforcement. |
| `certified` | Whether the current high-risk certification report is valid. |

Descriptions are part of the tool-selection interface. They SHOULD be concise and specific, including important exclusions and parameter expectations. A tool MUST request only the scopes necessary for its operation.

## 3. Permission scopes

Scopes use the format `domain:resource:action`, for example `home:lights:write` or `home:climate:write`.

- The server MUST check scopes on every call, including confirmation and undo calls.
- A tool MUST declare its minimum required scopes in its manifest.
- Missing or expired authorization MUST fail with `AUTH_REQUIRED`; the server MUST NOT silently broaden access.
- Grants SHOULD be limited to the user and resource involved in the request.

## 4. Risk and confirmation

| Risk | Examples | Required behavior |
|---|---|---|
| `low` | Timers, alarms, lights, media | Execute after validation and authorization; write an audit entry. |
| `medium` | Schedule exceptions, reversible bookings | Return a preview and require explicit confirmation before execution. |
| `high` | Payments, deletions, unlocking doors, security changes | Require a preview and explicit confirmation; refuse execution unless the tool has current certification. |

A preview MUST identify the service, tool, exact parameters, expected effect, and whether the action is irreversible. The confirmation token MUST be single-use, expire after 300 seconds, and be bound to a canonical hash of the exact parameters and action. On confirmation, the server MUST recompute and compare the hash before executing. Changed parameters, expired tokens, and replayed tokens MUST be rejected.

Confirmation MUST NOT be inferred from the initial request or from a model-generated statement. The client must make the preview and confirmation step clear to the user.

## 5. Response and error contract

Every tool response MUST include a status and a concise `speech` string. `speech` is the sentence to say: it MUST NOT depend on a later call or on client-side composition.

`detail` MAY carry a longer explanation. When a response withholds `detail` because the user prefers concise answers, it MUST set `detail_available=true` so the client knows an explanation exists, and the same text MUST be retrievable through a detail tool such as `tell_me_more`. A response MUST NOT set `detail_available=true` when no text can be returned.

A response SHOULD include a `trace`. Every decision, including a preview and a refusal, MUST return the `audit_id` of the row that records it.

The protocol-level status is one of `ok`, `confirmation_required`, or `error`. The `confirmation_required` status is distinct from an error: it indicates that execution has not yet occurred and a valid confirmation is needed.

| Error code | Meaning | Expected client behavior |
|---|---|---|
| `INVALID_PARAM` | A parameter failed schema or value validation. | Ask about the specific invalid field. |
| `OUT_OF_BOUNDS` | A value is outside the declared range or enumeration. | State the allowed range or choices. |
| `NOT_FOUND` | A referenced item does not exist. | Ask which item the user intended. |
| `AUTH_REQUIRED` | Required scope is missing or authorization expired. | Prompt the user to authorize or reconnect. |
| `PRIVACY_BLOCKED` | A privacy setting forbids the action. | Explain which setting prevented it. |
| `CONFIRMATION_REQUIRED` | A preview must be confirmed before execution. | Present the preview and request confirmation. |
| `TOKEN_CONSUMED` | The confirmation token has already been used. | Start a new action and confirmation flow. |
| `TOKEN_EXPIRED` | The confirmation token has expired. | Start a new action and confirmation flow. |
| `UPSTREAM_TIMEOUT` | An adapter exceeded its time budget. | Report the timeout and offer a retry. |
| `UPSTREAM_ERROR` | An adapter failed. | Report the failure; do not claim success or guess the result. |

Errors MUST be structured and MUST NOT imply that an action succeeded when it did not. The server SHOULD return a specific follow-up rather than asking the user to repeat the whole request.

## 6. Rules and execution

The rules engine MUST validate parameter bounds, relevant state conflicts, authorization, privacy settings, and certification status before an adapter runs. A valid request that would not change state SHOULD return `NO_CHANGE` rather than being treated as an execution failure.

Rules SHOULD be versioned data where practical. The rules version used for a decision MUST be recorded in its audit entry. Adapter calls MUST have bounded timeouts and map failures to the shared error taxonomy.

## 7. Audit and rollback

The server MUST append an audit record for executions and consequential decisions, including previews, refusals, and failed confirmations. Records SHOULD include the user reference, tool and version, scope used, canonical parameter hash, decision, result, timestamp, rules version, and compensator relationship. Raw parameters MAY be omitted under the user's retention setting.

Audit records MUST be append-only and hash-chained. Each row hash covers the row contents and the prior row hash. Verification MUST report the first broken link. Retention cleanup MUST preserve chain verifiability, for example by retaining a tombstone containing the record identifier, timestamp, tool, and decision.

Reversible tools MUST declare a compensator and retain enough pre-action state to invoke it. An undo MUST be a new action with its own authorization and audit entry linked to the original. Undo MUST NOT reach further back than the most recent executed action: if that action cannot be reversed, the server MUST refuse rather than quietly reversing an older one. Irreversible tools MUST be clearly identified in the preview and MUST NOT claim to support undo.

An undo inherits the authorization of the action it reverses: the server MUST check the scopes recorded on the original row before the compensator runs, and MUST NOT accept undo as a way around them. Re-confirming an undo is OPTIONAL when it only reverses an action the user already confirmed; if the server skips the preview, it MUST say so in the tool description and in this standard.

## 8. Privacy settings

Privacy settings are per user and MUST be enforced by the server, not merely communicated as client preferences.

- `retention_days` MUST support the declared values `0`, `7`, `30`, and `90`; `0` retains tombstones only.
- `personalization=false` MUST prevent stored preferences from influencing tool-selection hints or execution.
- `third_party_sharing=false` MUST refuse tools marked `external=true` with `PRIVACY_BLOCKED`.
- `microphone_mode` (`wake_word` or `continuous`) is a declared client-facing setting. The server MUST NOT claim to control microphone behavior it cannot enforce.

Every privacy-setting change MUST be audited.

## 9. Simulated user journeys

A journey is a YAML test case containing an ordered sequence of utterances or tool calls, expected tool choices, response statuses or error codes, and expected audit effects. The runner MUST fail a journey when any expectation differs from the observed result.

The suite SHOULD cover successful actions, ambiguous inputs, invalid and out-of-bounds parameters, missing authorization, privacy refusals, confirmation success, changed parameters, token expiry and replay, adapter failures, and undo flows. Simulated adapters MUST be identified as simulations; they MUST NOT be represented as real device integrations.

## 10. High-risk certification

A high-risk tool MUST be disabled in production until it has a current certification report. The report MUST be tied to the tool manifest version and the test run that produced it. Certification MUST verify all of the following:

1. The preview names the service and tool and states the exact effect and irreversible status.
2. The confirmation token is single-use, expires, and binds to the canonical parameter hash.
3. Bad, expired, replayed, and parameter-mismatched tokens are rejected.
4. Both successful execution and refusal are audited.
5. The full confirmation flow passes as a simulated journey.
6. The tool requests only its declared minimum scopes and honors privacy settings.

The server MUST NOT rely on a manually set `certified` flag alone: it must verify that the certification report is present, current, and matches the active manifest.

## 11. Compatibility

Changes to tool names, parameter schemas, scope requirements, risk tiers, or error meanings can break clients and MUST be treated as contract changes. Implementations SHOULD version tool manifests and keep error codes stable. A compatibility change MUST update this standard, the affected manifest, and the relevant journeys together.
