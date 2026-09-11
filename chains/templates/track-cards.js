// The full tracking cards, as one renderer.
//
// Two pages draw these: the public page after a subscriber unlocks the sealed
// payload in their own browser, and the private map from the copy the cloud
// task writes to its database. They must not drift, so there is one file and
// both inline it at build time.
//
// window.renderTrack(rootElement, fullPayload) -- nothing else is exported and
// nothing here fetches, decrypts or decides what a reader may see. It draws
// what it is handed.
(function(){
  const esc = v => String(v==null?'':v).replace(/[&<>"]/g, c=>(
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const UP='#3fd18b', DN='#ff5a3c', MAP='#7d8797';

  // Percent in, percent out. chains/track.py converts the ledger's fractions
  // once, at the boundary, so nothing here multiplies anything by a hundred.
  const p2 = v => v==null ? '—' : (v>0?'+':'') + v.toFixed(2) + '%';
  const n2 = v => v==null ? '—'
    : (Math.abs(v) >= 10000 ? Math.round(v).toLocaleString('en-US')
                            : v.toFixed(2));
  const sgn = v => v==null ? 'flat' : (v>0?'pos':(v<0?'neg':'flat'));
  // Four marks, four words. "none" is not "no": no means the report said the
  // opposite of the question, none means the report did not address it.
  const word = r => ['yes','no','mixed','none'].indexOf(r.status)>=0
    ? r.status : 'yes';
  const MARK_LABEL = {yes:'yes', no:'no', mixed:'mixed',
                      none:'no clear signal'};
  // A basket is always defined as "up if yes" -- that is how the question was
  // written, before anyone knew the answer. The legend and the column head
  // name that, not the mark: "up if mixed" describes nothing.
  const leg = r => r.status==='no' ? 'no' : 'yes';
  const ANSWERED = r => ['yes','no','mixed','none'].indexOf(r.status)>=0;

  const VBW=420, VBH=230, CX=100, CY=115, R1X=230, R2X=345, R2R=8, GAP=18, R2MAX=8;
  // Cut for the drawing, whole in the <title>: the same rule the map's cards
  // use, and the reason the hover is worth having.
  const REASON_MAX=12;
  const clip = (t,n) => { t=String(t||''); return t.length>n?t.slice(0,n)+'…':t; };

  const CIRC = 326.7;
  function ringSVG(n){
    const col = n<=3?DN : (n<=14?'#f2b632':MAP);
    const off = CIRC*(Math.max(0,Math.min(60,n))/60);
    const unit = n<0 ? 'days ago' : (n===0?'today':(n===1?'day':'days'));
    const num = n<0 ? -n : (n===0?'·':n);
    return `<div class="ring"><svg viewBox="0 0 118 118">
      <circle cx="59" cy="59" r="47" fill="#141922"/>
      <circle cx="59" cy="59" r="52" fill="none" stroke="#222a36" stroke-width="7"/>
      <circle cx="59" cy="59" r="52" fill="none" stroke="${col}" stroke-width="7"
        stroke-linecap="round" stroke-dasharray="${CIRC}" stroke-dashoffset="${off.toFixed(1)}"/>
    </svg><div class="n"><b>${esc(num)}</b><small>${esc(unit)}</small></div></div>`;
  }

  function constellation(r){
    const lab = {};
    (r.members||[]).forEach(m=>{ lab[m.id]=m.label; });
    const nameOf = i => lab[i] || String(i).toUpperCase();
    const why = {};
    (r.ring1_edges||[]).forEach(e=>{ why[e.id]=e.label||''; });
    const wins=(r.win||[]).slice(0,3), loses=(r.lose||[]).slice(0,3);
    const all=[...wins.map(i=>({id:i,win:true})),...loses.map(i=>({id:i,win:false}))];
    const total=(r.win||[]).length+(r.lose||[]).length;
    if(!all.length) return '';
    const ys = all.length===1 ? [CY] : all.map((_,i)=>45+i*(130/(all.length-1)));
    let g='', drawn=[];
    all.forEach((o,i)=>{
      const y=ys[i], col=o.win?UP:DN;
      const t=clip(nameOf(o.id),6), rr=t.length<=4?16:15;
      const fs=Math.max(7.5,Math.min(11,(rr*1.9)/Math.max(1,t.length)*1.35));
      drawn.push({id:o.id,y:y,col:col,r:rr});
      g+=`<path d="M${CX},${CY} C160,${CY} 180,${y.toFixed(1)} ${R1X},${y.toFixed(1)}" fill="none" stroke="${col}" stroke-width="1.6" opacity=".8"/>`;
      g+=`<circle cx="${R1X}" cy="${y.toFixed(1)}" r="${rr}" fill="#0b0e14" stroke="${col}" stroke-width="2"/>`;
      g+=`<text x="${R1X}" y="${(y+4).toFixed(1)}" text-anchor="middle" font-family="Inter,sans-serif" font-size="${fs.toFixed(1)}" font-weight="600" fill="#e8ecf2">${esc(t)}</text>`;
      const full=why[o.id];
      if(full){
        g+=`<text x="${R1X+rr+6}" y="${(y+4).toFixed(1)}" font-family="Inter,sans-serif" font-size="11" fill="${MAP}">${esc(clip(full,REASON_MAX))}<title>${esc(full)}</title></text>`;
      }
    });
    if(total>6) g+=`<text x="${R1X}" y="215" text-anchor="middle" font-family="Inter,sans-serif" font-size="11" fill="${MAP}">+${total-6} more</text>`;

    const at={}; drawn.forEach(d=>{ at[d.id]=d; });
    const side={}; (r.win2||[]).forEach(i=>{side[i]='win';});
    (r.lose2||[]).forEach(i=>{side[i]='lose';});
    const by={}, kids=[];
    for(const e of (r.ring2_edges||[])){
      const p=at[e.to]; if(!p) continue;
      if(!(e.from in side)) continue;
      if(!by[e.from]){ by[e.from]={id:e.from,parents:[],labels:[],win:side[e.from]==='win'}; kids.push(by[e.from]); }
      by[e.from].parents.push(p);
      by[e.from].labels.push(e.label||'');
    }
    const show=kids.slice(0,R2MAX), hidden=kids.length-show.length;
    const groups={};
    show.forEach(k=>{ k.at=k.parents.reduce((a,p)=>a+p.y,0)/k.parents.length;
      const key=k.parents.map(p=>p.id).join(','); (groups[key]=groups[key]||[]).push(k); });
    Object.values(groups).forEach(gp=>{ gp.forEach((k,n)=>{ k.y=gp[0].at+(n-(gp.length-1)/2)*GAP; }); });
    show.sort((a,b)=>a.y-b.y);
    let prev=-1e9; show.forEach(k=>{ k.y=Math.max(k.y,prev+GAP); prev=k.y; });
    if(show.length){
      const lift=22-show[0].y; if(lift>0) show.forEach(k=>{k.y+=lift;});
      const drop=show[show.length-1].y-(VBH-22); if(drop>0) show.forEach(k=>{k.y-=drop;});
    }
    let g2='';
    show.forEach(k=>{
      const y=k.y, col=k.parents[0].col, two=k.parents.length>1;
      k.parents.forEach(p=>{
        g2+=`<path d="M${R1X+p.r},${p.y.toFixed(1)} C${R1X+55},${p.y.toFixed(1)} ${R2X-55},${y.toFixed(1)} ${R2X-R2R},${y.toFixed(1)}" fill="none" stroke="${p.col}" stroke-width="1" opacity=".45"/>`;
      });
      g2+=`<circle cx="${R2X}" cy="${y.toFixed(1)}" r="${R2R}" fill="#0b0e14" stroke="${col}" stroke-width="${two?2:1.4}" opacity="${two?.95:.7}"/>`;
      const tip=(k.labels||[]).filter(Boolean).join(' · ');
      g2+=`<text x="${R2X+R2R+4}" y="${(y+3).toFixed(1)}" font-family="Inter,sans-serif" font-size="9" fill="${two?'#c7d0dc':'#9aa4b2'}" font-weight="${two?600:400}">${esc(clip(nameOf(k.id),9))}${tip?`<title>${esc(tip)}</title>`:''}</text>`;
    });
    if(hidden>0) g2+=`<text x="${R2X}" y="222" text-anchor="middle" font-family="Inter,sans-serif" font-size="9" fill="${MAP}">+${hidden}</text>`;

    const m = leg(r);
    return `<div class="cons"><svg viewBox="0 0 ${VBW} ${VBH}">
      <circle cx="${CX}" cy="${CY}" r="30" fill="none" stroke="#e8ecf2" opacity=".25"/>
      ${g2}${g}
      <circle cx="${CX}" cy="${CY}" r="22" fill="#0b0e14" stroke="#e8ecf2" stroke-width="2.2"/>
      <text x="${CX}" y="${CY+4}" text-anchor="middle" font-family="Inter,sans-serif" font-size="12" font-weight="600" fill="#e8ecf2">${esc(r.tk||'')}</text>
    </svg><div class="cap">
      <span><i style="border-color:${UP}"></i>up if ${m}</span>
      <span><i style="border-color:${DN}"></i>down if ${m}</span>
      ${show.length?`<span><i style="border-color:${UP};opacity:.55"></i>second ring</span>`:''}
    </div></div>`;
  }

  const CW=560, CH=230, PADL=44, PADR=54, PADT=16, PADB=26;
  function chart(r){
    const s = r.series;
    if(!s) return `<div class="chart"><svg viewBox="0 0 ${CW} ${CH}">
      <line x1="${PADL}" x2="${CW-PADR}" y1="${CH/2}" y2="${CH/2}" stroke="#222a36"/>
      <circle cx="${PADL}" cy="${CH/2}" r="3.4" fill="${MAP}"/>
      </svg></div><p class="pending">first print after the next close</p>`;
    const lines=['win','lose','ew','win2','lose2'].map(k=>({k:k,v:s[k]}))
      .filter(o=>o.v&&o.v.length);
    let hi=0; lines.forEach(o=>o.v.forEach(v=>{ if(v!=null) hi=Math.max(hi,Math.abs(v)); }));
    let T=8; for(const t of [2,4,8,16,32]) if(hi<=t){ T=t; break; }
    if(hi>32) T=Math.ceil(hi/8)*8;
    const n=s.dates.length, span=Math.max(40,n-1);
    const X=i=>PADL+(i/span)*(CW-PADL-PADR);
    const Y=v=>PADT+(1-(v+T)/(2*T))*(CH-PADT-PADB);
    let g='';
    for(const t of [T,T/2,0,-T/2,-T]){
      const y=Y(t);
      g+=`<line x1="${PADL}" x2="${CW-PADR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${t===0?'#2b3542':'#1a212c'}"/>`;
      g+=`<text x="${PADL-7}" y="${(y+3).toFixed(1)}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="9" fill="${MAP}">${t>0?'+':''}${t}%</text>`;
    }
    for(const h of [5,10,20,40]){
      if(h>span) continue;
      const x=X(h);
      g+=`<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${PADT}" y2="${CH-PADB}" stroke="#1a212c" stroke-dasharray="2 4"/>`;
      g+=`<text x="${x.toFixed(1)}" y="${CH-PADB+13}" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="9" fill="${MAP}">${h}d</text>`;
    }
    const xt=X(n-1);
    g+=`<line x1="${xt.toFixed(1)}" x2="${xt.toFixed(1)}" y1="${PADT}" y2="${CH-PADB}" stroke="#3a4658"/>`;
    g+=`<text x="${xt.toFixed(1)}" y="${PADT-4}" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="9" fill="${MAP}">today</text>`;
    const style={win:{c:UP,w:2.2,o:1,d:''},lose:{c:DN,w:2,o:1,d:''},
      ew:{c:MAP,w:1.6,o:1,d:' stroke-dasharray="4 3"'},
      win2:{c:UP,w:1.4,o:.55,d:''},lose2:{c:DN,w:1.4,o:.55,d:''}};
    for(const o of lines){
      const st=style[o.k]; let d='', started=false;
      o.v.forEach((v,i)=>{ if(v==null) return;
        d+=(started?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' '; started=true; });
      if(!d) continue;
      g+=`<path d="${d.trim()}" fill="none" stroke="${st.c}" stroke-width="${st.w}" opacity="${st.o}"${st.d} stroke-linejoin="round"/>`;
      if(['win','lose','ew'].includes(o.k)){
        const li=o.v.reduce((a,v,i)=>v==null?a:i,-1);
        if(li>=0){ const x=X(li), y=Y(o.v[li]);
          g+=`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="${st.c}"/>`;
          g+=`<text x="${(x+6).toFixed(1)}" y="${(y+3).toFixed(1)}" font-family="IBM Plex Mono,monospace" font-size="9" fill="${st.c}">${p2(o.v[li])}</text>`; }
      }
    }
    const m=leg(r);
    return `<div class="chart"><svg viewBox="0 0 ${CW} ${CH}">${g}</svg></div>
      <div class="cap">
        <span><i style="border-color:${UP}"></i>up if ${m}</span>
        <span><i style="border-color:${DN}"></i>down if ${m}</span>
        <span><i style="border-color:${MAP};border-top-style:dashed"></i>equal-weight map</span>
        ${r.has_r2?`<span><i style="border-color:${UP};opacity:.55"></i>second ring</span>`:''}
      </div>`;
  }

  // The same rows as a scored card, measured from the report instead of from
  // an entry, and captioned so nobody reads it as a position.
  function observed(r){
    const m = word(r);
    const heads = {win:['up if yes','up'], lose:['down if yes','dn'],
      win2:['up if yes · second ring','up'],
      lose2:['down if yes · second ring','dn']};
    const cols = `<tr><th>Station</th><th>Expected if yes</th>`
      + `<th>Report-day close</th><th>Last</th><th>Since report</th></tr>`;
    const ms = r.members||[];
    const cap = `<p class="obs">No position taken — this question resolved `
      + `${esc(MARK_LABEL[m]||m)}. Shown for observation; not part of the `
      + `record.</p>`;
    if(!ms.length) return `${cap}<div class="tw"><table class="mem">${cols}
      <tr><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr></table></div>`;
    const worst = Math.max(1, ...ms.map(x=>Math.abs(x.since_report||0)));
    let rows='';
    for(const g of ['win','lose','win2','lose2']){
      const inGroup = ms.filter(x=>x.group===g);
      if(!inGroup.length) continue;
      rows += `<tr class="grp"><td colspan="5"><span class="gchip ${heads[g][1]}">${esc(heads[g][0])}</span></td></tr>`;
      for(const x of inGroup){
        const w = Math.round(Math.min(40, Math.abs(x.since_report||0)/worst*40));
        const col = (x.since_report||0) >= 0 ? UP : DN;
        const bar = x.since_report==null ? ''
          : `<span class="bar" style="width:${w}px;background:${col}"></span>`;
        rows += `<tr><td>${esc(x.label)}${x.stale?` <span class="stale" title="last close ${x.stale} sessions old">·</span>`:''}</td>
          <td class="arrow">${x.expected_dir>0?'▲':'▼'}</td>
          <td>${n2(x.report_close)}</td>
          <td>${n2(x.last)}</td>
          <td class="${sgn(x.since_report)}">${p2(x.since_report)}${bar}</td></tr>`;
      }
    }
    return `${cap}<div class="tw"><table class="mem">${cols}${rows}</table></div>`;
  }

  // The same chart a scored card draws, from the report's close instead of an
  // entry's, and stamped so it can never be read as a result. The band is on
  // the chart itself rather than in a caption underneath: a chart travels --
  // into a screenshot, into a slide -- and the disclaimer has to travel with
  // it.
  function observedChart(r){
    const o = r.observed;
    if(!o || !o.dates || !o.dates.length) return '';
    if(o.dates.length < 2){
      // The report's own close and nothing after it yet. A dot on the zero
      // line, and a sentence saying so -- an empty column would leave the
      // reader wondering whether the chart had failed.
      const cx = CW/2, cy = CH/2;
      return `<div class="chart obschart">
        <span class="obsband">Observation · no position</span>
        <svg viewBox="0 0 ${CW} ${CH}">
          <line x1="8" x2="${CW-8}" y1="${cy}" y2="${cy}" stroke="#ffffff22" stroke-width="1"/>
          <circle cx="${cx}" cy="${cy}" r="4" fill="${UP}"/>
          <text x="${cx+9}" y="${cy+4}" font-family="IBM Plex Mono,monospace" font-size="10" fill="${UP}">0.00%</text>
        </svg></div>
        <p class="obsfoot">First move prints after the next close · `
        + `baselined on ${esc(o.from)}</p>`;
    }
    const keys = [['ew', MAP, 1, ' stroke-dasharray="3 3"'],
                  ['lose', DN, 1.6, ''], ['win2', UP, 1, ''],
                  ['win', UP, 1.9, '']];
    let lo = 0, hi = 0;
    keys.forEach(([k]) => (o[k]||[]).forEach(v => {
      if(v==null) return; lo = Math.min(lo, v); hi = Math.max(hi, v); }));
    const pad = Math.max(0.6, (hi - lo) * 0.18);
    lo -= pad; hi += pad;
    const n = o.dates.length;
    const X = i => 8 + (i/(n-1||1)) * (CW-16);
    const Y = v => CH-14 - ((v-lo)/((hi-lo)||1)) * (CH-30);
    let g = '';
    // the zero line: the report's own close
    g += `<line x1="8" x2="${CW-8}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="#ffffff22" stroke-width="1"/>`;
    for(const [k, col, w, dash] of keys){
      const v = o[k]; if(!v) continue;
      let d = '', started = false;
      v.forEach((y,i)=>{ if(y==null) return;
        d += (started?'L':'M') + X(i).toFixed(1) + ' ' + Y(y).toFixed(1) + ' ';
        started = true; });
      if(!d) continue;
      g += `<path d="${d.trim()}" fill="none" stroke="${col}" stroke-width="${w}"${dash} opacity="${k==='win'?1:.7}" stroke-linejoin="round"/>`;
      const li = v.reduce((a,y,i)=>y==null?a:i,-1);
      if(li>=0 && (k==='win'||k==='ew')){
        g += `<circle cx="${X(li).toFixed(1)}" cy="${Y(v[li]).toFixed(1)}" r="3" fill="${col}"/>`;
        g += `<text x="${(X(li)-4).toFixed(1)}" y="${(Y(v[li])-6).toFixed(1)}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="9" fill="${col}">${p2(v[li])}</text>`;
      }
    }
    return `<div class="chart obschart">
      <span class="obsband">Observation · no position</span>
      <svg viewBox="0 0 ${CW} ${CH}">${g}</svg></div>
      <div class="cap">
        <span><i style="border-color:${UP}"></i>up if yes</span>
        ${o.lose?`<span><i style="border-color:${DN}"></i>down if yes</span>`:''}
        <span><i style="border-color:${MAP};border-top-style:dashed"></i>equal-weight map</span>
      </div>
      <div class="obsnums">
        <div><b class="${sgn(o.up)}">${p2(o.up)}</b><span>up basket since the report</span></div>
        <div><b class="${sgn(o.up_ew)}">${p2(o.up_ew)}</b><span>up − map since the report</span></div>
      </div>
      <p class="obsfoot">${o.sessions} session${o.sessions===1?'':'s'} since ${esc(o.from)} · not scored, not in the hit rate</p>`;
  }

  function table(r){
    // A reported question has no entry, so it has no since-entry. What it has
    // is a price move since the day of the report, which is an observation and
    // is labelled as one -- nothing here is a position and nothing here is
    // scored.
    if(r.state==='reported') return observed(r);
    const m = leg(r);
    const heads = {win:['up if '+m,'up'], lose:['down if '+m,'dn'],
      win2:['up if '+m+' · second ring','up'],
      lose2:['down if '+m+' · second ring','dn']};
    const cols = `<tr><th>Station</th><th>Expected if ${esc(m)}</th>`
      + `<th>Report-day close</th><th>Entry close</th><th>Last</th>`
      + `<th>Today</th><th>Since entry</th></tr>`;
    const ms = r.members||[];
    if(!ms.length) return `<div class="tw"><table class="mem">${cols}
      <tr><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
      </table></div>`;
    const worst = Math.max(1, ...ms.map(x=>Math.abs(x.since_pct||0)));
    let rows='';
    for(const g of ['win','lose','win2','lose2']){
      const inGroup = ms.filter(x=>x.group===g);
      if(!inGroup.length) continue;
      rows += `<tr class="grp"><td colspan="7"><span class="gchip ${heads[g][1]}">${esc(heads[g][0])}</span></td></tr>`;
      for(const x of inGroup){
        const w = Math.round(Math.min(40, Math.abs(x.since_pct||0)/worst*40));
        const col = (x.since_pct||0) >= 0 ? UP : DN;
        const bar = x.since_pct==null ? ''
          : `<span class="bar" style="width:${w}px;background:${col}"></span>`;
        rows += `<tr><td>${esc(x.label)}${x.stale?` <span class="stale" title="last close ${x.stale} sessions old">·</span>`:''}</td>
          <td class="arrow">${x.expected_dir>0?'▲':'▼'}</td>
          <td>${n2(x.report_close)}</td>
          <td>${n2(x.entry_close)}</td>
          <td>${n2(x.last)}</td>
          <td class="${sgn(x.day_pct)}">${p2(x.day_pct)}</td>
          <td class="${sgn(x.since_pct)}">${p2(x.since_pct)}${bar}</td></tr>`;
      }
    }
    return `<div class="tw"><table class="mem">${cols}${rows}</table></div>`;
  }

  // The four sentences, in the order the question cards use them. Only the
  // sealed payload carries these; a card built from a public payload has none
  // and simply does not draw the block. A part the source has nothing for is
  // omitted rather than printed empty -- a v1 questions file has no "no"
  // sentence, and inventing one would be inventing the product.
  function question(r){
    if(!r.q && !r.yes && !r.no && !r.why) return '';
    // One column when only one side has a sentence. A v1 questions file has
    // no "no" sentence, and a half-width column beside an empty one wraps
    // three words to a line for no reason.
    const M = t => (window.GL ? GL.mark(t, r.terms) : esc(t));
    const both = !!(r.yes && r.no);
    const yn = (r.yes || r.no) ? `<div class="yn${both?'':' one'}">`
      + (r.yes?`<div class="y"><b>Yes looks like</b>${M(r.yes)}</div>`:'')
      + (r.no?`<div class="no"><b>No looks like</b>${M(r.no)}</div>`:'')
      + `</div>` : '';
    return (r.q?`<p class="q">${M(r.q)}</p>`:'')
      + yn
      + (r.why?`<p class="why"><b>Why it matters.</b> ${M(r.why)}</p>`:'')
      + (window.GL ? GL.chips(r.terms, 'Terms') : '');
  }

  // What the report said, in the marking task's own words. The build writes
  // none of this: an empty field renders nothing rather than a heading over a
  // blank.
  // The stored note opens "auto: mixed — ...", which is how the marking task
  // writes it and how it stays in the file. On the card both halves are
  // already said by the pill beside it -- MIXED, AUTO -- so printing them
  // again is the sentence apologising for itself before it starts. Stripped
  // for display and nowhere else: marks.json keeps every character.
  const AUTO_PREFIX = /^\s*auto:\s*(?:(?:mixed|none|yes|no)\s*[—–-]\s*)?/i;
  const sayClean = t => String(t || '').trim().replace(AUTO_PREFIX, '').trim();

  function findings(r){
    const said = sayClean(r.note || r.evidence);
    const read = String(r.read || '').trim();
    if(!said && !read) return '';
    let out = '';
    if(said) out += `<div class="found"><b>What the report said</b>`
      + `<p>${esc(said)}</p></div>`;
    // Commentary, and labelled as commentary. It is not in any number on this
    // page and the label says so on the line itself, not in a footnote.
    if(read) out += `<div class="read"><b>Read · not scored</b>`
      + `<p>${esc(read)}</p></div>`;
    return out;
  }

  function head(r, today){
    const m = word(r);
    const daysTo = d => Math.round((Date.parse(d+'T00:00:00Z')
      - Date.UTC(today.getUTCFullYear(),today.getUTCMonth(),today.getUTCDate()))/86400000);
    const nStations = (r.members||[]).length;
    const when = r.entry_date
      ? `marked ${String(r.marked_at||'').slice(0,10)} · entry close ${r.entry_date}`
      : (r.state==='marked'
          ? `marked ${String(r.marked_at||'').slice(0,10)} · entry at next close`
          : (r.state==='reported'
              ? `Reported ${esc(r.report_date||r.d)}`
              : `${esc(r.d)} · ${r.confirmed?'confirmed':'expected'}`));
    let badge='', line='';
    if(r.state==='upcoming'){
      badge = ringSVG(daysTo(r.d));
      line = `<div class="pre">Pre-registered · ${nStations} stations · entry at the close after the mark</div>`;
    } else if(r.state==='reported'){
      // The ring counted down to a date that has arrived, so it is gone. What
      // replaces it is the mark itself, and under it what was reported.
      badge = `<span class="pill ${m}">${esc(MARK_LABEL[m]||m)}`
        + `<span class="how">${r.auto?'auto':'manual'}</span></span>`;
      line = `<div class="day">No forecast — not in the hit rate</div>`;
    } else if(r.state==='none'){
      badge = ringSVG(daysTo(r.d));
      line = `<span class="pill grey">no forecast — ${esc(r.status||'not marked')}</span>`;
    } else {
      badge = `<span class="pill ${m}">${esc(MARK_LABEL[m]||m)}`
        + `<span class="how">${r.auto?'auto':'manual'}</span></span>`;
      line = r.entry_date
        ? `<div class="day">Day ${r.day_index} of 40`
          + (r.next_checkpoint ? ` · next checkpoint ${r.next_checkpoint}d in ${r.sessions_to} session${r.sessions_to===1?'':'s'}` : ' · every checkpoint scored')
          + `</div>`
        : `<div class="day">not entered yet</div>`;
    }
    const t = r.today||{};
    const nums = r.entry_date ? `<div class="big">
        <div><b class="${sgn(t.win_lose)}">${p2(t.win_lose)}</b><span>up − down today</span></div>
        <div><b class="${sgn(t.win_ew)}">${p2(t.win_ew)}</b><span>up − map today</span></div>
      </div>` + (r.has_r2?`<div class="small">
        <div><b class="${sgn(t.win2_lose2)}">${p2(t.win2_lose2)}</b><span>ring 2 up − down</span></div>
        <div><b class="${sgn(t.win2_ew)}">${p2(t.win2_ew)}</b><span>ring 2 up − map</span></div>
      </div>`:'') : '';
    return `<div>
      ${badge}
      <div class="who" style="margin-top:12px">${esc(r.who)}${r.tk?' · '+esc(r.tk):''}</div>
      <div class="dt">${esc(when)}</div>
      ${question(r)}
      ${findings(r)}
      ${line}${nums}
    </div>`;
  }

  function card(r, today){
    // A reported card plots from the report's close. It has no forecast
    // series -- it was never entered -- so it cannot use chart(), and the
    // constellation it used to show said nothing about what happened after.
    const mid = (r.state==='tracking'||r.state==='closed'||r.state==='marked')
      ? chart(r)
      : (r.state==='reported' && r.observed ? observedChart(r)
                                            : constellation(r));
    return `<article class="fc ${esc(r.state)}" data-id="${esc(r.qid)}" data-state="${esc(r.state)}">
      ${head(r, today)}<div>${mid}</div><div>${table(r)}</div></article>`;
  }

  function closedRow(r, today){
    const chips = ['5','10','20','40'].map(h=>{
      const d = (r.horizons||{})[h];
      return `<span class="${d?(d.hit?'hit':'miss'):''}">${h}d ${d?p2(d.spread):'—'}</span>`;
    }).join(' ');
    return `<details class="closed" data-id="${esc(r.qid)}" data-state="closed">
      <summary><b>${esc(r.who)}</b><span class="pill ${word(r)}">${word(r)}</span>${chips}</summary>
      ${card(r, today)}</details>`;
  }

  function tiles(S){
    const tile = (v,label,cls) =>
      `<div class="tile ${cls||''}"><b>${v}</b><span>${esc(label)}</span></div>`;
    const rate = s => (s && s.value!=null) ? Math.round(s.value*100)+'%' : '0 / 0';
    const mean = s => (s && s.value!=null) ? p2(s.value) : '0 / 0';
    const cap = (s,txt) => (s && s.n) ? txt+' (n='+s.n+')'
                                      : 'no scored forecasts yet';
    const nu = S.next_up||null;
    const counts = `<p class="tcap">${S.n_answered||0} answered · `
      + `${S.n_scored||0} scored · ${S.n_unscored||0} no forecast</p>`;
    return counts + `<div class="tiles">
      ${tile(`${S.n_scored||0} / ${S.n_cards||0}`,'tracking / all questions')}
      ${tile(rate(S.direct_hit_5), cap(S.direct_hit_5,'direct hit rate 5d'))}
      ${tile(mean(S.direct_spread_5), cap(S.direct_spread_5,'direct avg spread 5d'),
             S.direct_spread_5&&S.direct_spread_5.n?sgn(S.direct_spread_5.value):'')}
      ${tile(mean(S.direct_spread_20), cap(S.direct_spread_20,'direct vs map 20d'),
             S.direct_spread_20&&S.direct_spread_20.n?sgn(S.direct_spread_20.value):'')}
      ${tile(rate(S.ring2_hit_5), cap(S.ring2_hit_5,'second ring hit 5d'))}
      ${tile(S.n_upcoming||0, nu ? 'pre-registered · next '+nu.d+' '+nu.who
                                 : 'pre-registered')}
    </div>`;
  }

  window.renderTrack = function(root, data){
    // The payload carries its own glossary, so a card drawn from a decrypted
    // file underlines the same words as one drawn from live.json.
    if(window.GL) GL.use((data && data.glossary) || {});
    const F = (data && data.forecasts) || [], S = (data && data.summary) || {};
    const today = data && data.as_of ? new Date(data.as_of+'T00:00:00Z')
                                     : new Date();
    const open = F.filter(r=>r.state!=='closed');
    const shut = F.filter(r=>r.state==='closed');
    root.innerHTML = tiles(S)
      + open.map(r=>card(r, today)).join('')
      + (shut.length ? `<div class="sect">Closed · every checkpoint scored</div>`
          + shut.map(r=>closedRow(r, today)).join('') : '');
    return F.length;
  };
})();
