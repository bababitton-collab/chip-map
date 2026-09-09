// ---- dated questions: teaser (next 5) ----
(function(){
  // Fixed, and never the real text: a CSS blur is a picture, not
  // a lock, and blurring the real sentence would ship it in the DOM.
  const LOCK_DUMMY = 'שאלה נעולה — הטקסט המלא מגיע במייל השבועי יחד עם מה שצריך להקשיב לו בשיחת התוצאות';
  const W = D.watch||LIVE.watch||[]; if(!W.length) return;
  const today = new Date(D.as_of+'T00:00:00Z'); const now=new Date(); const ref = now>today?now:today;
  const days = d => Math.round((Date.parse(d+'T00:00:00Z') - Date.UTC(ref.getUTCFullYear(),ref.getUTCMonth(),ref.getUTCDate()))/86400000);
  const nameOf = id => (byId[id]&&byId[id].short) || id.toUpperCase();
  const rows = W.slice().sort((a,b)=>a.d.localeCompare(b.d)).filter(w=>days(w.d)>=0).slice(0,5);
  document.getElementById('wlist').innerHTML = rows.map(w=>{ const dd=days(w.d); return `<div class="wrow ${dd<=21?'soon':''}">
    <div class="wd"><b>${dd===0?'היום':'בעוד '+dd+' ימים'}</b>${w.d}<small>${w.tk}</small><em class="${w.confirmed?'c':''}">${w.confirmed?'מאושר':'צפוי'}</em></div>
    <div class="ww"><b>${w.who}</b>${w.cps.map(c=>`<span class="cp" data-cp="${c}">${c}</span>`).join('')}<span class="wl">${w.win.length?'מרוויח אם כן: <span dir="ltr">'+w.win.map(nameOf).join(' · ')+'</span>':''}${w.lose.length?' · מפסיד: <span dir="ltr">'+w.lose.map(nameOf).join(' · ')+'</span>':''}</span></div>
    <div class="wq">${w.locked? `<span class="blur">${LOCK_DUMMY}</span><span class="lockline">🔒 הטקסט המלא — <b>במייל השבועי</b></span>` : `${w.q}<span class="lis"><b>להקשיב ל:</b> ${w.listen}</span>`}</div></div>`; }).join('');
  document.querySelectorAll('#wlist .cp').forEach(el=>el.addEventListener('click',()=>{ const c=D.cps.find(c=>c.id===el.dataset.cp); const h=c&&c.holders[0]&&byId[c.holders[0].id]; if(h){ open(h); document.getElementById('stage').scrollIntoView({behavior:'smooth'}); } }));
})();
