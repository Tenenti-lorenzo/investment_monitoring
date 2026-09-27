/* ═══════════════════════════════════════
   PortfolioLab – Analisi approfondita (page /analisi)
   Loads a portfolio (current snapshot from the dashboard or a saved one),
   calls /api/analysis/deep then /api/analysis/look-through, renders
   KPIs, tables and HTML charts. Chart.js renderers live in analisi-charts.js.
═══════════════════════════════════════ */

(function () {
  const NOTIONAL = 10000;
  const $ = id => document.getElementById(id);
  const { eur, pct, nf2, catColor, C } = window.AnCharts;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, d = 2) => (v == null ? '—' : nf2.format(Number(v.toFixed(d))));
  const signed = (v, fmt) => (v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v > 0 ? '+' : ''}${fmt(v)}</span>`);
  const sPct = (v, d = 2) => signed(v, x => `${num(x, d)}%`);
  const sEur = v => signed(v, x => eur(x));

  // ── API ───────────────────────────────────────
  async function apiFetch(url, opts = {}) {
    const token = localStorage.getItem('auth_token') || '';
    const res = await fetch(url, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${token}` } });
    if (res.status === 401) {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_username');
      window.location.href = '/login';
      throw new Error('Sessione scaduta');
    }
    return res;
  }
  async function postJson(url, body) {
    const res = await apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  }

  // ── Portfolio sources ─────────────────────────
  function readSnapshot() {
    try { return JSON.parse(localStorage.getItem('analysis_portfolio') || 'null'); } catch { return null; }
  }

  async function loadSources() {
    const sel = $('anSource');
    const opts = [];
    const snap = readSnapshot();
    if (snap && snap.holdings?.length) {
      opts.push(`<option value="current">Portafoglio corrente – ${esc(snap.name)} (${snap.holdings.length} titoli)</option>`);
    }
    try {
      const res = await apiFetch('/api/portfolio/list');
      const items = res.ok ? await res.json() : [];
      items.forEach(p => opts.push(`<option value="saved:${esc(p.portfolio_id)}">💾 ${esc(p.name)} (${p.holdings_count} titoli)</option>`));
    } catch { /* list is optional */ }
    sel.innerHTML = opts.length ? opts.join('') : '<option value="">Nessun portafoglio: creane uno nella dashboard</option>';
    $('anRunBtn').disabled = !opts.length;
    if (snap && snap.holdings?.length) run();
  }

  async function getPortfolio(source) {
    if (source === 'current') return readSnapshot();
    const id = source.replace(/^saved:/, '');
    const res = await apiFetch(`/api/portfolio/load/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error('Portafoglio non trovato');
    return res.json();
  }

  /** Map a dashboard/saved portfolio to the DeepAnalysisRequest contract. */
  function buildRequest(p) {
    const pctMode = (p.inputMode || 'pct') === 'pct';
    const liq = parseFloat(p.liquidita) || 0;
    const holdings = (p.holdings || []).map(h => {
      const alloc = parseFloat(h.allocation) || 0;
      const amount = pctMode ? alloc / 100 * NOTIONAL : (parseFloat(h.amount) || null);
      return {
        isin: h.isin || '', ticker: h.ticker, yf_ticker: h.yf_ticker || null, name: h.name || h.ticker,
        category: h.category || 'Altro', currency: h.currency || null, geography: h.geography || null,
        ter: h.ter ?? null, allocation: alloc, amount,
        quantity: parseFloat(h.quantity) || null, purchase_price: parseFloat(h.purchase_price) || null,
        purchase_date: h.purchase_date || null,
      };
    });
    return {
      holdings,
      liquidita: pctMode ? liq / 100 * NOTIONAL : liq,
      lookback_years: parseInt($('anLookback').value, 10),
      risk_free: (parseFloat($('anRiskFree').value) || 0) / 100,
      benchmark: $('anBenchmark').value.trim() || 'SWDA.MI',
      _pctMode: pctMode,
    };
  }

  // ── Run ───────────────────────────────────────
  async function run() {
    const status = $('anStatus');
    const btn = $('anRunBtn');
    status.className = 'an-status';
    status.textContent = '⏳ Scarico storici prezzi e calcolo…';
    btn.disabled = true;
    try {
      const p = await getPortfolio($('anSource').value);
      if (!p || !p.holdings?.length) throw new Error('Portafoglio vuoto');
      const { _pctMode, ...req } = buildRequest(p);
      const deep = await postJson('/api/analysis/deep', req);
      renderDeep(deep, _pctMode);
      status.textContent = `✓ Dati al ${deep.as_of}. Radiografia ETF in corso…`;
      // Look-through uses the EUR values just computed (same order as the request).
      const ltReq = { ...req, holdings: req.holdings.map((h, i) => ({ ...h, amount: deep.holdings[i]?.value ?? h.amount })) };
      $('ltStatus').textContent = '⏳ Analisi composizione ETF…';
      postJson('/api/analysis/look-through', ltReq)
        .then(lt => { renderLookThrough(lt); $('ltStatus').textContent = ''; status.textContent = `✓ Dati al ${deep.as_of}`; })
        .catch(e => { $('ltStatus').textContent = `Look-through non disponibile: ${e.message}`; });
    } catch (e) {
      status.className = 'an-status error';
      status.textContent = `Errore: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  // ── Deep analysis rendering ───────────────────
  function kpi(label, value, sub = '') {
    return `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  }

  function renderNotes(d, pctMode) {
    const notes = [];
    if (pctMode) notes.push(`ℹ️ Portafoglio in percentuali: importi nozionali su ${eur(NOTIONAL)}.`);
    if (d.assumed_dates.length) notes.push(`ℹ️ Senza data di acquisto (assunto inizio orizzonte): ${d.assumed_dates.map(esc).join(', ')}.`);
    if (d.excluded.length) notes.push(`⚠️ Senza storico prezzi, valorizzati a prezzo fisso ed esclusi dalle metriche di rischio: ${d.excluded.map(esc).join(', ')} (copertura ${num(d.coverage_pct, 1)}%).`);
    $('anNotes').innerHTML = notes.map(n => `<div>${n}</div>`).join('');
  }

  function renderKpis(d) {
    const s = d.summary, r = d.risk;
    $('rendPeriod').textContent = `Dal ${s.start_date} al ${d.as_of}`;
    $('kpiRow').innerHTML = [
      kpi('Valore attuale', eur(s.current_value)),
      kpi('Capitale investito', eur(s.invested)),
      kpi('Guadagno / perdita', sEur(s.pl_eur), sPct(s.pl_pct)),
      kpi('TWR cumulato', sPct(s.twr), s.twr_annualized != null ? `${sPct(s.twr_annualized)} annuo` : 'meno di 1 anno'),
      kpi('MWR (XIRR)', s.mwr != null ? sPct(s.mwr) : '—', 'annuo, il tuo rendimento'),
      kpi('Max drawdown', `<span class="neg">${num(Math.min(...d.equity_curve.drawdown))}%</span>`, 'dall\'acquisto'),
      kpi('Sharpe', num(r.sharpe), `Sortino ${num(r.sortino)}`),
      kpi('Beta', num(r.beta), d.benchmark ? `vs ${esc(d.benchmark)}` : ''),
    ].join('');
  }

  function table(headers, rows, foot = '') {
    return `<div class="an-table-wrap"><table class="an-table"><thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('')}</tbody>${foot ? `<tfoot>${foot}</tfoot>` : ''}</table></div>`;
  }
  const sw = cat => `<span class="swatch" style="background:${catColor(cat)}"></span>`;

  function renderClassTable(d) {
    const s = d.summary;
    $('classTable').innerHTML = table(
      ['Asset class', 'Investito', 'Valore', 'P&L €', 'P&L %', 'Contributo'],
      d.classes.map(c => `<tr><td>${sw(c.category)}${esc(c.category)}</td><td>${eur(c.cost)}</td><td>${eur(c.value)}</td>
        <td>${sEur(c.pl_eur)}</td><td>${sPct(c.pl_pct)}</td><td>${signed(c.contribution_pp, x => `${num(x)} p.p.`)}</td></tr>`),
      `<tr><td>Totale</td><td>${eur(s.invested)}</td><td>${eur(s.current_value)}</td><td>${sEur(s.pl_eur)}</td><td>${sPct(s.pl_pct)}</td><td>${signed(s.pl_pct, x => `${num(x)} p.p.`)}</td></tr>`);
  }

  function renderHoldingTable(d) {
    const rows = [...d.holdings].sort((a, b) => b.pl_eur - a.pl_eur);
    $('holdingTable').innerHTML = `<div class="an-sub">Dettaglio per strumento (riconciliazione del ponte)</div>` + table(
      ['Strumento', 'Peso', 'Investito', 'Valore', 'Effetto prezzo', 'Effetto cambio', 'P&L %', 'Contributo'],
      rows.map(h => `<tr><td class="name">${sw(h.category)}<strong>${esc(h.ticker)}</strong> ${esc(h.name)}
          ${h.date_assumed ? '<span class="tag warn" title="Data di acquisto non indicata">data stimata</span>' : ''}</td>
        <td>${num(h.weight_pct, 1)}%</td><td>${eur(h.cost)}</td><td>${eur(h.value)}</td>
        <td>${sEur(h.price_effect)}</td><td>${h.currency === 'EUR' ? '—' : sEur(h.fx_effect)}</td>
        <td>${sPct(h.pl_pct)}</td><td>${signed(h.contribution_pp, x => `${num(x)} p.p.`)}</td></tr>`));
  }

  function riskRow(label, a, b, fmt) {
    return `<tr><td>${label}</td><td>${fmt(a)}</td><td>${b == null ? '—' : fmt(b)}</td></tr>`;
  }

  function renderRisk(d) {
    const r = d.risk, b = d.benchmark_risk || {};
    const lb = $('anLookback').value;
    $('riskPeriod').textContent = `Pesi attuali mantenuti costanti sugli ultimi ${lb} anni (dati giornalieri, in EUR).`;
    const p = v => (v == null ? '—' : `${num(v)}%`);
    const x = v => num(v);
    $('riskTable').innerHTML = table(['Metrica', 'Portafoglio', esc(d.benchmark || 'Benchmark')], [
      riskRow('CAGR (rendimento annuo composto)', r.cagr, b.cagr, p),
      riskRow('Volatilità annua', r.volatility, b.volatility, p),
      riskRow('Max drawdown', r.max_drawdown, b.max_drawdown, p),
      riskRow('Sharpe', r.sharpe, b.sharpe, x),
      riskRow('Sortino', r.sortino, b.sortino, x),
      riskRow('Calmar (CAGR / max DD)', r.calmar, b.calmar, x),
      riskRow('Beta vs benchmark', r.beta, 1, x),
      riskRow('Correlazione con benchmark', r.correlation_benchmark, 1, x),
      riskRow('VaR 95% giornaliero', r.var_95, b.var_95, p),
      riskRow('CVaR 95% giornaliero', r.cvar_95, b.cvar_95, p),
      riskRow('Giorno migliore / peggiore', r.best_day, null, v => `${p(v)} / ${p(r.worst_day)}`),
    ]) + `<div class="an-explain">Sharpe e Sortino: più alti = miglior rendimento per unità di rischio (Sortino penalizza
      solo la volatilità al ribasso). Beta &lt; 1 = portafoglio meno reattivo del benchmark.</div>`;
  }

  function heatColor(v) {
    // Diverging: blue (−1) → neutral gray (0) → red (+1)
    const lerp = (a, b, t) => Math.round(a + (b - a) * t);
    const [neg, mid, pos] = [[42, 120, 214], [56, 56, 53], [208, 59, 59]];
    const t = Math.min(1, Math.abs(v ?? 0));
    const to = (v ?? 0) >= 0 ? pos : neg;
    return `rgb(${lerp(mid[0], to[0], t)},${lerp(mid[1], to[1], t)},${lerp(mid[2], to[2], t)})`;
  }

  function renderCorrelation(corr) {
    const el = $('corrHeatmap');
    if (!corr) { el.innerHTML = '<p class="an-status">Servono almeno 2 strumenti con storico sufficiente.</p>'; return; }
    const n = corr.labels.length;
    const cells = [`<div></div>`, ...corr.labels.map(l => `<div class="hm-head" title="${esc(l)}">${esc(l)}</div>`)];
    corr.matrix.forEach((row, i) => {
      cells.push(`<div class="hm-row" title="${esc(corr.labels[i])}">${esc(corr.labels[i])}</div>`);
      row.forEach((v, j) => cells.push(`<div class="hm-cell" style="background:${heatColor(v)}"
        title="${esc(corr.labels[i])} / ${esc(corr.labels[j])}: ${num(v)}">${n <= 8 ? num(v) : ''}</div>`));
    });
    el.innerHTML = `<div class="heatmap" style="grid-template-columns:72px repeat(${n}, minmax(28px,1fr))">${cells.join('')}</div>
      <div class="hm-scale"><span>−1</span><span class="grad"></span><span>+1</span></div>`;
    window.AnCharts.rollingCorr(corr);
  }

  function renderFrontier(f) {
    if (!f) { $('frontierTable').innerHTML = '<p class="an-status">Servono almeno 2 strumenti con storico sufficiente.</p>'; return; }
    window.AnCharts.frontier(f);
    const w = fw => fw.weights.map(s => `${esc(s.label)} ${num(s.pct, 1)}%`).join(', ');
    $('frontierTable').innerHTML = table(['Portafoglio', 'Volatilità', 'Rendimento', 'Pesi'], [
      `<tr><td><span class="swatch" style="background:${C.s[1]}"></span>Il tuo</td><td>${num(f.current.vol)}%</td><td>${num(f.current.ret)}%</td><td class="name">attuali</td></tr>`,
      `<tr><td><span class="swatch" style="background:${C.s[2]}"></span>Min. volatilità</td><td>${num(f.min_vol.point.vol)}%</td><td>${num(f.min_vol.point.ret)}%</td><td class="name">${w(f.min_vol)}</td></tr>`,
      `<tr><td><span class="swatch" style="background:${C.s[3]}"></span>Max Sharpe</td><td>${num(f.max_sharpe.point.vol)}%</td><td>${num(f.max_sharpe.point.ret)}%</td><td class="name">${w(f.max_sharpe)}</td></tr>`,
    ]);
  }

  function renderScenarios(d) {
    const r = d.risk, mc = d.monte_carlo;
    window.AnCharts.distribution(d.distribution);
    $('distStats').innerHTML = [
      kpi('Skew', num(r.skew), r.skew < 0 ? 'coda sinistra' : 'coda destra'),
      kpi('Curtosi (excess)', num(r.kurtosis), r.kurtosis > 0 ? 'code spesse' : 'code sottili'),
      kpi('VaR 95%', `${num(r.var_95)}%`, '1 giorno su 20 perdi di più'),
      kpi('Giorni positivi', `${num(r.positive_days_pct, 1)}%`),
    ].join('');
    $('mcTitle').textContent = `Monte Carlo a ${mc.horizon_years} anni (2.000 scenari)`;
    window.AnCharts.monteCarlo(mc);
    const last = a => a[a.length - 1];
    $('mcStats').innerHTML = [
      kpi('Mediana finale', eur(last(mc.p50))),
      kpi('Scenario sfavorevole', eur(last(mc.p5)), '5° percentile'),
      kpi('Scenario favorevole', eur(last(mc.p95)), '95° percentile'),
      kpi('Prob. di perdita', `${num(mc.prob_loss, 1)}%`, `ipotesi: ${num(mc.mu, 1)}% ± ${num(mc.sigma, 1)}% annuo`),
    ].join('');
  }

  function renderAlternatives(alt) {
    window.AnCharts.alternatives(alt);
    $('altPeriod').textContent = alt.dates.length
      ? `Crescita di 10.000 € dal ${alt.dates[0]} al ${alt.dates[alt.dates.length - 1]}.` : '';
    $('altNote').textContent = 'Mix a pesi costanti con ribilanciamento giornaliero. Azionario = SWDA (MSCI World), '
      + 'obbligazionario = IEAG (Euro Aggregate). "Il tuo portafoglio" usa i pesi attuali sullo stesso periodo.';
    $('altTable').innerHTML = table(['Allocazione', 'Valore finale', 'CAGR', 'Volatilità', 'Max drawdown', 'Sharpe'],
      alt.items.map(a => `<tr><td>${esc(a.name)}</td><td>${eur(a.values[a.values.length - 1])}</td><td>${sPct(a.cagr)}</td>
        <td>${num(a.volatility)}%</td><td><span class="neg">${num(a.max_drawdown)}%</span></td><td>${num(a.sharpe)}</td></tr>`));
  }

  function renderDeep(d, pctMode) {
    $('anEmpty').classList.add('hidden');
    $('anResults').classList.remove('hidden');
    renderNotes(d, pctMode);
    renderKpis(d);
    const A = window.AnCharts;
    A.value(d.equity_curve);
    A.twr(d.equity_curve, d.benchmark);
    A.drawdown(d.equity_curve);
    A.classPL(d.classes);
    renderClassTable(d);
    A.waterfall(d.summary, d.holdings);
    renderHoldingTable(d);
    A.allocTime(d.allocation_over_time);
    A.drift(d.classes);
    renderRisk(d);
    renderCorrelation(d.correlation);
    renderFrontier(d.frontier);
    renderScenarios(d);
    renderAlternatives(d.alternatives);
  }

  // ── Look-through rendering ────────────────────
  function hbars(id, shares, color) {
    $(id).innerHTML = shares.length ? shares.slice(0, 10).map(s => `<div class="hbar-row">
        <span class="hbar-label" title="${esc(s.label)}">${esc(s.label)}</span>
        <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${Math.min(100, s.pct)}%;background:${color || C.s[0]}"></span></span>
        <span class="hbar-val">${num(s.pct, 1)}%</span></div>`).join('')
      : '<p class="an-status">Dati non disponibili</p>';
  }

  function renderBonds(lt) {
    // Ordinal blue ramp, AAA darkest; never darker than step 600 on the dark surface.
    const ratingColors = ['#184f95', '#1c5cab', '#256abf', '#2a78d6', '#3987e5', '#5598e7', '#86b6ef', '#5a6180'];
    $('bondKpis').innerHTML = [
      kpi('Peso obbligazionario', `${num(lt.asset_classes.find(s => s.label === 'Obbligazioni')?.pct ?? 0, 1)}%`, 'look-through'),
      kpi('Duration media', lt.portfolio_duration != null ? `${num(lt.portfolio_duration)} anni` : '—',
        lt.portfolio_duration != null ? `+1% tassi ≈ ${num(-lt.portfolio_duration, 1)}% sulla parte obbligazionaria` : ''),
    ].join('');
    $('bondCredit').innerHTML = lt.credit_quality.length ? `<div class="an-sub">Qualità del credito</div>
      <div class="stackbar">${lt.credit_quality.map((s, i) => `<span title="${esc(s.label)} ${num(s.pct, 1)}%" style="width:${s.pct}%;background:${ratingColors[i] || C.context}"></span>`).join('')}</div>
      <div class="legend-inline">${lt.credit_quality.map((s, i) => `<span><span class="swatch" style="background:${ratingColors[i] || C.context}"></span>${esc(s.label)} ${num(s.pct, 1)}%</span>`).join('')}</div>` : '';
    $('bondTable').innerHTML = lt.bonds.length ? table(['Strumento', 'Peso', 'Scadenza', 'Cedola', 'Prezzo', 'Rend. a scad.', 'Duration'],
      lt.bonds.map(b => `<tr><td class="name"><strong>${esc(b.ticker)}</strong> ${esc(b.name)} <span class="tag">${esc(b.kind)}</span></td>
        <td>${num(b.weight_pct, 1)}%</td><td>${b.maturity ? esc(b.maturity.slice(0, 10)) : '—'}</td>
        <td>${b.coupon_pct != null ? num(b.coupon_pct) + '%' : '—'}</td><td>${num(b.price)}</td>
        <td>${b.ytm_pct != null ? num(b.ytm_pct) + '%' : '—'}</td><td>${b.duration != null ? num(b.duration) : '—'}</td></tr>`))
      : '<p class="an-status" style="margin-top:10px">Nessuna componente obbligazionaria.</p>';
  }

  function renderCosts(lt) {
    $('costKpis').innerHTML = [
      kpi('TER medio ponderato', lt.ter_weighted != null ? `${num(lt.ter_weighted, 3)}%` : '—', 'sull\'intero portafoglio'),
      kpi('Costo annuo stimato', eur(lt.annual_cost)),
      kpi('Costo su 10 anni', eur(lt.cost_10y), 'a valore costante'),
      kpi('Quota coperta (hedged)', `${num(lt.hedged_pct, 1)}%`),
    ].join('');
    $('costTable').innerHTML = table(['Strumento', 'Valore', 'TER', 'Costo annuo'],
      lt.costs.map(c => `<tr><td class="name"><strong>${esc(c.ticker)}</strong> ${esc(c.name)}</td><td>${eur(c.value)}</td>
        <td>${c.ter != null ? num(c.ter, 3) + '%' : '—'}</td><td>${c.annual_cost != null ? eur(c.annual_cost) : '—'}</td></tr>`));
    hbars('ltCurrencies', lt.currencies);
    const nonEur = lt.currencies.filter(s => s.label !== 'EUR').reduce((a, s) => a + s.pct, 0);
    $('hedgeNote').innerHTML = `<strong>${num(nonEur, 1)}%</strong> del portafoglio è negoziato in valuta diversa dall'euro.
      Nota: la valuta di negoziazione non coincide con l'esposizione valutaria reale dei sottostanti (vedi area geografica);
      un ETF "EUR Hedged" neutralizza il cambio.`;
  }

  function renderLookThrough(lt) {
    hbars('ltClasses', lt.asset_classes);
    hbars('ltGeo', lt.geography);
    hbars('ltSectors', lt.sectors);
    $('ltExposures').innerHTML = table(['Titolo', 'Peso', 'Tramite'],
      lt.top_exposures.slice(0, 15).map(e => `<tr><td class="name"><strong>${esc(e.symbol)}</strong> ${esc(e.name)}</td>
        <td>${num(e.weight_pct)}%</td><td>${e.sources.map(esc).join(', ')}${e.sources.length > 1 ? ' <span class="tag warn">overlap</span>' : ''}</td></tr>`));
    $('ltOverlaps').innerHTML = lt.overlaps.length ? table(['ETF A', 'ETF B', 'Sovrapposizione'],
      lt.overlaps.map(o => `<tr><td>${esc(o.a)}</td><td>${esc(o.b)}</td><td>${num(o.overlap_pct, 1)}%</td></tr>`))
      : '<p class="an-status">Nessuna sovrapposizione rilevata tra le principali partecipazioni degli ETF.</p>';
    $('ltNote').textContent = lt.coverage_note;
    renderBonds(lt);
    renderCosts(lt);
  }

  // ── Init ──────────────────────────────────────
  const u = localStorage.getItem('auth_username');
  if (u) $('navUsername').textContent = '👤 ' + u;
  $('anRunBtn').addEventListener('click', run);
  loadSources();
})();
