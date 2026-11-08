/* ═══════════════════════════════════════
   PortfolioLab – projections on /altri-investimenti
   Life policies: value by type, paid vs surrender value, projection to
   maturity, death-benefit protection (TCM). Pension funds: Monte Carlo to
   retirement for the three investment lines. Exposes window.WealthProjections.
   The last API results are kept so 'langchange' re-renders without refetching.
═══════════════════════════════════════ */

(function () {
  const { BRANCHES, esc, eur, num, pct } = Wealth;
  const t = (k, v) => I18n.t(k, v);
  const PROFILES = {
    get conservative() { return t('wl.prof.conservative'); },
    get balanced() { return t('wl.prof.balanced'); },
    get dynamic() { return t('wl.prof.dynamic'); },
  };
  const nf1 = v => num(v, 1);

  async function getJson(url) {
    const res = await Session.apiFetch(url);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(body.detail || `HTTP ${res.status}`); e.status = res.status; throw e; }
    return body;
  }
  const tabs = (items, active) => `<div class="wl-tabs" role="tablist">${items.map(([k, label]) =>
    `<button type="button" role="tab" data-tab="${esc(k)}" class="${k === active ? 'active' : ''}"
      aria-selected="${k === active}">${label}</button>`).join('')}</div>`;
  function bindTabs(root, onPick) {
    root.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
      root.querySelectorAll('[data-tab]').forEach(x => {
        x.classList.toggle('active', x === b);
        x.setAttribute('aria-selected', String(x === b));
      });
      onPick(b.dataset.tab);
    }));
  }

  // ── Life policies ─────────────────────────────
  function byBranch(savings) {
    const tot = savings.reduce((t, p) => t + p.current_value, 0);
    const groups = {};
    savings.forEach(p => { const b = p.branch || 'other'; groups[b] = (groups[b] || 0) + p.current_value; });
    return Object.entries(groups).sort((a, b) => b[1] - a[1]).map(([b, v]) => `<div class="hbar-row">
      <span class="hbar-label">${BRANCHES[b] ?? esc(b)}</span>
      <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${tot ? v / tot * 100 : 0}%;background:${WealthCharts.branchColor(b)}"></span></span>
      <span class="hbar-val" title="${eur(v)}">${pct(tot ? v / tot * 100 : 0)}</span></div>`).join('');
  }

  function projectionNote(p) {
    const last = p.value.length - 1;
    const gain = p.value[last] - p.paid[last];
    const guarantee = p.guaranteed
      ? t(p.branch === 'multiramo' ? 'wl.pol.guaranteedMulti' : 'wl.pol.guaranteed')
      : t('wl.pol.noGuarantee');
    return `<strong>${esc(p.name)}</strong>: ${t(p.horizon_from_maturity ? 'wl.pol.noteMaturity' : 'wl.pol.note10y', {
      year: p.years[last], value: `<strong>${eur(p.value[last])}</strong>`, paid: eur(p.paid[last]),
      gain: `${gain >= 0 ? '+' : ''}${eur(gain)}`, rate: nf1(p.expected_return_pct) })}
      ${p.return_is_default ? `<span class="tag">${t('wl.pol.defaultRate')}</span>` : ''}. ${guarantee}`;
  }

  function protection(tcm) {
    if (!tcm.length) return '';
    return `<h3 class="an-sub">${t('wl.pol.tcmTitle')}</h3><div class="kpi-row">${tcm.map(p => {
      const per1000 = p.insured_capital ? p.annual_premium / p.insured_capital * 1000 : null;
      return `<div class="kpi"><div class="kpi-label">${esc(p.name)}</div>
        <div class="kpi-value">${eur(p.insured_capital)}</div>
        <div class="kpi-sub">${t('wl.pol.premium', { amount: eur(p.annual_premium) })}${per1000 != null ? ` · ${t('wl.pol.per1000', { n: num(per1000, 2) })}` : ''}</div></div>`;
    }).join('')}</div>
    <p class="an-explain">${t('wl.pol.tcmNote')}</p>`;
  }

  // Last fetch, for re-rendering: { host, policies | error, active }.
  let pol = null;

  async function renderPolicies(host, count) {
    pol = null;
    if (!count) { host.innerHTML = ''; return; }
    host.innerHTML = `<p class="an-status">${t('wl.pol.loading')}</p>`;
    try { pol = { host, policies: await getJson('/api/wealth/policies') }; } catch (e) {
      pol = { host, error: e.message };
    }
    drawPolicies();
  }

  function drawPolicies() {
    if (!pol) return;
    const { host, policies } = pol;
    if (pol.error != null) {
      host.innerHTML = `<p class="an-status error">${t('wl.pol.unavailable', { msg: esc(pol.error) })}</p>`; return;
    }
    const savings = policies.filter(p => p.years.length);
    const tcm = policies.filter(p => p.branch === 'tcm');
    if (!savings.some(p => p.asset_id === pol.active)) pol.active = savings[0]?.asset_id;
    host.innerHTML = (savings.length ? `
      <div class="an-grid-2" style="margin-top:14px">
        <div><h3 class="an-sub">${t('wl.pol.byType')}</h3><div class="hbars">${byBranch(savings)}</div></div>
        <div><h3 class="an-sub">${t('wl.pol.paidVsValue')}</h3>
          <div class="chart-box short"><canvas id="chPolBars" role="img" aria-label="${esc(t('wl.pol.barsAria'))}"></canvas></div></div>
      </div>
      <h3 class="an-sub">${t('wl.pol.projection')}</h3>
      ${savings.length > 1 ? tabs(savings.map(p => [p.asset_id, esc(p.name)]), pol.active) : ''}
      <div class="chart-box"><canvas id="chPolProj" role="img" aria-label="${esc(t('wl.pol.projAria'))}"></canvas></div>
      <p class="an-explain" id="polNote"></p>` : '') + protection(tcm);
    if (!savings.length) return;
    WealthCharts.policyBars('chPolBars', savings);
    const show = id => {
      const p = savings.find(x => x.asset_id === id);
      pol.active = id;
      WealthCharts.policyProjection('chPolProj', p);
      host.querySelector('#polNote').innerHTML = projectionNote(p);
    };
    bindTabs(host, show);
    show(pol.active);
  }

  // ── Pension funds ─────────────────────────────
  function pensionKpis(sim, sc) {
    const n = sc.net_at_retirement;
    return `
      <div class="kpi"><div class="kpi-label">${t('wl.pen.median')}</div><div class="kpi-value">${eur(n.p50)}</div>
        <div class="kpi-sub">${t('wl.pen.gross', { amount: eur(sc.gross_at_retirement.p50) })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.pen.real')}</div><div class="kpi-value">${eur(sc.net_real_p50)}</div>
        <div class="kpi-sub">${t('wl.pen.inflation', { n: nf1(sim.inflation_pct) })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.pen.bad')}</div><div class="kpi-value">${eur(n.p5)}</div>
        <div class="kpi-sub">${t('wl.pen.badSub')}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.pen.good')}</div><div class="kpi-value">${eur(n.p95)}</div>
        <div class="kpi-sub">${t('wl.pen.belowPaid', { pct: pct(sc.prob_below_paid) })}</div></div>`;
  }

  function compareTable(sim) {
    return `<div class="an-table-wrap"><table class="an-table"><thead><tr>
      <th>${t('wl.pen.th.profile')}</th><th>${t('wl.pen.th.return')}</th><th>${t('wl.pen.th.vol')}</th><th>${t('wl.pen.th.p5')}</th><th>${t('wl.pen.th.p50')}</th>
      <th>${t('wl.pen.th.p95')}</th><th>${t('wl.pen.th.risk')}</th></tr></thead><tbody>${sim.scenarios.map(s => `<tr>
      <td>${PROFILES[s.profile]}${s.profile === sim.chosen ? ` <span class="tag">${t('wl.pen.yours')}</span>` : ''}</td>
      <td>${nf1(s.mu_pct)}%</td><td>${nf1(s.sigma_pct)}%</td><td>${eur(s.net_at_retirement.p5)}</td>
      <td><strong>${eur(s.net_at_retirement.p50)}</strong></td><td>${eur(s.net_at_retirement.p95)}</td>
      <td>${pct(s.prob_below_paid)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function pensionBlock(el, sim, active) {
    const id = `chPen-${sim.asset_id}`;
    el.innerHTML = `<h3 class="an-sub">${t('wl.pen.title', { name: esc(sim.name) })}</h3>
      <p class="an-notes">${t('wl.pen.summary', {
        age: sim.current_age, retAge: sim.retirement_age, year: sim.years[sim.years.length - 1],
        years: sim.years_to_retirement, contrib: eur(sim.annual_contribution), tax: nf1(sim.tax_pct),
        paths: num(sim.paths, 0), paid: eur(sim.paid[sim.paid.length - 1]) })}</p>
      ${tabs(sim.scenarios.map(s => [s.profile, PROFILES[s.profile] + (s.profile === sim.chosen ? ` · ${t('wl.pen.yours')}` : '')]), active)}
      <div class="kpi-row k4" style="margin-top:12px" data-kpis></div>
      <div class="chart-box tall" style="margin-top:12px"><canvas id="${id}" role="img" aria-label="${esc(t('wl.pen.fanAria'))}"></canvas></div>
      <h3 class="an-sub">${t('wl.pen.compare')}</h3>${compareTable(sim)}
      <p class="an-explain">${t('wl.pen.note')}</p>`;
    const show = profile => {
      const sc = sim.scenarios.find(s => s.profile === profile);
      pens.active[sim.asset_id] = profile;
      el.querySelector('[data-kpis]').innerHTML = pensionKpis(sim, sc);
      WealthCharts.pensionFan(id, sim, sc);
    };
    bindTabs(el, show);
    show(active);
  }

  // Last results, for re-rendering: per fund { fund, sim } or { fund, error, status }.
  const pens = { host: null, results: [], active: {} };

  function drawPension(r) {
    const el = pens.host.querySelector(`[data-fund="${CSS.escape(r.fund.asset_id)}"]`);
    if (!el) return;
    const f = r.fund;
    if (r.sim) return pensionBlock(el, r.sim, pens.active[f.asset_id] ?? r.sim.chosen);
    if (r.error == null) { el.innerHTML = `<p class="an-status">${t('wl.pen.loading')}</p>`; return; }
    if (r.status !== 400) { el.innerHTML = `<p class="an-status error">${esc(f.name)}: ${esc(r.error)}</p>`; return; }
    el.innerHTML = `<div class="an-explain"><strong>${t('wl.pen.missingTitle', { name: esc(f.name) })}</strong> ${esc(r.error)}.
      <button type="button" class="btn btn-ghost btn-sm" style="margin-left:8px">${t('wl.pen.complete')}</button></div>`;
    el.querySelector('button').addEventListener('click', () =>
      window.dispatchEvent(new CustomEvent('wealth:edit', { detail: f.asset_id })));
  }

  async function renderPensions(host, funds) {
    pens.host = host;
    pens.results = funds.map(fund => ({ fund }));
    host.innerHTML = funds.map(f => `<div class="wl-pension" data-fund="${esc(f.asset_id)}"></div>`).join('');
    pens.results.forEach(drawPension);
    const current = pens.results;
    await Promise.all(current.map(async r => {
      try {
        r.sim = await getJson(`/api/wealth/pension/${encodeURIComponent(r.fund.asset_id)}`);
      } catch (e) {
        r.error = e.message;
        r.status = e.status;
      }
      if (pens.results === current) drawPension(r);
    }));
  }

  window.addEventListener('langchange', () => {
    drawPolicies();
    if (pens.host) pens.results.forEach(drawPension);
  });

  window.WealthProjections = { renderPolicies, renderPensions };
})();
