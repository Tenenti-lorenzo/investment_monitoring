/* ═══════════════════════════════════════
   PortfolioLab – Patrimonio complessivo (page /patrimonio)
   Picks saved portfolios (selection remembered per browser), then renders
   /api/wealth/summary: KPIs, composition bar, categories, mortgages, items.
═══════════════════════════════════════ */

(function () {
  const { CATEGORIES, color, esc, eur, signed, pct, fmtDate } = Wealth;
  const $ = id => document.getElementById(id);
  const PICK_KEY = 'networth_portfolios';

  const readPick = () => { try { return JSON.parse(localStorage.getItem(PICK_KEY)); } catch { return null; } };
  const writePick = ids => { try { localStorage.setItem(PICK_KEY, JSON.stringify(ids)); } catch { /* ignore */ } };
  const picked = () => [...document.querySelectorAll('#nwPick input:checked')].map(i => i.value);

  async function loadPortfolios() {
    const res = await Session.apiFetch('/api/portfolio/list');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const list = await res.json();
    if (!list.length) {
      $('nwPick').innerHTML = '<span class="an-status">Nessun portafoglio salvato. <a href="/">Vai alla dashboard →</a></span>';
      return;
    }
    const known = new Set(list.map(p => p.portfolio_id));
    const saved = (readPick() || []).filter(id => known.has(id));
    const sel = new Set(readPick() === null ? [list[0].portfolio_id] : saved);  // first visit: newest
    $('nwPick').innerHTML = list.map(p => `<label><input type="checkbox" value="${esc(p.portfolio_id)}"
      ${sel.has(p.portfolio_id) ? 'checked' : ''}/> ${esc(p.name)} <span class="wl-sub" style="display:inline">${fmtDate(p.savedAt)}</span></label>`).join('');
  }

  // ── Render ────────────────────────────────────
  function renderKpis(s) {
    const illiquid = s.total_assets - s.liquid_assets;
    const debtRatio = s.total_assets > 0 ? s.total_liabilities / s.total_assets * 100 : 0;
    $('nwKpis').innerHTML = `
      <div class="kpi"><div class="kpi-label">Patrimonio netto</div><div class="kpi-value">${eur(s.net_worth)}</div>
        <div class="kpi-sub">al ${new Date(s.as_of).toLocaleDateString('it-IT')}</div></div>
      <div class="kpi"><div class="kpi-label">Attività</div><div class="kpi-value">${eur(s.total_assets)}</div>
        <div class="kpi-sub">${s.categories.length} categorie</div></div>
      <div class="kpi"><div class="kpi-label">Debiti</div><div class="kpi-value ${s.total_liabilities ? 'neg' : ''}">${eur(-s.total_liabilities)}</div>
        <div class="kpi-sub">${pct(debtRatio)} delle attività</div></div>
      <div class="kpi"><div class="kpi-label">Liquido / illiquido</div><div class="kpi-value">${pct(s.total_assets ? s.liquid_assets / s.total_assets * 100 : 0)}</div>
        <div class="kpi-sub">${eur(s.liquid_assets)} · ${eur(illiquid)}</div></div>`;
  }

  function renderComposition(s) {
    const total = s.total_assets + s.total_liabilities;
    $('nwStack').innerHTML = total > 0 ? s.categories.map(c =>
      `<span style="width:${c.gross / total * 100}%;background:${color(c.category)}" title="${CATEGORIES[c.category].label}: ${eur(c.gross)}"></span>`).join('')
      + (s.total_liabilities ? `<span class="nw-debt" style="width:${s.total_liabilities / total * 100}%" title="Debiti: ${eur(s.total_liabilities)}"></span>` : '')
      : '';
    $('nwLegend').innerHTML = s.categories.map(c =>
      `<span><i class="swatch" style="background:${color(c.category)}"></i>${CATEGORIES[c.category].label} ${pct(c.share_pct)}</span>`).join('')
      + (s.total_liabilities ? '<span><i class="swatch nw-debt"></i>Debiti</span>' : '');
  }

  function renderCategories(s) {
    $('nwBars').innerHTML = s.categories.map(c => `<div class="hbar-row">
      <span class="hbar-label">${CATEGORIES[c.category].icon} ${CATEGORIES[c.category].label}</span>
      <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${c.share_pct}%;background:${color(c.category)}"></span></span>
      <span class="hbar-val">${pct(c.share_pct)}</span></div>`).join('')
      || '<p class="wl-empty">Nessun dato: scegli un portafoglio o <a href="/altri-investimenti">aggiungi dei beni</a>.</p>';
    $('nwCats').innerHTML = s.categories.map(c => `<tr>
      <td><i class="swatch" style="background:${color(c.category)}"></i>${CATEGORIES[c.category].label}</td>
      <td>${eur(c.gross)}</td><td>${c.liabilities ? `<span class="neg">${eur(-c.liabilities)}</span>` : '—'}</td>
      <td><strong>${eur(c.net)}</strong></td><td>${pct(c.share_pct)}</td></tr>`).join('');
    $('nwCatsFoot').innerHTML = s.categories.length ? `<tr><td>Totale</td><td>${eur(s.total_assets)}</td>
      <td>${s.total_liabilities ? eur(-s.total_liabilities) : '—'}</td><td>${eur(s.net_worth)}</td><td>100%</td></tr>` : '';
  }

  function renderMortgages(s) {
    const withLoan = s.assets.filter(a => a.mortgage);
    $('nwMortgages').innerHTML = withLoan.map(a => {
      const m = a.mortgage;
      const left = `${Math.floor(m.months_left / 12)} a ${m.months_left % 12} m`;
      return `<div class="nw-mortgage"><strong>${esc(a.name)}</strong>
        <div class="row"><span>Debito residuo${m.from_statement ? ' (estratto)' : ''}</span><span>${eur(m.balance)}</span></div>
        <div class="row"><span>Rata mensile</span><span>${eur(m.monthly_payment)}</span></div>
        ${m.payment_consistent === false ? `<div class="row"><span class="neg">⚠️ Rata banca diversa</span><span>${eur(m.declared_payment)}</span></div>` : ''}
        <div class="row"><span>Mancano</span><span>${left} · fine ${fmtDate(m.end_date)}</span></div>
        <div class="row"><span>Rimborsato</span><span>${pct(m.repaid_pct)}</span></div>
        <div class="nw-progress"><span style="width:${m.repaid_pct}%"></span></div></div>`;
    }).join('') || '<p class="wl-empty">Nessun mutuo. Si aggiunge da un immobile in <a href="/altri-investimenti#sec-real_estate">Altri investimenti</a>.</p>';
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
      || '<tr><td colspan="6" class="an-empty">Nessuna voce.</td></tr>';
  }

  async function refresh() {
    const ids = picked();
    writePick(ids);
    const status = $('nwStatus');
    status.classList.remove('error');
    status.textContent = 'Calcolo…';
    try {
      const s = await Wealth.postSummary(ids);
      const unvalued = s.portfolios.filter(p => p.value == null).map(p => `"${esc(p.name)}"`);
      $('nwWarn').innerHTML = unvalued.length
        ? `⚠️ ${unvalued.join(', ')} salvato in modalità % senza valore totale: contato 0. Imposta il totale sulla dashboard e risalva.` : '';
      status.textContent = '';
      renderKpis(s);
      renderComposition(s);
      renderCategories(s);
      renderMortgages(s);
      renderRows(s);
    } catch (e) {
      status.classList.add('error');
      status.textContent = `Errore: ${e.message}`;
    }
  }

  $('nwPick').addEventListener('change', refresh);
  Wealth.showUsername();
  loadPortfolios()
    .catch(e => { $('nwPick').innerHTML = `<span class="an-status error">Errore: ${esc(e.message)}</span>`; })
    .then(refresh);
})();
