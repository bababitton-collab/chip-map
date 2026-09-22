"""One page per question whose answer is in, at /<domain>/track/<qid>/.

    from chains import record_page
    record_page.render(card, dom)

WHY IT IS ITS OWN PAGE
----------------------
The forward-test page is a list of cards, and a card is a summary: the
question, the mark, the forecast map and one line saying what the basket did
against the map. The evidence behind that line -- every leg with its prices
and its share of the number, both benchmarks over the same window, and each
company's own path -- is a page's worth of material. Putting it on the card
buried the card; putting it here gives it room and gives the reader a link
they can send to somebody.

WHAT IT DRAWS, AND WHY IN THAT ORDER
------------------------------------
One question, read top to bottom: what was claimed, what the basket did
against its benchmarks, which leg moved the number, and then each company on
its own. Every chart shares one axis convention -- everything is rebased to
100 at the session the contract was signed on -- because two scales on one
picture is how a chart lies without saying anything false.

Everything here was measured by chains/record.py at build time from EODHD
end-of-day data. The page fetches nothing; the numbers are already in it.

WHAT IT REFUSES TO SAY
----------------------
A leg with no clean series is a row that says so. A basket with no series gets
a sentence, not an empty frame. The second ring is measured and shown, and it
is never averaged into the basket: a ring-2 leg has a bar of its own move and
no contribution, because it contributed nothing to a basket it was not in.
And whether the question counts toward the official score is track.official()'s
answer, repeated verbatim.
"""
from __future__ import annotations

import html
import json

# Served from this site, never from a CDN. chains/track.py copies both files
# next to the pages and chains/publish_site.py gates them like everything else.
VENDOR = ("lightweight-charts.standalone.production.js",
          "lightweight-charts.LICENSE.txt")
CREDIT = ("Charts drawn with TradingView Lightweight Charts™ "
          "(Apache-2.0), served from this site.")

TITLE = "{who} · track record · Linchpin Signal"
DESC = ("What the pre-registered basket did after {who} reported on {date}, "
        "measured against the equal-weight map and {bench_label}.")


NOT_ADVICE = "Research and analysis only. Not investment advice."
METHOD = (
    "Every price is EODHD end-of-day. The window runs from the session the "
    "scoring contract was signed on to the last close, and every chart on "
    "this page is rebased to 100 at that first session so one axis carries "
    "all of them. A basket is the equal weight of the legs that have a clean "
    "series, held from the first day of the window; each leg's contribution "
    "is its own move divided by the number of legs on its side. The second "
    "ring is measured over the same window and reported separately -- it is "
    "never averaged into the basket, so its legs carry a move and no "
    "contribution. EW_MAP is the equal-weight return of every priced station "
    "on the map, rebalanced daily; {bench_label} is {bench_symbol}. A leg "
    "priced through an ADR or OTC line is marked, and the number is the line "
    "that actually traded. Company lines are drawn from adjusted closes, the "
    "same source the basket and the benchmarks are measured from.")


def method_text(dom: str | None = None) -> str:
    """The methodology paragraph with this domain's benchmark named in it.

    The comparison line is part of the method, so it cannot be a fixed word:
    telling a reader of one industry's page that the second benchmark is
    another industry's index would describe a measurement nobody made.
    """
    from chains import forecast
    b = forecast.benchmark_for(dom)
    return METHOD.format(bench_label=b["label"], bench_symbol=b["symbol"])

# One axis, one convention: green is the basket and what rose, red is what
# fell, amber is SOX, grey is the benchmark map.
HERO_LINES = (("win", "Basket", "#3fd18b"),
              ("ew", "EW_MAP", "#7d8797"),
              ("sox", "SOX", "#f2b632"))


def hero_lines(dom: str | None = None) -> tuple:
    """The three lines and what to call them.

    The key stays "sox" wherever the number is stored -- that is the series
    name inside the record, and renaming it would move data nobody asked to
    move. What changes per domain is the LABEL, because a reader of an energy
    page must not be told the comparison line is a semiconductor index.
    """
    from chains import forecast
    label = forecast.benchmark_for(dom)["label"]
    return (HERO_LINES[0], HERO_LINES[1], ("sox", label, "#f2b632"))
COMPANY_COLOURS = ("#3fd18b", "#f2b632", "#5aa9ff", "#c084fc", "#2dd4bf",
                   "#fb923c", "#94a3b8", "#f472b6")
UP, DOWN = "#3fd18b", "#ff5a3c"


def esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def pct(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def num(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 10000 else f"{v:,.2f}"


def cls(v) -> str:
    return "flat" if v is None else ("pos" if v > 0 else ("neg" if v < 0 else "flat"))


def _tile(value: str, label: str, tone: str = "") -> str:
    return (f'<div class="tile"><b class="{tone}">{value}</b>'
            f'<span>{esc(label)}</span></div>')


def _legend(items) -> str:
    """A key for every chart carrying more than one series."""
    chips = "".join(f'<span class="chip"><i style="background:{col}"></i>'
                    f'{esc(label)}</span>' for label, col in items)
    return f'<div class="legendrow">{chips}</div>' if chips else ""


def _question(card: dict) -> str:
    out = []
    if card.get("q"):
        out.append(f'<p class="q">{esc(card["q"])}</p>')
    yes, no = card.get("yes"), card.get("no")
    if yes or no:
        out.append('<div class="yn">'
                   + (f'<div class="y"><b>Yes looks like</b>{esc(yes)}</div>' if yes else "")
                   + (f'<div class="n"><b>No looks like</b>{esc(no)}</div>' if no else "")
                   + "</div>")
    if card.get("why"):
        out.append(f'<p class="sub">{esc(card["why"])}</p>')
    for key, label in (("note", "What the report said"), ("evidence", "Evidence")):
        if card.get(key):
            out.append(f'<div class="said"><b>{label}</b>{esc(card[key])}</div>')
    return "".join(out)


# -- the charts --------------------------------------------------------------
def _hero(rec: dict, dom: str | None = None) -> str:
    """The basket against both benchmarks, all three rebased to 100."""
    b = rec.get("benchmarks") or {}
    s = b.get("series") or {}
    lines = hero_lines(dom)
    if len(s.get("dates") or []) < 2:
        return ('<p class="note">One session in this window, so there is no '
                'line to draw yet. It appears with the next close.</p>')
    return (f'<div class="chartbox hero">'
            f'<h3>Basket · EW_MAP · {esc(lines[2][1])}'
            f'<em>rebased to 100 · {esc(b.get("from"))} → '
            f'{esc(b.get("to"))}</em></h3>'
            f'{_legend([(lab, col) for key, lab, col in lines if s.get(key)])}'
            f'<div class="lw" id="lw-hero"></div>'
            f'<p>Each line starts at 100 on the session the contract was '
            f'signed on. Hover or touch a session to read all three.</p></div>')


def _contrib(rec: dict) -> str:
    """Horizontal bars around zero: who moved the number, and by how much.

    Drawn here rather than in the chart library. Bars around a zero axis are
    two divs and a width, they need no canvas, and they stay readable with no
    script running at all.
    """
    legs = rec.get("legs") or []
    ring1 = [l for l in legs if l.get("ring") != 2]
    ring2 = [l for l in legs if l.get("ring") == 2]
    if not legs:
        return '<p class="note">No legs were registered for this question.</p>'

    def value(leg):
        # Ring 1 put a share into the basket. Ring 2 was never in it, so what
        # it has is its own move over the same window.
        return leg.get("contribution") if leg.get("ring") != 2 \
            else leg.get("since_commit")

    if not [l for l in legs if value(l) is not None]:
        return ('<p class="note">No leg in this basket has a clean series over '
                'this window, so there is nothing to size a bar against.</p>')

    def block(group, title, note):
        """One group of bars, sized against its own widest.

        Each group is scaled to itself on purpose. A share of the basket's
        return and a ring-2 leg's own move are different measures, and one
        shared maximum would invite the reader to compare them by length --
        which is the one thing these two groups cannot do. The widest bar of
        each group is stated so the eye has a number to hold on to.
        """
        vals = [value(l) for l in group if value(l) is not None]
        scale = max((abs(v) for v in vals), default=0.0) or 1.0
        out = []
        for leg in group:
            v = value(leg)
            if v is None:
                out.append(f'<div class="crow"><span class="cname">'
                           f'{esc(leg.get("tk"))}</span>'
                           f'<span class="ctrack"></span>'
                           f'<span class="cval flat">no clean series</span></div>')
                continue
            w = abs(v) / scale * 50.0
            side = "right:50%" if v < 0 else "left:50%"
            out.append(
                f'<div class="crow"><span class="cname">{esc(leg.get("tk"))}</span>'
                f'<span class="ctrack"><i class="{cls(v)}" '
                f'style="{side};width:{w:.2f}%"></i></span>'
                f'<span class="cval {cls(v)}">{pct(v)}</span></div>')
        head = (f'<h4 class="csub">{title}<span>{note} Widest bar here is '
                f'{scale:.2f} percentage points.</span></h4>')
        return f'{head}<div class="cbars">{"".join(out)}</div>'

    blocks = [block(ring1, "The basket · share of its return",
                    "Each leg's own move over the window, divided by the "
                    "number of legs on its side; these add up to the basket "
                    "number above.")]
    if ring2:
        blocks.append(block(
            ring2, "Second ring · own move, not in the basket",
            "Measured over the same window and reported separately, never "
            "averaged into the number above. Scaled to itself: these bars are "
            "a different measure from the ones above and cannot be compared "
            "by length."))
    return f'<div class="chartbox wide">{"".join(blocks)}</div>'


def _companies(rec: dict) -> str:
    """Every basket company on one pair of axes, all rebased to 100."""
    cs = rec.get("companies") or []
    if not cs:
        return ('<p class="note">No basket company has a clean series over '
                'this window, so no lines are drawn.</p>')
    items = [(c.get("tk"), COMPANY_COLOURS[i % len(COMPANY_COLOURS)])
             for i, c in enumerate(cs)]
    return (f'<div class="chartbox wide"><h3>The basket, company by company'
            f'<em>rebased to 100 · {esc(rec.get("baseline"))} → '
            f'{esc(rec.get("last_session"))}</em></h3>'
            f'{_legend(items)}'
            f'<div class="lw" id="lw-companies"></div>'
            f'<p>Adjusted closes, each rebased to 100 on the first session of '
            f'the window so the lines can be read against one another. Hover '
            f'or touch a session for every company at once.</p></div>')


# -- the table ---------------------------------------------------------------
def _leg_row(leg: dict, rec: dict) -> str:
    via = ""
    if leg.get("priced_via") and leg["priced_via"] != "primary":
        via = (f'<span class="via" title="priced through the '
               f'{esc(str(leg["priced_via"]).upper())} line '
               f'{esc(leg.get("symbol"))}">{esc(leg["priced_via"])}</span>')
    name = f'{esc(leg.get("tk"))}{via}'
    side = f'<span class="side">{esc(leg.get("group"))}</span>'
    if leg.get("no_series"):
        return (f'<tr class="nos"><td>{name}</td><td>{side}</td>'
                f'<td colspan="6">{esc(leg["no_series"])}</td></tr>')
    entry = leg.get("entry_close")
    return (
        f'<tr><td>{name}</td><td>{side}</td>'
        f'<td>{esc(leg.get("entry_date") or rec.get("baseline"))}</td>'
        f'<td>{num(entry if entry is not None else leg.get("commit_close"))}</td>'
        f'<td>{num(leg.get("last"))}</td>'
        f'<td class="{cls(leg.get("day_pct"))}">{pct(leg.get("day_pct"))}</td>'
        f'<td class="{cls(leg.get("since_commit"))}">{pct(leg.get("since_commit"))}</td>'
        f'<td class="{cls(leg.get("contribution"))}">'
        f'{pct(leg.get("contribution")) if leg.get("ring") != 2 else "—"}</td></tr>')


def _legs_table(rec: dict) -> str:
    head = ("<tr><th>Company</th><th>Side</th><th>From</th><th>Price</th>"
            "<th>Last</th><th>Day</th><th>Since signed</th>"
            "<th>Contribution</th></tr>")
    legs = rec.get("legs") or []
    ring1 = [l for l in legs if l.get("ring") != 2]
    ring2 = [l for l in legs if l.get("ring") == 2]
    rows = [_leg_row(l, rec) for l in ring1]
    if not rows:
        rows.append('<tr class="nos"><td colspan="8">no legs were registered '
                    'for this question</td></tr>')
    if ring2:
        # Its own band in the same table: the same measurement over the same
        # window, kept visibly apart from the basket it is not part of.
        rows.append('<tr class="grp"><td colspan="8">second ring · measured, '
                    'not in the basket</td></tr>')
        rows.extend(_leg_row(l, rec) for l in ring2)
    return f'<div class="tw"><table class="legs">{head}{"".join(rows)}</table></div>'


def _meta(card: dict, rec: dict) -> str:
    official = rec.get("official") or {}
    verdict = rec.get("verdict") or card.get("status")
    return (
        '<div class="meta">'
        f'<div><span class="k">Question id</span>{esc(card.get("qid"))}</div>'
        f'<div><span class="k">Answered</span>{esc(rec.get("answer_date"))}</div>'
        f'<div><span class="k">Verdict</span>{esc(verdict)}</div>'
        f'<div><span class="k">Contract signed</span>{esc(rec.get("committed_at"))}</div>'
        f'<div><span class="k">Window</span>{esc(rec.get("baseline"))} → '
        f'{esc(rec.get("last_session"))}</div>'
        f'<div><span class="k">SHA-256</span><span class="hash">'
        f'{esc(rec.get("sha256"))}</span></div>'
        f'<div><span class="k">Official score</span>'
        f'{"counts" if official.get("counts") else "not counted"} — '
        f'{esc(official.get("reason"))}</div>'
        '</div>')


def _payload(rec: dict, dom: str | None = None) -> str:
    """Only what the two line charts draw, and nothing that is already text."""
    b = (rec.get("benchmarks") or {}).get("series") or {}
    HERO = hero_lines(dom)
    data = {
        "dates": b.get("dates") or [],
        # Rebased here rather than in the browser: one convention, applied
        # once, in the same file that documents it.
        "hero": [{"label": label, "color": col,
                  "values": [None if v is None else round(100.0 + v, 4)
                             for v in b.get(key) or []]}
                 for key, label, col in HERO if b.get(key)],
        "companies": [{"label": c.get("tk"),
                       "color": COMPANY_COLOURS[i % len(COMPANY_COLOURS)],
                       "values": c.get("values") or []}
                      for i, c in enumerate(rec.get("companies") or [])],
    }
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return f'<script id="record-data" type="application/json">{blob}</script>'


# No framework and no fetch: the data is already in the page and this only
# draws it. If the library is missing the function returns and the page keeps
# its tiles, its bars and its table -- every number on it is text.
CHART_JS = """
(function(){
  var LW = window.LightweightCharts, el = document.getElementById('record-data');
  if(!LW || !el) return;
  var D = {};
  try { D = JSON.parse(el.textContent); } catch(e) { return; }
  if(!(D.dates||[]).length) return;
  var THEME = {
    layout:{background:{color:'#141922'},textColor:'#7d8797',
            fontFamily:'IBM Plex Mono, monospace',fontSize:10,
            attributionLogo:false},
    grid:{vertLines:{color:'#1a212c'},horzLines:{color:'#1a212c'}},
    rightPriceScale:{borderColor:'#222a36'},
    timeScale:{borderColor:'#222a36',fixLeftEdge:true,fixRightEdge:true},
    crosshair:{mode:0,
      vertLine:{color:'#3a4658',width:1,style:2,labelBackgroundColor:'#222a36'},
      horzLine:{color:'#3a4658',width:1,style:2,labelBackgroundColor:'#222a36'}},
    // A window this short has nothing to pan to, so scaling and mouse panning
    // are off. Horizontal touch stays ON -- it is what raises the crosshair
    // under a thumb. Vertical touch is left to the page, so the chart can
    // never swallow a scroll.
    handleScroll:{mouseWheel:false, pressedMouseMove:false,
                  horzTouchDrag:true, vertTouchDrag:false},
    handleScale:false
  };
  function n2(v){ return (v==null||isNaN(v)) ? '\\u2014' : Number(v).toFixed(2); }
  function tfmt(t){
    if(typeof t === 'string') return t;
    if(t && t.year) return t.year + '-' + String(t.month).padStart(2,'0')
      + '-' + String(t.day).padStart(2,'0');
    return '';
  }
  function tipFor(box){
    var t = document.createElement('div');
    t.className = 'lwtip'; t.style.display = 'none';
    box.appendChild(t); return t;
  }
  function place(t, box, x0){
    t.style.display = 'block';
    var w = t.offsetWidth, x = x0 + 14;
    if(x + w + 10 > box.clientWidth) x = x0 - w - 14;
    t.style.left = Math.max(6, x) + 'px';
  }
  function sized(box, chart){
    if(typeof ResizeObserver !== 'function') return;
    new ResizeObserver(function(){
      chart.applyOptions({width:box.clientWidth, height:box.clientHeight});
      chart.timeScale().fitContent();
    }).observe(box);
  }
  // The crosshair is a mouse idea. A reader on a phone taps, and the library's
  // tracking mode answers a drag rather than a tap, so the readout is wired to
  // touch here: the x of the finger becomes a session index, and the row under
  // it is the row the crosshair would have shown. Passive, so the page still
  // scrolls under the same thumb.
  function onTouch(box, chart, t, count, render){
    function at(e){
      var p = e.touches && e.touches[0];
      if(!p) return;
      var r = box.getBoundingClientRect();
      var x = p.clientX - r.left;
      var lg = chart.timeScale().coordinateToLogical(x);
      if(lg == null) return;
      var i = Math.round(lg);
      if(i < 0) i = 0;
      if(i > count - 1) i = count - 1;
      var html = render(i);
      if(!html){ t.style.display = 'none'; return; }
      t.innerHTML = html;
      place(t, box, x);
    }
    box.addEventListener('touchstart', at, {passive:true});
    box.addEventListener('touchmove', at, {passive:true});
  }
  // One builder for both charts: they are the same picture of different
  // series -- lines rebased to 100, read together at one session.
  function lines(mountId, defs){
    var box = document.getElementById(mountId);
    if(!box || !defs.length) return;
    var chart = LW.createChart(box, Object.assign(
      {width:box.clientWidth, height:box.clientHeight}, THEME));
    var base = {type:'custom', formatter:function(v){ return n2(v); }};
    var made = [];
    defs.forEach(function(d){
      var data = [];
      for(var i=0;i<D.dates.length;i++)
        if(d.values[i] != null) data.push({time:D.dates[i], value:d.values[i]});
      if(!data.length) return;
      var s = chart.addLineSeries({color:d.color, lineWidth:2,
        priceLineVisible:false, lastValueVisible:false, priceFormat:base});
      s.setData(data);
      made.push({label:d.label, color:d.color, series:s, values:d.values});
    });
    if(!made.length) return;
    chart.timeScale().fitContent();
    var t = tipFor(box);
    function chip(label, color, v){
      return v == null ? ''
        : '<span style="color:' + color + '">' + label + '</span> ' + n2(v) + ' ';
    }
    chart.subscribeCrosshairMove(function(p){
      if(!p || !p.time || !p.point){ t.style.display='none'; return; }
      var rows = '';
      made.forEach(function(m){
        var v = p.seriesData.get(m.series);
        rows += chip(m.label, m.color, v ? v.value : null);
      });
      if(!rows){ t.style.display='none'; return; }
      t.innerHTML = '<b>' + tfmt(p.time) + '</b>' + rows;
      place(t, box, p.point.x);
    });
    onTouch(box, chart, t, D.dates.length, function(i){
      var rows = '';
      made.forEach(function(m){ rows += chip(m.label, m.color, m.values[i]); });
      return rows ? '<b>' + D.dates[i] + '</b>' + rows : '';
    });
    sized(box, chart);
  }
  lines('lw-hero', D.hero || []);
  lines('lw-companies', D.companies || []);
})();
"""


def main_html(card: dict, dom: str) -> str:
    rec = card.get("record") or {}
    b = rec.get("benchmarks") or {}
    verdict = esc(rec.get("verdict") or card.get("status") or "")
    tiles = "".join([
        _tile(pct(b.get("win")), "basket, since signed", cls(b.get("win"))),
        _tile(pct(b.get("ew")), "EW_MAP, same window", cls(b.get("ew"))),
        _tile(pct(b.get("sox")), f"{hero_lines(dom)[2][1]}, same window",
              cls(b.get("sox"))),
        _tile(pct(b.get("win_ew")), "excess over EW_MAP", cls(b.get("win_ew"))),
        _tile(str(b.get("sessions") if b.get("sessions") is not None else "—"),
              "sessions measured"),
    ])
    missing = rec.get("no_series") or []
    missing_note = (f'<p class="note">No clean daily series for '
                    f'{esc(", ".join(missing))} in this window; '
                    f'{"it is" if len(missing) == 1 else "they are"} listed '
                    f'without numbers rather than dropped.</p>'
                    if missing else "")
    return (
        f'<a class="back" href="/{esc(dom)}/track/">← Track record</a>'
        f'<div class="eyebrow">Closed question · {esc(card.get("d"))}</div>'
        f'<h1>{esc(card.get("who"))}'
        f'{" · " + esc(card.get("tk")) if card.get("tk") else ""}'
        f'<span class="pill {verdict}">{verdict}</span></h1>'
        f'{_question(card)}'
        '<h2>The basket, since the contract was signed</h2>'
        f'<div class="tiles">{tiles}</div>'
        f'{missing_note}'
        '<h2>Cumulative performance</h2>'
        f'{_hero(rec, dom)}'
        '<h2>What moved the number</h2>'
        f'{_contrib(rec)}'
        '<h2>Every company in the basket</h2>'
        f'{_companies(rec)}'
        '<h2>Every leg</h2>'
        f'{_legs_table(rec)}'
        '<h2>How this was measured</h2>'
        f'<p class="note">{esc(method_text(dom))}</p>'
        f'{_meta(card, rec)}'
        f'<div class="foot">{esc(NOT_ADVICE)}<br>'
        f'<a class="credit" href="../{VENDOR[1]}">{esc(CREDIT)}</a></div>'
        f'{_payload(rec, dom)}'
        f'<script src="../{VENDOR[0]}"></script>'
        f'<script>{CHART_JS}</script>')


def render(card: dict, dom: str, template: str | None = None) -> str:
    """The whole page for one closed question.

    ``dom`` is passed, never defaulted: this page links back to its own
    domain's track record, and a default would silently point a second
    industry's page at the first one's.
    """
    from chains import sitenav
    from chains.paths import templates_dir
    t = template if template is not None else (
        (templates_dir() / "track-detail.html").read_text(encoding="utf-8"))
    who = card.get("who") or card.get("qid") or ""
    for token, fill in (
            ("__TITLE__", esc(TITLE.format(who=who))),
            ("__DESC__", esc(DESC.format(
                who=who, date=card.get("d") or "",
                bench_label=hero_lines(dom)[2][1]))),
            ("__ANALYTICS__", sitenav.ANALYTICS),
            ("__SITE_NAV_CSS__", sitenav.CSS),
            ("__SITE_NAV__", sitenav.html(dom, "track",
                                          several=sitenav.several_maps())),
            ("__MAIN__", main_html(card, dom))):
        t = t.replace(token, fill)
    return t
