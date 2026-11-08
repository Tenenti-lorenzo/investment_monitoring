/* ═══════════════════════════════════════
   PortfolioLab – Superinvestitori (Dataroma 13F)
   Depends on globals from app.js: API, apiFetch, portfolio.
═══════════════════════════════════════ */

(function () {
  const loaded = { consensus: false, managers: false };
  // Last data per tab, so a language change re-renders without refetching.
  const state = { consensus: null, managers: null, managerError: false, portfolio: null, overlap: null };
  const t = (k, v) => I18n.t(k, v);

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, dec = 2) => v == null ? '—' : v.toLocaleString(I18n.locale, { maximumFractionDigits: dec });
  const usd = v => v == null ? '—' : '$' + num(v, 2);
  const bigUsd = v => {
    if (v == null) return '—';
    if (v >= 1e9) return '$' + num(v / 1e9, 2) + ' ' + t('si.unit.bn');
    if (v >= 1e6) return '$' + num(v / 1e6, 1) + ' ' + t('si.unit.mn');
    return '$' + num(v, 0);
  };
  const signed = v => v == null ? '—'
    : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v >= 0 ? '+' : ''}${num(v)}%</span>`;
  const activity = a => !a ? '' : `<span class="${/^(buy|add)/i.test(a) ? 'pos' : 'neg'}">${esc(a)}</span>`;
  const loading = el => { el.innerHTML = `<p class="si-meta">${esc(t('si.loading'))}</p>`; };
  const failed = (el, msg) => { el.innerHTML = `<p class="si-meta" style="color:var(--red)">${esc(msg)}</p>`; };

  /** Table with already-translated header labels. */
  function table(headers, rows) {
    return `<div class="si-table-wrap"><table class="si-table">
      <thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('')}</tbody></table></div>`;
  }

  async function getJson(url, opts) {
    const res = await apiFetch(`${API}${url}`, opts);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  }

  // ── Tab 1: most-owned stocks ──────────────────
  function renderConsensus() {
    const el = document.getElementById('siConsensus');
    const s = state.consensus;
    if (!s) return;
    if (s.loading) { loading(el); return; }
    if (s.error) { failed(el, t('si.err.dataroma', { msg: s.error })); return; }
    el.innerHTML = table(
      [t('si.col.stock'), t('si.col.managers'), t('si.col.pctAll'), t('si.col.maxPct'), t('si.col.holdPrice'), t('si.col.curPrice'), t('si.col.aboveLow')],
      s.stocks.map(x => `<tr>
        <td><span class="sym">${esc(x.symbol)}</span> ${esc(x.name)}</td>
        <td><strong>${num(x.ownership_count, 0)}</strong></td>
        <td>${num(x.pct_all, 3)}%</td>
        <td>${num(x.max_pct)}%</td>
        <td>${usd(x.hold_price)}</td>
        <td>${usd(x.current_price)}</td>
        <td>${num(x.pct_above_low)}%</td>
      </tr>`),
    ) + `<p class="si-note">${esc(t('si.consensus.note'))}</p>`;
  }

  async function loadConsensus() {
    state.consensus = { loading: true };
    renderConsensus();
    try {
      state.consensus = { stocks: await getJson('/api/superinvestors/consensus?limit=30') };
      loaded.consensus = true;
    } catch (e) { state.consensus = { error: e.message }; }
    renderConsensus();
  }

  // ── Tab 2: single manager portfolio ───────────
  function renderManagers() {
    const sel = document.getElementById('siManagerSelect');
    if (state.managerError) { sel.innerHTML = `<option value="">${esc(t('si.managers.error'))}</option>`; return; }
    if (!state.managers) { sel.innerHTML = `<option value="">${esc(t('si.managers.loading'))}</option>`; return; }
    const current = sel.value;
    sel.innerHTML = `<option value="">${esc(t('si.managers.choose'))}</option>` + state.managers.map(m =>
      `<option value="${esc(m.code)}">${esc(m.name)} · ${bigUsd(m.portfolio_value)} · ${esc(t('si.stocksCount', { n: m.num_stocks ?? '?' }))}</option>`,
    ).join('');
    sel.value = current;
  }

  async function loadManagers() {
    try {
      const managers = await getJson('/api/superinvestors');
      managers.sort((a, b) => (b.portfolio_value || 0) - (a.portfolio_value || 0));
      state.managers = managers;
      state.managerError = false;
      loaded.managers = true;
    } catch (e) {
      state.managerError = true;
    }
    renderManagers();
  }

  function renderManagerPortfolio() {
    const el = document.getElementById('siManagerPortfolio');
    const s = state.portfolio;
    if (!s) return;
    if (s.loading) { loading(el); return; }
    if (s.error) { failed(el, s.error); return; }
    const p = s.data;
    el.innerHTML = `
      <div class="si-meta"><strong style="color:var(--text)">${esc(p.name)}</strong> ·
        ${esc(p.period)} (${esc(t('si.asOf', { date: p.portfolio_date }))}) · ${esc(t('si.stocksCount', { n: num(p.num_stocks, 0) }))} · ${bigUsd(p.portfolio_value)} ·
        <a href="${esc(p.source_url)}" target="_blank" rel="noopener" style="color:var(--accent2)">Dataroma ↗</a></div>` +
      table(
        [t('si.col.stock'), t('si.col.pctPort'), t('si.col.activity'), t('si.col.value'), t('si.col.price13f'), t('si.col.curPrice'), t('si.col.chg13f')],
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
  }

  async function loadManagerPortfolio(code) {
    const el = document.getElementById('siManagerPortfolio');
    if (!code) { state.portfolio = null; el.innerHTML = ''; return; }
    const pending = state.portfolio = { loading: true };
    renderManagerPortfolio();
    let next;
    try {
      next = { data: await getJson(`/api/superinvestors/${encodeURIComponent(code)}`) };
    } catch (e) { next = { error: e.message }; }
    if (state.portfolio !== pending) return;   // a newer selection superseded this one
    state.portfolio = next;
    renderManagerPortfolio();
  }

  // ── Tab 3: who owns the user's stocks ─────────
  function renderOverlap() {
    const el = document.getElementById('siOverlap');
    const s = state.overlap;
    if (!s) return;
    if (s.loading) { loading(el); return; }
    if (s.empty) { el.innerHTML = `<p class="si-meta">${esc(t('si.overlap.empty'))}</p>`; return; }
    if (s.error) { failed(el, t('si.err.dataroma', { msg: s.error })); return; }
    const { res, missing } = s;
    el.innerHTML = (res.length ? res.map(r => `
      <div class="si-owner-card">
        <h4><span class="sym" style="font-family:var(--font-mono);color:var(--accent2)">${esc(r.symbol)}</span>
          ${esc(r.name)} <small>${esc(r.sector)} · ${esc(t('si.overlap.ownedBy')).replace('{n}', `<strong>${esc(r.ownership_count)}</strong>`)}</small></h4>
        ${table([t('si.col.manager'), t('si.col.pctPort'), t('si.col.activity'), t('si.col.value')],
          r.owners.map(o => `<tr>
            <td>${esc(o.manager)}</td><td><strong>${num(o.pct)}%</strong></td>
            <td>${activity(o.activity)}</td><td>${bigUsd(o.value)}</td>
          </tr>`))}
      </div>`).join('') : `<p class="si-meta">${esc(t('si.overlap.none'))}</p>`) +
      (missing.length ? `<p class="si-note">${esc(t('si.overlap.missing', { list: missing.join(', ') }))}</p>` : '');
  }

  async function loadOverlap() {
    // 'Azioni' is the backend category id, not display text.
    const symbols = [...new Set((typeof portfolio !== 'undefined' ? portfolio : [])
      .filter(h => h.category === 'Azioni' && h.ticker)
      .map(h => h.ticker.split(/\s+/)[0].toUpperCase()))];
    if (!symbols.length) { state.overlap = { empty: true }; renderOverlap(); return; }
    const pending = state.overlap = { loading: true };
    renderOverlap();
    let next;
    try {
      const res = await getJson('/api/superinvestors/overlap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      });
      const found = new Set(res.map(r => r.symbol));
      next = { res, missing: symbols.filter(s => !found.has(s.replace('/', '.'))) };
    } catch (e) { next = { error: e.message }; }
    if (state.overlap !== pending) return;   // a newer request superseded this one
    state.overlap = next;
    renderOverlap();
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
    // Re-render from the data already fetched (no new API calls).
    window.addEventListener('langchange', () => {
      renderConsensus(); renderManagers(); renderManagerPortfolio(); renderOverlap();
    });
    // Lazy-load the first tab only when the section scrolls into view.
    new IntersectionObserver((entries, obs) => {
      if (entries.some(e => e.isIntersecting)) { showTab('consensus'); obs.disconnect(); }
    }).observe(section);
  });
})();
