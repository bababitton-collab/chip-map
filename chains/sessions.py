"""Each listing's closes stamped with its own market's close, in UTC.

"The first close after a timestamp" is the entry rule of both the H1 test
(scripts/h1_backtest.py) and the event contract (chains/events.py), so it
lives here once.
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from zoneinfo import ZoneInfo

from chains import prices

# Each market's regular close, local time. Tokyo moved from 15:00 to 15:30 on
# 2024-11-05.
CLOSE = {"US": ("America/New_York", (16, 0)), "T": ("Asia/Tokyo", (15, 0)),
         "TW": ("Asia/Taipei", (13, 30)), "TWO": ("Asia/Taipei", (13, 30)),
         "KO": ("Asia/Seoul", (15, 30)), "KQ": ("Asia/Seoul", (15, 30)),
         "XETRA": ("Europe/Berlin", (17, 30)), "SHE": ("Asia/Shanghai", (15, 0)),
         "SHG": ("Asia/Shanghai", (15, 0)), "MI": ("Europe/Rome", (17, 30)),
         "BR": ("Europe/Brussels", (17, 30)), "PA": ("Europe/Paris", (17, 30)),
         "LSE": ("Europe/London", (16, 30)), "AU": ("Australia/Sydney", (16, 0)),
         "TO": ("America/Toronto", (16, 0)), "HK": ("Asia/Hong_Kong", (16, 0))}


def close_utc(suffix: str, d: dt.date) -> float:
    tz, (h, m) = CLOSE[suffix]
    if suffix == "T" and d >= dt.date(2024, 11, 5):
        h, m = 15, 30
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(tz)).timestamp()


class Line:
    """One listing's adjusted closes, each stamped with its own market's close."""

    def __init__(self, symbol: str):
        df = prices.load(symbol)
        rows = [(d, c) for d, c in zip(df["date"].to_list(), df["adj_close"].to_list()) if c]
        suffix = symbol.rsplit(".", 1)[-1]
        self.closes = [c for _, c in rows]
        self.ts = [close_utc(suffix, d) for d, _ in rows]
        self.dates = [d for d, _ in rows]

    def session0(self, ts: float) -> int:
        """Index of the first session that closes strictly after ``ts``."""
        return bisect_right(self.ts, ts)

    def ret(self, ts: float, a: int, b: int) -> float | None:
        """Return over sessions a..b (inclusive) after the event. Missing = None."""
        i0 = self.session0(ts)
        lo, hi = i0 + a - 1, i0 + b
        if lo < 0 or hi >= len(self.closes):
            return None
        return self.closes[hi] / self.closes[lo] - 1
