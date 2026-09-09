// ---- dated questions: teaser (next 5) ----
(function(){
  const W = D.watch||LIVE.watch||[]; if(!W.length) return;
  const today = new Date(D.as_of+'T00:00:00Z'); const now=new Date(); const ref = now>today?now:today;
  const days = d => Math.round((Date.parse(d+'T00:00:00Z') - Date.UTC(ref.getUTCFullYear(),ref.getUTCMonth(),ref.getUTCDate()))/86400000);
  const nameOf = id => (byId[id]&&byId[id].short) || id.toUpperCase();
  const rows = W.slice().sort((a,b)=>a.d.localeCompare(b.d)).filter(w=>days(w.d)>=0).slice(0,5);
  document.getElementById('wlist').innerHTML = rows.map(w=>{ const dd=days(w.d); return `<div class="wrow ${dd<=21?'soon':''}">
    <div class="wd"><b>${dd===0?'today':'in '+dd+' days'}</b>${w.d}<small>${w.tk}</small><em class="${w.confirmed?'c':''}">${w.confirmed?'confirmed':'expected'}</em></div>
    <div class="ww"><b>${w.who}</b>${w.cps.map(c=>`<span class="cp" data-cp="${c}">${c}</span>`).join('')}<span class="wl">${w.win.length?'gains if yes: '+w.win.map(nameOf).join(' · '):''}${w.lose.length?' · loses: '+w.lose.map(nameOf).join(' · '):''}</span></div>
    <div class="wq">${w.q}<span class="lis"><b>Listen for:</b> ${w.listen}</span></div></div>`; }).join('');
  document.querySelectorAll('#wlist .cp').forEach(el=>el.addEventListener('click',()=>{ const c=D.cps.find(c=>c.id===el.dataset.cp); const h=c&&c.holders[0]&&byId[c.holders[0].id]; if(h){ open(h); document.getElementById('stage').scrollIntoView({behavior:'smooth'}); } }));
})();
