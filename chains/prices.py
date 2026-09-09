"""Daily adjusted closes for every map entry that has a price symbol.

    from chains import prices
    prices.fetch_all(client)        # download and store
    prices.load("SHECY.US")         # read one back

STORAGE
-------
One parquet per symbol under ``<root>/chains/prices/``, columns
``date, symbol, adj_close, currency``. Partitioning by symbol rather than by
year because the access pattern is "give me this company's whole history" --
a chart line -- not "give me this date across companies".

CURRENCY IS CARRIED, NEVER CONVERTED
------------------------------------
Each series stays in the currency it trades in and the column says which.
Converting would import FX into a chart about chokepoints: a line for Tokyo
Electron converted to dollars moves when the yen moves, and a reader looking at
a chart titled "EUV lithography" would be looking partly at the dollar.

Nothing downstream needs the conversion either. Every comparison in
:mod:`chains.relative` is a ratio or a rebasing, and both are scale-free -- the
currency cancels. A basket rebases each member before averaging for the same
reason.

The one thing this does NOT buy: two series in different currencies cannot be
compared in level, only in shape. That is the correct limitation to have,
because the level comparison was never meaningful.

TWO PATHS TO THE SAME PARQUET
-----------------------------
With no cache, every series is downloaded whole from START. With a cache, only
the tail is fetched and merged. Both end at the same function, :func:`_write`,
so the schema is identical by construction rather than by two implementations
agreeing -- tested in tests/test_prices.py.

The tail fetch overlaps the stored history by OVERLAP_DAYS, and the overlap is
not thrown away: it is compared. ``adjusted_close`` is retroactive -- a split
rewrites every bar before it -- so a pure append would leave a series that is
correct after the split and wrong before it, joined at an invisible seam. When
the overlap disagrees by more than a rounding difference the whole series is
refetched. That is the only thing standing between an incremental build and a
chart with a step in it that no corporate action explains.

ADJUSTED, AND WHY IT IS THE VENDOR'S ADJUSTMENT HERE
----------------------------------------------------
``adjusted_close`` comes from EODHD. The swing lake computes its own adjustment
factors and validates them against corporate actions, because a strategy trades
on them and a wrong split silently rewrites history. This is a chart. The
vendor's adjustment is fit for that, and rebuilding the validation machinery
for a second dataset would be a large amount of work to make a picture very
slightly more correct. Recorded as a deliberate difference rather than an
oversight.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from chains.paths import prices_dir

START = "2019-01-01"

# How far back a tail fetch reaches before the last stored bar. Long enough to
# cover a holiday week plus a late vendor correction, short enough that the
# incremental path is still cheap.
OVERLAP_DAYS = 10

# Two adjusted closes for the same date are "the same" within this. Vendor
# floats wobble in the last place; a split moves them by a factor of 2 or more.
ADJ_TOLERANCE = 0.001

SCHEMA = {
    "date": pl.Date,
    "symbol": pl.Utf8,
    "adj_close": pl.Float64,
    "currency": pl.Utf8,
}

# EODHD exchange code -> trading currency. Deterministic: the exchange decides
# it, so it is a lookup and not a per-symbol field to fetch.
CURRENCY: dict[str, str] = {
    "US": "USD", "TW": "TWD", "TWO": "TWD", "KO": "KRW", "KQ": "KRW",
    "SHE": "CNY", "SHG": "CNY", "XETRA": "EUR", "F": "EUR", "AS": "EUR",
    "PA": "EUR", "BR": "EUR", "VI": "EUR", "MC": "EUR", "LS": "EUR",
    "SW": "CHF", "LSE": "GBP", "TO": "CAD", "AU": "AUD", "ST": "SEK",
    "CO": "DKK", "OL": "NOK", "HE": "EUR", "IR": "EUR",
}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def currency_for(symbol: str) -> str:
    """The currency a symbol trades in, from its exchange suffix.

    Unknown suffixes return "UNKNOWN" rather than defaulting to USD. A wrong
    currency label on a chart is a quiet error and a missing one is a loud one.
    """
    _, _, suffix = symbol.rpartition(".")
    return CURRENCY.get(suffix.upper(), "UNKNOWN")


def path_for(symbol: str) -> Path:
    return prices_dir() / f"{symbol.replace('.', '_')}.parquet"


def frame(symbol: str, rows: list[dict]) -> pl.DataFrame:
    """Vendor rows as the stored shape. The one place the schema is decided.

    The rejection rule lives here: a bar with no usable adjusted close is
    dropped rather than stored as a null, and a repeated date collapses to the
    last one the vendor sent. Both paths -- full download and tail append --
    go through this function, so neither can invent a column the other lacks.
    """
    if not rows:
        return pl.DataFrame(schema=SCHEMA)
    df = pl.DataFrame(
        {
            "date": [r.get("date") for r in rows],
            "symbol": [symbol] * len(rows),
            # coerced in Python, not by polars: the vendor mixes int and float
            # in one response and a strict Series build dies on the first int
            "adj_close": [_f(r.get("adjusted_close",
                                   r.get("adjClose", r.get("close"))))
                          for r in rows],
            "currency": [currency_for(symbol)] * len(rows),
        }
    ).with_columns(
        pl.col("date").cast(pl.Utf8).str.to_date(),
        pl.col("adj_close").cast(pl.Float64),
    ).drop_nulls("adj_close").unique(subset=["date"], keep="last").sort("date")
    return df.select(list(SCHEMA))


def _write(symbol: str, df: pl.DataFrame) -> int:
    p = path_for(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(SCHEMA)).write_parquet(p)
    return df.height


def store(symbol: str, rows: list[dict]) -> int:
    """Write one symbol's series whole. Returns the row count."""
    if not rows:
        return 0
    return _write(symbol, frame(symbol, rows))


def last_date(symbol: str):
    """The newest stored bar, or None when there is no cache for this symbol."""
    df = load(symbol)
    return None if df.is_empty() else df["date"].max()


def overlap_disagrees(stored: pl.DataFrame, fresh: pl.DataFrame) -> bool:
    """Do the two frames disagree about a date they both carry?

    True means the vendor has restated history -- a split, a dividend
    adjustment, a correction -- and the stored series is no longer on the same
    scale as the new bars. Appending across that seam would draw a step.
    """
    if stored.is_empty() or fresh.is_empty():
        return False
    both = stored.join(fresh, on="date", how="inner", suffix="_new")
    if both.is_empty():
        return False
    rel = ((both["adj_close_new"] - both["adj_close"]).abs()
           / both["adj_close"].abs().clip(lower_bound=1e-9))
    return bool(rel.max() > ADJ_TOLERANCE)


def append(symbol: str, rows: list[dict]) -> tuple[int, bool]:
    """Merge a tail fetch into the stored series.

    Returns (rows now stored, whether the whole series needs refetching). The
    caller does the refetch rather than this function, because it owns the
    client and the rate limit.
    """
    fresh = frame(symbol, rows)
    stored = load(symbol)
    if stored.is_empty():
        return _write(symbol, fresh), False
    if overlap_disagrees(stored, fresh):
        return stored.height, True
    merged = (pl.concat([stored, fresh], how="vertical")
              .unique(subset=["date"], keep="last")
              .sort("date"))
    return _write(symbol, merged), False


def load(symbol: str) -> pl.DataFrame:
    p = path_for(symbol)
    if not p.exists():
        return pl.DataFrame(schema=SCHEMA)
    return pl.read_parquet(p)


def load_many(symbols) -> pl.DataFrame:
    frames = [load(s) for s in symbols]
    frames = [f for f in frames if not f.is_empty()]
    return (pl.concat(frames, how="vertical") if frames
            else pl.DataFrame(schema=SCHEMA))


def symbols_in_map(doc: dict) -> list[str]:
    """Every distinct price symbol the map names, nodes and subnodes."""
    out: list[str] = []
    for coll in ("nodes", "subnodes"):
        for rec in doc.get(coll, []):
            s = rec.get("price_symbol")
            if s and s not in out:
                out.append(s)
            for extra in rec.get("price_members") or []:
                if extra not in out:
                    out.append(extra)
    return out


def challenger_symbols(doc: dict, resolve) -> list[str]:
    """Challenger tickers, resolved the same way node tickers are."""
    out: list[str] = []
    for lst in (doc.get("challengers") or {}).values():
        for c in lst or []:
            sym = resolve(c)
            if sym and sym not in out:
                out.append(sym)
    return out


def fetch_all(client, symbols, start: str = START, verbose: bool = True,
              incremental: bool = True) -> dict:
    """Download every symbol. One request each, two more for a restatement.

    Per symbol: no cache means the whole history from ``start``; a cache means
    the tail since the last stored bar, less an overlap. A tail whose overlap
    disagrees with what is stored costs a second request and is refetched
    whole -- the alternative is a series with a seam in it.

    Returns {symbol: rows stored}. A symbol the vendor has nothing for is 0,
    which is data, not an error: the map names companies that were listed once
    and companies that never were.
    """
    done: dict[str, int] = {}
    n_full = n_tail = n_refetch = 0
    for i, sym in enumerate(symbols, 1):
        since = last_date(sym) if incremental else None
        try:
            if since is None:
                done[sym] = store(sym, client.eod(sym, from_=start))
                n_full += 1
            else:
                frm = (since - timedelta(days=OVERLAP_DAYS)).isoformat()
                kept, restated = append(sym, client.eod(sym, from_=frm))
                if restated:
                    if verbose:
                        print(f"  {sym:<14} restated -- refetching whole series")
                    done[sym] = store(sym, client.eod(sym, from_=start))
                    n_refetch += 1
                else:
                    done[sym] = kept
                    n_tail += 1
        except Exception as exc:                       # noqa: BLE001
            done[sym] = 0
            if verbose:
                print(f"  {sym:<14} FAILED {type(exc).__name__}: {exc}"[:100])
            continue
        if verbose and i % 25 == 0:
            print(f"   {i}/{len(symbols)}")
    if verbose:
        print(f"  {n_full} downloaded whole, {n_tail} appended, "
              f"{n_refetch} refetched after a restatement")
    return done


def coverage(symbol: str, start: date, end: date) -> dict:
    """How much of the window this series actually prints in.

    ``weeks_with_a_bar`` is the density the drawing rule tests. Counted in
    calendar weeks rather than bars, because the question is whether a weekly
    chart has something to draw at each step, not how many trades happened.
    """
    df = load(symbol).filter(pl.col("date").is_between(start, end))
    total_weeks = max(1, (end - start).days // 7)
    weeks = (
        df.with_columns(pl.col("date").dt.truncate("1w").alias("w"))["w"]
        .n_unique() if not df.is_empty() else 0
    )
    return {
        "symbol": symbol,
        "bars": df.height,
        "weeks_with_a_bar": weeks,
        "weeks_in_window": total_weeks,
        "density": weeks / total_weeks,
        "first": str(df["date"].min()) if not df.is_empty() else None,
        "last": str(df["date"].max()) if not df.is_empty() else None,
        "currency": df["currency"][0] if not df.is_empty() else None,
    }
