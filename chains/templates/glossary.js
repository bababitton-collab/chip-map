// Plain-language definitions, in the page.
//
// window.GL.mark(text, only)  -> HTML with each matched term wrapped
// window.GL.find(text)        -> term ids, first-occurrence order, max 4
// window.GL.chips(ids)        -> the "Terms" line
//
// Three surfaces use it: the question cards, the tracking cards, and the
// station panel. It is one file inlined into both pages rather than three
// copies, for the same reason the card renderer is.
//
// WHICH terms a card shows is decided in Python and shipped per row, so the
// chips and the letter can never disagree with the page. What this does is
// place them: a disagreement here shows up as a missing underline, never as
// the wrong definition under the right word.
(function(){
  const esc = v => String(v==null?'':v).replace(/[&<>"]/g, c=>(
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const MAX = 4;

  // Handed in, not hunted for: the pages keep their data in a top-level
  // const, which is not a window property, so reaching for window.D found
  // nothing and every card rendered bare.
  let STORE = {};
  const terms = () => STORE;

  // Longest first, so "HBM4" takes the HBM entry rather than leaving a bare
  // "HBM" and a dangling 4, and "High-NA" is one term and not also the "NA"
  // inside it.
  function pairs(){
    const G = terms(), out = [];
    for(const id in G) for(const m of (G[id].match||[])) out.push([m, id]);
    out.sort((a,b)=> b[0].length - a[0].length || (a[0]<b[0]?-1:1));
    return out;
  }
  // A match string with a capital in it IS the word -- HBM, InP, FY27. A plain
  // lowercase one is a normal word, and "Capex" starting a sentence is capex.
  const cased = m => m !== m.toLowerCase();
  // Written as escapes, not as literal characters: the English page refuses
  // to ship any character in the Hebrew block, and a regex range is a
  // character like any other to a byte-level gate.
  const alnum = c => !!c && /[0-9A-Za-z\u0590-\u05FF]/.test(c);
  const rx = m => new RegExp(m.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),
                             cased(m) ? 'g' : 'gi');

  function spans(text, only){
    const claimed = [], out = [];
    for(const [m, id] of pairs()){
      if(only && only.indexOf(id) < 0) continue;
      const re = rx(m); let hit;
      while((hit = re.exec(text)) !== null){
        const s = hit.index, e = s + hit[0].length;
        if(alnum(text[s-1]) || alnum(text[e])) continue;
        if(claimed.some(c => s < c[1] && c[0] < e)) continue;
        claimed.push([s,e]); out.push([s,e,id]);
      }
    }
    out.sort((a,b)=>a[0]-b[0]);
    return out;
  }

  function find(text, limit){
    const out = [];
    for(const [_s,_e,id] of spans(text||'', null)){
      if(out.indexOf(id) < 0) out.push(id);
      if(out.length >= (limit||MAX)) break;
    }
    return out;
  }

  function mark(text, only){
    text = String(text==null?'':text);
    const G = terms();
    if(!text || !Object.keys(G).length) return esc(text);
    const keep = only && only.length ? only : find(text);
    let out = '', at = 0;
    for(const [s,e,id] of spans(text, keep)){
      out += esc(text.slice(at,s))
        + '<abbr class="gl" data-gl="' + esc(id) + '">'
        + esc(text.slice(s,e)) + '</abbr>';
      at = e;
    }
    return out + esc(text.slice(at));
  }

  function chips(ids, label){
    const G = terms();
    ids = (ids||[]).filter(i => G[i]);
    if(!ids.length) return '';
    return '<div class="terms"><b>' + esc(label||'Terms') + '</b>'
      + ids.map(i => '<span class="gchip gl" data-gl="' + esc(i) + '">'
                   + esc(G[i].label) + '</span>').join('')
      + '</div>';
  }

  // ---- the tooltip: one element, moved about ----------------------------
  let tip = null;
  function el(){
    if(tip) return tip;
    tip = document.createElement('div');
    tip.className = 'gltip';
    tip.setAttribute('role','tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }
  let current = null;
  function show(target){
    const G = terms(), t = G[target.dataset.gl];
    if(!t) return;
    current = target;
    const e = el();
    e.innerHTML = '<b>' + esc(t.label) + '</b>' + esc(t.def);
    e.hidden = false;
    const b = target.getBoundingClientRect();
    const w = e.offsetWidth, h = e.offsetHeight;
    let x = b.left + b.width/2 - w/2 + window.scrollX;
    let y = b.top - h - 9 + window.scrollY;
    x = Math.max(8, Math.min(x, window.innerWidth - w - 8 + window.scrollX));
    // Above the word unless there is no room, then below it.
    if(b.top - h - 9 < 0) y = b.bottom + 9 + window.scrollY;
    e.style.left = x + 'px';
    e.style.top = y + 'px';
  }
  function hide(){ current = null; if(tip) tip.hidden = true; }

  document.addEventListener('mouseover', ev => {
    const t = ev.target.closest && ev.target.closest('.gl[data-gl]');
    if(t) show(t);
  });
  document.addEventListener('mouseout', ev => {
    if(ev.target.closest && ev.target.closest('.gl[data-gl]')) hide();
  });
  // Tap on a touch screen, and a tap anywhere else closes it.
  document.addEventListener('click', ev => {
    const t = ev.target.closest && ev.target.closest('.gl[data-gl]');
    if(t){ ev.preventDefault(); show(t); } else hide();
  });
  document.addEventListener('keydown', ev => { if(ev.key === 'Escape') hide(); });
  // Follow the word rather than vanish. Hiding on scroll ate the tooltip a
  // hover had just opened, because scrolling the word into view fires a scroll
  // event of its own -- and after a real scroll it left the box pointing at
  // nothing.
  window.addEventListener('scroll', () => {
    if(current && tip && !tip.hidden){
      if(current.isConnected) show(current); else hide();
    }
  }, {passive:true});

  window.GL = {mark: mark, find: find, chips: chips, hide: hide,
               use: g => { STORE = g || {}; }};
})();
