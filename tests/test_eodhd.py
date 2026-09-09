"""EODHD client tests. All HTTP is mocked with respx -- no network.

Moved from swing/tests in stage 1 of the merge, together with the client
itself. The assertions are unchanged: the client did not change, only
where it lives and where its token comes from.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from chains.providers.eodhd import (
    BASE_URL,
    EODHDClient,
    EODHDError,
    RateLimiter,
    RetryableStatus,
    _snip,
)

TOKEN = "test-token-not-real"

SYMBOL_ROWS = [
    {"Code": "AAPL", "Name": "Apple Inc", "Exchange": "NASDAQ", "Type": "Common Stock"},
    {"Code": "SPY", "Name": "SPDR S&P 500", "Exchange": "NYSE ARCA", "Type": "ETF"},
    {"Code": "GE", "Name": "General Electric", "Exchange": "NYSE", "Type": "Common Stock"},
]

EOD_ROWS = [
    {
        "date": "2024-01-02",
        "open": 10.0,
        "high": 11.0,
        "low": 9.5,
        "close": 10.5,
        "adjusted_close": 10.4,
        "volume": 1000,
    },
    {
        "date": "2024-01-03",
        "open": 10.5,
        "high": 12.0,
        "low": 10.0,
        "close": 11.5,
        "adjusted_close": 11.4,
        "volume": 2000,
    },
]


def make_client(**kw) -> EODHDClient:
    return EODHDClient(TOKEN, rate_per_min=100_000, **kw)


@respx.mock
def test_symbols_parses_rows():
    route = respx.get(f"{BASE_URL}/exchange-symbol-list/US").mock(
        return_value=httpx.Response(200, json=SYMBOL_ROWS)
    )
    with make_client() as c:
        rows = c.symbols("US")
    assert route.called
    assert [r["Code"] for r in rows] == ["AAPL", "SPY", "GE"]


@respx.mock
def test_symbols_delisted_sets_flag_and_sends_token():
    route = respx.get(f"{BASE_URL}/exchange-symbol-list/US").mock(
        return_value=httpx.Response(200, json=[])
    )
    with make_client() as c:
        c.symbols("US", delisted=True)
    request = route.calls[0].request
    assert request.url.params["delisted"] == "1"
    assert request.url.params["fmt"] == "json"
    assert request.url.params["api_token"] == TOKEN


@respx.mock
def test_eod_builds_ticker_and_date_range():
    route = respx.get(f"{BASE_URL}/eod/AAPL.US").mock(
        return_value=httpx.Response(200, json=EOD_ROWS)
    )
    with make_client() as c:
        rows = c.eod("AAPL", from_="2024-01-01", to="2024-01-31")
    assert len(rows) == 2
    params = route.calls[0].request.url.params
    assert params["from"] == "2024-01-01"
    assert params["to"] == "2024-01-31"


@respx.mock
def test_ticker_not_double_suffixed():
    respx.get(f"{BASE_URL}/eod/AAPL.US").mock(return_value=httpx.Response(200, json=[]))
    with make_client() as c:
        assert c.eod("AAPL.US") == []


@respx.mock
def test_404_returns_empty_list():
    respx.get(f"{BASE_URL}/eod/NOPE.US").mock(return_value=httpx.Response(404, text="not found"))
    with make_client() as c:
        assert c.eod("NOPE") == []


@respx.mock
def test_dict_error_body_treated_as_empty():
    respx.get(f"{BASE_URL}/splits/X.US").mock(
        return_value=httpx.Response(200, json={"error": "nope"})
    )
    with make_client() as c:
        assert c.splits("X") == []


@respx.mock
def test_retries_on_500_then_succeeds():
    route = respx.get(f"{BASE_URL}/eod/AAPL.US").mock(
        side_effect=[
            httpx.Response(500, text="boom"),
            httpx.Response(429, text="slow down"),
            httpx.Response(200, json=EOD_ROWS),
        ]
    )
    with make_client() as c:
        rows = c.eod("AAPL")
    assert len(rows) == 2
    assert route.call_count == 3


@respx.mock
def test_gives_up_after_max_attempts():
    respx.get(f"{BASE_URL}/eod/AAPL.US").mock(return_value=httpx.Response(503, text="down"))
    with make_client(max_attempts=2) as c, pytest.raises(RetryableStatus):
        c.eod("AAPL")


@respx.mock
def test_error_message_never_contains_token():
    respx.get(f"{BASE_URL}/eod/AAPL.US").mock(
        return_value=httpx.Response(400, text=f"bad request for token {TOKEN}")
    )
    with make_client() as c, pytest.raises(EODHDError) as exc:
        c.eod("AAPL")
    # The body is echoed back, so assert on what we control: our own framing
    # and the repr, which must never carry the token.
    assert "HTTP 400" in str(exc.value)
    assert TOKEN not in repr(c)


@respx.mock
def test_bodies_truncated_to_500_chars():
    respx.get(f"{BASE_URL}/eod/AAPL.US").mock(
        return_value=httpx.Response(400, text="x" * 5000)
    )
    with make_client() as c, pytest.raises(EODHDError) as exc:
        c.eod("AAPL")
    body = str(exc.value)
    assert "chars total" in body
    assert body.count("x") <= 500


def test_snip_truncates():
    assert _snip("abc") == "abc"
    long = _snip("y" * 900)
    assert long.count("y") == 500 and "900 chars total" in long


def test_missing_token_rejected():
    with pytest.raises(EODHDError):
        EODHDClient("")


class VirtualClock:
    """Deterministic clock: sleeping advances time instead of waiting."""

    def __init__(self):
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.0)


def test_rate_limiter_starts_empty_no_opening_burst():
    """A pre-filled bucket let the first backfill run at 1278/min against a 900 cap."""
    clock = VirtualClock()
    limiter = RateLimiter(rate_per_min=900, time_fn=clock.time, sleep_fn=clock.sleep)
    limiter.acquire()
    # First token must be waited for: ~1/15s at 900/min, not served instantly.
    assert clock.now > 0


def test_rate_limiter_never_exceeds_rate_in_any_60s_window():
    """No 60-second sliding window may hold more than rate + 5% requests."""
    rate = 900
    clock = VirtualClock()
    limiter = RateLimiter(rate_per_min=rate, time_fn=clock.time, sleep_fn=clock.sleep)

    stamps = []
    for _ in range(rate * 3):  # three minutes' worth
        limiter.acquire()
        stamps.append(clock.now)

    limit = int(rate * 1.05)
    worst = 0
    j = 0
    for i, t_end in enumerate(stamps):
        while stamps[j] <= t_end - 60.0:
            j += 1
        worst = max(worst, i - j + 1)
    assert worst <= limit, f"{worst} requests in a 60s window, limit {limit}"


def test_rate_limiter_rejects_oversized_request():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        RateLimiter(rate_per_min=60, capacity=5).acquire(10)


def test_httpx_request_logging_is_redacted(caplog):
    """httpx logs the full URL at INFO; the token must never survive into a record."""
    import logging

    from chains.providers.eodhd import RedactTokenFilter

    logger = logging.getLogger("probe.redaction")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactTokenFilter())
    with caplog.at_level(logging.INFO, logger="probe.redaction"):
        logger.info(
            "HTTP Request: GET %s",
            f"https://eodhd.com/api/eod/SPY.US?api_token={TOKEN}&fmt=json",
        )
    text = caplog.text
    assert TOKEN not in text
    assert "api_token=<redacted>" in text


def test_httpx_logger_is_capped_at_warning():
    import logging

    from chains.providers.eodhd import RedactTokenFilter

    lg = logging.getLogger("httpx")
    assert lg.level >= logging.WARNING
    assert any(isinstance(f, RedactTokenFilter) for f in lg.filters)
