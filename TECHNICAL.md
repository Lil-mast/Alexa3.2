# Steadyhand: Technical Design

## 1. Architecture

```
Customer voice
     │
     ▼
Alexa+ (LLM: intent interpretation, response generation, UI rendering)
     │  MCP over Streamable HTTP, spec 2025-11-25
     ▼
Steadyhand MCP server (FastAPI, Python)            ← AWS only for the Alexa+ endpoint
     ├── Auth & scope check
     ├── Tool router
     ├── Rules engine (deterministic validation and execution)
     ├── Confirmation service (single-use tokens)
     ├── Audit log (append-only, hash-chained)
     ├── Privacy policy enforcer
     └── Device / service adapters (simulated for the demo)
     │
     ▼
SQLite (dev) / Postgres (deploy) for audit, settings, tokens
     ▲
     │  REST (JSON)
React console (Vite + TypeScript): trace viewer, audit browser, privacy panel, journey runner
```

**Division of responsibility.** The model never receives device credentials and never calls adapters directly. It produces a tool call with parameters. The router validates the call against the tool's schema, then the rules engine validates the values against declared bounds, and only then does an adapter run.

**AWS boundary.** AWS hosts the public MCP endpoint that Alexa+ connects to (for example, behind an Application Load Balancer or App Runner service). All other components run locally or on a non-AWS host. This keeps the AWS surface small and makes the rest of the stack portable. This is an assumption to confirm with the team.

## 2. Latency budget

Alexa+ requires a round trip under 500 ms for MCP calls. Budget:

| Step | Target |
|---|---|
| TLS + routing | 30 ms |
| Auth and scope check | 10 ms |
| Schema and rules validation | 5 ms |
| Adapter call (simulated: 0 ms; real: capped at 300 ms with timeout) | ≤ 300 ms |
| Audit write (async after response is sent where safe) | 0 ms on path |
| Serialization | 10 ms |

Rules: no LLM call anywhere in the server's request path. Keep the process warm (no cold start on the request path). Set adapter timeouts so a slow upstream returns a structured `TIMEOUT` error, not a hang.

## 3. Tool contract

Every tool is declared in a manifest with these fields:

```python
ToolSpec(
    name="thermostat_set",
    description="Set the target temperature for one thermostat zone. Use when the user asks to change heating or cooling.",
    scopes=["home:climate:write"],
    risk="low",            # low | medium | high
    reversible=True,
    compensator="thermostat_restore",   # tool that undoes this one
    params_schema=ThermostatSetParams.model_json_schema(),
    bounds={"target_c": (16, 28)},
    confirmation_template="Set {zone} to {target_c} °C",
)
```

Descriptions are part of the product. Alexa+ uses them to choose tools, so each description states when to use the tool and when not to.

### Risk tiers

| Tier | Examples | Behavior |
|---|---|---|
| low | timers, alarms, lights, media | executes immediately; logged |
| medium | thermostat changes outside a schedule, booking a reversible reservation | returns preview; confirmation token required |
| high | payments, deletions, unlocking doors, changing security settings | returns preview; confirmation token required; server refuses unless the tool is certified (see §8) |

### Confirmation flow

1. Client calls a medium or high tool without a token.
2. Server returns `status: "confirmation_required"`, a preview object (`service`, `tool`, `params`, `effect`, `irreversible: bool`), and a token.
3. Token is valid for 300 seconds and is bound to the exact parameter hash.
4. Client calls the same tool with the token. The server recomputes the hash. If anything changed, the token is rejected.
5. Token is consumed on use. Replay fails with `TOKEN_CONSUMED`.

### Response shape

```json
{
  "status": "ok | confirmation_required | error",
  "speech": "Timer set for ten minutes.",
  "detail": "Timer 'pasta' set for 10:00, ends at 18:42. Stored as timer_7f3.",
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 4}],
  "audit_id": "a_01HZ...",
  "error": null
}
```

`speech` is always present and short. This is the concise mode default. `detail` is optional and only returned when the caller asks for it.

## 4. Rules engine

The rules engine is a pure function of (tool spec, current state, parameters) → (decision, effect). It contains no model calls and no I/O except the adapter invocation after a decision.

Responsibilities:

- Bounds checks against the spec (ranges, enums, required fields).
- Conflict checks (for example, two alarms at the same minute, or a thermostat setpoint already at the requested value, which returns `NO_CHANGE` rather than an error).
- Policy checks (scope, privacy toggles, certification status).
- Compensator lookup for reversible actions.

Rules are data, not code, where possible (YAML files loaded at startup, versioned, and included in every audit entry as `rules_version`). This lets reviewers see exactly which rule approved an action.

## 5. Audit log

Append-only table with a hash chain:

| Column | Type | Notes |
|---|---|---|
| id | ULID | sortable |
| ts | timestamptz | server time |
| user_ref | text | pseudonymous household id |
| tool | text | tool name |
| tool_version | text | from manifest |
| scope_used | text | scope that authorized the call |
| params_hash | text | SHA-256 of canonical JSON params |
| params | json | omitted when retention setting is "minimal" |
| decision | text | executed, previewed, refused, no_change |
| result | text | ok, error code |
| compensator_of | ULID | links an undo to the original action |
| prev_hash | text | hash of previous row |
| row_hash | text | SHA-256 over this row plus prev_hash |

**Verification.** A CLI command (`steadyhand audit verify`) recomputes the chain and reports the first broken link. The console shows a green or red chain status.

**Retention.** A scheduled job deletes rows older than the user's retention setting. Deletion keeps a tombstone row (id, ts, tool, decision) so the chain stays verifiable.

## 6. Rollback

- Each reversible tool declares a `compensator`. Undo calls the compensator with the stored pre-state.
- "Undo that" resolves to the most recent reversible action in the same session. The response names what will be undone and runs under the same risk tier as the original.
- Irreversible tools are flagged `reversible=False`. Their preview states this clearly, and the confirmation text includes "This cannot be undone."

## 7. Privacy model

Stored per user, enforced server-side:

```python
class PrivacySettings(BaseModel):
    retention_days: Literal[0, 7, 30, 90] = 30   # 0 = keep only tombstones
    personalization: bool = True
    microphone_mode: Literal["wake_word", "continuous"] = "wake_word"  # declared, enforced by client
    third_party_sharing: bool = False
```

- `personalization=False`: the server ignores stored preferences during tool selection hints.
- `third_party_sharing=False`: tools with `external=True` in their manifest are refused with `PRIVACY_BLOCKED`.
- `microphone_mode` is declared in the server's privacy manifest so Alexa+ can surface it. The server does not control the microphone.

Every privacy change is itself an audit entry.

## 8. Developer standard

Published as `STANDARD.md` in the repo. Four parts:

**Permission scopes.** Named as `domain:resource:action` (for example, `home:lights:write`). Scopes are granted per user, and each tool declares the minimum it needs. Tokens never carry broad scopes by default.

**Error taxonomy.** A small, stable set of codes so every developer's tool fails the same way:

| Code | Meaning | Alexa+ follow-up |
|---|---|---|
| `INVALID_PARAM` | a value failed validation | ask for the specific field |
| `OUT_OF_BOUNDS` | a value is outside declared bounds | state the allowed range |
| `NOT_FOUND` | a referenced item does not exist | ask which item |
| `AUTH_REQUIRED` | scope missing or token expired | prompt re-link |
| `PRIVACY_BLOCKED` | a privacy setting forbids the action | explain the setting |
| `CONFIRMATION_REQUIRED` | preview needs confirmation | present preview |
| `TOKEN_CONSUMED` / `TOKEN_EXPIRED` | confirmation token unusable | restart the action |
| `UPSTREAM_TIMEOUT` | adapter exceeded its budget | offer to retry |
| `UPSTREAM_ERROR` | adapter failed | say so, do not guess |

**Simulated user journeys.** A journey is a YAML file: a sequence of utterances (or tool calls), expected tool choices, expected status codes, and expected audit entries. The runner executes journeys against a local server and fails on any mismatch. Journeys include happy paths, ambiguous requests, out-of-bounds requests, replayed tokens, and undo flows.

**Certification for high-risk actions.** A tool with `risk="high"` must pass a checklist before the server will enable it in production:

1. Preview names the service and tool exactly.
2. Confirmation token binds to the parameter hash and expires.
3. Refusal path tested with a bad token and a changed parameter.
4. Audit entry written for execution and for refusal.
5. Irreversible status stated in the preview.
6. A journey covering the full flow passes in CI.

The certification runner produces a report; the server reads a `certified: true` flag from the manifest only when the report is present and current.

## 9. Frontend console

React + TypeScript (Vite). Four screens:

- **Trace:** live list of tool calls with service, decision, latency, and audit id.
- **Audit:** searchable log with chain status and an "undo" action where a compensator exists.
- **Privacy:** the four toggles, each with a one-line explanation of its effect.
- **Journeys:** run the simulated journeys and see pass or fail per step.

The console talks to the server over REST (`/api/trace`, `/api/audit`, `/api/privacy`, `/api/journeys`). It is an operator and developer tool, not the customer experience. Customer-facing confirmations are rendered by Alexa+.

## 10. Repository layout

```
steadyhand/
├── README.md
├── TECHNICAL.md
├── STANDARD.md
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, mounts /mcp and /api
│   │   ├── mcp_server.py     # MCP tool registration (Streamable HTTP)
│   │   ├── router.py         # schema validation, scope check
│   │   ├── rules/            # engine.py, rules/*.yaml
│   │   ├── confirm.py        # tokens
│   │   ├── audit.py          # hash-chained log
│   │   ├── privacy.py
│   │   ├── adapters/         # timers.py, lights.py, climate.py, media.py, booking.py (simulated)
│   │   └── tools/            # ToolSpec manifests
│   ├── tests/
│   │   ├── unit/
│   │   └── journeys/         # YAML journeys
│   └── requirements.txt
├── frontend/
│   ├── src/
│   └── package.json
└── certification/
    └── run_certification.py
```

## 11. Build plan (hackathon)

| Block | Scope | Done when |
|---|---|---|
| 1 | MCP server, timers and lights, Streamable HTTP, 401 on unauthenticated calls | Local Inspector lists tools and calls them |
| 2 | Rules engine, bounds, error taxonomy | Out-of-bounds thermostat returns `OUT_OF_BOUNDS` |
| 3 | Confirmation tokens, booking tool (simulated) | Preview, confirm, replay refused |
| 4 | Audit log with hash chain, undo for lights and timers | `audit verify` passes; undo logged and linked |
| 5 | Privacy toggles enforced | Third-party tool refused when toggled off |
| 6 | Journeys and runner, console screens | Three journeys pass in CI |
| 7 | Demo polish, `STANDARD.md`, certification report for booking tool | Demo script runs end to end |

Cut order if time runs short: certification runner first (keep the checklist as a document), then the console's journey screen, then the booking tool. Never cut the rules engine, confirmations, or the audit log, because those are the principles the project is judged on.

## 12. Risks

- **Latency on Alexa+ round trips.** Mitigation: no LLM in the request path, warm process, adapter timeouts. Measure with the Local Inspector before the demo.
- **Alexa+ registration details.** The public docs describe the add-on flow through the `alexa-ai` CLI. Confirm the exact registration steps for a self-hosted server in the track resources before building the deployment.
- **Confirmation rendering is Alexa+'s.** Our preview object must be complete enough for Alexa+ to render. Validate the shape against the Alexa+ UX guidelines.
- **Scope creep.** Mitigation: the cut order above.
- **Device realism.** Adapters are simulated. Say so in the demo and show the adapter boundary as the integration point.