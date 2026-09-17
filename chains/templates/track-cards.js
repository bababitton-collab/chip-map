// The full tracking cards, as one renderer.
//
// Two pages draw these: the public page after a subscriber unlocks the sealed
// payload in their own browser, and the private map from the copy the cloud
// task writes to its database. They must not drift, so there is one file and
// both inline it at build time.
//
// window.renderTrack(rootElement, payload[, {tiles:false}]) and
// window.verifyPrereg(...) -- nothing else is exported, and
// nothing here fetches, decrypts or decides what a reader may see. It draws
// what it is handed.
(function(){
  const esc = v => String(v==null?'':v).replace(/[&<>"]/g, c=>(
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const UP='#3fd18b', DN='#ff5a3c', MAP='#7d8797';
  // SOX, the second benchmark: amber and dotted, so it never reads as the
  // dashed equal-weight map it sits beside. The map stays first.
  const SOX='#f2b632', SOX_DASH=' stroke-dasharray="1 3" stroke-linecap="round"';
  const hasPoints = v => (v||[]).some(x=>x!=null);

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

  // A policy date bets no basket: the answer is recorded and nothing is
  // forecast on it. The column says so, rather than drawing a centre with no
  // legs.
  const POLICY_STATE = 'Policy event · binary outcome · no forecast';
  function policyState(){
    return `<div class="cons policy"><div class="pband">${POLICY_STATE}</div></div>`;
  }

  // Every leg is drawn, on two arcs about the reporting company: up if yes to
  // the upper right, down if yes to the lower right. Spacing sets the radius,
  // so a long basket widens its arc and the drawing grows taller instead of
  // leaving legs out. Names come from the record's own labels, so a station
  // is named whether or not it has a price yet. Labels are placed the way the
  // map places its satellites: beside the dot, then out along its radial with
  // a leader, then without the reason, then shortened -- never over another
  // label, a dot or the centre. data-leg and data-box are read by the check
  // that every leg is drawn and no two labels touch.
  const R1MIN=125, LEG_GAP=30, ARC=Math.PI*0.36, ARC0=0.14, DOT=7, HUB=34, LAB_FS=12.5;
  const textW = (t, fs, bold) => String(t).length*fs*(bold?0.6:0.57);
  function constellation(r){
    if(r.observe_only) return policyState();
    const lab = Object.assign({}, r.labels||{});
    (r.members||[]).forEach(m=>{ if(!lab[m.id]) lab[m.id]=m.label; });
    const nameOf = i => lab[i] || String(i).toUpperCase();
    const why = {};
    (r.ring1_edges||[]).forEach(e=>{ why[e.id]=e.label||''; });
    const wins=r.win||[], loses=r.lose||[];
    if(!wins.length && !loses.length) return '';
    const R=Math.max(R1MIN, (Math.max(wins.length, loses.length)-1)*LEG_GAP/ARC);
    const VH=Math.max(VBH, Math.ceil(2*(R*Math.sin(ARC0+ARC)+26)));
    const CY=VH/2;
    const place=(ids, win)=>{
      const step=LEG_GAP/R, span=Math.max(0, ids.length-1)*step;
      const start=(win ? -(ARC0+ARC) : ARC0) + (ARC-span)/2;
      return ids.map((id,i)=>{ const th=start+i*step;
        return {id:id, win:win, th:th, x:CX+Math.cos(th)*R, y:CY+Math.sin(th)*R,
                col:win?UP:DN, r:DOT}; });
    };
    const legs=[...place(wins,true), ...place(loses,false)];

    const at={}; legs.forEach(d=>{ at[d.id]=d; });
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
      const drop=show[show.length-1].y-(VH-22); if(drop>0) show.forEach(k=>{k.y-=drop;});
    }

    // Ring-1 labels, greedy in leg order, kept left of the second ring.
    const maxX = show.length ? R2X-R2R-8 : VBW-2;
    const placed=[], dots=legs.map(d=>({x:d.x, y:d.y, r:DOT+2})), hub={x:CX, y:CY, r:HUB};
    const onC=(b,c)=>{ const dx=c.x-Math.max(b.x0,Math.min(c.x,b.x1)), dy=c.y-Math.max(b.y0,Math.min(c.y,b.y1));
      return dx*dx+dy*dy<c.r*c.r; };
    const clear=b=>b.x0>=2 && b.x1<=maxX && b.y0>=2 && b.y1<=VH-2
      && !placed.some(p=>b.x0<p.x1+2 && p.x0<b.x1+2 && b.y0<p.y1+2 && p.y0<b.y1+2)
      && !dots.some(c=>onC(b,c)) && !onC(b,hub);
    const boxAt=(ax,ay,s,w)=> s==='right'
      ? {x0:ax+DOT+4, x1:ax+DOT+4+w, y0:ay-8, y1:ay+7, tx:ax+DOT+4, ty:ay+4.5, anchor:'start'}
      : s==='left'
      ? {x0:ax-DOT-4-w, x1:ax-DOT-4, y0:ay-8, y1:ay+7, tx:ax-DOT-4, ty:ay+4.5, anchor:'end'}
      : s==='above'
        ? {x0:ax-w/2, x1:ax+w/2, y0:ay-DOT-18, y1:ay-DOT-3, tx:ax, ty:ay-DOT-6.5, anchor:'middle'}
        : {x0:ax-w/2, x1:ax+w/2, y0:ay+DOT+3, y1:ay+DOT+18, tx:ax, ty:ay+DOT+14.5, anchor:'middle'};
    legs.forEach(d=>{
      const name=nameOf(d.id), full=why[d.id]||'';
      const cands=full ? [{name:name, reason:true}] : [];
      cands.push({name:name, reason:false});
      for(let cut=name.length-1; cut>=3; cut--) cands.push({name:name.slice(0,cut).trimEnd()+'…', reason:false});
      const sides=d.win ? ['right','above','left','below'] : ['right','below','left','above'];
      let got=null;
      for(const c of cands){
        const w=textW(c.name,LAB_FS,true)+(c.reason ? 6+textW(clip(full,REASON_MAX),LAB_FS,false) : 0);
        for(let k=0; k<=6 && !got; k++){
          const ax=d.x+Math.cos(d.th)*10*k, ay=d.y+Math.sin(d.th)*10*k;
          for(const s of sides){ const b=boxAt(ax,ay,s,w); if(clear(b)){ got=Object.assign(b,{c:c, k:k}); break; } }
        }
        if(got) break;
      }
      d.forced=!got;
      if(!got){ const c={name:name.slice(0,3)+'…', reason:false};
        got=Object.assign(boxAt(d.x,d.y,'right',textW(c.name,LAB_FS,true)), {c:c, k:0}); }
      placed.push(got);
      d.lab=got;
    });
    let g='', gl='';
    legs.forEach(d=>{
      const L=d.lab;
      g+=`<path d="M${CX},${CY} C${(CX+R*0.45).toFixed(1)},${CY} ${(d.x-R*0.3).toFixed(1)},${d.y.toFixed(1)} ${d.x.toFixed(1)},${d.y.toFixed(1)}" fill="none" stroke="${d.col}" stroke-width="1.6" opacity=".8"/>`;
      if(L.k>0) g+=`<line x1="${d.x.toFixed(1)}" y1="${d.y.toFixed(1)}" x2="${Math.max(L.x0,Math.min(d.x,L.x1)).toFixed(1)}" y2="${Math.max(L.y0,Math.min(d.y,L.y1)).toFixed(1)}" stroke="${MAP}" stroke-width=".8" opacity=".6"/>`;
    });
    legs.forEach(d=>{
      g+=`<circle data-leg="${esc(d.id)}" cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="${DOT}" fill="#0b0e14" stroke="${d.col}" stroke-width="2"><title>${esc(nameOf(d.id))}</title></circle>`;
      const L=d.lab, full=why[d.id]||'';
      gl+=`<text data-lab="${esc(d.id)}" data-box="${[L.x0,L.y0,L.x1,L.y1].map(v=>v.toFixed(1)).join(',')}"${d.forced?' data-forced="1"':''} x="${L.tx.toFixed(1)}" y="${L.ty.toFixed(1)}" text-anchor="${L.anchor}" font-family="Inter,sans-serif" font-size="${LAB_FS}"><tspan font-weight="600" fill="#e8ecf2">${esc(L.c.name)}</tspan>`;
      if(L.c.reason) gl+=`<tspan dx="6" fill="${MAP}">${esc(clip(full,REASON_MAX))}<title>${esc(full)}</title></tspan>`;
      gl+=`</text>`;
    });

    let g2='';
    show.forEach(k=>{
      const y=k.y, col=k.parents[0].col, two=k.parents.length>1;
      k.parents.forEach(p=>{
        g2+=`<path d="M${(p.x+p.r).toFixed(1)},${p.y.toFixed(1)} C${(p.x+p.r+55).toFixed(1)},${p.y.toFixed(1)} ${R2X-55},${y.toFixed(1)} ${R2X-R2R},${y.toFixed(1)}" fill="none" stroke="${p.col}" stroke-width="1" opacity=".45"/>`;
      });
      g2+=`<circle cx="${R2X}" cy="${y.toFixed(1)}" r="${R2R}" fill="#0b0e14" stroke="${col}" stroke-width="${two?2:1.4}" opacity="${two?.95:.7}"/>`;
      const tip=(k.labels||[]).filter(Boolean).join(' · ');
      g2+=`<text x="${R2X+R2R+4}" y="${(y+3).toFixed(1)}" font-family="Inter,sans-serif" font-size="9" fill="${two?'#c7d0dc':'#9aa4b2'}" font-weight="${two?600:400}">${esc(clip(nameOf(k.id),9))}${tip?`<title>${esc(tip)}</title>`:''}</text>`;
    });
    if(hidden>0) g2+=`<text x="${R2X}" y="222" text-anchor="middle" font-family="Inter,sans-serif" font-size="9" fill="${MAP}">+${hidden}</text>`;

    const m = leg(r);
    return `<div class="cons"><svg viewBox="0 0 ${VBW} ${VH}">
      <circle cx="${CX}" cy="${CY}" r="30" fill="none" stroke="#e8ecf2" opacity=".25"/>
      ${g2}${g}${gl}
      <circle cx="${CX}" cy="${CY}" r="22" fill="#0b0e14" stroke="#e8ecf2" stroke-width="2.2"/>
      <text x="${CX}" y="${CY+4}" text-anchor="middle" font-family="Inter,sans-serif" font-size="12" font-weight="600" fill="#e8ecf2">${esc(r.tk||'')}</text>
    </svg><div class="cap">
      <span><i style="border-color:${UP}"></i>up if ${m}</span>
      <span><i style="border-color:${DN}"></i>down if ${m}</span>
      ${show.length?`<span><i style="border-color:${UP};opacity:.55"></i>second ring</span>`:''}
    </div></div>`;
  }

  // What a chart draws: the direct basket, the equal-weight map and SOX, and
  // the lose basket only when there is one. The second ring is a number under
  // the chart and never a line -- two greens over a handful of sessions could
  // not be told apart. Three styles that cannot be confused on the dark
  // ground: green solid, grey dashed, amber dotted. The map's grey is lighter
  // than the axis grey so the dashes read over the grid.
  const EW = '#9aa4b2';
  const DRAWN = ['win','lose','ew','sox'];
  const LINE = {
    win: {c:UP,  w:2,   d:'', label:m=>`up if ${m}`,
          swatch:`border-color:${UP}`},
    lose:{c:DN,  w:2,   d:'', label:m=>`down if ${m}`,
          swatch:`border-color:${DN}`},
    ew:  {c:EW,  w:1.4, d:' stroke-dasharray="4 3"', label:()=>'equal-weight map',
          swatch:`border-color:${EW};border-top-style:dashed`},
    sox: {c:SOX, w:1.4, d:SOX_DASH, label:()=>'SOX',
          swatch:`border-color:${SOX};border-top-style:dotted`},
  };
  const R2_NOTE = 'second ring · shown as a number';
  const drawnLines = s => DRAWN.filter(k=>hasPoints(s[k])).map(k=>({k:k, v:s[k]}));

  // A member whose last close is old says so, in words, after the separator.
  // The separator is written only with something after it: a bare "·" after a
  // name read as a suffix that failed to print.
  const staleNote = x => {
    const s = x.stale ? `${x.stale} sessions stale` : '';
    return s ? ` <span class="stale" title="last close ${esc(x.stale)} sessions old">· ${esc(s)}</span>` : '';
  };

  // The commitment on file, as commitments.json has it. A contract
  // re-committed before its answer date says when and why on one line, and
  // each hash it replaced is folded away beneath.
  function revisedLine(c){
    if(!c || !c.revised_at) return '';
    const before = String(c.revised_at) < String(c.answer_date);
    return `<div class="rev" data-revised="${esc(c.revised_at)}" style="margin-top:4px;font-family:IBM Plex Mono,monospace;font-size:.66rem;line-height:1.5;color:#e8ecf2">Revised ${esc(c.revised_at)} — ${before?'before':'not before'} the answer date${c.revision_note?' · '+esc(c.revision_note):''}</div>`;
  }
  function previousCommitments(c){
    const hist = c && c.revised_at && Array.isArray(c.history) ? c.history : [];
    return hist.slice().reverse().map(h=>`<details class="prev" style="margin-top:6px;font-family:IBM Plex Mono,monospace;font-size:.66rem;color:#7d8797"><summary>Previous commitment: ${esc(String(h.sha256||'').slice(0,12))}…, committed ${esc(h.committed_at)}</summary><div style="word-break:break-all">SHA-256 ${esc(h.sha256)} · replaced</div></details>`).join('');
  }

  // Every drawn line, then a filled dot where it ends with its value beside
  // it, so each line can be traced to a number. Painted map-first so the
  // basket sits on top. When lines end close together the labels are pushed
  // apart and the dots stay where the lines end; a dark outline keeps a label
  // readable over a line running under it.
  const LABEL_GAP = 11;
  function plot(lines, X, Y, top, bottom, side){
    let g = '';
    const ends = [];
    for(const ln of [...lines].reverse()){
      const st = LINE[ln.k];
      let d = '', started = false;
      ln.v.forEach((v,i)=>{ if(v==null) return;
        d += (started?'L':'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1) + ' ';
        started = true; });
      if(!d) continue;
      g += `<path data-line="${ln.k}" d="${d.trim()}" fill="none" stroke="${st.c}" stroke-width="${st.w}"${st.d} stroke-linejoin="round"/>`;
      const li = ln.v.reduce((a,v,i)=>v==null?a:i,-1);
      ends.push({k:ln.k, x:X(li), y:Y(ln.v[li]), v:ln.v[li], c:st.c});
    }
    ends.sort((a,b)=>a.y-b.y);
    let prev = -1e9;
    ends.forEach(e=>{ e.ly = Math.max(e.y, prev + LABEL_GAP); prev = e.ly; });
    const over = ends.length ? ends[ends.length-1].ly - bottom : 0;
    if(over > 0) ends.forEach(e=>{ e.ly = Math.max(top, e.ly - over); });
    for(const e of ends){
      g += `<circle data-end="${e.k}" cx="${e.x.toFixed(1)}" cy="${e.y.toFixed(1)}" r="3" fill="${e.c}"/>`;
      g += `<text data-end="${e.k}" x="${(e.x + 6*side).toFixed(1)}" y="${(e.ly+3).toFixed(1)}"${side<0?' text-anchor="end"':''} font-family="IBM Plex Mono,monospace" font-size="9" font-weight="600" fill="${e.c}" stroke="#0b0e14" stroke-width="3" paint-order="stroke">${p2(e.v)}</text>`;
    }
    return g;
  }

  // Exactly the lines drawn, in the order they matter, and the second ring as
  // a note with a dot rather than a line swatch -- only when its number shows.
  function legend(lines, m, ring2){
    return `<div class="cap">`
      + lines.map(ln=>`<span data-legend="${ln.k}"><i style="${LINE[ln.k].swatch}"></i>${LINE[ln.k].label(m)}</span>`).join('')
      + (ring2 ? `<span data-legend="r2"><i style="width:7px;height:7px;border:0;border-radius:50%;vertical-align:middle;background:${UP};opacity:.55"></i>${R2_NOTE}</span>` : '')
      + `</div>`;
  }

  const CW=560, CH=230, PADL=44, PADR=54, PADT=16, PADB=26;
  function chart(r){
    const s = r.series;
    if(!s) return `<div class="chart"><svg viewBox="0 0 ${CW} ${CH}">
      <line x1="${PADL}" x2="${CW-PADR}" y1="${CH/2}" y2="${CH/2}" stroke="#222a36"/>
      <circle cx="${PADL}" cy="${CH/2}" r="3.4" fill="${MAP}"/>
      </svg></div><p class="pending">first print after the next close</p>`;
    const lines = drawnLines(s);
    let hi=0; lines.forEach(ln=>ln.v.forEach(v=>{ if(v!=null) hi=Math.max(hi,Math.abs(v)); }));
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
    g += plot(lines, X, Y, PADT+4, CH-PADB-4, 1);
    const m=leg(r);
    // The second ring's numbers sit beside the card's other numbers; the
    // note shows exactly when they do.
    return `<div class="chart"><svg viewBox="0 0 ${CW} ${CH}">${g}</svg></div>
      ${legend(lines, m, r.has_r2)}`;
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
        rows += `<tr><td>${esc(x.label)}${staleNote(x)}</td>
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
  function observedChart(r, withNums){
    // withNums === false keeps the lines and drops the four numbers under
    // them. A card whose question has closed says its number once, in the
    // record line, and says it since the contract was signed rather than
    // since the report -- two numbers for one basket read as a discrepancy.
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
    const lines = drawnLines(o);
    let lo = 0, hi = 0;
    lines.forEach(ln => ln.v.forEach(v => {
      if(v==null) return; lo = Math.min(lo, v); hi = Math.max(hi, v); }));
    const pad = Math.max(0.6, (hi - lo) * 0.18);
    lo -= pad; hi += pad;
    const n = o.dates.length;
    const X = i => 8 + (i/(n-1||1)) * (CW-16);
    const Y = v => CH-14 - ((v-lo)/((hi-lo)||1)) * (CH-30);
    let g = '';
    // the zero line: the report's own close
    g += `<line x1="8" x2="${CW-8}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="#ffffff22" stroke-width="1"/>`;
    g += plot(lines, X, Y, 12, CH-10, -1);
    // The second ring is not drawn. It is this number, read at the last point
    // its basket reached, and the legend notes it only when it is shown.
    const w2 = o.win2 || [];
    const li2 = w2.reduce((a,y,i)=>y==null?a:i,-1);
    const up2 = li2>=0 ? w2[li2] : null;
    const nums = withNums === false ? '' : `<div class="obsnums">
        <div><b class="${sgn(o.up)}">${p2(o.up)}</b><span>up basket since the report</span></div>
        <div><b class="${sgn(o.up_ew)}">${p2(o.up_ew)}</b><span>up − map since the report</span></div>
        <div><b class="${sgn(o.up_sox)}">${p2(o.up_sox)}</b><span>up − SOX since the report</span></div>
        ${up2!=null?`<div><b class="${sgn(up2)}">${p2(up2)}</b><span>up · second ring since the report</span></div>`:''}
      </div>`;
    return `<div class="chart obschart">
      <span class="obsband">Observation · no position</span>
      <svg viewBox="0 0 ${CW} ${CH}">${g}</svg></div>
      ${legend(lines, 'yes', up2!=null)}
      ${nums}
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
        rows += `<tr><td>${esc(x.label)}${staleNote(x)}</td>
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

  // The official score: one number per scored question -- the excess over the
  // equal-weight map at the pre-registered primary horizon. Every other
  // horizon, and SOX, is a diagnostic read beside it and never a second chance
  // to be right. N counts questions, not horizons.
  function officialScore(r){
    if(!r.entry_date) return '';
    const PH = String(r.primary_horizon||20);
    const hz = r.horizons||{}, h = hz[PH];
    const diag = Object.keys(hz).filter(k=>k!==PH && hz[k])
      .sort((a,b)=>Number(a)-Number(b)).map(k=>`${k}d ${p2(hz[k].spread)}`);
    if(h && h.spread_sox!=null) diag.push(`vs SOX at ${PH}d ${p2(h.spread_sox)}`);
    const big = 'display:block;font-family:IBM Plex Mono,monospace;font-weight:500;line-height:1.1';
    const val = h
      ? `<b data-official-value class="${h.hit?'pos':'neg'}" style="${big};font-size:1.6rem">${p2(h.spread)}</b><span>${h.hit?'hit':'miss'} · locked ${esc(h.date)}</span>`
      : `<b data-official-value class="flat" style="${big};font-size:1.1rem">pending</b><span>locks at session ${PH} · day ${esc(r.day_index)} of ${PH}</span>`;
    return `<div class="official" data-official="${PH}" data-official-state="${h?'scored':'pending'}" style="margin-top:14px;padding:10px 12px;border:1px solid #31405a;border-radius:8px">
      <div style="font-family:IBM Plex Mono,monospace;font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:#b3bccb;margin-bottom:6px">Official score · ${PH}-session excess vs EW_MAP</div>
      <div style="font-family:IBM Plex Mono,monospace;font-size:.62rem;color:#7d8797">${val}</div>
      ${diag.length?`<div data-diagnostic style="margin-top:8px;font-family:IBM Plex Mono,monospace;font-size:.6rem;color:#7d8797">Diagnostic, not the score · ${diag.map(esc).join(' · ')}</div>`:''}
    </div>`;
  }

  // Why an answered card is not (or not yet) in the official score, in the
  // card's own words. A scored card says it with its number instead.
  function offNote(r){
    const o = r.official;
    if(!o || !ANSWERED(r) || r.entry_date || o.state==='scored') return '';
    const lead = o.state==='pending' ? 'Not yet in the official score' : 'Not in the official score';
    return `<div class="offnote" data-official-state="${esc(o.state)}" style="margin-top:8px;font-family:IBM Plex Mono,monospace;font-size:.66rem;color:#7d8797;line-height:1.5">${lead} · ${esc(o.reason)}</div>`;
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
    // Not answered yet, so no Verify box: the revision sits under the
    // pre-registered line itself. An answered card carries it in that box.
    if(!ANSWERED(r)) line += revisedLine(r.commitment) + previousCommitments(r.commitment);
    const t = r.today||{};
    const nums = r.entry_date ? `<div class="big">
        <div><b class="${sgn(t.win_lose)}">${p2(t.win_lose)}</b><span>up − down today</span></div>
        <div><b class="${sgn(t.win_ew)}">${p2(t.win_ew)}</b><span>up − map today</span></div>
        <div><b class="${sgn(t.win_sox)}">${p2(t.win_sox)}</b><span>vs SOX</span></div>
      </div>` + (r.has_r2?`<div class="small">
        <div><b class="${sgn(t.win2_lose2)}">${p2(t.win2_lose2)}</b><span>ring 2 up − down</span></div>
        <div><b class="${sgn(t.win2_ew)}">${p2(t.win2_ew)}</b><span>ring 2 up − map</span></div>
      </div>`:'') : '';
    return `<div>
      ${badge}
      <div class="who" style="margin-top:12px">${r.record
        ? `<a class="trecname" href="${esc(r.qid)}/">${esc(r.who)}${r.tk?' · '+esc(r.tk):''}</a>`
        : `${esc(r.who)}${r.tk?' · '+esc(r.tk):''}`}</div>
      <div class="dt">${esc(when)}</div>
      ${question(r)}
      ${findings(r)}
      ${line}${officialScore(r)}${offNote(r)}${nums}
    </div>`;
  }

  // Pre-registration. A resolved question carries the contract it was scored
  // under -- the exact bytes that were hashed -- and the SHA-256 that was
  // published before its answer date. The reader's browser recomputes the
  // hash, so nothing here has to be taken on trust. The contract is revealed
  // only once the answer is in, which is when its yes/no wording stops being
  // paid. Hashing is the only WebCrypto call in this file; it opens nothing.
  const PREREG_TEXT = {
    verified: 'Verified — committed before the answer date',
    late: (c,a) => `Hash matches, but not a valid preregistration — committed ${c}, not before the answer date ${a}`,
    mismatch: (h,s) => `Mismatch — the revealed contract hashes to ${h.slice(0,16)}…, not the committed ${s.slice(0,16)}…`,
    unavailable: 'This browser cannot compute SHA-256 on this page (it needs a secure https page)',
  };
  async function verifyPrereg(contract, sha, valid, committed, answer){
    const c = globalThis.crypto;
    if(!(c && c.subtle && globalThis.TextEncoder))
      return {state:'unavailable', text:PREREG_TEXT.unavailable};
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(contract));
    const hex = Array.from(new Uint8Array(buf), b=>b.toString(16).padStart(2,'0')).join('');
    if(hex !== String(sha).toLowerCase())
      return {state:'mismatch', hex:hex, text:PREREG_TEXT.mismatch(hex, String(sha))};
    if(!valid) return {state:'late', hex:hex, text:PREREG_TEXT.late(committed, answer)};
    return {state:'verified', hex:hex, text:PREREG_TEXT.verified};
  }
  window.verifyPrereg = verifyPrereg;

  function prereg(r){
    const p = r.prereg;
    if(!p || !p.contract || !ANSWERED(r)) return '';
    const ok = !!p.valid_preregistration;
    // A contract re-committed before its answer date says when and why. Verify
    // checks the hash in force; the ones it replaced are folded away below.
    const c = p.revised_at ? p
      : (r.commitment && r.commitment.revised_at ? r.commitment : null);
    const revised = revisedLine(c);
    const previous = previousCommitments(c);
    return `<div class="prereg" data-prereg="${esc(r.qid)}" data-sha="${esc(p.sha256)}" data-valid="${ok?'1':'0'}" data-committed="${esc(p.committed_at)}" data-answer="${esc(p.answer_date)}" data-contract="${esc(p.contract)}" style="margin-top:12px;padding:10px 12px;border:1px solid #222a36;border-radius:6px;font-family:IBM Plex Mono,monospace;font-size:.7rem;color:#b3bccb">
      <div>Pre-registered ${esc(p.committed_at)} · answer date ${esc(p.answer_date)} · primary horizon ${esc(p.primary_horizon)} sessions${ok?'':' · <b style="color:#f2b632">not a valid preregistration</b>'}</div>${revised}
      <div style="word-break:break-all;margin:6px 0;color:#7d8797">SHA-256 ${esc(p.sha256)} · ${p.hash_source==='commitments.json'?'read from commitments.json':'as carried in this page'}</div>
      <button type="button" data-verify style="font:inherit;color:#e8ecf2;background:#141922;border:1px solid #31405a;border-radius:4px;padding:4px 10px;cursor:pointer">Verify preregistration</button>
      <span class="pr-result" role="status" style="margin-left:8px"></span>${previous}
      <details style="margin-top:6px"><summary>Scoring contract — the exact bytes that were hashed</summary><pre style="white-space:pre-wrap;word-break:break-all">${esc(p.contract)}</pre></details>
    </div>`;
  }

  // One line on the card, and a door. The legs, the charts and the benchmark
  // table live on the question's own page -- a card that carried them stopped
  // being a card. chains/record.py measured every number here.
  function recordLine(r){
    const R = r.record;
    if(!R) return '';
    const b = R.benchmarks || {};
    const n = b.sessions;
    return `<p class="trecline" data-record="${esc(r.qid)}">
      <span class="trecnums">basket <b class="${sgn(b.win)}">${p2(b.win)}</b>
        · EW_MAP <b class="${sgn(b.ew)}">${p2(b.ew)}</b>
        · <b class="${sgn(b.win_ew)}">${p2(b.win_ew)}</b> vs the map
        over ${n==null?'—':n} session${n===1?'':'s'}</span>
      <a class="trecmore" href="${esc(r.qid)}/">Full record →</a></p>`;
  }

  // The master table: one row per question that has closed. Sorted in the
  // browser only -- the numbers are the build's.
  const RT_COLS = [['qid','Question',0], ['who','Company',0],
                   ['answer_date','Answered',0], ['verdict','Verdict',0],
                   ['basket','Basket',1], ['ew','EW_MAP',1], ['sox','SOX',1],
                   ['excess_ew','vs EW_MAP',1], ['sessions','Sessions',2],
                   ['committed_at','Signed',0], ['sha','Hash',0]];
  function recordTable(rows){
    if(!rows || !rows.length)
      return '<p class="empty">No question has closed yet.</p>';
    // The index links into the detail page; everything heavy lives there.
    const cell = (r, k, kind) =>
      k === 'qid' ? `<td><a href="${esc(r.qid)}/">${esc(r.qid)}</a></td>`
      : kind === 1 ? `<td class="${sgn(r[k])}">${p2(r[k])}</td>`
      : kind === 2 ? `<td>${r[k]==null?'—':r[k]}</td>`
      : `<td>${esc(r[k]==null?'—':r[k])}</td>`;
    const head = RT_COLS.map(([k,l]) =>
      `<th data-col="${esc(k)}" scope="col">${esc(l)}</th>`).join('');
    const body = rows.map(r =>
      `<tr data-qid="${esc(r.qid)}">`
      + RT_COLS.map(([k,,kind]) => cell(r, k, kind)).join('') + `</tr>`).join('');
    return `<div class="tw2"><table data-record-table><tr>${head}</tr>${body}</table></div>`;
  }
  function wireSort(box){
    if(!box || box.__sortWired) return;
    box.__sortWired = true;
    box.addEventListener('click', ev => {
      const th = ev.target && ev.target.closest ? ev.target.closest('th[data-col]') : null;
      if(!th) return;
      const table = th.closest('table'), rows = [...table.rows].slice(1);
      const i = [...th.parentNode.children].indexOf(th);
      const dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
      table.querySelectorAll('th[data-col]').forEach(h => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
      const val = tr => {
        const t = tr.cells[i].textContent.trim().replace(/[%,+]/g, '');
        const n = parseFloat(t);
        return isNaN(n) ? t.toLowerCase() : n;
      };
      rows.sort((a, b) => { const x = val(a), y = val(b);
                            return (x > y ? 1 : x < y ? -1 : 0) * dir; });
      rows.forEach(tr => table.appendChild(tr));
    });
  }

  function card(r, today){
    // A reported card plots from the report's close. It has no forecast
    // series -- it was never entered -- so it cannot use chart(), and the
    // constellation it used to show said nothing about what happened after.
    const mid = (r.state==='tracking'||r.state==='closed'||r.state==='marked')
      ? chart(r)
      : (r.state==='reported' && r.observed ? observedChart(r, !r.record)
                                            : constellation(r));
    // A closed question keeps its chart -- the basket against the map and
    // SOX is the card's signature, and a card without it is a paragraph. What
    // it loses is the heavy member table, which its own page draws properly
    // with every leg's prices beside it.
    if(r.record)
      return `<article class="fc light ${esc(r.state)}" data-id="${esc(r.qid)}" data-state="${esc(r.state)}">
      ${head(r, today)}<div>${mid}</div><div>${recordLine(r)}${prereg(r)}</div></article>`;
    return `<article class="fc ${esc(r.state)}" data-id="${esc(r.qid)}" data-state="${esc(r.state)}">
      ${head(r, today)}<div>${mid}</div><div>${table(r)}${recordLine(r)}${prereg(r)}</div></article>`;
  }

  function closedRow(r, today){
    const chips = ['5','10','20','40'].map(h=>{
      const d = (r.horizons||{})[h];
      const primary = h===String(r.primary_horizon||20);
      return `<span class="${d?(d.hit?'hit':'miss'):''}"${primary?' data-official="1"':''}>${h}d${primary?' official':''} ${d?p2(d.spread):'—'}</span>`;
    }).join(' ');
    return `<details class="closed" data-id="${esc(r.qid)}" data-state="closed">
      <summary><b>${esc(r.who)}</b><span class="pill ${word(r)}">${word(r)}</span>${chips}</summary>
      ${card(r, today)}</details>`;
  }

  // The record. It leads with the official score -- the excess over the
  // equal-weight map at the primary horizon -- and every number carries its N.
  // N counts scored QUESTIONS, never horizons. Below the interval threshold no
  // range is drawn at all: the record says how few there are instead. The
  // other horizons, SOX and the second ring sit beneath, labelled for what they
  // are.
  function tiles(S){
    const tile = (v,label,cls,attr) =>
      `<div class="tile ${cls||''}"${attr||''}><b>${v}</b><span>${esc(label)}</span></div>`;
    const rate = s => (s && s.value!=null) ? Math.round(s.value*100)+'%' : '0 / 0';
    const cap = (s,txt) => (s && s.n) ? txt+' (n='+s.n+')'
                                      : 'no scored forecasts yet';
    const pct = v => v==null ? '—' : Math.round(v*100)+'%';
    const R = S.record || null;
    const PH = (R && R.primary_horizon) || 20;
    const N = R ? (R.n||0) : 0;
    const lbl = t => `<div class="rlbl" style="font-family:IBM Plex Mono,monospace;font-size:.62rem;letter-spacing:.12em;text-transform:uppercase;color:#b3bccb;margin:0 0 8px">${t}</div>`;
    const nu = S.next_up||null;
    const flight = Math.max(0, (S.n_forecasts||0) - N);
    const counts = `<p class="tcap">${S.n_answered||0} answered · `
      + `${N} scored at ${PH} sessions · ${flight} in flight · `
      + `${S.n_unscored||0} no forecast</p>`;

    let head;
    if(!N){
      head = `<div class="record" data-record-n="0">
        ${lbl(`Official score · ${PH}-session excess vs EW_MAP`)}
        <p class="empty" data-record-empty>No forecast has completed its ${PH}-session window yet.</p>
      </div>`;
    } else {
      const few = N < (R.min_n_for_interval||8);
      const tooFew = `N=${N} — too few to estimate a range`;
      const band = (iv, fmt) => iv ? `95% range ${fmt(iv[0])} to ${fmt(iv[1])}` : tooFew;
      head = `<div class="record" data-record-n="${N}">
        ${lbl(`Official score · ${PH}-session excess vs EW_MAP · N = ${N} scored question${N===1?'':'s'}`)}
        <div class="tiles">
          ${tile(N, `N · questions scored at ${PH} sessions`, '', ' data-stat="n"')}
          ${tile(`${R.hits}/${N}`, `hit rate ${pct(R.hit_rate)} · ${few ? tooFew : band(R.hit_rate_interval, pct)}`, '', ' data-stat="hit"')}
          ${tile(p2(R.mean_excess), `mean excess, signed to the call · ${few ? tooFew : band(R.mean_excess_interval, p2)}`, sgn(R.mean_excess), ' data-stat="mean"')}
          ${tile(p2(R.median_excess), `median excess, signed to the call (N=${N})`, sgn(R.median_excess), ' data-stat="median"')}
        </div>
      </div>`;
    }

    const D = (R && R.diagnostic) || {};
    const X = (R && R.sox) || {};
    const dtiles = ['5','10','40']
      .filter(h => D[h] && (h !== '40' || D[h].n))
      .map(h => tile(D[h].n ? `${D[h].hits}/${D[h].n}` : '0 / 0',
                     D[h].n ? `hit at ${h}d (n=${D[h].n})` : 'no scored forecasts yet')
              + tile(D[h].n && D[h].mean_excess!=null ? p2(D[h].mean_excess) : '0 / 0',
                     D[h].n ? `mean excess at ${h}d (n=${D[h].n})` : 'no scored forecasts yet'))
      .join('');
    const diag = `<div class="diag" data-diagnostic-row style="margin-top:6px">
      ${lbl('Diagnostic, not the score')}
      <div class="tiles">
        ${dtiles}
        ${tile(X.n ? p2(X.mean_excess) : '0 / 0', X.n ? `excess vs SOX at ${PH}d (n=${X.n})` : 'no scored forecasts yet', '', ' data-stat="sox"')}
        ${tile(rate(S.ring2_hit_5), cap(S.ring2_hit_5,'second ring hit 5d'))}
        ${tile(S.n_upcoming||0, nu ? 'pre-registered · next '+nu.d+' '+nu.who
                                   : 'pre-registered')}
      </div>
    </div>`;
    return counts + head + diag;
  }

  window.renderTrack = function(root, data, opts){
    // {tiles:false}: the page draws the scoreboard once, over the free
    // cards, and not again over the ones a key opens beneath them.
    opts = opts || {};
    // The payload carries its own glossary, so a card drawn from a decrypted
    // file underlines the same words as one drawn from live.json.
    if(window.GL) GL.use((data && data.glossary) || {});
    const F = (data && data.forecasts) || [], S = (data && data.summary) || {};
    const today = data && data.as_of ? new Date(data.as_of+'T00:00:00Z')
                                     : new Date();
    const open = F.filter(r=>r.state!=='closed');
    const shut = F.filter(r=>r.state==='closed');
    root.innerHTML = (opts.tiles === false ? '' : tiles(S))
      + open.map(r=>card(r, today)).join('')
      + (shut.length ? `<div class="sect">Closed · every checkpoint scored</div>`
          + shut.map(r=>closedRow(r, today)).join('') : '');
    // The master table lives outside the cards, in its own section. The
    // private map inlines this file and has no such element; it simply is not
    // drawn there.
    // Three hosts run this renderer: the public page, which has the section;
    // the private map, which does not; and the node harness in
    // tests/test_track.py, which has no document at all. Reaching for one
    // unguarded took every card down with it.
    const rt = (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById('record-table') : null;
    if(rt){
      rt.innerHTML = recordTable((data && data.record_table) || []);
      wireSort(rt);
    }
    // One listener per root, however many times the cards are redrawn.
    if(root.addEventListener && !root.__preregWired){
      root.__preregWired = true;
      root.addEventListener('click', ev=>{
        const b = ev.target && ev.target.closest ? ev.target.closest('[data-verify]') : null;
        if(!b) return;
        const box = b.closest('[data-prereg]'), out = box.querySelector('.pr-result');
        out.textContent = 'Checking…';
        verifyPrereg(box.dataset.contract, box.dataset.sha, box.dataset.valid==='1',
                     box.dataset.committed, box.dataset.answer)
          .then(res=>{ out.textContent = res.text; box.dataset.state = res.state; })
          .catch(()=>{ out.textContent = PREREG_TEXT.unavailable; });
      });
    }
    return F.length;
  };
})();
