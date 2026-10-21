"""Local MCP client for manual checks and the demo.

This is a developer tool, not an Alexa+ simulator. It does not choose tools or
write speech; it sends exactly the call you type and prints the structured
result, so you can see what Alexa+ will see over the same Streamable HTTP
transport. The deterministic decision still belongs to the server.

Examples, from `backend/` while the server runs on port 8000:

    python -m app.cli tools
    python -m app.cli call timer_set '{"duration_seconds": 600}'
    python -m app.cli call lights_set '{"room": "living_room", "brightness": 30}'
    python -m app.cli bench --n 100

Set `ALEXA_MCP_URL` and `ALEXA_TOKEN` to point at a deployed instance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DEFAULT_URL = "http://localhost:8000/mcp"
DEFAULT_TOKEN = "dev-token"


@asynccontextmanager
async def _connect(url: str, token: str):
    """Open one initialized MCP session.

    The MCP SDK owns the transport and the session handshake. Reusing its client
    means this tool exercises the same initialize, tools/list, and tools/call
    path as Alexa+, not a private shortcut through the router.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30.0) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session, http_client


def _api_base(url: str) -> str:
    """Turn the MCP endpoint into the console API origin."""
    return url[:-4] if url.endswith("/mcp") else url.rstrip("/")


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


async def _list_tools(url: str, token: str) -> int:
    async with _connect(url, token) as (session, _):
        tools = await session.list_tools()
    for tool in tools.tools:
        required = tool.input_schema.get("required", [])
        title = f"  {tool.title}" if tool.title else ""
        print(f"{tool.name}{title}")
        print(f"  required: {', '.join(required) if required else 'none'}")
        if tool.description:
            print(f"  {tool.description}")
        print()
    print(f"{len(tools.tools)} tools")
    return 0


async def _call(url: str, token: str, tool: str, params: dict[str, Any]) -> int:
    async with _connect(url, token) as (session, _):
        result = await session.call_tool(tool, params)
    payload = result.structured_content
    if payload is None:
        # A protocol error has no structured result. Print whatever content the
        # server sent so the failure is visible instead of silent.
        print(result.content)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if result.is_error or payload.get("status") == "error" else 0


async def _bench(url: str, token: str, tool: str, params: dict[str, Any], runs: int) -> int:
    """Measure end to end over one MCP session, including JSON-RPC overhead.

    This is the number that matters for the voice turn: the deterministic router
    itself is sub-millisecond, but Alexa+ pays for the transport too.
    """
    async with _connect(url, token) as (session, _):
        # Warm up imports, rule loading, and the first trace allocation before
        # measuring, so p50 is not dominated by a one-time cost.
        for _ in range(3):
            await session.call_tool(tool, params)

        samples: list[float] = []
        failures = 0
        for _ in range(runs):
            started = time.perf_counter()
            result = await session.call_tool(tool, params)
            samples.append((time.perf_counter() - started) * 1000)
            if result.is_error or (result.structured_content or {}).get("status") == "error":
                failures += 1

    print(
        f"{tool} n={runs} "
        f"p50={_percentile(samples, 0.50):.2f}ms "
        f"p95={_percentile(samples, 0.95):.2f}ms "
        f"p99={_percentile(samples, 0.99):.2f}ms "
        f"max={max(samples):.2f}ms"
    )
    if failures:
        print(f"{failures} call(s) returned an error", file=sys.stderr)
        return 1
    return 0


async def _whoami(url: str, token: str) -> int:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=10.0) as client:
        response = await client.get(f"{_api_base(url)}/api/whoami")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return 0 if response.is_success else 1


async def _run(args: argparse.Namespace) -> int:
    if args.command == "tools":
        return await _list_tools(args.url, args.token)
    if args.command == "whoami":
        return await _whoami(args.url, args.token)
    if args.command == "call":
        return await _call(args.url, args.token, args.tool, args.params)
    return await _bench(args.url, args.token, args.tool, args.params, args.n)


def _parse_params(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"parameters are not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("parameters must be a JSON object")
    return value


def _describe(exc: BaseException) -> list[str]:
    """Flatten the task-group wrappers the MCP SDK uses.

    A connection failure arrives as `ExceptionGroup: unhandled errors in a
    TaskGroup`, which tells a developer nothing. The nested cause is the useful
    part, so print the whole chain.
    """
    if isinstance(exc, BaseExceptionGroup):
        lines: list[str] = []
        for child in exc.exceptions:
            lines.extend(_describe(child))
        return lines
    lines = [f"{type(exc).__name__}: {exc}"]
    if exc.__cause__ is not None:
        lines.extend(_describe(exc.__cause__))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    parser.add_argument("--url", default=os.environ.get("ALEXA_MCP_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("ALEXA_TOKEN", DEFAULT_TOKEN))
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("tools", help="list the tools Alexa+ sees")
    commands.add_parser("whoami", help="show the subject and scopes for the token")

    call = commands.add_parser("call", help="call one tool with a JSON object")
    call.add_argument("tool")
    call.add_argument("params", nargs="?", default="{}")

    bench = commands.add_parser("bench", help="measure tool-call latency over MCP")
    bench.add_argument("--tool", default="lights_set")
    bench.add_argument("--params", default='{"room": "office", "brightness": 50}')
    bench.add_argument("--n", type=int, default=50)

    args = parser.parse_args(argv)
    if args.command in {"call", "bench"}:
        try:
            args.params = _parse_params(args.params)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "bench" and args.n < 1:
        parser.error("--n must be at least 1")

    try:
        return asyncio.run(_run(args))
    except httpx2.HTTPError as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        print("Is the server running? uv run uvicorn app.main:app --port 8000", file=sys.stderr)
        return 2
    except Exception as exc:
        # A CLI should print the cause, not a traceback. Task-group wrappers are
        # flattened by _describe so the connection error is visible.
        for line in _describe(exc):
            print(line, file=sys.stderr)
        print("Is the server running? uv run uvicorn app.main:app --port 8000", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
