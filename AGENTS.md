# Working on Alexa

This repository is a deterministic MCP server for Alexa+. The model interprets
the user. The server validates the parameters, applies versioned rules, executes
a simulated action, and returns structured speech and a trace. See
`TECHNICAL.md`, `STANDARD.md`, `BUILD_PLAN.md`, and `DECISIONS.md` before changing
a contract.

The project name is **Alexa**. Use `Alexa`, `alexa`, or `ALEXA_` in code, docs,
environment variables, logger names, and client ids.

## First commands

Run from `backend/`:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd backend
uv run python -m app.cli tools
uv run python -m app.cli call timer_set '{"duration_seconds": 600}'
uv run python -m app.cli bench --n 100
```

Checks:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
python3 ../scripts/check_leaks.py --self-test
```

Enable the pre-commit leak scan once per clone:

```bash
git config core.hooksPath .githooks
```

Do not commit unless the user asks. The working tree is often intentionally
uncommitted while a build day is in progress.

## Layout

| Path | Owns |
|---|---|
| `backend/app/main.py` | FastAPI app, `/mcp` mount, REST console API, health, metadata, startup warnings |
| `backend/app/mcp_server.py` | `MCPServer`, tool registration, MCP annotations, per-request principal |
| `backend/app/router.py` | The only execution path: auth, scope, rules, confirmation, adapter, trace, log |
| `backend/app/rules/` | Versioned `rules.yaml`, loader, validation, defaults, display labels |
| `backend/app/tools/` | Tool manifests (`specs.py`) and handlers |
| `backend/app/adapters/` | Simulated device and booking state |
| `backend/app/confirm.py` | Single-use confirmation tokens |
| `backend/app/auth.py` | Static bearer verifier, scopes, 401 challenge, REST dependency |
| `backend/app/models.py` | Wire contract and error taxonomy |
| `backend/tests/` | Unit tests plus a real uvicorn MCP round trip |

## Invariants

- Keep `Router.execute` as the only path from a tool call to an adapter. MCP and
  REST are thin wrappers. Tests call the router directly.
- Auth comes before validation. Do not let an unauthenticated caller learn the
  schema from error messages.
- Scope check comes before execution. A confirmation token never bypasses it.
- Rules own value constraints. `ToolSpec` owns identity, risk, scopes, and the
  confirmation template. `RULES.check_tools(TOOLS)` fails at startup on drift.
- Business errors are tool results with `status: "error"`, not protocol errors.
  Preserve `code`, `field`, `allowed`, and `follow_up`.
- Speech is server-composed and deterministic. Do not add a model call to the
  request path.
- Confirmation tokens are single-use, bound to subject, tool, and parameter
  hash, and consumed only after the adapter succeeds.
- The trace stores a parameter hash, never raw parameters or tokens. `audit_id`
  stays null until the audit log exists.
- Subjects are pseudonymous. A raw `amzn1.` id is refused at token parsing.
- `app.mount("/", mcp_app)` stays last so `/health`, `/api`, `/docs`, and the
  metadata route win.
- Tool titles and hints come from `ToolSpec`. Do not duplicate them in the
  decorator.

## Style

- No em dashes and no en dashes in prose. Use a colon, a comma, or a full stop.
  This is a hard house rule, not a preference.
- Comments explain intent, tradeoffs, and failure modes, not syntax.
- Keep line length at 120. Ruff selects `E`, `F`, `I`, `UP`, `B`, `ASYNC`, `RUF`.
- Prefer small, typed functions and Pydantic models at boundaries.
- New behavior needs a test. A live MCP path needs an HTTP test; a rule needs a
  rules test.

## Security and privacy

- Never commit a real token, deployment URL, AWS account id, Alexa skill id, or
  key. `.env` is ignored; `.env.example` is the shape only.
- The development token `dev-token` is public on purpose. It must be replaced
  before a public deployment. Startup warns when it is not.
- Do not log tokens, raw parameters, or full request bodies. The subject,
  parameter hash, decision, and trace id are enough to debug.
- `book_room` is marked external. The Day 3 privacy gate must refuse it when
  third-party sharing is off.
- The container runs as UID 10001. Do not add root-only files or writable paths
  without a reason.

## Current state

Day 2 is complete: four tools (`timer_set`, `lights_set`, `thermostat_set`,
`book_room`), versioned YAML rules, confirmation tokens, simulated adapters, a
trace buffer, a console API, and 76 tests. Day 1 and Day 2 details are in
`BUILD_LOG.md`.

Day 3 next: hash-chained audit and seeded fixture, `alexa audit verify`, undo
tools, `tell_me_more`, concise mode, and privacy toggles. Day 4: React console,
voice proxy, journeys, deploy, and demo.

Known gaps: no Alexa+ registration or App Runner deployment yet; no OAuth
authorization server; no physical device test; no persistence; no real device
integrations; no license chosen.
