"""Round-trip bad prints in the chains price store.

THE SHAPE
---------
A bar that moves more than 5x and gives at least 80% of it straight back the
next print. A security cannot do that. The swing lake has carried this detector
since the level-shift work (swing/data/exclusions.py, ROUND_TRIP_LOG_MOVE =
ln 5, ROUND_TRIP_REVERSAL = 0.8) and the same thresholds are used here, so the
two stores agree on what an impossible move is.

The detector is reimplemented rather than imported: chains may not import swing,
and a shared constant is not worth a shared dependency. The values are quoted
above so a change in one is visible as a difference from the other.

WHY THIS STORE NEEDS IT TOO
---------------------------
300604.SHE printed 12,163,602 on a rebased scale on 2019-04-29 with neighbours
at 117 and 111. One bad print in one series was enough to make a log axis
useless for the whole chart, and it was only noticed because it was large. A
print that is merely wrong by 5x breaks nothing visually and is still wrong.

WHAT REPAIR MEANS HERE
----------------------
The bar's price is NULLED, not deleted and not corrected. Nulling keeps the
date in the series as a day that exists with no usable price, which is what the
weekly resampler and the density rule already know how to handle. Correcting it
would mean inventing a number.

Every nulled bar is written to round_trip_backup.parquet first, whole, so the
repair reverses with one write.
"""
from __future__ import annotations

import math

import polars as pl

from chains import prices
from chains.paths import out_dir

LOG_MOVE = math.log(5.0)      # a print that moves more than 5x
REVERSAL = 0.8                # and gives at least 80% of it straight back


def backup_path():
    return out_dir() / "round_trip_backup.parquet"


def events(df: pl.DataFrame) -> pl.DataFrame:
    """Bars in one series that leave the level and come straight back.

    A RUN, not a single bar. The first version compared each bar against its
    two neighbours, which cannot see a spike lasting more than one print:
    300604.SHE holds 985,531.5864 on BOTH 2019-04-29 and 2019-04-30 against
    neighbours near 10, so for the first bad bar the next move was zero and for
    the second the previous move was zero, and the round trip was invisible
    from either end. Ibiden holds the same wrong value on eight separate US
    market holidays.

    So: find where the price leaves its level by more than 5x, follow the run
    for as long as it stays away, and accept it as a bad print only when the
    first bar after the run returns to within 20% of where the price was before
    it. A move that leaves and STAYS is a different thing -- a split, a
    redenomination, a real repricing -- and this must not touch it.
    """
    empty = df.head(0).with_columns(
        pl.lit(0.0).alias("move_in"), pl.lit(0.0).alias("move_out"))
    if df.height < 3:
        return empty
    d = df.sort("date")
    px = d["adj_close"].to_list()
    dates = d["date"].to_list()
    bad: list[int] = []
    i = 1
    while i < len(px) - 1:
        before = px[i - 1]
        if not before or not px[i]:
            i += 1
            continue
        move_in = math.log(px[i] / before)
        if abs(move_in) <= LOG_MOVE:
            i += 1
            continue
        # follow the run while it stays away from the pre-run level
        j = i
        while j < len(px) and px[j] and abs(math.log(px[j] / before)) > LOG_MOVE:
            j += 1
        if j >= len(px) or not px[j]:
            i = j + 1                     # runs to the end: not a round trip
            continue
        back = math.log(px[j] / before)
        if abs(back) < (1.0 - REVERSAL) * abs(move_in):
            bad.extend(range(i, j))
        i = j + 1 if j > i else i + 1
    if not bad:
        return empty
    return d[bad].with_columns(
        pl.lit(0.0).alias("move_in"), pl.lit(0.0).alias("move_out")
    ).with_columns(
        pl.Series("move_in", [math.log(px[k] / px[k - 1]) if px[k - 1] else 0.0
                              for k in bad]),
        pl.Series("move_out", [
            math.log(px[k + 1] / px[k]) if k + 1 < len(px) and px[k] else 0.0
            for k in bad]),
    )


def scan_all(symbols) -> pl.DataFrame:
    """Every round-trip print across the whole chains store."""
    found = []
    for sym in symbols:
        df = prices.load(sym)
        ev = events(df)
        if ev.is_empty():
            continue
        found.append(ev.select(
            "symbol", "date", "adj_close", "currency", "move_in", "move_out"))
    if not found:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "date": pl.Date, "adj_close": pl.Float64,
            "currency": pl.Utf8, "move_in": pl.Float64, "move_out": pl.Float64})
    return pl.concat(found, how="vertical").sort(["symbol", "date"])


def repair(found: pl.DataFrame, dry_run: bool = False) -> int:
    """Null the price on every detected bar. Backs the rows up first."""
    if found.is_empty():
        return 0
    if dry_run:
        return found.height
    p = backup_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    found.write_parquet(p)
    for sym in found["symbol"].unique().to_list():
        bad = set(found.filter(pl.col("symbol") == sym)["date"].to_list())
        df = prices.load(sym)
        fixed = df.with_columns(
            pl.when(pl.col("date").is_in(list(bad)))
            .then(None)
            .otherwise(pl.col("adj_close"))
            .alias("adj_close")
        ).drop_nulls("adj_close")
        fixed.write_parquet(prices.path_for(sym))
    return found.height


def restore() -> int:
    """Put every nulled bar back. The repair has a way home or it is not run."""
    p = backup_path()
    if not p.exists():
        return 0
    back = pl.read_parquet(p)
    for sym in back["symbol"].unique().to_list():
        rows = back.filter(pl.col("symbol") == sym).select(
            "date", "symbol", "adj_close", "currency")
        df = pl.concat([prices.load(sym), rows], how="vertical")
        df.unique(subset=["date"], keep="last").sort("date").write_parquet(
            prices.path_for(sym))
    return back.height
