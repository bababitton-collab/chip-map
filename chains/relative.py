"""Rebased series, holder/challenger ratios, layer baskets, signal markers.

WHAT THE PAGE GETS, AND WHY IT IS SHAPED THIS WAY
-------------------------------------------------
Everything here is scale-free: a series divided by its own first value, or one
series divided by another. That is what lets Tokyo Electron in yen sit beside
ASML in euros on one chart without converting either. The currency cancels in a
ratio and in a rebasing, and it does not cancel in an average of raw prices --
which is why a basket rebases every member FIRST and averages the rebased
values, never the prices.

Averaging raw prices across currencies produces a number with no units. It
would still draw a line, and the line would look plausible, and it would be
meaningless. Stated here because that is the mistake this module exists to not
make.

THE DENSITY RULE
----------------
A series is stored regardless of how thinly it trades. It is DRAWN only if at
least 60% of the weeks in the chart window contain a bar. Below that it appears
in the legend as "line too thin to draw" with its bar count, and nothing is
interpolated, forward-filled, or bridged.

The alternative -- drawing a line through nineteen prints spread over twenty
months -- shows a reader a smooth trajectory that the data does not contain.
The gaps ARE the information: a line that prints four times a year is telling
you something about the security, and papering over it with interpolation
converts that signal into a fabricated shape.

MISSING IS EXPLICIT
-------------------
A chokepoint whose holder has no price line gets ``{"series": null, "reason":
...}``, never an absent key. A page that has to distinguish "no data" from
"key I forgot to read" will get it wrong on the day it matters.
"""
from __future__ import annotations

from datetime import date

import polars as pl

from chains import prices

MIN_WEEKLY_DENSITY = 0.60
MIN_BASKET_MEMBERS = 3
# how close to the window start a series must begin to count as covering it.
# Three weeks of slack for a holiday run or a late first print; not three years.
COVERS_WINDOW_SLACK_DAYS = 21


def weekly(df: pl.DataFrame) -> pl.DataFrame:
    """Last close in each calendar week. No fill: a week with no bar is absent."""
    if df.is_empty():
        return df
    return (
        df.sort("date")
        .with_columns(pl.col("date").dt.truncate("1w").alias("week"))
        .group_by("week")
        .agg(pl.col("adj_close").last(), pl.col("date").last())
        .sort("week")
        .rename({"week": "w"})
    )


def rebase(df: pl.DataFrame, start: date, end: date, base: float = 100.0):
    """Weekly series divided by its first value in the window, times 100.

    Returns (points, diagnostics). ``points`` is [[iso_week, value], ...] --
    a list of pairs rather than two arrays, so a gap cannot silently misalign
    the dates against the values.
    """
    sub = df.filter(pl.col("date").is_between(start, end))
    w = weekly(sub)
    weeks_in_window = max(1, (end - start).days // 7)
    first_bar = sub["date"].min() if not sub.is_empty() else None
    own_weeks = max(1, ((end - first_bar).days // 7)) if first_bar else 1
    diag = {
        "bars": sub.height,
        "weeks_with_a_bar": w.height,
        "weeks_in_window": weeks_in_window,
        "density_in_window": round(w.height / weeks_in_window, 3),
        "density_since_first_bar": round(w.height / own_weeks, 3),
        "first_bar": str(first_bar) if first_bar else None,
        "currency": df["currency"][0] if not df.is_empty() else None,
    }
    # THIN and YOUNG are different problems and only one is a reason not to draw.
    # GE Vernova listed in March 2024: it covers 32% of a window that starts in
    # 2019 and 101% of its own life. Refusing to draw it would hide a liquid
    # company because it is new, while drawing it from its first print
    # interpolates nothing -- the line simply starts later, which is true.
    # Tokyo Ohka Kogyo covers 11% of its own life. That is thin, and a line
    # through it would be an interpolation presented as a measurement.
    # COVERAGE and DENSITY are different questions and the basket needs the
    # first one. CRDO listed in January 2022 and prints every week since, so it
    # covers 61% of a window opening in 2019 -- over the density threshold, and
    # still absent for the first three years. Judging membership on density
    # alone let it in, and the basket then silently truncated to the date CRDO
    # started, throwing away 2019-2021 for every other member.
    diag["covers_window"] = bool(
        first_bar is not None
        and (first_bar - start).days <= COVERS_WINDOW_SLACK_DAYS
    )
    diag["drawable"] = diag["density_since_first_bar"] >= MIN_WEEKLY_DENSITY
    if not diag["drawable"]:
        diag["classification"] = "too_thin"
        diag["reason"] = (f"line too thin to draw -- {diag['bars']} bars in the "
                          f"window, {w.height} of {weeks_in_window} weeks")
    elif not diag["covers_window"]:
        diag["classification"] = "short_history"
        diag["note"] = (f"drawn from {diag['first_bar']}, not thin: "
                        f"{diag['density_since_first_bar']:.0%} of the weeks "
                        f"since its first print")
    else:
        diag["classification"] = "ok"
    if w.is_empty():
        return [], {**diag, "drawable": False,
                    "reason": "no bars in the window"}
    first = w["adj_close"][0]
    if not first:
        return [], {**diag, "drawable": False, "reason": "first value is zero"}
    pts = [[str(a), round(b / first * base, 2)]
           for a, b in zip(w["w"].to_list(), w["adj_close"].to_list())]
    return pts, diag


def ratio(a: pl.DataFrame, b: pl.DataFrame, start: date, end: date):
    """Holder over challenger, as the QUOTIENT OF THE TWO REBASED SERIES.

    Defined this way on purpose. The page does not receive a ratio series -- it
    divides the two rebased lines it already has -- so there must be exactly one
    definition of what that quotient is, and it must be this one. An earlier
    version rebased the raw ratio to 100 at the first common week, which agrees
    with the page's arithmetic only when both series start on the same week and
    silently disagrees by a constant factor when they do not.

    Both sides rebase against their OWN first value in the window, so the
    quotient starts at 100 only when they begin together. When the challenger
    lists later, the line starts wherever the holder had got to by then, which
    is the honest picture: the challenger did not exist before that.
    """
    pa, _ = rebase(a, start, end)
    pb, _ = rebase(b, start, end)
    if not pa or not pb:
        return [], {"weeks": 0, "reason": "one side has no bars in the window"}
    da, db = dict(pa), dict(pb)
    common = sorted(set(da) & set(db))
    if not common:
        return [], {"weeks": 0, "reason": "no week where both printed"}
    pts = [[w, round(da[w] / db[w] * 100.0, 2)] for w in common if db[w]]
    return pts, {"weeks": len(pts),
                 "definition": "rebased_holder / rebased_challenger * 100"}


def basket(symbols: list[str], start: date, end: date):
    """Equal-weight basket: rebase EVERY member, then average the rebased values.

    Not the average of the prices. Members trade in yen, euros, won and dollars,
    and the mean of those is a number with no units that still draws a line.
    Rebasing first makes every member a pure index and the average meaningful.

    A member is included only if it is drawable on its own; a series too thin to
    draw is too thin to contribute to an average, where its staleness would be
    hidden by the other members rather than visible as a gap.
    """
    # A basket takes only members that COVER THE WINDOW. A member that listed
    # halfway through is drawable on its own -- its line simply starts later --
    # but inside an average it is different: the basket would either truncate
    # to the newest member's history, throwing away years of the others, or
    # jump on the week that member joins. Both are artefacts of composition
    # rather than facts about the layer.
    #
    # Coverage, not density: CRDO prints every week since January 2022, which
    # is 61% of a 2019 window and enough to pass a density test, and it was
    # still absent for three of the seven years.
    used, skipped, series = [], [], {}
    for s in symbols:
        pts, diag = rebase(prices.load(s), start, end)
        if pts and diag.get("covers_window") and diag.get("drawable"):
            series[s] = dict(pts)
            used.append(s)
        else:
            skipped.append({
                "symbol": s,
                "reason": diag.get("reason") or diag.get("note") or "no data",
                "classification": diag.get("classification", "no_data"),
            })
    diag = {
        "member_count": len(used),
        "members": used,
        "excluded": skipped,
        "note": "each member rebased to 100 first, then averaged",
    }
    if not series:
        return [], {**diag, "reason": "no member covers the whole window"}
    if len(series) < MIN_BASKET_MEMBERS:
        # A "layer basket" of two companies is not a basket, it is two
        # companies with the label of a sector. Below three the average stops
        # describing the layer and starts describing whoever happens to be in
        # it, so it is not drawn and the count says why.
        return [], {**diag,
                    "reason": (f"only {len(series)} full-window member(s); "
                               f"a basket needs {MIN_BASKET_MEMBERS}")}
    weeks = sorted(set().union(*(set(v) for v in series.values())))
    pts = []
    for w in weeks:
        vals = [v[w] for v in series.values() if w in v]
        if len(vals) == len(series):      # every member printed that week
            pts.append([w, round(sum(vals) / len(vals), 2)])
    return pts, {**diag, "weeks": len(pts)}


def markers(doc: dict) -> dict[str, list[dict]]:
    """Every challenger signal that carries an as_of date, by chokepoint."""
    out: dict[str, list[dict]] = {}
    for cp, lst in (doc.get("challengers") or {}).items():
        for c in lst or []:
            when = c.get("as_of")
            if not when:
                continue
            out.setdefault(cp, []).append({
                "date": when,
                "challenger": c.get("name"),
                "label": (str(c.get("signal") or "")[:160]),
                "stage": c.get("stage"),
                "source": c.get("signal_source"),
            })
    for cp in out:
        out[cp].sort(key=lambda m: m["date"])
    return out


def label_for(rec: dict) -> dict:
    """The legend label, taken from the map rather than decided here.

    The display rules were written into v2.1 precisely so this function has
    nothing to choose: a category node charts under its member's name, a parent
    proxy carries "(parent)", a renamed company carries its former name.
    """
    return {
        "name": rec.get("display_name") or rec.get("name"),
        "note": rec.get("legend_note"),
        "rule": rec.get("display_rule"),
        "symbol": rec.get("price_symbol"),
        "symbol_kind": rec.get("price_symbol_kind"),
        "price_note": rec.get("price_note"),
    }
