from __future__ import annotations

from app.cli import main
from tests.conftest import TEST_TOKEN


def test_cli_lists_tools(live_server, capsys):
    code = main(["--url", live_server, "--token", TEST_TOKEN, "tools"])

    output = capsys.readouterr().out
    assert code == 0
    assert "timer_set" in output
    assert "book_room" in output
    assert "8 tools" in output


def test_cli_calls_a_tool(live_server, capsys):
    code = main(
        [
            "--url",
            live_server,
            "--token",
            TEST_TOKEN,
            "call",
            "lights_set",
            '{"room": "office", "on": true}',
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert '"status": "ok"' in output
    assert "Office lights on." in output


def test_cli_returns_nonzero_for_a_business_error(live_server, capsys):
    code = main(
        [
            "--url",
            live_server,
            "--token",
            TEST_TOKEN,
            "call",
            "thermostat_set",
            '{"zone": "office", "target_c": 35}',
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert "OUT_OF_BOUNDS" in output
    assert "between 16 and 28 degrees Celsius" in output


def test_cli_whoami(live_server, capsys):
    code = main(["--url", live_server, "--token", TEST_TOKEN, "whoami"])

    output = capsys.readouterr().out
    assert code == 0
    assert "test-user" in output
    assert "home:timers:write" in output


def test_cli_audit_verify(live_server, capsys):
    code = main(["--url", live_server, "--token", TEST_TOKEN, "audit", "verify"])

    output = capsys.readouterr().out
    assert code == 0
    assert output.startswith("audit chain ok:")
    assert "head" in output


def test_cli_audit_list(live_server, capsys):
    main(
        [
            "--url",
            live_server,
            "--token",
            TEST_TOKEN,
            "call",
            "timer_set",
            '{"duration_seconds": 60}',
        ]
    )
    capsys.readouterr()

    code = main(["--url", live_server, "--token", TEST_TOKEN, "audit", "list", "--limit", "5"])

    output = capsys.readouterr().out
    assert code == 0
    assert "timer_set" in output
    assert "executed" in output
    assert "seeded from audit_seed.json" in output
