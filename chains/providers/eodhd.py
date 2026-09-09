"""Thin EODHD REST client. Shared by both strategies.

Promoted from ``swing.data.eodhd`` in stage 1 of the merge. ``smallcap``
had its own client over a different HTTP stack; this one replaced it,
because it already carried three things the other did not: a tenacity
retry policy, an error taxonomy that separates retryable from terminal,
and redaction of the API token at the logging layer.

Design rules that matter here:

- The API token is a secret. It is never logged, never put in an exception
  message, and never included in a repr. httpx's own ``raise_for_status``
  embeds the full request URL (token included) in the exception text, so this
  module never calls it -- non-2xx is turned into our own redacted error.
- Response bodies are truncated to 500 chars before they reach a log or an
  exception, so a huge HTML error page cannot flood the logs.
- Every outbound call passes through a shared token bucket (900 req/min by
  default) so a thread pool cannot exceed the plan's rate limit.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from chains.providers.ratelimit import RateLimiter

log = logging.getLogger(__name__)

BASE_URL = "https://eodhd.com/api"
MAX_BODY_CHARS = 500
DEFAULT_TIMEOUT = 60.0
DEFAULT_RATE_PER_MIN = 900
TOKEN_ENV = "EODHD_API_TOKEN"

__all__ = [
    "BASE_URL",
    "EODHDClient",
    "EODHDError",
    "NotFound",
    "RateLimiter",
    "RedactTokenFilter",
    "RetryableStatus",
    "TOKEN_ENV",
]

# The token travels in the query string of every request, and httpx logs the
# full URL at INFO. Left alone that writes the secret into any log the CLI
# configures, so httpx/httpcore request logging is capped at WARNING and any
# record that still carries the parameter is redacted before it is emitted.
_TOKEN_PARAM = re.compile(r"(api_token=)[^&\s\"']+")


class RedactTokenFilter(logging.Filter):
    """Scrub ``api_token=...`` out of a log record before it is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        if "api_token=" in message:
            record.msg = _TOKEN_PARAM.sub(r"\1<redacted>", message)
            record.args = ()
        return True


def silence_http_logging() -> None:
    """Stop the HTTP stack from logging URLs that contain the token.

    Called at import: any entry point that constructs a client is protected,
    not just the ones that remember to opt in.
    """
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        if not any(isinstance(f, RedactTokenFilter) for f in logger.filters):
            logger.addFilter(RedactTokenFilter())


silence_http_logging()


def _snip(text: str) -> str:
    """Truncate a response body so it is safe to log."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[:MAX_BODY_CHARS] + f"... [{len(text)} chars total]"


class EODHDError(RuntimeError):
    """Any EODHD failure. Messages never contain the API token."""


class RetryableStatus(EODHDError):
    """429 or 5xx -- worth retrying with backoff."""


class NotFound(EODHDError):
    """404 -- the symbol or endpoint has no data. Callers treat this as empty."""


class EODHDClient:
    """Minimal EODHD client covering the endpoints stage 1 needs."""

    def __init__(
        self,
        api_token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        rate_per_min: int = DEFAULT_RATE_PER_MIN,
        client: httpx.Client | None = None,
        max_attempts: int = 6,
    ):
        # core cannot import either strategy's settings object, so the token
        # is either handed in or read from the environment. Both engines
        # already load their own .env before constructing a client.
        token = api_token if api_token is not None else os.environ.get(
            TOKEN_ENV, ""
        )
        if not token:
            raise EODHDError(f"{TOKEN_ENV} is not set")
        self._token = token
        self._limiter = RateLimiter(rate_per_min)
        self._max_attempts = max_attempts
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)

    # -- plumbing ---------------------------------------------------------

    def _send(self, path: str, params: dict[str, Any]) -> Any:
        """One rate-limited request. Raises RetryableStatus / NotFound / EODHDError."""
        self._limiter.acquire()
        full = {**params, "api_token": self._token, "fmt": "json"}
        try:
            resp = self._client.get(path, params=full)
        except httpx.TransportError:
            # httpx builds its message from the URL, which carries the token.
            # Raise our own so nothing downstream can log it.
            raise RetryableStatus(f"transport error for {path}") from None

        code = resp.status_code
        if code == 429 or code >= 500:
            raise RetryableStatus(f"HTTP {code} for {path}: {_snip(resp.text)}")
        if code == 404:
            raise NotFound(f"HTTP 404 for {path}")
        if code >= 400:
            raise EODHDError(f"HTTP {code} for {path}: {_snip(resp.text)}")
        try:
            return resp.json()
        except ValueError:
            raise EODHDError(f"non-JSON response for {path}: {_snip(resp.text)}") from None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}

        @retry(
            retry=retry_if_exception_type(RetryableStatus),
            wait=wait_exponential_jitter(initial=1.0, max=60.0),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        )
        def _attempt() -> Any:
            return self._send(path, params)

        return _attempt()

    def _get_rows(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        """GET returning a list of dicts. A 404 or a non-list body means 'no data'."""
        try:
            payload = self._get(path, params)
        except NotFound:
            log.info("no data (404) for %s", path)
            return []
        if payload is None:
            return []
        if isinstance(payload, dict):
            # EODHD signals some errors as a JSON object rather than a status code.
            log.warning("unexpected object response for %s: %s", path, _snip(str(payload)))
            return []
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict)]

    @staticmethod
    def _ticker(symbol: str, exchange: str = "US") -> str:
        return symbol if "." in symbol else f"{symbol}.{exchange}"

    # -- endpoints --------------------------------------------------------

    def symbols(self, exchange: str = "US", delisted: bool = False) -> list[dict]:
        """Full symbol list for an exchange. ``delisted=True`` returns dead tickers."""
        params: dict[str, Any] = {}
        if delisted:
            params["delisted"] = 1
        return self._get_rows(f"/exchange-symbol-list/{exchange}", params)

    def eod(
        self,
        symbol: str,
        from_: str | None = None,
        to: str | None = None,
        exchange: str = "US",
    ) -> list[dict]:
        """Daily bars: date, open, high, low, close, adjusted_close, volume."""
        params: dict[str, Any] = {}
        if from_:
            params["from"] = from_
        if to:
            params["to"] = to
        return self._get_rows(f"/eod/{self._ticker(symbol, exchange)}", params)

    def bulk_last_day(self, exchange: str = "US", date: str | None = None) -> list[dict]:
        """One call for the whole exchange's most recent session."""
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        return self._get_rows(f"/eod-bulk-last-day/{exchange}", params)

    def splits(
        self,
        symbol: str,
        from_: str | None = None,
        to: str | None = None,
        exchange: str = "US",
    ) -> list[dict]:
        """Split history. The date range is optional: swing asks for all of
        it, smallcap bounds it by the backtest window."""
        params: dict[str, Any] = {}
        if from_:
            params["from"] = from_
        if to:
            params["to"] = to
        return self._get_rows(f"/splits/{self._ticker(symbol, exchange)}", params)

    def symbol_changes(self, from_: str, to: str) -> list[dict]:
        """Ticker changes in a date range.

        Ported from smallcap's client, which was the only side that had it.
        EODHD only covers 2024 onward here -- a 2018 window returns an empty
        list rather than an error, so an empty result is not evidence that
        nothing changed. See docs/MERGE-PLAN.md.
        """
        return self._get_rows(
            "/symbol-change-history", {"from": from_, "to": to}
        )

    def dividends(self, symbol: str, exchange: str = "US") -> list[dict]:
        return self._get_rows(f"/div/{self._ticker(symbol, exchange)}")

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> EODHDClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:  # never leak the token
        return f"<EODHDClient rate={self._limiter.rate_per_sec * 60:.0f}/min>"
