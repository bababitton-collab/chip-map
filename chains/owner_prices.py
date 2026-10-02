"""Price-only feed for domain owners that are on no map (/domains/ chips).

    python -m chains.owner_prices   -> out/domains/owner_prices.json

The same provider (Yahoo) and the same 52-week return as the map cards
(chains.live_snapshot.ret over 365 days of adjusted closes), and the same
liquidity gate as a question leg (chains.liquidity: 91-day mean traded value
in USD and a close within the gate's sessions). Below the gate, the chip keeps
"—" (r52w is null).

These owners are NOT map nodes: nothing here is written to a map, a price
store a map reads, or any EW universe. The file is generated (out/ is not
committed) and rebuilt nightly as a build step of the root domain only.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# Yahoo suffix -> the repository's suffix, for its currency table.
REPO = {"": "US", "KS": "KO", "KQ": "KQ", "T": "T", "HE": "HE", "DE": "XETRA", "AX": "AU", "TO": "TO",
        "SZ": "SHE", "SS": "SHG", "SW": "SW", "L": "LSE", "HK": "HK", "BR": "BR", "PA": "PA", "AS": "AS",
        "TW": "TW", "TWO": "TWO", "MI": "MI", "VI": "VI", "CO": "CO", "ST": "ST"}


def out_path() -> Path:
    from chains.paths import out_dir
    return out_dir("semi").parent / "domains" / "owner_prices.json"


def map_tickers() -> set[str]:
    """Every priced node of every map, in Yahoo spelling."""
    from chains import domains, mapfile
    from chains.paths import map_path
    from chains.providers.yahoo import to_yahoo
    out = set()
    for dom in domains.discover():
        for n in mapfile.load(map_path(dom)).get("nodes", []):
            if n.get("price_symbol") and n.get("price_symbol_kind") != "none":
                try:
                    out.add(to_yahoo(n["price_symbol"]))
                except Exception:  # noqa: BLE001 -- a venue with no Yahoo spelling is not on Yahoo
                    pass
    return out


def owners_off_map() -> list[str]:
    from chains.paths import data_root
    p = data_root() / "domains" / "public.json"
    if not p.exists():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    on = map_tickers()
    return sorted({t for d in doc["domains"] for t in d.get("owners") or []} - on)


def measure(client, fx, ticker: str, today: dt.date) -> dict:
    from chains import currencies, liquidity
    from chains.live_snapshot import ret
    from chains.providers.yahoo import YahooClient, _epoch
    suf = ticker.rpartition(".")[2] if "." in ticker else ""
    cur = currencies.of(f"X.{REPO.get(suf, suf)}")
    try:
        payload = client._get(ticker, {"interval": "1d", "events": "div,split",
                                       "period1": _epoch(today - dt.timedelta(days=430)),
                                       "period2": _epoch(today, end=True)})
        bars = [b for b in YahooClient._rows(ticker, ticker, payload) if b.get("adjusted_close")]
    except Exception as e:  # noqa: BLE001 -- reported per ticker
        return {"r52w": None, "gate_ok": False, "why": f"price vendor: {type(e).__name__}"}
    if not bars:
        return {"r52w": None, "gate_ok": False, "why": "no bars"}
    rows = [(dt.date.fromisoformat(b["date"]), b["adjusted_close"]) for b in bars]
    last = rows[-1][0]
    recent = [b for b in bars if dt.date.fromisoformat(b["date"]) >= today - dt.timedelta(days=liquidity.ADV_DAYS)
              and b.get("volume") is not None and b.get("close")]
    rate = fx(cur)
    adv = rate * sum(b["close"] * b["volume"] for b in recent) / len(recent) if recent and rate else None
    why = []
    if adv is None:
        why.append(f"no traded value or no {cur}->USD rate")
    elif adv < liquidity.MIN_ADV_USD:
        why.append(f"91-day mean traded value US${adv:,.0f} under US${liquidity.MIN_ADV_USD:,}")
    if liquidity.sessions_since(last, today) >= liquidity.GATE_SESSIONS:
        why.append(f"last close {last} is stale")
    r = ret(rows, 365)
    return {"r52w": None if why or r is None else round(r, 4), "gate_ok": not why, "last": last.isoformat(),
            "adv_usd": None if adv is None else round(adv), "currency": cur, "why": "; ".join(why) or None}


def main(argv: list[str] | None = None) -> int:
    from chains import liquidity
    from chains.paths import DEFAULT_DOMAIN, domain
    from chains.providers.yahoo import YahooClient
    if domain() != DEFAULT_DOMAIN:
        print(f"owner prices: built once, with {DEFAULT_DOMAIN}; nothing to do for {domain()}")
        return 0
    tickers = owners_off_map()
    today = dt.date.today()
    with YahooClient(rate_per_min=60) as c:
        m = liquidity.Measure(today, client=c)
        rows = {t: measure(c, m.fx, t, today) for t in tickers}
    p = out_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"as_of": today.isoformat(), "owners": rows}, indent=1), encoding="utf-8",
                 newline="\n")
    below = [t for t, r in rows.items() if not r["gate_ok"]]
    print(f"owner prices: {len(rows)} owners on no map; {len(below)} below the gate or without data: {below}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
