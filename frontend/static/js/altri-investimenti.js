/* ═══════════════════════════════════════
   PortfolioLab – Altri investimenti (page /altri-investimenti)
   CRUD on /api/assets; the tables show the server valuation from
   /api/wealth/summary (ownership share, mortgage amortisation).
   Texts come from static/i18n/wealth*.js; on 'langchange' everything is
   re-rendered from the data already loaded.
═══════════════════════════════════════ */

(function () {
  const { CATEGORIES, BRANCHES, esc, eur, signed, num, fmtDate } = Wealth;
  const $ = id => document.getElementById(id);
  const t = (k, v) => I18n.t(k, v);

  // Per kind: section copy, form labels, table columns [header, (valuation, asset) => html].
  const gainCols = (investedLabel) => [
    [investedLabel, v => eur(v.invested)],
    [t('wl.col.gain'), v => signed(v.gain)],
  ];
  const KINDS = {
    life_insurance: {
      desc: () => t('wl.li.desc'),
      labels: () => ({ provider: t('wl.li.provider'), current_value: t('wl.li.value'), invested: t('wl.li.invested'), annual_contribution: t('wl.li.annual') }),
      cols: () => [[t('wl.li.colValue'), v => eur(v.gross_value)], ...gainCols(t('wl.li.colInvested')),
        [t('wl.li.colAnnual'), (v, a) => eur(a.annual_contribution)]],
    },
    pension_fund: {
      desc: () => t('wl.pf.desc'),
      labels: () => ({ provider: t('wl.pf.provider'), current_value: t('wl.pf.value'), invested: t('wl.pf.invested'), annual_contribution: t('wl.pf.annual') }),
      cols: () => [[t('wl.pf.colValue'), v => eur(v.gross_value)], ...gainCols(t('wl.pf.colInvested')),
        [t('wl.pf.colAnnual'), (v, a) => eur(a.annual_contribution)]],
    },
    real_estate: {
      desc: () => t('wl.re.desc'),
      labels: () => ({ provider: t('wl.re.provider'), current_value: t('wl.re.value'), invested: t('wl.re.invested') }),
      cols: () => [[t('wl.re.colValue'), v => eur(v.gross_value)],
        [t('wl.re.colMortgage'), v => (v.mortgage ? `<span class="neg">${eur(-v.liability)}</span>` : '—')],
        [t('wl.re.colNet'), v => `<strong>${eur(v.net_value)}</strong>`],
        [t('wl.re.colPayment'), v => (v.mortgage ? eur(v.mortgage.monthly_payment) + paymentBadge(v.mortgage) : '—')],
        [t('wl.re.colEnd'), v => (v.mortgage ? fmtDate(v.mortgage.end_date) : '—')]],
    },
    private: {
      desc: () => t('wl.pm.desc'),
      labels: () => ({ provider: t('wl.pm.provider'), current_value: t('wl.pm.value'), invested: t('wl.pm.invested'), annual_contribution: t('wl.pm.annual') }),
      cols: () => [[t('wl.pm.colValue'), v => eur(v.gross_value)], ...gainCols(t('wl.pm.colInvested'))],
    },
    other: {
      desc: () => t('wl.ot.desc'),
      labels: () => ({ provider: t('wl.ot.provider'), current_value: t('wl.ot.value'), invested: t('wl.ot.invested') }),
      cols: () => [[t('wl.ot.colValue'), v => eur(v.gross_value)], ...gainCols(t('wl.ot.colInvested'))],
    },
  };
  // Bank instalment vs the one computed from amount, rate and duration.
  function paymentBadge(m) {
    if (m.payment_consistent == null) return '';
    return m.payment_consistent
      ? ` <span class="tag" title="${esc(t('wl.mort.bankOkTitle'))}">${t('wl.mort.bankOk')}</span>`
      : ` <span class="tag warn" title="${esc(t('wl.mort.bankDiffTitle', { amount: eur(m.declared_payment) }))}">${t('wl.mort.bankDiff', { amount: eur(m.declared_payment) })}</span>`;
  }
  function paymentWarnings(rows) {
    const bad = rows.filter(v => v.mortgage?.payment_consistent === false);
    if (!bad.length) return '';
    return `<div class="an-explain"><strong>${t('wl.mort.checkTitle')}</strong> ${bad.map(v => {
      const m = v.mortgage;
      const why = m.implied_years == null
        ? t('wl.mort.whyInterest')
        : t('wl.mort.whyYears', { n: num(m.implied_years) });
      return `<br>• <strong>${esc(v.name)}</strong>: ${t('wl.mort.checkLine', { calc: eur(m.monthly_payment), bank: eur(m.declared_payment), why })}`;
    }).join('')}</div>`;
  }

  const defaultLabels = () => ({ provider: t('wl.f.provider'), current_value: t('wl.f.value'), invested: t('wl.f.invested'), annual_contribution: t('wl.f.annual') });

  const state = { assets: new Map(), valuations: [], summary: null, error: null };
  const form = $('wlForm');
  const fields = form.elements;  // named controls (form.name would also shadow HTMLFormElement.name)
  let formCtx = null;            // { kind, editing } while the form is open

  // ── Skeleton ──────────────────────────────────
  $('wlSections').innerHTML = Object.keys(KINDS).map(k => `
    <section class="card" id="sec-${k}">
      <div class="wl-head"></div>
      <div id="tbl-${k}"></div>
      <div id="extra-${k}"></div>
    </section>`).join('');
  function renderHeads() {
    $('wlToc').innerHTML = Object.keys(KINDS).map(k =>
      `<a href="#sec-${k}">${CATEGORIES[k].icon} ${CATEGORIES[k].label}</a>`).join('')
      + `<a href="/patrimonio">${t('wl.toc.networth')}</a>`;
    Object.entries(KINDS).forEach(([k, cfg]) => {
      $(`sec-${k}`).querySelector('.wl-head').innerHTML = `
        <div class="card-header"><h2><span class="wl-icon">${CATEGORIES[k].icon}</span>${CATEGORIES[k].label}</h2>
          <p>${cfg.desc()}</p></div>
        <button type="button" class="btn btn-ghost btn-sm" data-add="${k}">${t('wl.add')}</button>`;
    });
  }

  // ── Render ────────────────────────────────────
  function renderKpis(s) {
    const own = s.categories.filter(c => c.category !== 'portfolio');
    const gross = own.reduce((t, c) => t + c.gross, 0);
    const debt = own.reduce((t, c) => t + c.liabilities, 0);
    const n = own.reduce((t, c) => t + c.count, 0);
    $('wlKpis').innerHTML = `
      <div class="kpi"><div class="kpi-label">${t('wl.kpi.value')}</div><div class="kpi-value">${eur(gross)}</div>
        <div class="kpi-sub">${n === 1 ? t('wl.kpi.item', { n }) : t('wl.kpi.items', { n })}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.kpi.mortgages')}</div><div class="kpi-value ${debt ? 'neg' : ''}">${eur(-debt)}</div>
        <div class="kpi-sub">${t('wl.kpi.mortgagesSub')}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.kpi.net')}</div><div class="kpi-value">${eur(gross - debt)}</div>
        <div class="kpi-sub">${t('wl.kpi.netSub')}</div></div>
      <div class="kpi"><div class="kpi-label">${t('wl.kpi.networth')}</div>
        <div class="kpi-value" style="font-size:16px;margin-top:6px"><a href="/patrimonio">${t('wl.kpi.open')}</a></div>
        <div class="kpi-sub">${t('wl.kpi.networthSub')}</div></div>`;
  }

  function renderTable(kind) {
    const cols = KINDS[kind].cols();
    const rows = state.valuations.filter(v => v.kind === kind);
    const host = $(`tbl-${kind}`);
    if (!rows.length) { host.innerHTML = `<p class="wl-empty">${t('wl.empty')}</p>`; return; }
    const head = `<tr><th>${t('wl.col.name')}</th>${cols.map(c => `<th>${c[0]}</th>`).join('')}<th></th></tr>`;
    const body = rows.map(v => {
      const a = state.assets.get(v.asset_id) || {};
      const sub = [v.provider, a.insurance_branch && BRANCHES[a.insurance_branch], a.pension_line,
        a.ownership_pct != null && a.ownership_pct < 100 ? t('wl.tbl.share', { n: num(a.ownership_pct) }) : ''].filter(Boolean).map(esc).join(' · ');
      return `<tr><td class="name">${esc(v.name)}${sub ? `<span class="wl-sub">${sub}</span>` : ''}</td>
        ${cols.map(c => `<td>${c[1](v, a)}</td>`).join('')}
        <td><span class="wl-actions"><button type="button" data-edit="${v.asset_id}">${t('wl.edit')}</button>
          <button type="button" class="del" data-del="${v.asset_id}">${t('wl.delete')}</button></span></td></tr>`;
    }).join('');
    const tot = rows.reduce((t, v) => t + v.net_value, 0);
    host.innerHTML = `<div class="an-table-wrap"><table class="an-table"><thead>${head}</thead><tbody>${body}</tbody>
      ${rows.length > 1 ? `<tfoot><tr><td>${t('wl.tbl.total')}</td><td colspan="${cols.length + 1}">${eur(tot)}</td></tr></tfoot>` : ''}
      </table></div>${kind === 'real_estate' ? paymentWarnings(rows) : ''}`;
  }

  function renderStatus() {
    const status = $('wlStatus');
    status.classList.toggle('error', !!state.error);
    status.textContent = state.error ? t('wl.error', { msg: state.error })
      : state.summary ? '' : t('wl.loading');
  }

  function renderData() {
    renderStatus();
    if (!state.summary) return;
    renderKpis(state.summary);
    Object.keys(KINDS).forEach(renderTable);
  }

  async function load() {
    state.error = null;
    $('wlStatus').classList.remove('error');
    try {
      const [res, summary] = await Promise.all([Session.apiFetch('/api/assets'), Wealth.postSummary([])]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.assets = new Map((await res.json()).map(a => [a.asset_id, a]));
      state.valuations = summary.assets;
      state.summary = summary;
      renderData();
      const byKind = k => [...state.assets.values()].filter(a => a.kind === k);
      WealthProjections.renderPolicies($('extra-life_insurance'), byKind('life_insurance').length);
      WealthProjections.renderPensions($('extra-pension_fund'), byKind('pension_fund'));
    } catch (e) {
      state.error = e.message;
      renderStatus();
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
  // Labels and title that depend on the asset kind (re-run on 'langchange').
  function renderFormTexts() {
    if (!formCtx) return;
    const { kind, editing } = formCtx;
    const labels = { ...defaultLabels(), ...KINDS[kind].labels() };
    form.querySelectorAll('[data-label]').forEach(el => { el.textContent = labels[el.dataset.label]; });
    $('wlFormTitle').textContent = `${editing ? t('wl.form.edit') : t('wl.form.new')} – ${CATEGORIES[kind].label}`;
  }

  function openForm(kind, asset = null) {
    form.reset();
    $('wlFormError').hidden = true;
    fields.kind.value = kind;
    form.querySelectorAll('[data-kinds]').forEach(el => { el.hidden = !el.dataset.kinds.split(' ').includes(kind); });
    formCtx = { kind, editing: !!asset };
    renderFormTexts();
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
  const closeForm = () => { $('wlModal').classList.add('hidden'); formCtx = null; };

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

  // Validation errors (FastAPI 422 list) → field names in the interface language.
  function describeError(detail) {
    if (!Array.isArray(detail)) return detail || t('wl.err.invalid');
    const names = { name: t('wl.err.f.name'), current_value: t('wl.err.f.current_value'), principal: t('wl.err.f.principal'),
      years: t('wl.err.f.years'), start_date: t('wl.err.f.start_date'), annual_rate_pct: t('wl.err.f.annual_rate_pct'),
      ownership_pct: t('wl.err.f.ownership_pct'), monthly_payment: t('wl.err.f.monthly_payment'),
      end_date: t('wl.err.f.end_date'), mortgage: t('wl.err.f.mortgage'),
      birth_year: t('wl.err.f.birth_year'), retirement_age: t('wl.err.f.retirement_age'), tax_pct: t('wl.err.f.tax_pct'),
      expected_return_pct: t('wl.err.f.expected_return_pct'), ramo_i_share_pct: t('wl.err.f.ramo_i_share_pct'),
      insured_capital: t('wl.err.f.insured_capital') };
    const list = [...new Set(detail.map(d => names[d.loc?.[d.loc.length - 1]] || d.loc?.slice(-1)[0]))].join(', ');
    return t('wl.err.check', { fields: list });
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
      if (!a || !confirm(t('wl.confirmDelete', { name: a.name }))) return;
      del.disabled = true;
      try {
        const res = await Session.apiFetch(`/api/assets/${encodeURIComponent(a.asset_id)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error();
        await load();
      } catch {
        del.disabled = false;
        alert(t('wl.deleteError'));
      }
    }
  });

  // "Completa i dati" in the pension simulation opens the form of that fund.
  window.addEventListener('wealth:edit', ev => {
    const a = state.assets.get(ev.detail);
    if (a) openForm(a.kind, a);
  });
  window.addEventListener('langchange', () => {
    renderHeads();
    renderData();
    renderFormTexts();
  });
  renderHeads();
  renderStatus();
  Wealth.showUsername();
  load();
})();
