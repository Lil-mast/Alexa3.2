from __future__ import annotations

from time import perf_counter

from app.auth import Principal
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


def test_router_hot_path_stays_in_memory():
    """A guard against accidental I/O, not a benchmark.

    The simulated adapter and the trace buffer are in memory, so a call should
    take well under a millisecond. The assertion is deliberately loose for slow
    CI runners; it fails if a future change adds a file read, a network call, or
    a sleep to the path Alexa+ waits on.
    """
    state = AppState(settings=make_settings())
    router = Router(state)
    principal = Principal(subject="bench-user", client_id="bench", scopes=tuple(ALL_SCOPES))
    params = {"room": "office", "brightness": 50}

    for _ in range(5):
        assert router.execute("lights_set", params, principal).status == "ok"

    samples: list[float] = []
    for _ in range(200):
        started = perf_counter()
        response = router.execute("lights_set", params, principal)
        samples.append((perf_counter() - started) * 1000)
        assert response.status == "ok"

    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 25.0, f"p95 router latency was {p95:.2f}ms"
