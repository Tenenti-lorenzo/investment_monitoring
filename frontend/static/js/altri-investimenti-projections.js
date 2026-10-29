/* ═══════════════════════════════════════
   PortfolioLab – projections on /altri-investimenti
   Life policies: value by type, paid vs surrender value, projection to
   maturity, death-benefit protection (TCM). Pension funds: Monte Carlo to
   retirement for the three investment lines. Exposes window.WealthProjections.
═══════════════════════════════════════ */

(function () {
  const { BRANCHES, esc, eur, pct } = Wealth;
  const PROFILES = { conservative: 'Conservativo', balanced: 'Bilanciato', dynamic: 'Dinamico' };
  const nf1 = v => v.toLocaleString('it-IT', { maximumFractionDigits: 1 });

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
      <span class="hbar-label">${BRANCHES[b]}</span>
      <span class="hbar-track"><span class="hbar-fill" style="display:block;width:${tot ? v / tot * 100 : 0}%;background:${WealthCharts.branchColor(b)}"></span></span>
      <span class="hbar-val" title="${eur(v)}">${pct(tot ? v / tot * 100 : 0)}</span></div>`).join('');
  }

  function projectionNote(p) {
    const last = p.value.length - 1;
    const gain = p.value[last] - p.paid[last];
    return `<strong>${esc(p.name)}</strong>: a ${p.horizon_from_maturity ? 'scadenza' : '10 anni (nessuna scadenza indicata)'}
      nel ${p.years[last]} stimati <strong>${eur(p.value[last])}</strong> a fronte di ${eur(p.paid[last])} versati
      (${gain >= 0 ? '+' : ''}${eur(gain)}), con rendimento ${nf1(p.expected_return_pct)}% annuo
      ${p.return_is_default ? '<span class="tag">stima per tipo</span>' : ''}.
      ${p.guaranteed ? ' La linea tratteggiata è il capitale garantito (premi versati' + (p.branch === 'multiramo' ? ', solo quota Ramo I' : '') + '): verifica le condizioni del tuo contratto.' : ' Ramo III: nessuna garanzia, il valore segue i mercati.'}`;
  }

  function protection(tcm) {
    if (!tcm.length) return '';
    return `<h3 class="an-sub">Protezione caso morte (TCM)</h3><div class="kpi-row">${tcm.map(p => {
      const per1000 = p.insured_capital ? p.annual_premium / p.insured_capital * 1000 : null;
      return `<div class="kpi"><div class="kpi-label">${esc(p.name)}</div>
        <div class="kpi-value">${eur(p.insured_capital)}</div>
        <div class="kpi-sub">premio ${eur(p.annual_premium)}/anno${per1000 != null ? ` · ${per1000.toLocaleString('it-IT', { maximumFractionDigits: 2 })} € ogni 1.000 € assicurati` : ''}</div></div>`;
    }).join('')}</div>
    <p class="an-explain">La TCM non accumula capitale: è un costo di protezione, conta zero nel patrimonio.</p>`;
  }

  async function renderPolicies(host, count) {
    if (!count) { host.innerHTML = ''; return; }
    host.innerHTML = '<p class="an-status">Calcolo proiezioni…</p>';
    let policies;
    try { policies = await getJson('/api/wealth/policies'); } catch (e) {
      host.innerHTML = `<p class="an-status error">Proiezioni non disponibili: ${esc(e.message)}</p>`; return;
    }
    const savings = policies.filter(p => p.years.length);
    const tcm = policies.filter(p => p.branch === 'tcm');
    const first = savings[0]?.asset_id;
    host.innerHTML = (savings.length ? `
      <div class="an-grid-2" style="margin-top:14px">
        <div><h3 class="an-sub">Valore per tipologia</h3><div class="hbars">${byBranch(savings)}</div></div>
        <div><h3 class="an-sub">Premi versati vs valore di riscatto</h3>
          <div class="chart-box short"><canvas id="chPolBars" role="img" aria-label="Premi versati e valore di riscatto per polizza"></canvas></div></div>
      </div>
      <h3 class="an-sub">Proiezione a scadenza</h3>
      ${savings.length > 1 ? tabs(savings.map(p => [p.asset_id, esc(p.name)]), first) : ''}
      <div class="chart-box"><canvas id="chPolProj" role="img" aria-label="Proiezione del valore della polizza"></canvas></div>
      <p class="an-explain" id="polNote"></p>` : '') + protection(tcm);
    if (!savings.length) return;
    WealthCharts.policyBars('chPolBars', savings);
    const show = id => {
      const p = savings.find(x => x.asset_id === id);
      WealthCharts.policyProjection('chPolProj', p);
      host.querySelector('#polNote').innerHTML = projectionNote(p);
    };
    bindTabs(host, show);
    show(first);
  }

  // ── Pension funds ─────────────────────────────
  function pensionKpis(sim, sc) {
    const n = sc.net_at_retirement;
    return `
      <div class="kpi"><div class="kpi-label">Mediana netta</div><div class="kpi-value">${eur(n.p50)}</div>
        <div class="kpi-sub">lordo ${eur(sc.gross_at_retirement.p50)}</div></div>
      <div class="kpi"><div class="kpi-label">In euro di oggi</div><div class="kpi-value">${eur(sc.net_real_p50)}</div>
        <div class="kpi-sub">inflazione ${nf1(sim.inflation_pct)}%/anno</div></div>
      <div class="kpi"><div class="kpi-label">Scenario sfavorevole</div><div class="kpi-value">${eur(n.p5)}</div>
        <div class="kpi-sub">solo 5 scenari su 100 fanno peggio</div></div>
      <div class="kpi"><div class="kpi-label">Scenario favorevole</div><div class="kpi-value">${eur(n.p95)}</div>
        <div class="kpi-sub">sotto meno del versato: ${pct(sc.prob_below_paid)}</div></div>`;
  }

  function compareTable(sim) {
    return `<div class="an-table-wrap"><table class="an-table"><thead><tr>
      <th>Profilo (netto)</th><th>Rend. atteso</th><th>Volatilità</th><th>Sfavorevole 5%</th><th>Mediana</th>
      <th>Favorevole 95%</th><th>Rischio &lt; versato</th></tr></thead><tbody>${sim.scenarios.map(s => `<tr>
      <td>${PROFILES[s.profile]}${s.profile === sim.chosen ? ' <span class="tag">il tuo</span>' : ''}</td>
      <td>${nf1(s.mu_pct)}%</td><td>${nf1(s.sigma_pct)}%</td><td>${eur(s.net_at_retirement.p5)}</td>
      <td><strong>${eur(s.net_at_retirement.p50)}</strong></td><td>${eur(s.net_at_retirement.p95)}</td>
      <td>${pct(s.prob_below_paid)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function pensionBlock(el, sim) {
    const id = `chPen-${sim.asset_id}`;
    el.innerHTML = `<h3 class="an-sub">Simulazione Monte Carlo – ${esc(sim.name)}</h3>
      <p class="an-notes">Oggi ${sim.current_age} anni → pensione a ${sim.retirement_age} nel ${sim.years[sim.years.length - 1]}
        (${sim.years_to_retirement} anni) · contributo ${eur(sim.annual_contribution)}/anno · tasse ${nf1(sim.tax_pct)}% ·
        ${sim.paths.toLocaleString('it-IT')} scenari · versato a fine periodo ${eur(sim.paid[sim.paid.length - 1])}</p>
      ${tabs(sim.scenarios.map(s => [s.profile, PROFILES[s.profile] + (s.profile === sim.chosen ? ' · il tuo' : '')]), sim.chosen)}
      <div class="kpi-row k4" style="margin-top:12px" data-kpis></div>
      <div class="chart-box tall" style="margin-top:12px"><canvas id="${id}" role="img" aria-label="Ventaglio degli scenari fino alla pensione"></canvas></div>
      <h3 class="an-sub">Confronto tra profili</h3>${compareTable(sim)}
      <p class="an-explain">Ipotesi di lungo periodo, al netto dei costi del fondo e della tassazione annua sui rendimenti:
        non sono previsioni. Contributi costanti, nessuna anticipazione. Le tasse sono applicate all'intero capitale
        finale con l'aliquota che hai indicato; la rendita effettiva dipende dai coefficienti del fondo.</p>`;
    const show = profile => {
      const sc = sim.scenarios.find(s => s.profile === profile);
      el.querySelector('[data-kpis]').innerHTML = pensionKpis(sim, sc);
      WealthCharts.pensionFan(id, sim, sc);
    };
    bindTabs(el, show);
    show(sim.chosen);
  }

  async function renderPensions(host, funds) {
    host.innerHTML = funds.map(f => `<div class="wl-pension" data-fund="${esc(f.asset_id)}"><p class="an-status">Simulazione…</p></div>`).join('');
    await Promise.all(funds.map(async f => {
      const el = host.querySelector(`[data-fund="${f.asset_id}"]`);
      try {
        pensionBlock(el, await getJson(`/api/wealth/pension/${encodeURIComponent(f.asset_id)}`));
      } catch (e) {
        if (e.status !== 400) { el.innerHTML = `<p class="an-status error">${esc(f.name)}: ${esc(e.message)}</p>`; return; }
        el.innerHTML = `<div class="an-explain"><strong>${esc(f.name)} – simulazione alla pensione.</strong> ${esc(e.message)}.
          <button type="button" class="btn btn-ghost btn-sm" style="margin-left:8px">Completa i dati</button></div>`;
        el.querySelector('button').addEventListener('click', () =>
          window.dispatchEvent(new CustomEvent('wealth:edit', { detail: f.asset_id })));
      }
    }));
  }

  window.WealthProjections = { renderPolicies, renderPensions };
})();
