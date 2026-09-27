/* ═══════════════════════════════════════
   PortfolioLab – Superinvestitori (Dataroma 13F)
   Depends on globals from app.js: API, apiFetch, portfolio.
═══════════════════════════════════════ */

(function () {
  const loaded = { consensus: false, managers: false };

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, dec = 2) => v == null ? '—' : v.toLocaleString('it-IT', { maximumFractionDigits: dec });
  const usd = v => v == null ? '—' : '$' + num(v, 2);
  const bigUsd = v => {
    if (v == null) return '—';
    if (v >= 1e9) return '$' + num(v / 1e9, 2) + ' B';
    if (v >= 1e6) return '$' + num(v / 1e6, 1) + ' M';
    return '$' + num(v, 0);
  };
  const signed = v => v == null ? '—'
    : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${num(v)}%</span>`;
  const activity = a => !a ? '' : `<span class="${/^(buy|add)/i.test(a) ? 'pos' : 'neg'}">${esc(a)}</span>`;
  const loading = el => { el.innerHTML = '<p class="si-meta">Caricamento…</p>'; };
  const failed = (el, msg) => { el.innerHTML = `<p class="si-meta" style="color:var(--red)">${esc(msg)}</p>`; };

  function table(headers, rows) {
    return `<div class="si-table-wrap"><table class="si-table">
      <thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('')}</tbody></table></div>`;
  }

  async function getJson(url, opts) {
    const res = await apiFetch(`${API}${url}`, opts);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  }

  // ── Tab 1: most-owned stocks ──────────────────
  async function loadConsensus() {
    const el = document.getElementById('siConsensus');
    loading(el);
    try {
      const stocks = await getJson('/api/superinvestors/consensus?limit=30');
      el.innerHTML = table(
        ['Titolo', 'N° gestori', '% tot.', 'Max % port.', 'Prezzo medio*', 'Prezzo att.', 'Sopra min 52s'],
        stocks.map(s => `<tr>
          <td><span class="sym">${esc(s.symbol)}</span> ${esc(s.name)}</td>
          <td><strong>${num(s.ownership_count, 0)}</strong></td>
          <td>${num(s.pct_all, 3)}%</td>
          <td>${num(s.max_pct)}%</td>
          <td>${usd(s.hold_price)}</td>
          <td>${usd(s.current_price)}</td>
          <td>${num(s.pct_above_low)}%</td>
        </tr>`),
      ) + '<p class="si-note">* Prezzo di riferimento alla data del filing 13F.</p>';
      loaded.consensus = true;
    } catch (e) { failed(el, `Errore Dataroma: ${e.message}`); }
  }

  // ── Tab 2: single manager portfolio ───────────
  async function loadManagers() {
    const sel = document.getElementById('siManagerSelect');
    try {
      const managers = await getJson('/api/superinvestors');
      managers.sort((a, b) => (b.portfolio_value || 0) - (a.portfolio_value || 0));
      sel.innerHTML = '<option value="">Scegli un superinvestitore…</option>' + managers.map(m =>
        `<option value="${esc(m.code)}">${esc(m.name)} · ${bigUsd(m.portfolio_value)} · ${m.num_stocks ?? '?'} titoli</option>`,
      ).join('');
      loaded.managers = true;
    } catch (e) {
      sel.innerHTML = '<option value="">Errore nel caricamento</option>';
    }
  }

  async function loadManagerPortfolio(code) {
    const el = document.getElementById('siManagerPortfolio');
    if (!code) { el.innerHTML = ''; return; }
    loading(el);
    try {
      const p = await getJson(`/api/superinvestors/${encodeURIComponent(code)}`);
      el.innerHTML = `
        <div class="si-meta"><strong style="color:var(--text)">${esc(p.name)}</strong> ·
          ${esc(p.period)} (al ${esc(p.portfolio_date)}) · ${num(p.num_stocks, 0)} titoli · ${bigUsd(p.portfolio_value)} ·
          <a href="${esc(p.source_url)}" target="_blank" rel="noopener" style="color:var(--accent2)">Dataroma ↗</a></div>` +
        table(
          ['Titolo', '% port.', 'Attività', 'Valore', 'Prezzo 13F', 'Prezzo att.', 'Var. da 13F'],
          p.holdings.map(h => `<tr>
            <td><span class="sym">${esc(h.symbol)}</span> ${esc(h.name)}</td>
            <td><strong>${num(h.pct)}%</strong></td>
            <td>${activity(h.activity)}</td>
            <td>${bigUsd(h.value)}</td>
            <td>${usd(h.reported_price)}</td>
            <td>${usd(h.current_price)}</td>
            <td>${signed(h.change_vs_reported_pct)}</td>
          </tr>`),
        );
    } catch (e) { failed(el, e.message); }
  }

  // ── Tab 3: who owns the user's stocks ─────────
  async function loadOverlap() {
    const el = document.getElementById('siOverlap');
    const symbols = [...new Set((typeof portfolio !== 'undefined' ? portfolio : [])
      .filter(h => h.category === 'Azioni' && h.ticker)
      .map(h => h.ticker.split(/\s+/)[0].toUpperCase()))];
    if (!symbols.length) {
      el.innerHTML = '<p class="si-meta">Aggiungi delle azioni al portafoglio per vedere quali superinvestitori le possiedono.</p>';
      return;
    }
    loading(el);
    try {
      const res = await getJson('/api/superinvestors/overlap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      });
      const found = new Set(res.map(r => r.symbol));
      const missing = symbols.filter(s => !found.has(s.replace('/', '.')));
      el.innerHTML = (res.length ? res.map(r => `
        <div class="si-owner-card">
          <h4><span class="sym" style="font-family:var(--font-mono);color:var(--accent2)">${esc(r.symbol)}</span>
            ${esc(r.name)} <small>${esc(r.sector)} · posseduto da <strong>${r.ownership_count}</strong> superinvestitori</small></h4>
          ${table(['Gestore', '% port.', 'Attività', 'Valore'],
            r.owners.map(o => `<tr>
              <td>${esc(o.manager)}</td><td><strong>${num(o.pct)}%</strong></td>
              <td>${activity(o.activity)}</td><td>${bigUsd(o.value)}</td>
            </tr>`))}
        </div>`).join('') : '<p class="si-meta">Nessuno dei tuoi titoli è nei portafogli dei superinvestitori.</p>') +
        (missing.length ? `<p class="si-note">Non detenuti / non coperti (solo azioni USA): ${missing.map(esc).join(', ')}</p>` : '');
    } catch (e) { failed(el, `Errore Dataroma: ${e.message}`); }
  }

  // ── Wiring ────────────────────────────────────
  const panes = { consensus: 'siConsensus', managers: 'siManagers', overlap: 'siOverlap' };

  function showTab(tab) {
    document.querySelectorAll('.si-tab').forEach(b => b.classList.toggle('active', b.dataset.siTab === tab));
    Object.entries(panes).forEach(([k, id]) => document.getElementById(id).classList.toggle('hidden', k !== tab));
    if (tab === 'consensus' && !loaded.consensus) loadConsensus();
    if (tab === 'managers' && !loaded.managers) loadManagers();
    if (tab === 'overlap') loadOverlap();   // portfolio may have changed
  }

  document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('superinvestitori');
    if (!section) return;
    document.querySelectorAll('.si-tab').forEach(b => b.addEventListener('click', () => showTab(b.dataset.siTab)));
    document.getElementById('siManagerSelect').addEventListener('change', e => loadManagerPortfolio(e.target.value));
    // Lazy-load the first tab only when the section scrolls into view.
    new IntersectionObserver((entries, obs) => {
      if (entries.some(e => e.isIntersecting)) { showTab('consensus'); obs.disconnect(); }
    }).observe(section);
  });
})();
