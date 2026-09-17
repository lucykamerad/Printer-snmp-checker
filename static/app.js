const CRIT = 5, WARN = 15;
let allPrinters = [], pollTimer = null;

/* ---- Utils ---- */
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') }

function toast(msg, dur=2500){
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'), dur);
}

function pctClass(pct){
  if(pct===null||pct===undefined) return 'nd';
  if(pct<=CRIT) return 'crit';
  if(pct<=WARN) return 'warn';
  return 'ok';
}

function badgeHtml(min_pct){
  if(min_pct===null||min_pct===undefined) return '<span class="card-badge badge-nd">N/D</span>';
  if(min_pct<=CRIT) return `<span class="card-badge badge-crit">⚠ CRITICO ${min_pct.toFixed(1)}%</span>`;
  if(min_pct<=WARN) return `<span class="card-badge badge-warn">↓ BASSO ${min_pct.toFixed(1)}%</span>`;
  return `<span class="card-badge badge-ok">OK ${min_pct.toFixed(1)}%</span>`;
}

function barHtml(pct){
  const cls = pctClass(pct);
  const w   = pct!==null ? Math.min(100,Math.max(0,pct)).toFixed(1) : 0;
  const pctStr = pct!==null ? `${pct.toFixed(1)}%` : 'N/D';
  return `
    <div class="supply-head">
      <span class="supply-name">__DESC__</span>
      <span class="supply-pct pct-${cls}">${pctStr}</span>
    </div>
    <div class="bar-track"><div class="bar-fill fill-${cls}" style="width:${pct!==null?w+'%':'100%'}"></div></div>`;
}

/* ---- Render grid ---- */
function renderGrid(){
  const query   = document.getElementById('search-input').value.toLowerCase();
  const sortBy  = document.getElementById('sort-select').value;
  let data = [...allPrinters];

  if(query) data = data.filter(p =>
    p.name.toLowerCase().includes(query) || p.ip.includes(query)
  );

  data.sort((a,b)=>{
    if(sortBy==='min_asc'){
      const an = a.min_pct===null, bn = b.min_pct===null;
      if(an&&bn) return 0; if(an) return 1; if(bn) return -1;
      return a.min_pct - b.min_pct;
    }
    if(sortBy==='min_desc'){
      const an = a.min_pct===null, bn = b.min_pct===null;
      if(an&&bn) return 0; if(an) return 1; if(bn) return -1;
      return b.min_pct - a.min_pct;
    }
    if(sortBy==='name') return a.name.localeCompare(b.name);
    if(sortBy==='ip'){
      const ai = a.ip.split('.').map(Number), bi = b.ip.split('.').map(Number);
      for(let i=0;i<4;i++) if(ai[i]!==bi[i]) return ai[i]-bi[i];
      return 0;
    }
    return 0;
  });

  const grid = document.getElementById('printers-grid');
  if(!data.length){
    grid.innerHTML = `<div class="empty">Nessuna stampante trovata${query?' per la ricerca "'+esc(query)+'"':''}</div>`;
    return;
  }

  grid.innerHTML = data.map(p => {
    const supSorted = [...p.supplies].sort((a,b)=>{
      const an=a.percent===null, bn=b.percent===null;
      if(an&&bn) return 0; if(an) return 1; if(bn) return -1;
      return a.percent - b.percent;
    });
    const supHtml = supSorted.map(s => `
      <div class="supply-row">
        ${barHtml(s.percent).replace('__DESC__', esc(s.desc))}
      </div>`).join('');

    return `
    <div class="card">
      <div class="card-head">
        <div class="card-left">
          <span class="card-name">${esc(p.name)}</span>
          <span class="card-ip">${esc(p.ip)}</span>
        </div>
        ${badgeHtml(p.min_pct)}
      </div>
      ${p.supplies.length
        ? `<div class="sec-label">Forniture (${p.supplies.length})</div>${supHtml}`
        : '<div class="sec-label">Nessuna fornitura rilevata</div>'}
      <div class="card-foot">rilevato alle ${esc(p.scanned_at||'—')}</div>
    </div>`;
  }).join('');
}

/* ---- Stats ---- */
function updateStats(printers, ts){
  const total   = printers.length;
  const crits   = printers.filter(p=>p.min_pct!==null&&p.min_pct<=CRIT).length;
  const warns   = printers.filter(p=>p.min_pct!==null&&p.min_pct<=WARN&&p.min_pct>CRIT).length;
  const supplies= printers.reduce((s,p)=>s+p.supplies.length,0);
  document.getElementById('st-total').textContent    = total||'—';
  document.getElementById('st-crit').textContent     = total?crits:'—';
  document.getElementById('st-crit-sub').textContent = crits>0 ? `${crits} richiedo${crits>1?'no':''} attenzione!` : '';
  document.getElementById('st-warn').textContent     = total?warns:'—';
  document.getElementById('st-supplies').textContent = total?supplies:'—';
  document.getElementById('st-ts').textContent       = ts||'—';
}

/* ---- Scan ---- */
function startScan(){
  const btn    = document.getElementById('btn-scan');
  const subnet = document.getElementById('cfg-subnet').value.trim() || null;
  const comm   = document.getElementById('cfg-community').value.trim() || 'public';
  const hostsRaw = document.getElementById('cfg-hosts').value.trim();
  const hosts  = hostsRaw ? hostsRaw.split(',').map(h=>h.trim()).filter(Boolean) : null;

  const params = new URLSearchParams();
  if(subnet) params.append('subnet', subnet);
  if(comm)   params.append('community', comm);
  if(hosts)  params.append('hosts', hosts.join(','));

  btn.disabled = true;
  btn.textContent = '↻ Scansione...';
  document.getElementById('scan-bar-wrap').style.display = 'block';
  document.getElementById('scan-label').textContent = 'Avvio...';

  fetch('/api/scan', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:params})
    .then(r=>r.json())
    .then(d=>{
      if(d.ok){ pollStatus(); }
      else { toast('Errore: ' + d.error); resetScanBtn(); }
    })
    .catch(()=>{ toast('Errore di rete'); resetScanBtn(); });
}

function resetScanBtn(){
  const btn = document.getElementById('btn-scan');
  btn.disabled = false; btn.textContent = '▶ Scansiona';
  document.getElementById('scan-bar-wrap').style.display = 'none';
}

function pollStatus(){
  clearTimeout(pollTimer);
  fetch('/api/status')
    .then(r=>r.json())
    .then(d=>{
      const fill  = document.getElementById('scan-bar-fill');
      const label = document.getElementById('scan-label');
      if(d.running){
        const pct = d.total>0 ? Math.round(d.progress/d.total*100) : 0;
        fill.style.width = pct+'%';
        label.textContent = `${d.progress}/${d.total} host`;
        pollTimer = setTimeout(pollStatus, 600);
      } else {
        fill.style.width = '100%';
        label.textContent = d.error ? 'Errore' : `Completata — ${d.finished||''}`;
        setTimeout(()=>{ document.getElementById('scan-bar-wrap').style.display='none'; label.textContent='—'; },3000);
        resetScanBtn();
        fetchPrinters();
        if(d.error) toast('Errore scansione: '+d.error);
      }
    })
    .catch(()=>{ pollTimer = setTimeout(pollStatus, 1500); });
}

function fetchPrinters(){
  fetch('/api/printers')
    .then(r=>r.json())
    .then(d=>{
      allPrinters = d.printers || [];
      updateStats(allPrinters, d.scanned_at);
      renderGrid();
    });
}

/* ---- Config panel ---- */
function toggleCfg(){
  const p = document.getElementById('cfg-panel');
  p.style.display = p.style.display==='none'||!p.style.display ? 'block' : 'none';
}

/* ---- Export ---- */
function exportTxt(){
  window.open('/api/export/txt','_blank');
}
function exportJson(){
  window.open('/api/export/json','_blank');
}

/* ---- Wire up buttons ---- */
document.getElementById('btn-cfg').addEventListener('click', toggleCfg);
document.getElementById('btn-scan').addEventListener('click', startScan);
document.getElementById('btn-export-txt').addEventListener('click', exportTxt);
document.getElementById('btn-export-json').addEventListener('click', exportJson);
document.getElementById('search-input').addEventListener('input', renderGrid);
document.getElementById('sort-select').addEventListener('change', renderGrid);

/* ---- Init ---- */
fetchPrinters();
// Auto-ricarica dati ogni 30s se non c'è scansione in corso
setInterval(()=>{ if(!document.getElementById('btn-scan').disabled) fetchPrinters(); }, 30000);
