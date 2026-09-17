"""One page per question whose answer is in, at /<domain>/track/<qid>/.

    from chains import record_page
    record_page.render(card, dom="semi")

WHY IT IS ITS OWN PAGE
----------------------
The forward-test page is a list of cards, and a card is a summary: the
question, the mark, and one line saying what the basket did against the map.
The evidence behind that line -- every leg with its prices and its share of the
number, both benchmarks over the same window, and a candle chart per company --
is a page's worth of material. Putting it on the card buried the card; putting
it here gives it room and gives the reader a link they can send to somebody.

Everything on this page was measured by chains/record.py at build time from
EODHD end-of-day data. Nothing is computed in the browser, nothing is fetched,
and there is no script on the page at all.

WHAT IT REFUSES TO SAY
----------------------
A leg with no clean series is a row that says so. A basket with no drawable
series gets a sentence, not an empty frame. And whether the question counts
toward the official score is track.official()'s answer, repeated verbatim: a
question answered without a direction reads "not in the official score" and
never a number invented for the occasion.
"""
from __future__ import annotations

import html
import json

# Served from this site, never from a CDN. chains/track.py copies both files
# next to the pages and chains/publish_site.py gates them like everything else.
VENDOR = ("lightweight-charts.standalone.production.js",
          "lightweight-charts.LICENSE.txt")
# Short on purpose. A question signed last week has three sessions, so this
# average has one point; it fills in as the window grows, and drawing it from
# the first day would be drawing a line through a single number.
MA_N = 5
CREDIT = ("Charts drawn with TradingView Lightweight Charts™ "
          "(Apache-2.0), served from this site.")

TITLE = "{who} · track record · Linchpin Signal"
DESC = ("What the pre-registered basket did after {who} reported on {date}, "
        "measured against the equal-weight map and SOX.")
NOT_ADVICE = "Research and analysis only. Not investment advice."
METHOD = (
    "Every price is EODHD end-of-day. The window runs from the session the "
    "scoring contract was signed on to the last close. A basket is the equal "
    "weight of the legs that have a clean series, held from the first day of "
    "the window; each leg's contribution is its own move divided by the number "
    "of legs on its side. EW_MAP is the equal-weight return of every priced "
    "station on the map, rebalanced daily; SOX is SOXQ.US. A leg priced "
    "through an ADR or OTC line is marked, and the number is the line that "
    "actually traded.")


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


def _legs_table(rec: dict) -> str:
    head = ("<tr><th>Company</th><th>Side</th><th>From</th><th>Price</th>"
            "<th>Last</th><th>Day</th><th>Since signed</th>"
            "<th>Contribution</th></tr>")
    rows = []
    for leg in rec.get("legs") or []:
        via = ""
        if leg.get("priced_via") and leg["priced_via"] != "primary":
            via = (f'<span class="via" title="priced through the '
                   f'{esc(str(leg["priced_via"]).upper())} line '
                   f'{esc(leg.get("symbol"))}">{esc(leg["priced_via"])}</span>')
        name = f'{esc(leg.get("tk"))}{via}'
        side = f'<span class="side">{esc(leg.get("group"))}</span>'
        if leg.get("no_series"):
            rows.append(f'<tr class="nos"><td>{name}</td><td>{side}</td>'
                        f'<td colspan="6">{esc(leg["no_series"])}</td></tr>')
            continue
        rows.append(
            f'<tr><td>{name}</td><td>{side}</td>'
            f'<td>{esc(leg.get("entry_date") or rec.get("baseline"))}</td>'
            f'<td>{num(leg.get("entry_close") if leg.get("entry_close") is not None else leg.get("commit_close"))}</td>'
            f'<td>{num(leg.get("last"))}</td>'
            f'<td class="{cls(leg.get("day_pct"))}">{pct(leg.get("day_pct"))}</td>'
            f'<td class="{cls(leg.get("since_commit"))}">{pct(leg.get("since_commit"))}</td>'
            f'<td class="{cls(leg.get("contribution"))}">{pct(leg.get("contribution"))}</td></tr>')
    if not rows:
        rows.append('<tr class="nos"><td colspan="8">no legs were registered '
                    'for this question</td></tr>')
    return f'<div class="tw"><table class="legs">{head}{"".join(rows)}</table></div>'


def _ma_note(c: dict) -> str:
    """The average is mentioned only once it has a point to draw.

    A window shorter than the average is the ordinary case for a question
    signed last week: MA_N sessions have to pass before the line has a single
    value. A caption promising an amber line that is not on the chart would be
    describing something the reader cannot see, so it waits until it is there.
    """
    return (f' The amber line is a {MA_N}-session moving average.'
            if (c.get("sessions") or 0) >= MA_N else '')


def _charts(rec: dict) -> str:
    charts = rec.get("candles") or []
    if not charts:
        return (f'<p class="note">No clean daily series for any leg in this '
                f'window, so no candles are drawn.</p>')
    out = []
    for c in charts:
        out.append(
            f'<div class="chartbox"><h3>{esc(c.get("tk"))}'
            f'<em>{esc(c.get("symbol"))} · {c.get("sessions")} session'
            f'{"" if c.get("sessions") == 1 else "s"}</em></h3>'
            f'<div class="lw" id="lw-{esc(c.get("id"))}"></div>'
            # The build-time drawing of the same bars, for a reader whose
            # browser runs no script. It is what the page showed before, so
            # nothing is lost by turning JavaScript off -- only the crosshair.
            f'<noscript>{c.get("svg") or ""}</noscript>'
            f'<p>Daily open, high, low and close from {esc(rec.get("baseline"))} '
            f'to {esc(rec.get("last_session"))}. Hover or touch a session for '
            f'its numbers.{_ma_note(c)}</p></div>')
    return f'<div class="charts">{"".join(out)}</div>'


BENCH_LINES = (("win", "Basket", "#3fd18b"),
               ("ew", "EW_MAP", "#7d8797"),
               ("sox", "SOX", "#f2b632"))


def _bench(rec: dict) -> str:
    """The three lines over the holding window, on one pair of axes."""
    b = rec.get("benchmarks") or {}
    s = b.get("series") or {}
    if len(s.get("dates") or []) < 2:
        return ('<p class="note">One session in this window, so there is no '
                'line to draw yet. It appears with the next close.</p>')
    chips = "".join(f'<span class="chip"><i style="background:{col}"></i>'
                    f'{esc(label)}</span>'
                    for key, label, col in BENCH_LINES if s.get(key))
    return (f'<div class="chartbox wide"><h3>Basket · EW_MAP · SOX'
            f'<em>{esc(b.get("from"))} → {esc(b.get("to"))}</em></h3>'
            f'<div class="legendrow">{chips}</div>'
            f'<div class="lw" id="lw-bench"></div>'
            f'<p>Cumulative per cent from the session the contract was signed '
            f'on. Hover or touch a session to read all three.</p></div>')


def _payload(rec: dict) -> str:
    """Only what the charts draw: the bars, the three lines, the average."""
    data = {"ma": MA_N,
            "candles": [{"id": c.get("id"), "bars": c.get("bars") or []}
                        for c in (rec.get("candles") or []) if c.get("bars")],
            "series": (rec.get("benchmarks") or {}).get("series") or {}}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return (f'<script id="record-data" type="application/json">{blob}'
            f'</script>')


# No framework and no fetch: the data is already in the page, and this only
# draws it. If the library is missing the function returns and the <noscript>
# drawings are what the reader gets -- a page that half-draws would be worse
# than one that draws once, at build time.
CHART_JS = """
(function(){
  var LW = window.LightweightCharts, el = document.getElementById('record-data');
  if(!LW || !el) return;
  var D = {};
  try { D = JSON.parse(el.textContent); } catch(e) { return; }
  var THEME = {
    layout:{background:{color:'#141922'},textColor:'#7d8797',
            fontFamily:'IBM Plex Mono, monospace',fontSize:10},
    grid:{vertLines:{color:'#1a212c'},horzLines:{color:'#1a212c'}},
    rightPriceScale:{borderColor:'#222a36'},
    timeScale:{borderColor:'#222a36',fixLeftEdge:true,fixRightEdge:true},
    crosshair:{mode:0,
      vertLine:{color:'#3a4658',width:1,style:2,labelBackgroundColor:'#222a36'},
      horzLine:{color:'#3a4658',width:1,style:2,labelBackgroundColor:'#222a36'}},
    // A three-session window has nothing to pan to, so scaling and mouse
    // panning are off. Horizontal touch stays ON -- it is what raises the
    // crosshair under a thumb, and turning handleScroll off wholesale turns
    // the touch readout off with it. Vertical touch is left to the page, so
    // the chart can never swallow a scroll.
    handleScroll:{mouseWheel:false, pressedMouseMove:false,
                  horzTouchDrag:true, vertTouchDrag:false},
    handleScale:false
  };
  function tfmt(t){
    if(typeof t === 'string') return t;
    if(t && t.year) return t.year + '-' + String(t.month).padStart(2,'0')
      + '-' + String(t.day).padStart(2,'0');
    return '';
  }
  function n2(v){ return (v==null||isNaN(v)) ? '\\u2014' : Number(v).toFixed(2); }
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
  // The crosshair is a mouse idea. A reader on a phone taps, and the library's
  // tracking mode answers a drag rather than a tap, so the readout is wired to
  // touch here instead of waiting for it: the x of the finger becomes a
  // session index, and the row under it is the row the crosshair would have
  // shown. Passive listeners, so the page still scrolls under the thumb.
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
  function ma(bars, n){
    var out = [], sum = 0;
    for(var i=0;i<bars.length;i++){
      sum += bars[i].close;
      if(i >= n) sum -= bars[i-n].close;
      if(i >= n-1) out.push({time:bars[i].time, value:sum/n});
    }
    return out;
  }
  function sized(box, chart){
    if(typeof ResizeObserver !== 'function') return;
    new ResizeObserver(function(){
      chart.applyOptions({width:box.clientWidth, height:box.clientHeight});
      chart.timeScale().fitContent();
    }).observe(box);
  }
  (D.candles||[]).forEach(function(c){
    var box = document.getElementById('lw-' + c.id);
    if(!box || !c.bars || !c.bars.length) return;
    var chart = LW.createChart(box, Object.assign(
      {width:box.clientWidth, height:box.clientHeight}, THEME));
    var s = chart.addCandlestickSeries({
      upColor:'#3fd18b', downColor:'#ff5a3c',
      borderUpColor:'#3fd18b', borderDownColor:'#ff5a3c',
      wickUpColor:'#3fd18b', wickDownColor:'#ff5a3c'});
    s.setData(c.bars);
    var m = ma(c.bars, D.ma || 5), ms = null;
    if(m.length){
      ms = chart.addLineSeries({color:'#f2b632', lineWidth:1,
        priceLineVisible:false, lastValueVisible:false,
        crosshairMarkerVisible:false});
      ms.setData(m);
    }
    chart.timeScale().fitContent();
    var t = tipFor(box);
    function row(time, o, h, l, c2, mv){
      return '<b>' + time + '</b>O ' + n2(o) + ' \\u00b7 H ' + n2(h)
        + ' \\u00b7 L ' + n2(l) + ' \\u00b7 C ' + n2(c2)
        + (mv != null ? ' \\u00b7 MA' + (D.ma||5) + ' ' + n2(mv) : '');
    }
    chart.subscribeCrosshairMove(function(p){
      if(!p || !p.time || !p.point){ t.style.display='none'; return; }
      var b = p.seriesData.get(s);
      if(!b){ t.style.display='none'; return; }
      var mv = ms ? p.seriesData.get(ms) : null;
      t.innerHTML = row(tfmt(p.time), b.open, b.high, b.low, b.close,
                        mv ? mv.value : null);
      place(t, box, p.point.x);
    });
    onTouch(box, chart, t, c.bars.length, function(i){
      var b = c.bars[i];
      if(!b) return '';
      // The average starts later than the bars do, so its index is offset by
      // however many sessions it needed before it had a value at all.
      var mv = m.length ? (m[i - (c.bars.length - m.length)]||{}).value : null;
      return row(b.time, b.open, b.high, b.low, b.close,
                 mv == null ? null : mv);
    });
    sized(box, chart);
  });
  var B = D.series || {}, bx = document.getElementById('lw-bench');
  if(bx && (B.dates||[]).length > 1){
    var chart = LW.createChart(bx, Object.assign(
      {width:bx.clientWidth, height:bx.clientHeight}, THEME));
    var pct = {type:'custom', formatter:function(v){ return n2(v) + '%'; }};
    var made = [];
    [['win','Basket','#3fd18b'],['ew','EW_MAP','#7d8797'],
     ['sox','SOX','#f2b632']].forEach(function(d){
      var vals = B[d[0]];
      if(!vals) return;
      var data = [];
      for(var i=0;i<B.dates.length;i++)
        if(vals[i] != null) data.push({time:B.dates[i], value:vals[i]});
      if(!data.length) return;
      var s = chart.addLineSeries({color:d[2], lineWidth:2,
        priceLineVisible:false, lastValueVisible:false, priceFormat:pct});
      s.setData(data);
      made.push([d[1], d[2], s, vals]);
    });
    chart.timeScale().fitContent();
    var t = tipFor(bx);
    function chip(label, color, v){
      return v == null ? ''
        : '<span style="color:' + color + '">' + label + '</span> '
          + n2(v) + '% ';
    }
    chart.subscribeCrosshairMove(function(p){
      if(!p || !p.time || !p.point){ t.style.display='none'; return; }
      var rows = '';
      made.forEach(function(m){
        var v = p.seriesData.get(m[2]);
        rows += chip(m[0], m[1], v ? v.value : null);
      });
      if(!rows){ t.style.display='none'; return; }
      t.innerHTML = '<b>' + tfmt(p.time) + '</b>' + rows;
      place(t, bx, p.point.x);
    });
    onTouch(bx, chart, t, B.dates.length, function(i){
      var rows = '';
      made.forEach(function(m){ rows += chip(m[0], m[1], m[3][i]); });
      return rows ? '<b>' + B.dates[i] + '</b>' + rows : '';
    });
    sized(bx, chart);
  }
})();
"""


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


def main_html(card: dict, dom: str = "semi") -> str:
    rec = card.get("record") or {}
    b = rec.get("benchmarks") or {}
    verdict = esc(rec.get("verdict") or card.get("status") or "")
    tiles = "".join([
        _tile(pct(b.get("win")), "basket, since signed", cls(b.get("win"))),
        _tile(pct(b.get("ew")), "EW_MAP, same window", cls(b.get("ew"))),
        _tile(pct(b.get("sox")), "SOX, same window", cls(b.get("sox"))),
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
        '<h2>Every leg</h2>'
        f'{_legs_table(rec)}'
        '<h2>The basket against the map and SOX</h2>'
        f'{_bench(rec)}'
        '<h2>Daily candles, one per company</h2>'
        f'{_charts(rec)}'
        '<h2>How this was measured</h2>'
        f'<p class="note">{esc(METHOD)}</p>'
        f'{_meta(card, rec)}'
        f'<div class="foot">{esc(NOT_ADVICE)}<br>'
        f'<a href="../{VENDOR[1]}">{esc(CREDIT)}</a></div>'
        f'{_payload(rec)}'
        f'<script src="../{VENDOR[0]}"></script>'
        f'<script>{CHART_JS}</script>')


def render(card: dict, dom: str = "semi", template: str | None = None) -> str:
    """The whole page for one closed question."""
    from chains import sitenav
    from chains.paths import templates_dir
    t = template if template is not None else (
        (templates_dir() / "track-detail.html").read_text(encoding="utf-8"))
    who = card.get("who") or card.get("qid") or ""
    for token, fill in (
            ("__TITLE__", esc(TITLE.format(who=who))),
            ("__DESC__", esc(DESC.format(who=who, date=card.get("d") or ""))),
            ("__ANALYTICS__", sitenav.ANALYTICS),
            ("__SITE_NAV_CSS__", sitenav.CSS),
            ("__SITE_NAV__", sitenav.html(dom, "track")),
            ("__MAIN__", main_html(card, dom))):
        t = t.replace(token, fill)
    return t
