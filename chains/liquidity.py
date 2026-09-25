"""Whether a basket leg's price line can carry a forecast: traded, and recently.

    python -m chains.liquidity --stale    # the nightly line: legs gone quiet (never fails)
    python -m chains.liquidity --report   # every leg's traded value, thinnest first

A leg is scored by its price, so the question is about the LINE, not the
company. TOK is a real supplier to TSMC; its only US line, TOKCF,
traded about US$8,500 a day and went three weeks without a close. A basket
leg priced on a line like that measures nothing.

THE GATE -- at commit time, in chains/preregister.py
----------------------------------------------------
Every leg of a question being committed or re-committed needs a price line
with a three-month average daily traded value (close x volume, converted to
US dollars) of at least MIN_ADV_USD, and a close within the last
GATE_SESSIONS completed sessions. A failing leg blocks --write and --recommit.
The figures used are stored beside the commitment in commitments.json --
informational, outside the hashed contract -- so a reader can see what the
line looked like the day the question was fixed.

THE NIGHTLY LINE -- in chains/build_all.py
------------------------------------------
From the price store, no vendor call: any basket leg with more than
STALE_SESSIONS sessions without a close is printed, and added to the run
summary in CI. It is a report. It changes nothing and never fails the build.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Callable

from chains import currencies

MIN_ADV_USD = 250_000
ADV_DAYS = 91               # "three months" of daily bars
GATE_SESSIONS = 3           # a close within the last three completed sessions
STALE_SESSIONS = 3          # the nightly line: more than this without a close

# The table lives in chains/currencies.py. It used to live here too, and
# the two copies drifted -- see that module. Re-exported under the old
# name because the report and the tests read it.
CURRENCY_BY_EXCHANGE = currencies.BY_SUFFIX


class LiquidityError(RuntimeError):
    """The check could not be run at all -- which is not the same as passing.

    Kept, and still raised by the provider underneath: a leg whose traded
    value could not be read is not a leg that passed. What changed is that the
    reason is no longer ever "the token is missing" -- the price source needs
    no key.
    """


def currency_of(symbol: str) -> str:
    """The venue's currency, or UNKNOWN.

    It used to answer "USD" for a suffix it did not know. That is how 2269.HK
    came to read 7.8x its real traded value: the closes were Hong Kong
    dollars, nothing converted them, and nothing raised. UNKNOWN reaches fx()
    below, finds no rate, and the leg is refused -- which is what an
    unmeasurable leg deserves.
    """
    return currencies.of(symbol)


def sessions_since(last: dt.date, today: dt.date) -> int:
    """Completed weekday sessions after ``last`` and before ``today``."""
    n, d = 0, last + dt.timedelta(days=1)
    while d < today:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


# ----------------------------------------------------------------- measuring
class Measure:
    """Three months of daily bars per symbol from the price vendor, with FX to
    dollars.

    ``measure(symbol)`` -> {symbol, adv_usd, adv_shares, sessions, last_close,
    currency} or {symbol, error}. One instance per run: symbols and rates are
    cached.
    """

    def __init__(self, today: dt.date, client=None):
        self.today = today
        if client is None:
            from chains.providers.yahoo import YahooClient
            client = YahooClient(rate_per_min=300)
        self.client = client
        self._got: dict[str, dict] = {}
        self._fx: dict[str, float | None] = {"USD": 1.0}

    def close(self) -> None:
        if hasattr(self.client, "close"):
            self.client.close()

    def _bars(self, symbol: str, days: int) -> list[dict]:
        frm = (self.today - dt.timedelta(days=days)).isoformat()
        return self.client.eod(symbol, from_=frm, to=self.today.isoformat())

    def fx(self, cur: str) -> float | None:
        if cur == "GBX":
            gbp = self.fx("GBP")
            return None if gbp is None else gbp / 100
        if cur not in self._fx:
            # USD->currency first, inverted. The direct quote is rounded to four
            # decimals, which for a won is one significant digit: KRWUSD reads
            # 0.0007 against 1/USDKRW = 0.000737, five percent off.
            rate = None
            inv = self._bars(f"USD{cur}.FOREX", 14)
            if inv and inv[-1].get("close"):
                rate = 1.0 / float(inv[-1]["close"])
            else:
                rows = self._bars(f"{cur}USD.FOREX", 14)
                if rows and rows[-1].get("close"):
                    rate = float(rows[-1]["close"])
            self._fx[cur] = rate
        return self._fx[cur]

    def __call__(self, symbol: str) -> dict:
        if symbol in self._got:
            return self._got[symbol]
        try:
            rows = [r for r in self._bars(symbol, ADV_DAYS) if r.get("volume") is not None and r.get("close")]
        except Exception as e:                                  # noqa: BLE001 -- reported per leg
            got = {"symbol": symbol, "error": f"price vendor: {type(e).__name__}"}
        else:
            cur = currency_of(symbol)
            rate = self.fx(cur) if rows else None
            if not rows:
                got = {"symbol": symbol, "error": "no daily bars with volume in three months"}
            elif rate is None:
                got = {"symbol": symbol, "error": f"no {cur}->USD rate from the price vendor"}
            else:
                got = {"symbol": symbol, "currency": cur, "sessions": len(rows), "last_close": rows[-1]["date"],
                       "adv_shares": sum(float(r["volume"]) for r in rows) / len(rows),
                       "adv_usd": rate * sum(float(r["volume"]) * float(r["close"]) for r in rows) / len(rows)}
        self._got[symbol] = got
        return got


# ----------------------------------------------------------------- the gate
def check_leg(leg: str, symbol: str | None, measure: Callable[[str], dict], today: dt.date) -> dict:
    rec: dict = {"leg": leg, "symbol": symbol, "ok": False}
    if not symbol:
        rec["why"] = "no price line on the map"
        return rec
    m = measure(symbol)
    if m.get("error"):
        rec["why"] = m["error"]
        return rec
    missing = sessions_since(dt.date.fromisoformat(m["last_close"]), today)
    rec.update(adv_usd=round(m["adv_usd"]), last_close=m["last_close"], sessions_missing=missing)
    problems = []
    if m["adv_usd"] < MIN_ADV_USD:
        problems.append(f"three-month average daily traded value US${m['adv_usd']:,.0f} is under US${MIN_ADV_USD:,}")
    if missing >= GATE_SESSIONS:
        problems.append(f"last close {m['last_close']} is {missing} completed sessions old -- a close within the "
                        f"last {GATE_SESSIONS} sessions is required")
    rec["ok"] = not problems
    rec["why"] = "; ".join(problems)
    return rec


def symbols_of(doc: dict) -> dict[str, str | None]:
    return {n["id"]: n.get("price_symbol") for n in doc.get("nodes", [])}


def legs_of(row: dict) -> list[str]:
    return [] if row.get("observe_only") else list(row.get("win") or []) + list(row.get("lose") or [])


def check_row(row: dict, doc: dict, measure: Callable[[str], dict], today: dt.date) -> dict:
    sym = symbols_of(doc)
    legs = [check_leg(i, sym.get(i), measure, today) for i in legs_of(row)]
    return {"qid": row.get("id") or row.get("qid"), "ok": all(x["ok"] for x in legs), "legs": legs}


def check_rows(rows: list[dict], doc: dict, measure: Callable[[str], dict] | None = None,
               today: dt.date | None = None) -> dict[str, dict]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    own = measure is None
    measure = measure or Measure(today)
    try:
        return {r.get("id") or r.get("qid"): check_row(r, doc, measure, today) for r in rows}
    finally:
        if own:
            measure.close()


def blocking_message(qid: str, result: dict) -> str:
    bad = [x for x in result["legs"] if not x["ok"]]
    return (f"{qid}: not committed -- {len(bad)} basket leg(s) fail the liquidity gate:\n"
            + "\n".join(f"    {x['leg']} ({x['symbol'] or 'no symbol'}): {x['why']}" for x in bad)
            + "\n  Replace or drop the leg, then run again.")


def describe(result: dict) -> str:
    lines = [f"  {result['qid']}: {'passes' if result['ok'] else 'FAILS'} the liquidity gate"]
    for x in result["legs"]:
        val = f"US${x['adv_usd']:,}/day, last close {x['last_close']}" if "adv_usd" in x else "no measure"
        lines.append(f"    {'ok  ' if x['ok'] else 'FAIL'} {x['leg']:<14} {str(x['symbol']):<12} {val}"
                     + (f" -- {x['why']}" if x["why"] else ""))
    return "\n".join(lines)


def stored(result: dict, day: str) -> dict:
    """What commitments.json keeps: the figures the gate passed on, that day."""
    return {"checked_at": day, "min_adv_usd": MIN_ADV_USD,
            "legs": {x["leg"]: {"symbol": x["symbol"], "adv_usd": x["adv_usd"], "last_close": x["last_close"]}
                     for x in result["legs"]}}


def record_problems(rec, committed_at: str) -> list[str]:
    if not isinstance(rec, dict) or set(rec) != {"checked_at", "min_adv_usd", "legs"}:
        return ["liquidity is not {checked_at, min_adv_usd, legs}"]
    out = []
    if rec["checked_at"] != committed_at:
        out.append("liquidity was not checked on the day the contract was committed")
    if not isinstance(rec["legs"], dict):
        return out + ["liquidity legs is not a mapping"]
    for leg, v in rec["legs"].items():
        if not isinstance(v, dict) or set(v) != {"symbol", "adv_usd", "last_close"}:
            out.append(f"liquidity leg {leg} is not {{symbol, adv_usd, last_close}}")
        elif not isinstance(v["adv_usd"], int) or v["adv_usd"] < rec["min_adv_usd"]:
            out.append(f"liquidity leg {leg} is recorded under the minimum it was checked against")
    return out


# ----------------------------------------------------------------- nightly
def stale_legs(rows: list[dict], doc: dict, sessions_of: Callable[[str], int | None] | None = None
               ) -> list[dict]:
    """Basket legs with more than STALE_SESSIONS sessions without a close, from
    the price store. ``sessions_of(symbol)`` is injectable for tests."""
    if sessions_of is None:
        from chains import forecast, track
        syms = sorted({s for s in symbols_of(doc).values() if s})
        book = forecast.Book(syms)
        cal = forecast.sessions([s for s in syms if s.endswith(".US")])

        def sessions_of(s):                                      # noqa: E306
            return track._stale(book, s, cal[-1], cal) if cal and book.has(s) else None
    sym = symbols_of(doc)
    by_leg: dict[str, dict] = {}
    for r in rows:
        for leg in legs_of(r):
            by_leg.setdefault(leg, {"leg": leg, "symbol": sym.get(leg), "questions": []})["questions"].append(
                r.get("id") or r.get("qid"))
    out = []
    for leg, v in by_leg.items():
        n = sessions_of(v["symbol"]) if v["symbol"] else None
        if n is None or n > STALE_SESSIONS:
            out.append(dict(v, sessions=n))
    return sorted(out, key=lambda v: (-(v["sessions"] or 10 ** 6), v["leg"]))


def stale_lines(flagged: list[dict]) -> list[str]:
    if not flagged:
        return [f"legs: no basket leg is more than {STALE_SESSIONS} sessions without a close"]
    return ([f"legs: {len(flagged)} basket leg(s) more than {STALE_SESSIONS} sessions without a close "
             f"(report only -- nothing is changed)"]
            + [f"  {v['leg']} {v['symbol'] or 'no symbol'}: "
               + ("no price series" if v["sessions"] is None else f"{v['sessions']} sessions without a close")
               + f" -- {', '.join(v['questions'])}" for v in flagged])


def main(argv: list[str] | None = None) -> int:
    import argparse
    from chains import mapfile
    from chains.paths import watch_path

    ap = argparse.ArgumentParser(prog="python -m chains.liquidity")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stale", action="store_true", help="the nightly line, from the price store; exits 0")
    mode.add_argument("--report", action="store_true", help="every leg's traded value")
    a = ap.parse_args(argv)
    rows = json.loads(watch_path().read_text(encoding="utf-8"))
    doc = mapfile.load()

    if a.stale:
        try:
            lines = stale_lines(stale_legs(rows, doc))
        except Exception as e:                                  # noqa: BLE001 -- a report never stops the build
            lines = [f"legs: check skipped ({type(e).__name__}: {e})"]
        print("\n".join(lines))
        summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        return 0

    try:
        results = check_rows(rows, doc)
    except LiquidityError as e:
        print(f"liquidity: {e}")
        return 1
    legs: dict[str, dict] = {}
    for qid, res in results.items():
        for x in res["legs"]:
            legs.setdefault(x["leg"], dict(x, questions=[]))["questions"].append(qid)
    print(f"{'leg':<14} {'symbol':<12} {'3-mo ADV (USD)':>16}  {'last close':<10}  gate  questions")
    for x in sorted(legs.values(), key=lambda x: x.get("adv_usd", -1)):
        adv = f"{x['adv_usd']:>16,}" if "adv_usd" in x else f"{'--':>16}"
        print(f"{x['leg']:<14} {str(x['symbol']):<12} {adv}  {x.get('last_close', '--'):<10}  "
              f"{'ok  ' if x['ok'] else 'FAIL'}  {', '.join(x['questions'])}" + (f"  ({x['why']})" if x["why"] else ""))
    failing = [q for q, r in results.items() if not r["ok"]]
    print(f"\n{len(results)} questions, {len(legs)} distinct legs; "
          f"{len(failing)} question(s) with a failing leg{': ' + ', '.join(failing) if failing else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
