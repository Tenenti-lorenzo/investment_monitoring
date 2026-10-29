/* ═══════════════════════════════════════
   PortfolioLab – Altri investimenti (page /altri-investimenti)
   CRUD on /api/assets; the tables show the server valuation from
   /api/wealth/summary (ownership share, mortgage amortisation).
═══════════════════════════════════════ */

(function () {
  const { CATEGORIES, BRANCHES, esc, eur, signed, fmtDate } = Wealth;
  const $ = id => document.getElementById(id);

  // Per kind: section copy, form labels, table columns [header, (valuation, asset) => html].
  const gainCols = (investedLabel) => [
    [investedLabel, v => eur(v.invested)],
    ['Guadagno', v => signed(v.gain)],
  ];
  const KINDS = {
    life_insurance: {
      desc: 'Ramo I, unit linked, multiramo, TCM. Valore = valore di riscatto alla data.',
      labels: { provider: 'Compagnia', current_value: 'Valore di riscatto (€) *', invested: 'Premi versati (€)', annual_contribution: 'Premio annuo (€)' },
      cols: [['Valore riscatto', v => eur(v.gross_value)], ...gainCols('Premi versati'),
        ['Premio annuo', (v, a) => eur(a.annual_contribution)]],
    },
    pension_fund: {
      desc: 'Fondi negoziali, aperti e PIP. Valore = posizione maturata dall\'ultimo estratto.',
      labels: { provider: 'Fondo', current_value: 'Posizione maturata (€) *', invested: 'Contributi versati (€)', annual_contribution: 'Contributo annuo (€)' },
      cols: [['Posizione', v => eur(v.gross_value)], ...gainCols('Versato'),
        ['Contributo annuo', (v, a) => eur(a.annual_contribution)]],
    },
    real_estate: {
      desc: 'Casa di abitazione, seconde case, immobili a reddito. Il mutuo residuo viene sottratto.',
      labels: { provider: 'Indirizzo / città', current_value: 'Valore di mercato (€) *', invested: 'Prezzo di acquisto (€)' },
      cols: [['Valore (quota)', v => eur(v.gross_value)],
        ['Mutuo residuo', v => (v.mortgage ? `<span class="neg">${eur(-v.liability)}</span>` : '—')],
        ['Netto', v => `<strong>${eur(v.net_value)}</strong>`],
        ['Rata', v => (v.mortgage ? eur(v.mortgage.monthly_payment) + paymentBadge(v.mortgage) : '—')],
        ['Fine mutuo', v => (v.mortgage ? fmtDate(v.mortgage.end_date) : '—')]],
    },
    private: {
      desc: 'Private equity / debt, venture, club deal, crowdfunding, quote di società non quotate.',
      labels: { provider: 'Piattaforma / gestore', current_value: 'Valore attuale / NAV (€) *', invested: 'Capitale investito (€)', annual_contribution: 'Richiami annui previsti (€)' },
      cols: [['Valore / NAV', v => eur(v.gross_value)], ...gainCols('Investito')],
    },
    other: {
      desc: 'Conti deposito, TFR in azienda, oro fisico, crediti, beni da collezione…',
      labels: { provider: 'Banca / dove', current_value: 'Valore attuale (€) *', invested: 'Costo (€)' },
      cols: [['Valore', v => eur(v.gross_value)], ...gainCols('Costo')],
    },
  };
  // Bank instalment vs the one computed from amount, rate and duration.
  function paymentBadge(m) {
    if (m.payment_consistent == null) return '';
    return m.payment_consistent
      ? ' <span class="tag" title="Coincide con la rata della banca">✓ banca</span>'
      : ` <span class="tag warn" title="La banca indica ${eur(m.declared_payment)}">⚠️ banca ${eur(m.declared_payment)}</span>`;
  }
  function paymentWarnings(rows) {
    const bad = rows.filter(v => v.mortgage?.payment_consistent === false);
    if (!bad.length) return '';
    return `<div class="an-explain"><strong>Dati del mutuo da controllare.</strong> ${bad.map(v => {
      const m = v.mortgage;
      const why = m.implied_years == null
        ? 'con quel tasso la rata della banca non copre nemmeno gli interessi: controlla il TAN'
        : `con quel tasso la rata della banca corrisponde a una durata di circa ${m.implied_years.toLocaleString('it-IT')} anni`;
      return `<br>• <strong>${esc(v.name)}</strong>: rata calcolata ${eur(m.monthly_payment)}, banca ${eur(m.declared_payment)}; ${why}.
        Verifica importo erogato, TAN, durata e data (spese o assicurazioni incluse nella rata la fanno differire).`;
    }).join('')}</div>`;
  }

  const DEFAULT_LABELS = { provider: 'Compagnia / gestore', current_value: 'Valore attuale (€) *', invested: 'Versato / costo (€)', annual_contribution: 'Versamento annuo (€)' };

  const state = { assets: new Map(), valuations: [] };
  const form = $('wlForm');
  const fields = form.elements;  // named controls (form.name would also shadow HTMLFormElement.name)

  // ── Skeleton ──────────────────────────────────
  $('wlToc').innerHTML = Object.keys(KINDS).map(k =>
    `<a href="#sec-${k}">${CATEGORIES[k].icon} ${CATEGORIES[k].label}</a>`).join('')
    + '<a href="/patrimonio">📊 Patrimonio complessivo →</a>';
  $('wlSections').innerHTML = Object.entries(KINDS).map(([k, cfg]) => `
    <section class="card" id="sec-${k}">
      <div class="wl-head">
        <div class="card-header"><h2><span class="wl-icon">${CATEGORIES[k].icon}</span>${CATEGORIES[k].label}</h2>
          <p>${cfg.desc}</p></div>
        <button type="button" class="btn btn-ghost btn-sm" data-add="${k}">+ Aggiungi</button>
      </div>
      <div id="tbl-${k}"></div>
      <div id="extra-${k}"></div>
    </section>`).join('');

  // ── Render ────────────────────────────────────
  function renderKpis(s) {
    const own = s.categories.filter(c => c.category !== 'portfolio');
    const gross = own.reduce((t, c) => t + c.gross, 0);
    const debt = own.reduce((t, c) => t + c.liabilities, 0);
    const n = own.reduce((t, c) => t + c.count, 0);
    $('wlKpis').innerHTML = `
      <div class="kpi"><div class="kpi-label">Valore beni</div><div class="kpi-value">${eur(gross)}</div>
        <div class="kpi-sub">${n} ${n === 1 ? 'voce' : 'voci'}</div></div>
      <div class="kpi"><div class="kpi-label">Mutui residui</div><div class="kpi-value ${debt ? 'neg' : ''}">${eur(-debt)}</div>
        <div class="kpi-sub">quota a tuo carico</div></div>
      <div class="kpi"><div class="kpi-label">Netto fuori mercato</div><div class="kpi-value">${eur(gross - debt)}</div>
        <div class="kpi-sub">esclusi i portafogli</div></div>
      <div class="kpi"><div class="kpi-label">Patrimonio complessivo</div>
        <div class="kpi-value" style="font-size:16px;margin-top:6px"><a href="/patrimonio">Apri la vista →</a></div>
        <div class="kpi-sub">con i portafogli salvati</div></div>`;
  }

  function renderTable(kind) {
    const cfg = KINDS[kind];
    const rows = state.valuations.filter(v => v.kind === kind);
    const host = $(`tbl-${kind}`);
    if (!rows.length) { host.innerHTML = '<p class="wl-empty">Nessuna voce. Usa "+ Aggiungi".</p>'; return; }
    const head = `<tr><th>Nome</th>${cfg.cols.map(c => `<th>${c[0]}</th>`).join('')}<th></th></tr>`;
    const body = rows.map(v => {
      const a = state.assets.get(v.asset_id) || {};
      const sub = [v.provider, BRANCHES[a.insurance_branch], a.pension_line,
        a.ownership_pct < 100 ? `quota ${a.ownership_pct}%` : ''].filter(Boolean).map(esc).join(' · ');
      return `<tr><td class="name">${esc(v.name)}${sub ? `<span class="wl-sub">${sub}</span>` : ''}</td>
        ${cfg.cols.map(c => `<td>${c[1](v, a)}</td>`).join('')}
        <td><span class="wl-actions"><button type="button" data-edit="${v.asset_id}">Modifica</button>
          <button type="button" class="del" data-del="${v.asset_id}">Elimina</button></span></td></tr>`;
    }).join('');
    const tot = rows.reduce((t, v) => t + v.net_value, 0);
    host.innerHTML = `<div class="an-table-wrap"><table class="an-table"><thead>${head}</thead><tbody>${body}</tbody>
      ${rows.length > 1 ? `<tfoot><tr><td>Totale netto</td><td colspan="${cfg.cols.length + 1}">${eur(tot)}</td></tr></tfoot>` : ''}
      </table></div>${kind === 'real_estate' ? paymentWarnings(rows) : ''}`;
  }

  async function load() {
    const status = $('wlStatus');
    status.classList.remove('error');
    try {
      const [res, summary] = await Promise.all([Session.apiFetch('/api/assets'), Wealth.postSummary([])]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.assets = new Map((await res.json()).map(a => [a.asset_id, a]));
      state.valuations = summary.assets;
      status.textContent = '';
      renderKpis(summary);
      Object.keys(KINDS).forEach(renderTable);
      const byKind = k => [...state.assets.values()].filter(a => a.kind === k);
      WealthProjections.renderPolicies($('extra-life_insurance'), byKind('life_insurance').length);
      WealthProjections.renderPensions($('extra-pension_fund'), byKind('pension_fund'));
    } catch (e) {
      status.classList.add('error');
      status.textContent = `Errore: ${e.message}`;
    }
  }

  // ── Form ──────────────────────────────────────
  const mortgageMode = () => form.querySelector('[name="mortgage_mode"]:checked').value;
  function syncMortgage() {
    const on = fields.has_mortgage.checked;
    const mode = mortgageMode();
    form.querySelectorAll('[data-mortgage]').forEach(el => {
      el.hidden = !on || (el.dataset.mode != null && el.dataset.mode !== mode);
    });
  }
  function syncBranch() {
    const kindHidden = el => !el.dataset.kinds.split(' ').includes(fields.kind.value);
    form.querySelectorAll('[data-branches]').forEach(el => {
      el.hidden = kindHidden(el) || !el.dataset.branches.split(' ').includes(fields.insurance_branch.value);
    });
  }

  function openForm(kind, asset = null) {
    form.reset();
    $('wlFormError').hidden = true;
    fields.kind.value = kind;
    form.querySelectorAll('[data-kinds]').forEach(el => { el.hidden = !el.dataset.kinds.split(' ').includes(kind); });
    const labels = { ...DEFAULT_LABELS, ...KINDS[kind].labels };
    form.querySelectorAll('[data-label]').forEach(el => { el.textContent = labels[el.dataset.label]; });
    $('wlFormTitle').textContent = `${asset ? 'Modifica' : 'Nuova voce'} – ${CATEGORIES[kind].label}`;
    if (asset) {
      ['asset_id', 'name', 'provider', 'insurance_branch', 'pension_line', 'ownership_pct', 'current_value',
        'invested', 'annual_contribution', 'notes', 'insured_capital', 'maturity_date', 'expected_return_pct',
        'ramo_i_share_pct', 'pension_profile', 'birth_year', 'retirement_age', 'tax_pct']
        .forEach(f => { fields[f].value = asset[f] ?? ''; });
      const m = asset.mortgage;
      fields.has_mortgage.checked = !!m;
      if (m) {
        const simple = m.input_mode === 'payment_end';
        form.querySelector(`[name="mortgage_mode"][value="${simple ? 'payment_end' : 'loan_terms'}"]`).checked = true;
        ['annual_rate_pct', 'years', 'start_date', 'end_date', 'balance_override']
          .forEach(f => { fields[f].value = m[f] ?? ''; });
        fields[simple ? 'monthly_payment_simple' : 'monthly_payment'].value = m.monthly_payment ?? '';
        fields[simple ? 'principal_simple' : 'principal'].value = m.principal ?? '';
      }
    }
    syncMortgage();
    syncBranch();
    $('wlModal').classList.remove('hidden');
    fields.name.focus();
  }
  const closeForm = () => $('wlModal').classList.add('hidden');

  function readForm() {
    const num = f => (fields[f].value === '' ? null : Number(fields[f].value));
    const kind = fields.kind.value;
    const body = {
      asset_id: fields.asset_id.value || null,
      kind,
      name: fields.name.value.trim(),
      provider: fields.provider.value.trim(),
      current_value: num('current_value') ?? 0,
      invested: num('invested'),
      annual_contribution: !fields.annual_contribution.closest('[data-kinds]').hidden ? num('annual_contribution') : null,
      insurance_branch: kind === 'life_insurance' ? (fields.insurance_branch.value || null) : null,
      pension_line: kind === 'pension_fund' ? fields.pension_line.value.trim() : '',
      ownership_pct: kind === 'real_estate' ? (num('ownership_pct') ?? 100) : 100,
      notes: fields.notes.value.trim(),
      mortgage: null,
    };
    if (kind === 'life_insurance') Object.assign(body, {
      insured_capital: num('insured_capital'),
      maturity_date: fields.maturity_date.value || null,
      expected_return_pct: num('expected_return_pct'),
      ramo_i_share_pct: fields.insurance_branch.value === 'multiramo' ? num('ramo_i_share_pct') : null,
    });
    if (kind === 'pension_fund') Object.assign(body, {
      pension_profile: fields.pension_profile.value || null,
      birth_year: num('birth_year'),
      retirement_age: num('retirement_age') ?? 67,
      tax_pct: num('tax_pct'),
    });
    if (kind === 'real_estate' && fields.has_mortgage.checked) {
      const mode = mortgageMode();
      body.mortgage = mode === 'payment_end'
        ? { input_mode: mode, monthly_payment: num('monthly_payment_simple'), annual_rate_pct: num('annual_rate_pct') ?? 0,
            end_date: fields.end_date.value || null, principal: num('principal_simple'),
            balance_override: num('balance_override') }
        : { input_mode: mode, principal: num('principal'), annual_rate_pct: num('annual_rate_pct') ?? 0,
            years: num('years'), start_date: fields.start_date.value || null,
            monthly_payment: num('monthly_payment'), balance_override: num('balance_override') };
    }
    return body;
  }

  function describeError(detail) {
    if (!Array.isArray(detail)) return detail || 'Dati non validi';
    const names = { name: 'nome', current_value: 'valore', principal: 'importo mutuo', years: 'durata',
      start_date: 'data stipula', annual_rate_pct: 'tasso', ownership_pct: 'quota', monthly_payment: 'rata',
      end_date: 'data ultima rata', mortgage: 'dati del mutuo',
      birth_year: 'anno di nascita', retirement_age: 'età pensione', tax_pct: 'tasse',
      expected_return_pct: 'rendimento atteso', ramo_i_share_pct: 'quota Ramo I', insured_capital: 'capitale assicurato' };
    return 'Controlla: ' + [...new Set(detail.map(d => names[d.loc?.[d.loc.length - 1]] || d.loc?.slice(-1)[0]))].join(', ');
  }

  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const err = $('wlFormError');
    err.hidden = true;
    $('wlSave').disabled = true;
    try {
      const res = await Session.apiFetch('/api/assets', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(readForm()),
      });
      if (!res.ok) throw new Error(describeError((await res.json().catch(() => ({}))).detail));
      closeForm();
      await load();
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
    } finally {
      $('wlSave').disabled = false;
    }
  });
  fields.has_mortgage.addEventListener('change', syncMortgage);
  form.querySelectorAll('[name="mortgage_mode"]').forEach(r => r.addEventListener('change', syncMortgage));
  fields.insurance_branch.addEventListener('change', syncBranch);
  $('wlCancel').addEventListener('click', closeForm);
  $('wlModal').addEventListener('click', ev => { if (ev.target === $('wlModal')) closeForm(); });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeForm(); });

  $('wlSections').addEventListener('click', async ev => {
    const add = ev.target.closest('[data-add]');
    if (add) return openForm(add.dataset.add);
    const edit = ev.target.closest('[data-edit]');
    if (edit) {
      const a = state.assets.get(edit.dataset.edit);
      return a && openForm(a.kind, a);
    }
    const del = ev.target.closest('[data-del]');
    if (del) {
      const a = state.assets.get(del.dataset.del);
      if (!a || !confirm(`Eliminare "${a.name}"?`)) return;
      del.disabled = true;
      try {
        const res = await Session.apiFetch(`/api/assets/${encodeURIComponent(a.asset_id)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error();
        await load();
      } catch {
        del.disabled = false;
        alert('Errore nella eliminazione.');
      }
    }
  });

  // "Completa i dati" in the pension simulation opens the form of that fund.
  window.addEventListener('wealth:edit', ev => {
    const a = state.assets.get(ev.detail);
    if (a) openForm(a.kind, a);
  });
  Wealth.showUsername();
  load();
})();
