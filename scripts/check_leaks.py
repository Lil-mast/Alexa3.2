#!/usr/bin/env python3
"""Refuse to commit values that belong in .env, not a public repository.

Default scope is what is staged for the next commit, which is what the
pre-commit hook uses. `--all` scans every tracked and untracked, unignored file
and is what CI runs. `--self-test` checks the rules themselves.

The scanner is deliberately dependency free. It must run before `uv sync` and
without a virtualenv, and it must never need a package that could be compromised
before the check runs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

# Nothing below the repository root is ours to scan, and caches only add noise.
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage",
    "dist",
    "build",
}

# Lock files contain public package URLs and hashes, not secrets. Scanning them
# creates noise without adding safety.
EXCLUDED_NAMES = {
    "uv.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
}

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".whl",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
}

# Values the repository ships on purpose are recognized in `_placeholder`.
# Keep that function exact: a substring match would hide real identifiers.

# Hosts that appear in documentation and examples. A real deployment host is
# not on this list, which is the point: an App Runner or tunnel hostname in a
# tracked file is a finding.
DOC_HOSTS = {
    "amazon.com",
    "aws.amazon.com",
    "developer.amazon.com",
    "devpost.com",
    "example.com",
    "example.net",
    "example.org",
    "example.us-east-1.awsapprunner.com",
    "fastapi.tiangolo.com",
    "github.com",
    "githubusercontent.com",
    "json-schema.org",
    "modelcontextprotocol.io",
    "npmjs.com",
    "openid.net",
    "packaging.python.org",
    "peps.python.org",
    "pydantic.dev",
    "pypi.org",
    "python.org",
    "rfc-editor.org",
    "starlette.dev",
    "uvicorn.dev",
    "w3.org",
    "ietf.org",
    "unicode.org",
    # Documented demo origins and a public provider API. These are not
    # secrets; the deployment and voice docs need the exact hosts.
    "alexa.vercel.app",
    "alexa-api.onrender.com",
    "api.elevenlabs.io",
    "google.com",
    "googleapis.com",
}

LOCAL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "testserver",
    "host.docker.internal",
}


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    fix: str
    # Return True to skip a match. Used for documentation URLs and placeholders
    # that would otherwise drown the real finding.
    allow: Callable[[re.Match[str]], bool] | None = None


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    hit: str
    fix: str


def _placeholder(hit: str) -> bool:
    """True only for the exact example values the repository ships.

    A substring check is tempting and wrong: every Alexa skill id contains a
    12-digit-looking run, and the account placeholder would hide a real id that
    happened to share those digits. Compare the structure instead.
    """
    if hit in {"AKIAIOSFODNN7EXAMPLE", "dev-token", "test-token"}:
        return True
    if hit.startswith("amzn1.ask.skill."):
        return hit in {
            "amzn1.ask.skill.00000000-0000-0000-0000-000000000000",
            "amzn1.ask.skill.11111111-2222-3333-4444-555555555555",
        }
    if "arn:aws" in hit:
        return any(f":{value}:" in hit for value in ("000000000000", "123456789012"))
    return False


def _host_allowed(host: str) -> bool:
    host = host.lower().strip(".")
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    if host in DOC_HOSTS:
        return True
    # A subdomain of a documentation host is still documentation, for example
    # raw.githubusercontent.com or docs.aws.amazon.com.
    return any(host.endswith("." + allowed) for allowed in DOC_HOSTS)


def _url_allowed(match: re.Match[str]) -> bool:
    raw = match.group(0).rstrip(".,;:)]}")
    # CORS settings and env examples use comma-separated lists. Treat every
    # member as its own URL instead of reading `host,http://...` as one host.
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return bool(parts) and all(_single_url_allowed(part) for part in parts)


def _single_url_allowed(raw: str) -> bool:
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return False
    # Tunnels have their own rule, with a more useful message.
    if host.endswith(".trycloudflare.com") or "ngrok" in host:
        return True
    return _host_allowed(host)


def _credentials_allowed(match: re.Match[str]) -> bool:
    # Credentials in any URL are a finding, even on an example host. The fix is
    # always the same: use a secret reference, never a URL.
    return False


RULES = [
    Rule(
        name="private key",
        pattern=re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        fix="remove the key, revoke it, and store the replacement in a secret manager",
    ),
    Rule(
        name="AWS access key",
        pattern=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        fix="remove the key, revoke it in IAM, and use a role or secret reference",
    ),
    Rule(
        name="AWS secret access key",
        pattern=re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})"),
        fix="remove the key, revoke it in IAM, and use a role or secret reference",
    ),
    Rule(
        name="Alexa skill id",
        pattern=re.compile(r"amzn1\.ask\.skill\.[0-9a-fA-F-]{36}"),
        fix="put it in .env as ALEXA_SKILL_ID instead",
    ),
    Rule(
        name="AWS account id in an ARN",
        pattern=re.compile(r"arn:aws[a-z-]*:[^:\s]+:[^:\s]*:(\d{12}):"),
        fix="keep real ARNs in .env or in the deployment tool, never in a tracked file",
    ),
    Rule(
        name="credentials in a URL",
        pattern=re.compile(r"https?://[^\s'\"`/@:]+:[^\s'\"`/@]+@"),
        fix="use a bearer token or a secret reference, never user:password in a URL",
        allow=_credentials_allowed,
    ),
    Rule(
        name="tunnel URL",
        pattern=re.compile(r"[a-z0-9-]+\.(?:trycloudflare\.com|ngrok-free\.app|ngrok\.app|ngrok\.io|ngrok\.dev)"),
        fix="put the tunnel URL in .env, and remember that a quick tunnel expires",
    ),
    Rule(
        name="real endpoint",
        pattern=re.compile(r"https?://[^\s'\"`)<>\]]+"),
        fix="put the deployment URL in .env as ALEXA_PUBLIC_URL instead",
        allow=_url_allowed,
    ),
    Rule(
        name="secret assignment",
        pattern=re.compile(
            r"(?i)\b(?:api[_-]?key|api[_-]?secret|client[_-]?secret|access[_-]?token|auth[_-]?token|password)"
            r"\b\s*[:=]\s*['\"]([A-Za-z0-9_\-./+=]{16,})['\"]"
        ),
        fix="move the value to .env and commit only the variable name",
    ),
]


def scan_text(path: str, text: str) -> list[Finding]:
    """Scan one decoded file. Kept separate so --self-test can call it."""
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                hit = match.group(0)
                if _placeholder(hit):
                    continue
                if rule.allow and rule.allow(match):
                    continue
                findings.append(
                    Finding(
                        file=path,
                        line=line_number,
                        rule=rule.name,
                        hit=hit,
                        fix=rule.fix,
                    )
                )
    return findings


def _text_findings(path: str, data: bytes) -> list[Finding]:
    # A NUL byte in the first block is a cheap binary check. Images and archives
    # cannot carry a usable secret as text, and decoding them wastes time.
    if b"\0" in data[:8192]:
        return []
    return scan_text(path, data.decode("utf-8", errors="replace"))


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"check_leaks needs a git repository: {message}")
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def _candidates(scan_all: bool) -> list[str]:
    if scan_all:
        # Tracked plus untracked, unignored files: what a `git add -A` would
        # commit. Ignored files, including .env, stay out of scope.
        names = _git("ls-files", "-z") + _git("ls-files", "--others", "--exclude-standard", "-z")
    else:
        # Added, copied, or modified files in the index. Deletions have no
        # content to scan.
        names = _git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z")
    return sorted(set(names))


def check(scan_all: bool) -> list[Finding]:
    findings: list[Finding] = []
    for relative in _candidates(scan_all):
        path = (ROOT / relative).resolve()
        if path == SELF or not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix in BINARY_SUFFIXES:
            continue
        # An environment file staged on purpose is always a finding, even if its
        # current contents happen to look harmless.
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(
                Finding(
                    file=relative,
                    line=1,
                    rule="environment file",
                    hit=path.name,
                    fix="move it to .env, keep it ignored, and commit only .env.example",
                )
            )
            continue
        findings.extend(_text_findings(relative, path.read_bytes()))
    return findings


def _clip(value: str, limit: int = 80) -> str:
    value = value.replace("\n", " ")
    return value if len(value) <= limit else value[: limit - 1] + "~"


def report(findings: list[Finding], scope: str) -> int:
    if not findings:
        print(f"No leaks in {scope}.")
        return 0
    print(f"\nWait: {len(findings)} value(s) that should not be in a public repository.\n", file=sys.stderr)
    for finding in findings:
        print(f"  {finding.file}:{finding.line}  {finding.rule}: {_clip(finding.hit)}", file=sys.stderr)
        print(f"      fix: {finding.fix}", file=sys.stderr)
    print(
        "\nUnstage the file, move the value to .env, and commit again."
        "\nIf the hit is a documented placeholder, add it to PLACEHOLDERS in scripts/check_leaks.py."
        "\nDo not use --no-verify to hide a real secret.\n",
        file=sys.stderr,
    )
    return 1


def self_test() -> int:
    """A small truth table so a broken regex fails before it hides a secret."""
    cases: list[tuple[str, str, bool]] = [
        ("host", "http://localhost:8000/mcp", False),
        ("host", "https://abc123.us-east-1.awsapprunner.com/mcp", True),
        ("host", "https://example.com/mcp", False),
        ("host", "https://github.com/org/repo", False),
        ("host", "https://random-name.trycloudflare.com/mcp", True),
        ("host", "https://user:pass@example.com/mcp", True),
        ("account", "arn:aws:iam::999999999999:role/app", True),
        ("account", "arn:aws:iam::123456789012:role/app", False),
        ("skill", "amzn1.ask.skill.12345678-1234-1234-1234-123456789012", True),
        ("skill", "amzn1.ask.skill.00000000-0000-0000-0000-000000000000", False),
        ("key", "AKIA1234567890ABCDEF", True),
        ("key", "AKIAIOSFODNN7EXAMPLE", False),
        ("secret", 'password = "correct-horse-battery-staple"', True),
        ("secret", 'password = "short"', False),
        ("key", "-----BEGIN PRIVATE KEY-----", True),
        ("token", 'ALEXA_TOKENS_JSON={"dev-token":{"subject":"demo-user"}}', False),
    ]
    failures = 0
    for name, text, expected in cases:
        found = bool(scan_text("self-test", text))
        if found != expected:
            failures += 1
            print(f"FAIL {name}: expected finding={expected}, got {found}: {_clip(text)}", file=sys.stderr)
    if failures:
        return 1
    print(f"check_leaks self-test passed ({len(cases)} cases).")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="scan tracked and untracked files instead of staged files")
    parser.add_argument("--self-test", action="store_true", help="check the scanner rules against sample values")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        return self_test()

    findings = check(args.all)
    scope = "tracked or untracked files" if args.all else "staged files"
    return report(findings, scope)


if __name__ == "__main__":
    raise SystemExit(main())
