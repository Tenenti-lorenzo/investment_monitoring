/* ═══════════════════════════════════════
   PortfolioLab – Analisi approfondita (page /analisi)
   Loads a portfolio (current snapshot from the dashboard or a saved one),
   calls /api/analysis/deep then /api/analysis/look-through, renders
   KPIs, tables and HTML charts. Chart.js renderers live in analisi-charts.js.
   Texts come from static/i18n/analisi*.js; on 'langchange' everything is
   re-rendered from the last results (no new API calls).
═══════════════════════════════════════ */

(function () {
  const NOTIONAL = 10000;
  const $ = id => document.getElementById(id);
  const t = (k, v) => I18n.t(k, v);
  const A = window.AnCharts;
  const { eur, catColor, C, label } = A;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, d = 2) => (v == null ? '—' : A.n2(Number(v.toFixed(d))));
  const signed = (v, fmt) => (v == null ? '—' : `<span class="${v >= 0 ? 'pos' : 'neg'}">${v > 0 ? '+' : ''}${fmt(v)}</span>`);
  const sPct = (v, d = 2) => signed(v, x => `${num(x, d)}%`);
  const sEur = v => signed(v, x => eur(x));
  const pp = v => signed(v, x => t('an.unit.pp', { v: num(x) }));
  /** ISO date (YYYY-MM-DD…) → short date in the interface language; unparsable → as is. */
  const date = iso => {
    const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
    return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString(I18n.locale, { day: 'numeric', month: 'short', year: 'numeric' });
  };

  // Last results and status lines, re-rendered on language change.
  const state = { sources: null, deep: null, pctMode: false, lookback: null, lt: null, status: null, ltStatus: null };

  // ── API ───────────────────────────────────────
  const apiFetch = (url, opts) => Session.apiFetch(url, opts);
  async function postJson(url, body) {
    const res = await apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  }
  /** Frontend's own error: the key lets the status line follow the language. */
  const uiError = key => Object.assign(new Error(t(key)), { key });
  const errText = e => (e.key ? t(e.key) : e.message);

  // ── Status lines ──────────────────────────────
  /** s = { key, vars, error } | null */
  function setStatus(s) {
    state.status = s;
    const el = $('anStatus');
    el.className = s?.error ? 'an-status error' : 'an-status';
    el.textContent = s ? t(s.key, s.vars) : '';
  }
  function setLtStatus(s) {
    state.ltStatus = s;
    $('ltStatus').textContent = s ? t(s.key, s.vars) : '';
  }
  // Error messages may need translating at render time (uiError) → vars resolved lazily.
  const errVars = e => ({ get msg() { return errText(e); } });

  // ── Portfolio sources ─────────────────────────
  function readSnapshot() {
    try { return JSON.parse(localStorage.getItem('analysis_portfolio') || 'null'); } catch { return null; }
  }

  function renderSources() {
    const { snap, items } = state.sources;
    const sel = $('anSource');
    const prev = sel.value;
    const opts = [];
    if (snap && snap.holdings?.length) {
      opts.push(`<option value="current">${esc(t('an.src.current', { name: snap.name, n: snap.holdings.length }))}</option>`);
    }
    items.forEach(p => opts.push(`<option value="saved:${esc(p.portfolio_id)}">${esc(t('an.src.saved', { name: p.name, n: p.holdings_count }))}</option>`));
    sel.innerHTML = opts.length ? opts.join('') : `<option value="">${esc(t('an.src.none'))}</option>`;
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    $('anRunBtn').disabled = !opts.length;
    return opts.length;
  }

  async function loadSources() {
    const snap = readSnapshot();
    let items = [];
    try {
      const res = await apiFetch('/api/portfolio/list');
      items = res.ok ? await res.json() : [];
    } catch { /* list is optional */ }
    state.sources = { snap, items };
    renderSources();
    if (snap && snap.holdings?.length) run();
  }

  async function getPortfolio(source) {
    if (source === 'current') return readSnapshot();
    const id = source.replace(/^saved:/, '');
    const res = await apiFetch(`/api/portfolio/load/${encodeURIComponent(id)}`);
    if (!res.ok) throw uiError('an.err.notFound');
    return res.json();
  }

  /** Map a dashboard/saved portfolio to the DeepAnalysisRequest contract. */
  function buildRequest(p) {
    const pctMode = (p.inputMode || 'pct') === 'pct';
    const liq = parseFloat(p.liquidita) || 0;
    // Percent portfolios are sized on the declared total value, else on a notional amount.
    const declaredTotal = parseFloat(p.portfolioTotal) || 0;
    const base = declaredTotal > 0 ? declaredTotal : NOTIONAL;
    const holdings = (p.holdings || []).map(h => {
      const alloc = parseFloat(h.allocation) || 0;
      const amount = pctMode ? alloc / 100 * base : (parseFloat(h.amount) || null);
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
      liquidita: pctMode ? liq / 100 * base : liq,
      lookback_years: parseInt($('anLookback').value, 10),
      risk_free: (parseFloat($('anRiskFree').value) || 0) / 100,
      benchmark: $('anBenchmark').value.trim() || 'SWDA.MI',
      _pctMode: pctMode && !(declaredTotal > 0),  // only a notional base needs the caveat
    };
  }

  // ── Run ───────────────────────────────────────
  async function run() {
    const btn = $('anRunBtn');
    setStatus({ key: 'an.st.loading' });
    btn.disabled = true;
    try {
      const p = await getPortfolio($('anSource').value);
      if (!p || !p.holdings?.length) throw uiError('an.err.empty');
      const { _pctMode, ...req } = buildRequest(p);
      const deep = await postJson('/api/analysis/deep', req);
      Object.assign(state, { deep, pctMode: _pctMode, lookback: req.lookback_years, lt: null });
      renderDeep(deep, _pctMode);
      const asOf = { get date() { return date(deep.as_of); } };
      setStatus({ key: 'an.st.ltRunning', vars: asOf });
      // Look-through uses the EUR values just computed (same order as the request).
      const ltReq = { ...req, holdings: req.holdings.map((h, i) => ({ ...h, amount: deep.holdings[i]?.value ?? h.amount })) };
      setLtStatus({ key: 'an.st.ltLoading' });
      postJson('/api/analysis/look-through', ltReq)
        .then(lt => { state.lt = lt; renderLookThrough(lt); setLtStatus(null); setStatus({ key: 'an.st.done', vars: asOf }); })
        .catch(e => setLtStatus({ key: 'an.st.ltUnavailable', vars: errVars(e) }));
    } catch (e) {
      setStatus({ key: 'an.st.error', vars: errVars(e), error: true });
    } finally {
      btn.disabled = false;
    }
  }

  // ── Deep analysis rendering ───────────────────
  function kpi(label_, value, sub = '') {
    return `<div class="kpi"><div class="kpi-label">${label_}</div><div class="kpi-value">${value}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  }

  function renderNotes(d, pctMode) {
    const notes = [];
    if (pctMode) notes.push(t('an.note.pct', { amount: eur(NOTIONAL) }));
    if (d.assumed_dates.length) notes.push(t('an.note.assumed', { list: d.assumed_dates.map(esc).join(', ') }));
    if (d.excluded.length) notes.push(t('an.note.excluded', { list: d.excluded.map(esc).join(', '), pct: num(d.coverage_pct, 1) }));
    $('anNotes').innerHTML = notes.map(n => `<div>${n}</div>`).join('');
  }

  function renderKpis(d) {
    const s = d.summary, r = d.risk;
    $('rendPeriod').textContent = t('an.ret.period', { from: date(s.start_date), to: date(d.as_of) });
    $('kpiRow').innerHTML = [
      kpi(t('an.kpi.value'), eur(s.current_value)),
      kpi(t('an.kpi.invested'), eur(s.invested)),
      kpi(t('an.kpi.pl'), sEur(s.pl_eur), sPct(s.pl_pct)),
      kpi(t('an.kpi.twr'), sPct(s.twr), s.twr_annualized != null ? t('an.kpi.perYear', { v: sPct(s.twr_annualized) }) : t('an.kpi.lessThanYear')),
      kpi('MWR (XIRR)', s.mwr != null ? sPct(s.mwr) : '—', t('an.kpi.mwrSub')),
      kpi(t('an.kpi.maxDd'), `<span class="neg">${num(Math.min(...d.equity_curve.drawdown))}%</span>`, t('an.kpi.sinceBuy')),
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
      [t('an.th.class'), t('an.th.invested'), t('an.th.value'), 'P&L €', 'P&L %', t('an.th.contrib')],
      d.classes.map(c => `<tr><td>${sw(c.category)}${esc(label(c.category))}</td><td>${eur(c.cost)}</td><td>${eur(c.value)}</td>
        <td>${sEur(c.pl_eur)}</td><td>${sPct(c.pl_pct)}</td><td>${pp(c.contribution_pp)}</td></tr>`),
      `<tr><td>${t('an.th.total')}</td><td>${eur(s.invested)}</td><td>${eur(s.current_value)}</td><td>${sEur(s.pl_eur)}</td><td>${sPct(s.pl_pct)}</td><td>${pp(s.pl_pct)}</td></tr>`);
  }

  function renderHoldingTable(d) {
    const rows = [...d.holdings].sort((a, b) => b.pl_eur - a.pl_eur);
    $('holdingTable').innerHTML = `<div class="an-sub">${t('an.hold.sub')}</div>` + table(
      [t('an.th.instrument'), t('an.th.weight'), t('an.th.invested'), t('an.th.value'), t('an.th.priceEffect'), t('an.th.fxEffect'), 'P&L %', t('an.th.contrib')],
      rows.map(h => `<tr><td class="name">${sw(h.category)}<strong>${esc(h.ticker)}</strong> ${esc(h.name)}
          ${h.date_assumed ? `<span class="tag warn" title="${esc(t('an.hold.dateTitle'))}">${t('an.hold.dateTag')}</span>` : ''}</td>
        <td>${num(h.weight_pct, 1)}%</td><td>${eur(h.cost)}</td><td>${eur(h.value)}</td>
        <td>${sEur(h.price_effect)}</td><td>${h.currency === 'EUR' ? '—' : sEur(h.fx_effect)}</td>
        <td>${sPct(h.pl_pct)}</td><td>${pp(h.contribution_pp)}</td></tr>`));
  }

  function riskRow(label_, a, b, fmt) {
    return `<tr><td>${label_}</td><td>${fmt(a)}</td><td>${b == null ? '—' : fmt(b)}</td></tr>`;
  }

  function renderRisk(d) {
    const r = d.risk, b = d.benchmark_risk || {};
    $('riskPeriod').textContent = t('an.risk.period', { n: state.lookback ?? $('anLookback').value });
    const p = v => (v == null ? '—' : `${num(v)}%`);
    const x = v => num(v);
    $('riskTable').innerHTML = table([t('an.th.metric'), t('an.th.portfolio'), esc(d.benchmark || t('an.th.benchmark'))], [
      riskRow(t('an.risk.cagr'), r.cagr, b.cagr, p),
      riskRow(t('an.risk.vol'), r.volatility, b.volatility, p),
      riskRow(t('an.kpi.maxDd'), r.max_drawdown, b.max_drawdown, p),
      riskRow('Sharpe', r.sharpe, b.sharpe, x),
      riskRow('Sortino', r.sortino, b.sortino, x),
      riskRow('Calmar (CAGR / max DD)', r.calmar, b.calmar, x),
      riskRow(t('an.risk.beta'), r.beta, 1, x),
      riskRow(t('an.risk.corrBench'), r.correlation_benchmark, 1, x),
      riskRow(t('an.risk.var'), r.var_95, b.var_95, p),
      riskRow(t('an.risk.cvar'), r.cvar_95, b.cvar_95, p),
      riskRow(t('an.risk.bestWorst'), r.best_day, null, v => `${p(v)} / ${p(r.worst_day)}`),
    ]) + `<div class="an-explain">${t('an.risk.explain')}</div>`;
  }

  function heatColor(v) {
    // Diverging: blue (−1) → neutral gray (0) → red (+1)
    const lerp = (a, b, k) => Math.round(a + (b - a) * k);
    const [neg, mid, pos] = [[42, 120, 214], [56, 56, 53], [208, 59, 59]];
    const k = Math.min(1, Math.abs(v ?? 0));
    const to = (v ?? 0) >= 0 ? pos : neg;
    return `rgb(${lerp(mid[0], to[0], k)},${lerp(mid[1], to[1], k)},${lerp(mid[2], to[2], k)})`;
  }

  function renderCorrelation(corr) {
    const el = $('corrHeatmap');
    if (!corr) { el.innerHTML = `<p class="an-status">${t('an.corr.needTwo')}</p>`; return; }
    const n = corr.labels.length;
    const cells = [`<div></div>`, ...corr.labels.map(l => `<div class="hm-head" title="${esc(l)}">${esc(l)}</div>`)];
    corr.matrix.forEach((row, i) => {
      cells.push(`<div class="hm-row" title="${esc(corr.labels[i])}">${esc(corr.labels[i])}</div>`);
      row.forEach((v, j) => cells.push(`<div class="hm-cell" style="background:${heatColor(v)}"
        title="${esc(corr.labels[i])} / ${esc(corr.labels[j])}: ${num(v)}">${n <= 8 ? num(v) : ''}</div>`));
    });
    el.innerHTML = `<div class="heatmap" style="grid-template-columns:72px repeat(${n}, minmax(28px,1fr))">${cells.join('')}</div>
      <div class="hm-scale"><span>−1</span><span class="grad"></span><span>+1</span></div>`;
    A.rollingCorr(corr);
  }

  function renderFrontier(f) {
    if (!f) { $('frontierTable').innerHTML = `<p class="an-status">${t('an.corr.needTwo')}</p>`; return; }
    A.frontier(f);
    const w = fw => fw.weights.map(s => `${esc(label(s.label))} ${num(s.pct, 1)}%`).join(', ');
    $('frontierTable').innerHTML = table([t('an.th.portfolio'), t('an.th.vol'), t('an.th.return'), t('an.th.weights')], [
      `<tr><td><span class="swatch" style="background:${C.s[1]}"></span>${t('an.fr.yours')}</td><td>${num(f.current.vol)}%</td><td>${num(f.current.ret)}%</td><td class="name">${t('an.fr.current')}</td></tr>`,
      `<tr><td><span class="swatch" style="background:${C.s[2]}"></span>${t('an.fr.minVol')}</td><td>${num(f.min_vol.point.vol)}%</td><td>${num(f.min_vol.point.ret)}%</td><td class="name">${w(f.min_vol)}</td></tr>`,
      `<tr><td><span class="swatch" style="background:${C.s[3]}"></span>${t('an.fr.maxSharpe')}</td><td>${num(f.max_sharpe.point.vol)}%</td><td>${num(f.max_sharpe.point.ret)}%</td><td class="name">${w(f.max_sharpe)}</td></tr>`,
    ]);
  }

  function renderScenarios(d) {
    const r = d.risk, mc = d.monte_carlo;
    A.distribution(d.distribution);
    $('distStats').innerHTML = [
      kpi(t('an.kpi.skew'), num(r.skew), r.skew < 0 ? t('an.kpi.leftTail') : t('an.kpi.rightTail')),
      kpi(t('an.kpi.kurt'), num(r.kurtosis), r.kurtosis > 0 ? t('an.kpi.fatTails') : t('an.kpi.thinTails')),
      kpi('VaR 95%', `${num(r.var_95)}%`, t('an.kpi.varSub')),
      kpi(t('an.kpi.posDays'), `${num(r.positive_days_pct, 1)}%`),
    ].join('');
    $('mcTitle').textContent = t('an.mc.title', { n: mc.horizon_years });
    A.monteCarlo(mc);
    const last = a => a[a.length - 1];
    $('mcStats').innerHTML = [
      kpi(t('an.mc.median'), eur(last(mc.p50))),
      kpi(t('an.mc.bad'), eur(last(mc.p5)), t('an.mc.p5')),
      kpi(t('an.mc.good'), eur(last(mc.p95)), t('an.mc.p95')),
      kpi(t('an.mc.probLoss'), `${num(mc.prob_loss, 1)}%`, t('an.mc.assume', { mu: num(mc.mu, 1), sigma: num(mc.sigma, 1) })),
    ].join('');
  }

  function renderAlternatives(alt) {
    A.alternatives(alt);
    $('altPeriod').textContent = alt.dates.length
      ? t('an.alt.period', { amount: eur(10000), from: date(alt.dates[0]), to: date(alt.dates[alt.dates.length - 1]) }) : '';
    $('altNote').textContent = t('an.alt.note');
    $('altTable').innerHTML = table([t('an.th.allocation'), t('an.th.final'), 'CAGR', t('an.th.vol'), t('an.kpi.maxDd'), 'Sharpe'],
      alt.items.map(a => `<tr><td>${esc(label(a.name))}</td><td>${eur(a.values[a.values.length - 1])}</td><td>${sPct(a.cagr)}</td>
        <td>${num(a.volatility)}%</td><td><span class="neg">${num(a.max_drawdown)}%</span></td><td>${num(a.sharpe)}</td></tr>`));
  }

  function renderDeep(d, pctMode) {
    $('anEmpty').classList.add('hidden');
    $('anResults').classList.remove('hidden');
    renderNotes(d, pctMode);
    renderKpis(d);
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
        <span class="hbar-label" title="${esc(label(s.label))}">${esc(label(s.label))}</span>
        <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${Math.min(100, s.pct)}%;background:${color || C.s[0]}"></span></span>
        <span class="hbar-val">${num(s.pct, 1)}%</span></div>`).join('')
      : `<p class="an-status">${t('an.lt.na')}</p>`;
  }

  function renderBonds(lt) {
    // Ordinal blue ramp, AAA darkest; never darker than step 600 on the dark surface.
    const ratingColors = ['#184f95', '#1c5cab', '#256abf', '#2a78d6', '#3987e5', '#5598e7', '#86b6ef', '#5a6180'];
    $('bondKpis').innerHTML = [
      kpi(t('an.bond.kpiWeight'), `${num(lt.asset_classes.find(s => s.label === 'Obbligazioni')?.pct ?? 0, 1)}%`, t('an.lt.term')),
      kpi(t('an.bond.kpiDur'), lt.portfolio_duration != null ? t('an.unit.years', { n: num(lt.portfolio_duration) }) : '—',
        lt.portfolio_duration != null ? t('an.bond.rateShock', { v: num(-lt.portfolio_duration, 1) }) : ''),
    ].join('');
    $('bondCredit').innerHTML = lt.credit_quality.length ? `<div class="an-sub">${t('an.bond.credit')}</div>
      <div class="stackbar">${lt.credit_quality.map((s, i) => `<span title="${esc(label(s.label))} ${num(s.pct, 1)}%" style="width:${s.pct}%;background:${ratingColors[i] || C.context}"></span>`).join('')}</div>
      <div class="legend-inline">${lt.credit_quality.map((s, i) => `<span><span class="swatch" style="background:${ratingColors[i] || C.context}"></span>${esc(label(s.label))} ${num(s.pct, 1)}%</span>`).join('')}</div>` : '';
    $('bondTable').innerHTML = lt.bonds.length ? table([t('an.th.instrument'), t('an.th.weight'), t('an.th.maturity'), t('an.th.coupon'), t('an.th.price'), t('an.th.ytm'), t('an.th.duration')],
      lt.bonds.map(b => `<tr><td class="name"><strong>${esc(b.ticker)}</strong> ${esc(b.name)} <span class="tag">${esc(label(b.kind))}</span></td>
        <td>${num(b.weight_pct, 1)}%</td><td>${b.maturity ? esc(date(b.maturity)) : '—'}</td>
        <td>${b.coupon_pct != null ? num(b.coupon_pct) + '%' : '—'}</td><td>${num(b.price)}</td>
        <td>${b.ytm_pct != null ? num(b.ytm_pct) + '%' : '—'}</td><td>${b.duration != null ? num(b.duration) : '—'}</td></tr>`))
      : `<p class="an-status" style="margin-top:10px">${t('an.bond.none')}</p>`;
  }

  function renderCosts(lt) {
    $('costKpis').innerHTML = [
      kpi(t('an.cost.ter'), lt.ter_weighted != null ? `${num(lt.ter_weighted, 3)}%` : '—', t('an.cost.terSub')),
      kpi(t('an.cost.annual'), eur(lt.annual_cost)),
      kpi(t('an.cost.10y'), eur(lt.cost_10y), t('an.cost.10ySub')),
      kpi(t('an.cost.hedged'), `${num(lt.hedged_pct, 1)}%`),
    ].join('');
    $('costTable').innerHTML = table([t('an.th.instrument'), t('an.th.value'), 'TER', t('an.th.annualCost')],
      lt.costs.map(c => `<tr><td class="name"><strong>${esc(c.ticker)}</strong> ${esc(c.name)}</td><td>${eur(c.value)}</td>
        <td>${c.ter != null ? num(c.ter, 3) + '%' : '—'}</td><td>${c.annual_cost != null ? eur(c.annual_cost) : '—'}</td></tr>`));
    hbars('ltCurrencies', lt.currencies);
    const nonEur = lt.currencies.filter(s => s.label !== 'EUR').reduce((a, s) => a + s.pct, 0);
    $('hedgeNote').innerHTML = t('an.cost.hedgeNote', { pct: num(nonEur, 1) });
  }

  function renderLookThrough(lt) {
    hbars('ltClasses', lt.asset_classes);
    hbars('ltGeo', lt.geography);
    hbars('ltSectors', lt.sectors);
    $('ltExposures').innerHTML = table([t('an.th.security'), t('an.th.weight'), t('an.th.via')],
      lt.top_exposures.slice(0, 15).map(e => `<tr><td class="name"><strong>${esc(e.symbol)}</strong> ${esc(e.name)}</td>
        <td>${num(e.weight_pct)}%</td><td>${e.sources.map(esc).join(', ')}${e.sources.length > 1 ? ` <span class="tag warn">${t('an.lt.overlapTag')}</span>` : ''}</td></tr>`));
    $('ltOverlaps').innerHTML = lt.overlaps.length ? table(['ETF A', 'ETF B', t('an.th.overlap')],
      lt.overlaps.map(o => `<tr><td>${esc(o.a)}</td><td>${esc(o.b)}</td><td>${num(o.overlap_pct, 1)}%</td></tr>`))
      : `<p class="an-status">${t('an.lt.noOverlap')}</p>`;
    $('ltNote').textContent = label(lt.coverage_note);
    renderBonds(lt);
    renderCosts(lt);
  }

  // ── Init ──────────────────────────────────────
  const u = localStorage.getItem('auth_username');
  if (u) $('navUsername').textContent = '👤 ' + u;
  $('anRunBtn').addEventListener('click', run);
  // Language change: redraw from the last results (formats were rebuilt by analisi-charts.js).
  window.addEventListener('langchange', () => {
    if (state.sources) renderSources();
    if (state.deep) renderDeep(state.deep, state.pctMode);
    if (state.lt) renderLookThrough(state.lt);
    setStatus(state.status);
    setLtStatus(state.ltStatus);
  });
  loadSources();
})();
