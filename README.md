# chip-map

A living map of the AI chip supply chain: 49 stations from raw materials to
data centres, the 14 chokepoints where one or two companies hold something
nobody else can supply, and the dated questions that will change the picture.
Each chokepoint carries a pulse — the holder's 13-week return minus its listed
challengers' — so the map shows not just who holds a bottleneck but whether the
market thinks the hold is tightening or eroding. Beside it sits a forecast
board: every question that gets answered on a known day, and which earlier
question leaks part of the answer first. Every number carries a source URL;
where no source was found the figure is marked **estimate**, and estimates are
never quietly upgraded into facts.

Marked answers become a **forecast ledger**: the baskets that gain and lose are
pre-registered in `data/watch.json`, in git, before the event; the score runs
from the first close after the mark against an equal-weight index of the whole
map, at 5, 10 and 20 sessions. It is a forward test and it cannot be anything
else — a row whose baskets differ from the registered ones is refused. The
sample is small and every number carries its N, with `no capital decision below
N=30` attached to the summary at every horizon.

The whole thing rebuilds itself after every US session (05:30 UTC, Tue-Sat) on
GitHub Actions and serves itself from GitHub Pages. The two snapshots are also
force-pushed to an orphan `live` branch, so the current one is readable at
`https://raw.githubusercontent.com/bababitton-collab/chip-map/live/live.json`
without going through Pages. `python -m chains.build_all` runs eight steps in
dependency order — prices, repair, page, fundamentals, live, pages, and the two
briefs — and each one fails the run, because a green build that quietly served
a fortnight-old snapshot would be worse than a red one. Prices come from EODHD
(the only step needing a key, a repository secret) and are cached between runs,
so the first build downloads 138 full histories and later ones fetch only the
tail; an overlap is compared each time, because `adjusted_close` is retroactive
and a split would otherwise join two scales at an invisible seam. Fundamentals
come from SEC EDGAR's public companyfacts API with no key at all. Then
`python -m chains.publish_site` assembles `site/` and refuses to publish if a
single Hebrew character has reached the English page or its data file. Run it
locally with `pip install -r requirements.txt` and the same two commands;
`--skip-prices` builds everything from the cache and needs no key.

**This is a map of exposures. It is not a trading signal, not investment
advice, and not a recommendation to anyone.** It says which question is
answered on which day, who is affected if the answer is yes, and what to listen
for — not what to buy. The forecast board's "lean" is a count of hints that
have already been answered; there is no hypothesis behind it and no backtest
under it, deliberately. Prices lag by up to a week, each company is shown in
its own currency, and Japanese names are priced through US depositary receipts,
so two lines can be compared in shape but never in level.

---

## Layout

| | |
|---|---|
| `chains/` | the package: builders, page templates, the weekly entry point |
| `data/` | curated input, tracked: the map and the two dated-question lists |
| `out/` | derived output — prices, snapshots, pages, briefs. Gitignored |
| `site/` | what Pages serves, assembled by `chains/publish_site.py`. Gitignored |
| `tests/` | the suite, including the isolation check described below |
| `tools/tour/` | `render_tour.py`, which renders the map's tour mode to video. Run by hand, needs Chrome and ffmpeg, not part of CI; it drives the frozen page beside it because the templates carry no tour overlay |

Everything is configured by environment, with defaults relative to the
repository root, so a fresh clone builds with no configuration but the token:
`CHIP_MAP_DATA`, `CHIP_MAP_OUT`, `CHIP_MAP_SITE`, `CHIP_MAP_PRICES`,
`EODHD_API_TOKEN` (prices only), `ANSWERS_URL` (optional). See
`chains/paths.py`, which is the one file that knows where anything lives.

`tests/test_isolation.py` walks every module's AST and fails on an import of
the projects this was extracted from, or on any string that names a path
leaving the repository. That is not ceremony: this code used to read a 700 MB
database at an absolute path in a sibling project, and that single read is what
kept the build tied to one laptop.

## Before the first build

Two things a person has to do, both by hand:

1. **`EODHD_API_TOKEN`** — add it as a repository secret (Settings → Secrets
   and variables → Actions). Never paste it into a terminal or a chat.
2. **`CONTACT` in `chains/edgar.py`** — replace the placeholder with a real
   email address. SEC's fair-access policy requires a User-Agent identifying
   the caller, and rejects anything else with a 403.

Optionally, `ANSWERS_URL` as a repository *variable*: a link to the exported
answers, which colour the board. It is fetched with a short timeout, validated
row by row, and any failure logs one line and continues with none — the map
must never go dark because a share link expired.
