/* ═══════════════════════════════════════
   PortfolioLab – Patrimonio complessivo (page /patrimonio)
   Picks saved portfolios (selection remembered per browser), then renders
   /api/wealth/summary: KPIs, composition bar, categories, mortgages, items.
   On 'langchange' everything is re-rendered from the last data loaded.
═══════════════════════════════════════ */

(function () {
  const { CATEGORIES, color, esc, eur, signed, pct, fmtDate } = Wealth;
  const $ = id => document.getElementById(id);
  const t = (k, v) => I18n.t(k, v);
  const PICK_KEY = 'networth_portfolios';
  // Last data loaded: portfolio list (null = not loaded), summary, errors.
  const state = { list: null, listError: null, summary: null, error: null, loading: false };

  const readPick = () => { try { return JSON.parse(localStorage.getItem(PICK_KEY)); } catch { return null; } };
  const writePick = ids => { try { localStorage.setItem(PICK_KEY, JSON.stringify(ids)); } catch { /* ignore */ } };
  const picked = () => [...document.querySelectorAll('#nwPick input:checked')].map(i => i.value);

  async function loadPortfolios() {
    const res = await Session.apiFetch('/api/portfolio/list');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.list = await res.json();
    const known = new Set(state.list.map(p => p.portfolio_id));
    const saved = (readPick() || []).filter(id => known.has(id));
    renderPick(new Set(readPick() === null && state.list.length ? [state.list[0].portfolio_id] : saved));  // first visit: newest
  }

  function renderPick(sel) {
    if (state.listError != null) {
      $('nwPick').innerHTML = `<span class="an-status error">${t('nw.error', { msg: esc(state.listError) })}</span>`;
      return;
    }
    if (state.list === null) { $('nwPick').innerHTML = `<span class="an-status">${t('nw.loading')}</span>`; return; }
    if (!state.list.length) {
      $('nwPick').innerHTML = `<span class="an-status">${t('nw.pick.none')}</span>`;
      return;
    }
    $('nwPick').innerHTML = state.list.map(p => `<label><input type="checkbox" value="${esc(p.portfolio_id)}"
      ${sel.has(p.portfolio_id) ? 'checked' : ''}/> ${esc(p.name)} <span class="wl-sub" style="display:inline">${fmtDate(p.savedAt)}</span></label>`).join('');
  }

  // ── Render ────────────────────────────────────
  function renderKpis(s) {
    const illiquid = s.total_assets - s.liquid_assets;
    const debtRatio = s.total_assets > 0 ? s.total_liabilities / s.total_assets * 100 : 0;
    $('nwKpis').innerHTML = `
      <div class="kpi"><div class="kpi-label">${t('nw.kpi.net')}</div><div class="kpi-value">${eur(s.net_worth)}</div>
        <div class="kpi-sub">${t('nw.kpi.asOf', { date: new Date(s.as_of).toLocaleDateString(I18n.locale) })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('nw.kpi.assets')}</div><div class="kpi-value">${eur(s.total_assets)}</div>
        <div class="kpi-sub">${t(s.categories.length === 1 ? 'nw.kpi.category' : 'nw.kpi.categories', { n: s.categories.length })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('nw.debts')}</div><div class="kpi-value ${s.total_liabilities ? 'neg' : ''}">${eur(-s.total_liabilities)}</div>
        <div class="kpi-sub">${t('nw.kpi.debtRatio', { pct: pct(debtRatio) })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('nw.kpi.liquid')}</div><div class="kpi-value">${pct(s.total_assets ? s.liquid_assets / s.total_assets * 100 : 0)}</div>
        <div class="kpi-sub">${eur(s.liquid_assets)} · ${eur(illiquid)}</div></div>`;
  }

  function renderComposition(s) {
    const total = s.total_assets + s.total_liabilities;
    $('nwStack').innerHTML = total > 0 ? s.categories.map(c =>
      `<span style="width:${c.gross / total * 100}%;background:${color(c.category)}" title="${esc(CATEGORIES[c.category].label)}: ${eur(c.gross)}"></span>`).join('')
      + (s.total_liabilities ? `<span class="nw-debt" style="width:${s.total_liabilities / total * 100}%" title="${esc(t('nw.debts'))}: ${eur(s.total_liabilities)}"></span>` : '')
      : '';
    $('nwLegend').innerHTML = s.categories.map(c =>
      `<span><i class="swatch" style="background:${color(c.category)}"></i>${CATEGORIES[c.category].label} ${pct(c.share_pct)}</span>`).join('')
      + (s.total_liabilities ? `<span><i class="swatch nw-debt"></i>${t('nw.debts')}</span>` : '');
  }

  function renderCategories(s) {
    $('nwBars').innerHTML = s.categories.map(c => `<div class="hbar-row">
      <span class="hbar-label">${CATEGORIES[c.category].icon} ${CATEGORIES[c.category].label}</span>
      <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${c.share_pct}%;background:${color(c.category)}"></span></span>
      <span class="hbar-val">${pct(c.share_pct)}</span></div>`).join('')
      || `<p class="wl-empty">${t('nw.cat.empty')}</p>`;
    $('nwCats').innerHTML = s.categories.map(c => `<tr>
      <td><i class="swatch" style="background:${color(c.category)}"></i>${CATEGORIES[c.category].label}</td>
      <td>${eur(c.gross)}</td><td>${c.liabilities ? `<span class="neg">${eur(-c.liabilities)}</span>` : '—'}</td>
      <td><strong>${eur(c.net)}</strong></td><td>${pct(c.share_pct)}</td></tr>`).join('');
    $('nwCatsFoot').innerHTML = s.categories.length ? `<tr><td>${t('nw.cat.total')}</td><td>${eur(s.total_assets)}</td>
      <td>${s.total_liabilities ? eur(-s.total_liabilities) : '—'}</td><td>${eur(s.net_worth)}</td><td>100%</td></tr>` : '';
  }

  function renderMortgages(s) {
    const withLoan = s.assets.filter(a => a.mortgage);
    $('nwMortgages').innerHTML = withLoan.map(a => {
      const m = a.mortgage;
      const left = t('nw.mort.left', { y: Math.floor(m.months_left / 12), m: m.months_left % 12 });
      return `<div class="nw-mortgage"><strong>${esc(a.name)}</strong>
        <div class="row"><span>${t(m.from_statement ? 'nw.mort.balanceStatement' : 'nw.mort.balance')}</span><span>${eur(m.balance)}</span></div>
        <div class="row"><span>${t('nw.mort.payment')}</span><span>${eur(m.monthly_payment)}</span></div>
        ${m.payment_consistent === false ? `<div class="row"><span class="neg">${t('nw.mort.bankDiff')}</span><span>${eur(m.declared_payment)}</span></div>` : ''}
        <div class="row"><span>${t('nw.mort.remaining')}</span><span>${t('nw.mort.leftEnd', { left, end: fmtDate(m.end_date) })}</span></div>
        ${m.repaid_pct == null ? '' : `<div class="row"><span>${t('nw.mort.repaid')}</span><span>${pct(m.repaid_pct)}</span></div>
        <div class="nw-progress"><span style="width:${m.repaid_pct}%"></span></div>`}</div>`;
    }).join('') || `<p class="wl-empty">${t('nw.mort.none')}</p>`;
  }

  function renderRows(s) {
    const rows = [
      ...s.portfolios.map(p => ({ name: p.name, category: 'portfolio', gross: p.value, debt: 0, net: p.value, gain: null })),
      ...s.assets.map(a => ({ name: a.name, sub: a.provider, category: a.kind, gross: a.gross_value, debt: a.liability, net: a.net_value, gain: a.gain })),
    ].sort((x, y) => (y.net ?? 0) - (x.net ?? 0));
    $('nwRows').innerHTML = rows.map(r => `<tr>
      <td class="name">${esc(r.name)}${r.sub ? `<span class="wl-sub">${esc(r.sub)}</span>` : ''}</td>
      <td><i class="swatch" style="background:${color(r.category)}"></i>${CATEGORIES[r.category].label}</td>
      <td>${eur(r.gross)}</td><td>${r.debt ? `<span class="neg">${eur(-r.debt)}</span>` : '—'}</td>
      <td><strong>${eur(r.net)}</strong></td><td>${signed(r.gain)}</td></tr>`).join('')
      || `<tr><td colspan="6" class="an-empty">${t('nw.rows.empty')}</td></tr>`;
  }

  function renderStatus() {
    const status = $('nwStatus');
    status.classList.toggle('error', state.error != null);
    status.textContent = state.error != null ? t('nw.error', { msg: state.error }) : state.loading ? t('nw.computing') : '';
  }

  function renderSummary() {
    renderStatus();
    const s = state.summary;
    if (!s) return;
    const unvalued = s.portfolios.filter(p => p.value == null).map(p => `"${esc(p.name)}"`);
    $('nwWarn').innerHTML = unvalued.length ? t('nw.warn.unvalued', { names: unvalued.join(', ') }) : '';
    renderKpis(s);
    renderComposition(s);
    renderCategories(s);
    renderMortgages(s);
    renderRows(s);
  }

  async function refresh() {
    const ids = picked();
    writePick(ids);
    state.error = null;
    state.loading = true;
    renderStatus();
    try {
      state.summary = await Wealth.postSummary(ids);
    } catch (e) {
      state.error = e.message;
    }
    state.loading = false;
    if (state.error != null) renderStatus(); else renderSummary();
  }

  window.addEventListener('langchange', () => {
    renderPick(new Set(picked()));
    renderSummary();
  });
  $('nwPick').addEventListener('change', refresh);
  Wealth.showUsername();
  renderPick(new Set());
  loadPortfolios()
    .catch(e => { state.listError = e.message; renderPick(new Set()); })
    .then(refresh);
})();
