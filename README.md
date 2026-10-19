# Alexa 3.5

**A deterministic rules and audit layer for Alexa+ agents.**

Steadyhand is a self-hosted MCP server that lets Alexa+ control real things (timers, alarms, lights, thermostats, media) and take consequential actions (bookings, payments, deletions) without letting the language model touch device state directly. The model interprets what the user meant. Rules decide what happens. Every action is previewed, confirmed when risky, logged, and reversible where possible.

## The problem

Voice assistants fail in two opposite ways. Simple commands become unreliable when a model is asked to do work a rule should do: a timer set to "ten minutes" should be exactly ten minutes every time. Consequential actions become unsafe when a misheard word triggers a purchase or deletes something with no record of who or what caused it.

Steadyhand separates those two concerns. The LLM handles ambiguity in language. Deterministic code handles state changes.

## What it does

**Deterministic actions.** Timers, alarms, lighting, thermostats, and media controls run through a rules engine. The model picks a tool and parameters. The engine validates them against explicit bounds (for example, thermostat setpoints between 16 and 28 °C) and applies the change. The same input always produces the same result.

**Confirmations before consequential actions.** Every tool declares a risk tier. Low-risk actions run immediately. Medium and high-risk actions return a structured preview naming the service, the tool, the exact parameters, and the expected effect. The server issues a single-use confirmation token that expires after five minutes. Nothing executes until a second call presents that token.

**Concise mode.** Responses default to terse, one-sentence answers. A `detail` flag in the tool response carries the longer explanation, and Alexa+ can offer it as a follow-up ("want the details?").

**Rollback and audit.** Every tool call is written to an append-only log with a hash chain, so tampering is detectable. Each entry records the tool name, the caller's scope, the parameters, the result, and the compensating action if one exists. Reversible actions (lights, thermostat, timers) expose an undo tool. Irreversible actions (deletions, payments) are marked as such before confirmation.

**Visible tool use.** Each response includes a trace of the tools called, which service each one touched, and whether it succeeded. The Steadyhand console shows the same trace so developers and reviewers can see exactly what happened.

**Privacy controls.** Four toggles, each stored per user and enforced by the server, not by convention: retention (how long audit entries and transcripts are kept), personalization (whether preferences are used), microphone behavior (wake-word only versus continuous, passed through as a declared requirement), and third-party sharing (whether tool results may leave the household's services).

**Developer standard.** Steadyhand ships as a reference implementation of an MCP developer standard: permission scopes per tool, a shared error taxonomy, simulated user journeys for testing, and a certification checklist that high-risk tools must pass before submission.

## Quick start

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend console
cd frontend
npm install
npm run dev
```

The MCP endpoint is served at `http://localhost:8000/mcp`. Inspect it with the Alexa+ Local Inspector or the MCP Inspector before connecting it to Alexa+.

## Demo script (three minutes)

1. Ask Alexa+ to set a ten-minute timer. It runs immediately. Show the audit entry.
2. Ask it to dim the living room lights to 30 percent. Show the rule that validated the value.
3. Ask it to set the thermostat to 35 degrees. The rules engine rejects it with a structured error, and Alexa+ asks a specific follow-up.
4. Ask it to book a room for Friday. The preview appears, naming the booking service and tool. Confirm, and show the token being consumed.
5. Say "undo that." Show the compensating action and the new audit entry linked to the original.
6. Show the privacy panel. Turn off third-party sharing and repeat step 4 to show the tool is refused.

## Scope

**In scope:** the MCP server, the rules engine, confirmations, the audit log, concise mode, privacy enforcement, the console UI, the developer standard documents, and a test harness with simulated journeys.

**Out of scope:** real device integrations beyond simulators, the visual rendering of confirmations (owned by Alexa+), and the legacy Alexa skill migration (owned by Alexa+).

## Status

Hackathon build. See `TECHNICAL.md` for architecture, contracts, and the build plan.