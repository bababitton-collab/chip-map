"""Candlesticks as SVG, drawn at build time.

    from chains import candles
    candles.svg(prices.bars("NVDA.US", start, end), title="NVDA.US")

WHY AT BUILD TIME
-----------------
The page already carries its own drawing code for the tracking chart, and that
chart is a line: one number per session, redrawn as the window moves. A candle
is four numbers a day that never change once the session has closed, so it is
a picture of something finished -- and a finished picture belongs in the file
rather than in a library the reader has to download to see it. No dependency,
no canvas, no runtime: a string of SVG a static host serves and a screen reader
can be told what it is.

WHAT IT DRAWS AND WHAT IT REFUSES TO
------------------------------------
One rectangle per session between open and close, one line between high and
low, green where the close is at or above the open and red where it is below --
the map's own two colours. The scale is linear and spans the window's own high
and low; there is no second axis, no volume, no indicator, and no gap-filling.
A session the vendor never printed is simply not a candle: the next one sits
beside it, and the date labels underneath say where the holes are.

An empty list returns an empty string. A caller with nothing to draw writes
"no clean series" instead, and never a chart of zero.
"""
from __future__ import annotations

import datetime as dt
import html

UP = "#3fd18b"          # --erode on the map
DOWN = "#ff5a3c"        # --tight
WICK_UP = "#2fa96f"
WICK_DOWN = "#c9462e"
AXIS = "#7d8797"
RULE = "#222a36"
BG = "#0b0e14"

WIDTH = 720
HEIGHT = 220
PAD_L = 8
PAD_R = 54             # the price axis, on the right where the last bar is
PAD_T = 10
PAD_B = 28             # room for one row of date labels


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None          # NaN is not a price


def _fmt(v: float) -> str:
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def _day(d) -> str:
    if isinstance(d, (dt.date, dt.datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def svg(bars: list[dict], width: int = WIDTH, height: int = HEIGHT,
        title: str = "", label: str = "") -> str:
    """One candle per bar. Empty string when there is nothing to draw.

    ``bars`` is what prices.bars() returns: date, open, high, low, close.
    ``title`` names the series for a reader; ``label`` is the accessible
    description, and defaults to a sentence built from the window.
    """
    rows = []
    for b in bars or []:
        o, h, lo, c = (_num(b.get("open")), _num(b.get("high")),
                       _num(b.get("low")), _num(b.get("close")))
        if None in (o, h, lo, c):
            continue
        rows.append((_day(b.get("date")), o, h, lo, c))
    if not rows:
        return ""

    hi = max(r[2] for r in rows)
    low = min(r[3] for r in rows)
    span = hi - low or (hi or 1.0) * 0.02
    hi, low = hi + span * 0.06, low - span * 0.06
    span = hi - low

    plot_w = width - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    step = plot_w / len(rows)
    body = max(1.0, min(9.0, step * 0.62))

    def y_of(v: float) -> float:
        return PAD_T + (hi - v) / span * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="{height}" role="img" preserveAspectRatio="none" '
        f'aria-label="{html.escape(label or _sentence(rows, title))}">',
        f'<rect width="{width}" height="{height}" fill="{BG}"/>',
    ]
    # Three rules: the window's high, its midpoint and its low, priced on the
    # right. Enough to read a level off, few enough to stay out of the way.
    for v in (hi - span * 0.06, (hi + low) / 2, low + span * 0.06):
        y = y_of(v)
        parts.append(f'<line x1="{PAD_L}" x2="{PAD_L + plot_w:.1f}" '
                     f'y1="{y:.1f}" y2="{y:.1f}" stroke="{RULE}"/>')
        parts.append(f'<text x="{PAD_L + plot_w + 6:.1f}" y="{y + 3.5:.1f}" '
                     f'fill="{AXIS}" font-family="IBM Plex Mono,monospace" '
                     f'font-size="10">{_fmt(v)}</text>')

    for i, (day, o, h, lo, c) in enumerate(rows):
        x = PAD_L + step * (i + 0.5)
        up = c >= o
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y_of(h):.1f}" '
                     f'y2="{y_of(lo):.1f}" stroke="{WICK_UP if up else WICK_DOWN}" '
                     f'stroke-width="1"><title>{html.escape(day)} · O {_fmt(o)} '
                     f'H {_fmt(h)} L {_fmt(lo)} C {_fmt(c)}</title></line>')
        top, bottom = y_of(max(o, c)), y_of(min(o, c))
        parts.append(f'<rect x="{x - body / 2:.1f}" y="{top:.1f}" '
                     f'width="{body:.1f}" height="{max(1.0, bottom - top):.1f}" '
                     f'fill="{UP if up else DOWN}"/>')

    first, last = rows[0][0], rows[-1][0]
    parts.append(f'<text x="{PAD_L}" y="{height - 4}" fill="{AXIS}" '
                 f'font-family="IBM Plex Mono,monospace" font-size="10">{first}</text>')
    parts.append(f'<text x="{PAD_L + plot_w:.1f}" y="{height - 4}" fill="{AXIS}" '
                 f'font-family="IBM Plex Mono,monospace" font-size="10" '
                 f'text-anchor="end">{last}</text>')
    if title:
        parts.append(f'<text x="{PAD_L}" y="{PAD_T + 10}" fill="{AXIS}" '
                     f'font-family="IBM Plex Mono,monospace" font-size="10">'
                     f'{html.escape(title)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _sentence(rows: list[tuple], title: str) -> str:
    name = title or "the series"
    return (f"Daily candlestick chart of {name}, {len(rows)} sessions from "
            f"{rows[0][0]} to {rows[-1][0]}. Open, high, low and close per "
            f"session; green where the close was at or above the open.")
