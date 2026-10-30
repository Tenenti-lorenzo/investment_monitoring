/* ═══════════════════════════════════════
   PortfolioLab – Frontend App Logic
═══════════════════════════════════════ */

const API = '';

// ── Auth helpers ─────────────────────────────
// Session handling (rotating token, 15-minute inactivity expiry) lives in session.js.
const apiFetch = (url, opts) => Session.apiFetch(url, opts);

// Chart colors are read from the CSS theme tokens at draw time (scriptable
// options), so a light/dark switch only needs a chart.update().
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const themeMuted = () => cssVar('--muted');
const themeGrid  = () => cssVar('--border2');
window.addEventListener('themechange', () => {
  [allocationChart, geoChart, perfChart].forEach(c => c && c.update('none'));
});

const CAT_COLORS = {
  'ETF Azionario':       '#8b5cf6',
  'ETF Obbligazionario': '#06b6d4',
  'ETF':                 '#8b5cf6',
  'Azioni':              '#3b82f6',
  'Criptovalute':        '#22d3a0',
  'Liquidità':           '#f59e0b',
  'Obbligazioni':        '#10b981',
};
const CAT_ICONS = {
  'ETF Azionario':       '📊',
  'ETF Obbligazionario': '📋',
  'ETF':                 '📊',
  'Azioni':              '👤',
  'Criptovalute':        '₿',
  'Liquidità':           '💰',
  'Obbligazioni':        '🏛️',
};
const GEO_COLORS = {
  'Nord America': '#3b82f6',
  'Europa': '#8b5cf6',
  'Asia-Pacifico': '#22d3a0',
  'Latam': '#f59e0b',
  'Altre': '#94a3b8',
  'Altre regioni': '#94a3b8',
  'Africa/ME': '#f43f5e',
  'Europa Emergente': '#a78bfa',
  'Globale': '#6366f1',
};
const CUR_COLORS = {
  'USD': '#3b82f6',
  'EUR': '#8b5cf6',
  'GBP': '#06b6d4',
  'JPY': '#f59e0b',
  'CHF': '#22d3a0',
  'CAD': '#f43f5e',
  'AUD': '#a78bfa',
  'DKK': '#94a3b8',
  'SEK': '#64748b',
};
const CUR_FLAGS = {
  'USD': '🇺🇸', 'EUR': '🇪🇺', 'GBP': '🇬🇧', 'JPY': '🇯🇵',
  'CHF': '🇨🇭', 'CAD': '🇨🇦', 'AUD': '🇦🇺', 'DKK': '🇩🇰',
  'SEK': '🇸🇪', 'NOK': '🇳🇴',
};

// Display labels for values the backend sends in Italian (categories, regions,
// risk tiers…): the Italian value stays the identifier/colour key, only the
// shown label is translated (unknown values are shown as they are).
const CAT_KEYS = {
  'ETF Azionario': 'dash.cat.etfEquity', 'ETF Obbligazionario': 'dash.cat.etfBond', 'ETF': 'dash.cat.etf',
  'Azioni': 'dash.cat.stocks', 'Criptovalute': 'dash.cat.crypto', 'Liquidità': 'dash.cat.cash',
  'Obbligazioni': 'dash.cat.bonds',
};
const GEO_KEYS = {
  'Nord America': 'dash.geo.northAmerica', 'Europa': 'dash.geo.europe', 'Asia-Pacifico': 'dash.geo.asiaPacific',
  'Latam': 'dash.geo.latam', 'Altre': 'dash.geo.other', 'Altre regioni': 'dash.geo.otherRegions',
  'Africa/ME': 'dash.geo.africaMe', 'Europa Emergente': 'dash.geo.emergingEurope', 'Globale': 'dash.geo.global',
  'Mercati Emergenti': 'dash.geo.emerging',
};
const RISK_KEYS = {
  'Molto basso': 'dash.risk.veryLow', 'Basso': 'dash.risk.low', 'Medio': 'dash.risk.medium',
  'Alto': 'dash.risk.high', 'Molto alto': 'dash.risk.veryHigh', 'N/D': 'dash.na',
};
const PROFILE_KEYS = {
  'Conservativo': 'dash.profile.conservative', 'Moderato': 'dash.profile.moderate',
  'Moderatamente Aggressivo': 'dash.profile.modAggressive', 'Aggressivo': 'dash.profile.aggressive',
};
const BOND_TYPE_KEYS = {
  'Governativo': 'dash.bond.type.gov', 'Corporate': 'dash.bond.type.corp', 'Obbligazione': 'dash.bond.type.bond',
};
const labelOf = (keys, v) => (keys[v] ? I18n.t(keys[v]) : v);
const catLabel = c => labelOf(CAT_KEYS, c);
const geoLabel = g => labelOf(GEO_KEYS, g);

// ── State ──────────────────────────────────
let portfolio = [];   // { isin, ticker, yf_ticker, name, category, allocation, amount, geography, currency }
let pac = [];         // PAC entries
let lastSearchData = null;
let allocationChart = null;
let geoChart = null;
let inputMode = 'pct'; // 'pct' | 'amount'
let portfolioTotal = 0; // EUR value of the whole portfolio, declared in 'pct' mode
const fxPerEur = { EUR: 1 }; // currency → units per 1 EUR (null = unavailable)
let baseCurrency = 'EUR';
let _perfDataFull = null;
let _perfExcluded = [];
let _currentPeriodDays = 365;
let _perfNote = null;  // { key, color } of the message shown instead of the chart
let savedCount = 0;    // saved portfolios, shown on the load button

// ── DOM refs ────────────────────────────────
const searchInput   = document.getElementById('searchInput');
const searchBtn     = document.getElementById('searchBtn');
const searchResult  = document.getElementById('searchResult');
const holdingsTbody = document.getElementById('holdingsTbody');
const analyzeBtn    = document.getElementById('analyzeBtn');
const demoBtn       = document.getElementById('demoBtn');
const clearBtn      = document.getElementById('clearBtn');
const liquiditaInp  = document.getElementById('liquiditaInput');
const liquiditaLbl  = document.getElementById('liquiditaLabel');
const totalPctEl    = document.getElementById('totalPct');
const dashboard     = document.getElementById('dashboard');
const modeToggleBtn = document.getElementById('modeToggle');
const allocHeader   = document.getElementById('allocHeader');
const totalInp      = document.getElementById('portfolioTotalInput');
const totalRow      = document.getElementById('portfolioTotalRow');

// ── Mode toggle ──────────────────────────────
// Labels that depend on the input mode (also refreshed on language change).
function renderModeLabels() {
  const isPct = inputMode === 'pct';
  modeToggleBtn.textContent = isPct ? I18n.t('dash.mode.toAmount', { cur: baseCurrency }) : I18n.t('dash.mode.toPct');
  modeToggleBtn.classList.toggle('mode-amount-active', !isPct);
  allocHeader.textContent = isPct ? I18n.t('dash.tbl.allocPct') : I18n.t('dash.tbl.amount', { cur: baseCurrency });
  liquiditaLbl.textContent = isPct ? I18n.t('dash.liq.pct') : I18n.t('dash.liq.amount', { cur: baseCurrency });
}

modeToggleBtn.addEventListener('click', () => {
  const liqUnit = document.getElementById('liquiditaUnit');
  const liqVal = parseFloat(liquiditaInp.value || 0);
  if (inputMode === 'pct') {
    // % → EUR: with a declared total, positions and cash keep their value.
    if (portfolioTotal > 0) {
      portfolio.forEach(h => { h.amount = round2(portfolioTotal * (h.allocation || 0) / 100); });
      liquiditaInp.value = round2(portfolioTotal * liqVal / 100);
    }
    inputMode = 'amount';
    renderModeLabels();
    if (liqUnit) liqUnit.textContent = baseCurrency;
    liquiditaInp.removeAttribute('max');
    liquiditaInp.step = '100';
  } else {
    // EUR → %: the amounts' sum becomes the declared total.
    const totalAmt = portfolio.reduce((s, h) => s + (parseFloat(h.amount) || 0), 0) + liqVal;
    if (totalAmt > 0) {
      setPortfolioTotal(totalAmt);
      liquiditaInp.value = round2(liqVal / totalAmt * 100);
    }
    inputMode = 'pct';
    renderModeLabels();
    if (liqUnit) liqUnit.textContent = '%';
    liquiditaInp.max = '100';
    liquiditaInp.step = '0.1';
  }
  renderTable();
  updateTotal();
});

// ── Portfolio total (pct mode): % → EUR amount → number of shares ──
const round2 = v => Math.round(v * 100) / 100;

function setPortfolioTotal(v) {
  portfolioTotal = v > 0 ? round2(v) : 0;
  totalInp.value = portfolioTotal || '';
}
totalInp.addEventListener('input', () => {
  portfolioTotal = parseFloat(totalInp.value) || 0;
  updateTotal();
});

// Fetch (once) the EUR rate of every currency in the portfolio, then refresh the labels.
async function ensureFxRates() {
  const missing = [...new Set(portfolio.map(h => h.currency).filter(c => c && !(c in fxPerEur)))];
  if (!missing.length) return;
  missing.forEach(c => { fxPerEur[c] = undefined; });  // in flight: don't refetch
  await Promise.all(missing.map(async c => {
    try {
      const res = await apiFetch(`${API}/api/fx/${encodeURIComponent(c)}`);
      fxPerEur[c] = res.ok ? (await res.json()).per_eur : null;
    } catch { fxPerEur[c] = null; }
  }));
  refreshDerived();
}

// Shares (or bond nominal) a EUR amount buys at the last known price, null if unknown.
function sharesFor(h, amountEur) {
  if (!(amountEur > 0) || !(h.price > 0)) return null;
  const rate = h.currency ? fxPerEur[h.currency] : 1;
  if (!(rate > 0)) return null;
  const local = amountEur * rate;
  return isBond(h) ? local / h.price * 100 : local / h.price;
}

function derivedLabel(h) {
  if (inputMode !== 'pct' || !(portfolioTotal > 0)) return '';
  const amt = portfolioTotal * (h.allocation || 0) / 100;
  if (!(amt > 0)) return '';
  const n = sharesFor(h, amt);
  const fmtN = v => v.toLocaleString(I18n.locale, { maximumFractionDigits: v >= 100 ? 0 : 2 });
  const shares = n == null
    ? (h.price > 0 && h.currency && fxPerEur[h.currency] === undefined ? ' · …' : '')
    : ' · ' + I18n.t(isBond(h) ? 'dash.derived.nominal' : 'dash.derived.shares', { n: fmtN(n) });
  return `€ ${fmtAmt(amt)}${shares}`;
}

function refreshDerived() {
  holdingsTbody.querySelectorAll('.holding-derived').forEach(el => {
    const h = portfolio[+el.dataset.idx];
    if (h) el.textContent = derivedLabel(h);
  });
}

// ── Search ──────────────────────────────────
searchBtn.addEventListener('click', doSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

async function doSearch() {
  const q = searchInput.value.trim();
  if (!q) return;

  searchResult.className = 'search-result loading';
  searchResult.innerHTML = `<span class="spinner"></span> ${I18n.t('dash.search.loading')}`;

  try {
    const res = await apiFetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || I18n.t('dash.search.notFound'));
    }
    const data = await res.json();
    lastSearchData = data;
    renderSearchResult(data);
  } catch (e) {
    searchResult.className = 'search-result error';
    searchResult.innerHTML = `❌ ${e.message}`;
  }
}

const RISK_COLORS = {
  'Molto basso': '#10b981', 'Basso': '#22c55e', 'Medio': '#f59e0b',
  'Alto': '#f97316', 'Molto alto': '#ef4444', 'N/D': '#888',
};

// Bond detail panel: type, issuer country, live sovereign risk (FRED).
function renderBondPanel(d) {
  if (d.category !== 'Obbligazioni') return '';
  const r = d.sovereign_risk;
  const meta = [];
  if (d.bond_type)      meta.push(labelOf(BOND_TYPE_KEYS, d.bond_type));
  if (d.issuer_country) meta.push(I18n.t('dash.bond.issuer', { c: d.issuer_country }));
  if (d.currency)       meta.push(d.currency);
  const metaLine = meta.length
    ? `<div style="font-size:12px;color:var(--text);margin-bottom:6px">${meta.join(' · ')}</div>`
    : '';

  let riskLine = '';
  if (r) {
    const rc = RISK_COLORS[r.risk_tier] || '#888';
    const parts = [`<span style="color:${rc};font-weight:700">${labelOf(RISK_KEYS, r.risk_tier)}</span>`];
    if (r.yield_10y != null)       parts.push(I18n.t('dash.bond.yield10', { v: r.yield_10y }));
    if (r.bund_spread_bps != null) parts.push(I18n.t('dash.bond.spread', { v: r.bund_spread_bps }));
    riskLine = `
      <div style="font-size:12px;color:var(--muted)">${I18n.t('dash.bond.sovRisk', { v: parts.join(' · ') })}</div>
      ${r.as_of ? `<div style="font-size:10px;color:var(--muted)">FRED · ${r.as_of}</div>` : ''}
      ${r.note ? `<div style="font-size:10px;color:var(--muted);margin-top:4px;font-style:italic">${r.note}</div>` : ''}`;
  }
  let marketLine = '';
  const m = d.market_data;
  if (m) {
    const n = (v, dec = 2) => v != null ? v.toLocaleString(I18n.locale, { maximumFractionDigits: dec }) : '—';
    const vc = m.change_pct == null ? 'var(--muted)' : m.change_pct >= 0 ? 'var(--green)' : 'var(--red)';
    const cpn = m.coupon_annual_pct ?? m.coupon_period_pct;
    const facts = [];
    if (m.maturity) facts.push(I18n.t('dash.bond.maturity', { d: new Date(m.maturity).toLocaleDateString(I18n.locale) }));
    if (cpn != null) facts.push(I18n.t(m.coupon_annual_pct == null ? 'dash.bond.couponPeriod' : 'dash.bond.coupon', { v: n(cpn, 3) }));
    if (m.min_lot != null) facts.push(I18n.t('dash.bond.minLot', { n: n(m.min_lot, 0) }));
    marketLine = `
      <div style="font-size:12px;color:var(--text);margin-bottom:4px">
        ${I18n.t('dash.bond.last')} <strong>${n(m.last_price, 3)}</strong>
        <span style="color:${vc}">${m.change_pct != null ? (m.change_pct >= 0 ? '+' : '') + n(m.change_pct) + '%' : ''}</span>
        · ${I18n.t('dash.bond.ref')} ${n(m.reference_price, 3)} · ${I18n.t('dash.bond.official')} ${n(m.official_price, 3)}
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:4px">
        ${I18n.t('dash.bond.today')} ${n(m.day_low, 3)}–${n(m.day_high, 3)} · ${I18n.t('dash.bond.year')} ${n(m.year_low, 3)}–${n(m.year_high, 3)} · ${I18n.t('dash.bond.volume')} ${n(m.volume, 0)}
      </div>
      ${facts.length ? `<div style="font-size:11px;color:var(--muted);margin-bottom:4px">${facts.join(' · ')}</div>` : ''}
      <div style="font-size:10px;color:var(--muted);margin-bottom:6px">Borsa Italiana · ${m.market}${m.last_trade_at ? ' · ' + new Date(m.last_trade_at).toLocaleString(I18n.locale) : ''}</div>`;
  }
  if (!metaLine && !riskLine && !marketLine) return '';
  return `
    <div style="margin-top:10px;background:var(--bg);border-radius:8px;padding:10px 12px;border:1px solid var(--border)">
      <div style="font-size:10px;color:var(--muted);font-weight:700;margin-bottom:6px;letter-spacing:0.07em;text-transform:uppercase">${I18n.t('dash.bond.details')}</div>
      ${metaLine}${marketLine}${riskLine}
    </div>`;
}

function renderSearchResult(d) {
  const color = CAT_COLORS[d.category] || '#888';
  const isPct = inputMode === 'pct';
  const inpStyle = 'background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:13px;font-family:inherit;outline:none';
  const mismatchWarn = d.isin_mismatch
    ? `<div class="sr-warn">${I18n.t('dash.sr.mismatch')}</div>`
    : '';
  const noDataNote = d.description && !d.price
    ? `<div style="font-size:11px;color:var(--amber);margin-top:4px">ℹ️ ${d.description}</div>`
    : '';
  const bondPanel = renderBondPanel(d);
  const allocSection = isPct ? `
    <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);display:flex;align-items:center;gap:8px">
      <label style="font-size:11px;color:var(--muted);min-width:140px">${I18n.t('dash.sr.alloc')}</label>
      <input type="number" id="srAllocInput" min="0" step="0.1" value="10"
        style="${inpStyle};width:75px" />
      <span style="color:var(--muted);font-size:13px">%</span>
    </div>` : '';

  searchResult.className = 'search-result';
  searchResult.innerHTML = `
    <div class="sr-info">
      <div class="sr-name">${d.name}</div>
      <div class="sr-ticker">${d.ticker}${d.exch ? ' · ' + d.exch : ''}${d.currency ? ' · ' + d.currency : ''}${d.price ? ' · ' + fmtQuote(d) : ''}${d.ter != null ? ' · <span style="color:var(--amber)">TER ' + d.ter.toFixed(2) + '%</span>' : ''}</div>
      ${d.sector ? `<div class="sr-meta">${d.sector}${d.industry ? ' · ' + d.industry : ''}</div>` : ''}
      ${d.fundFamily ? `<div class="sr-meta">${d.fundFamily}</div>` : ''}
      ${mismatchWarn}${noDataNote}
    </div>
    <span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${catLabel(d.category)}</span>
    ${bondPanel}

    <div style="margin-top:10px;background:var(--bg);border-radius:8px;padding:12px 14px;border:1px solid var(--border)">
      <div style="font-size:10px;color:var(--muted);font-weight:700;margin-bottom:10px;letter-spacing:0.07em;text-transform:uppercase">${I18n.t('dash.sr.position')}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="font-size:11px;color:var(--muted)">${I18n.t('dash.sr.totalValue')}</label>
          <input type="number" id="srValueInput" min="0" step="100" placeholder="${I18n.t('dash.sr.valuePh')}"
            style="${inpStyle};width:115px" />
        </div>
        <span style="color:var(--muted);font-size:12px;padding-bottom:7px">${I18n.t('dash.sr.or')}</span>
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="font-size:11px;color:var(--muted)">${I18n.t(isBond(d) ? 'dash.sr.nominal' : 'dash.sr.qty')}</label>
          <input type="number" id="srQtyInput" min="0" step="0.001" placeholder="${I18n.t('dash.sr.qtyPh')}"
            style="${inpStyle};width:95px" />
        </div>
        <span style="color:var(--muted);font-size:14px;padding-bottom:7px">×</span>
        <div style="display:flex;flex-direction:column;gap:4px">
          <label style="font-size:11px;color:var(--muted)">${isBond(d) ? I18n.t('dash.sr.buyPricePct') : I18n.t('dash.sr.buyPrice', { cur: d.currency || 'EUR' })}</label>
          <input type="number" id="srBuyPriceInput" min="0" step="0.01" placeholder="${I18n.t(isBond(d) ? 'dash.sr.bondPricePh' : 'dash.sr.perShare')}"
            style="${inpStyle};width:120px" />
        </div>
      </div>
      ${allocSection}
    </div>

    <button class="btn btn-primary sr-add-btn" id="srAddBtn" style="margin-top:10px">${I18n.t('dash.sr.add')}</button>
  `;

  // Auto-calc value from qty × price
  const autoCalc = () => {
    const qty = parseFloat(document.getElementById('srQtyInput')?.value || '') || 0;
    const price = parseFloat(document.getElementById('srBuyPriceInput')?.value || '') || 0;
    if (qty > 0 && price > 0) {
      const vi = document.getElementById('srValueInput');
      if (vi && !vi.value) vi.value = positionValue(lastSearchData, qty, price).toFixed(2);
    }
  };
  document.getElementById('srQtyInput')?.addEventListener('blur', autoCalc);
  document.getElementById('srBuyPriceInput')?.addEventListener('blur', autoCalc);

  document.getElementById('srAddBtn').addEventListener('click', () => {
    const totalValue = parseFloat(document.getElementById('srValueInput')?.value || 0);
    const allocPct   = parseFloat(document.getElementById('srAllocInput')?.value || 0);
    const qty        = parseFloat(document.getElementById('srQtyInput')?.value || '') || null;
    const buyPrice   = parseFloat(document.getElementById('srBuyPriceInput')?.value || '') || null;
    const computedValue = totalValue || (qty && buyPrice ? positionValue(lastSearchData, qty, buyPrice) : 0);

    if (inputMode === 'pct' && allocPct <= 0) { alert(I18n.t('dash.sr.needAlloc')); return; }
    if (inputMode === 'amount' && computedValue <= 0) { alert(I18n.t('dash.sr.needValue')); return; }

    const h = { ...lastSearchData };
    if (qty !== null) h.quantity = qty;
    if (buyPrice !== null) h.purchase_price = buyPrice;
    if (inputMode === 'pct') {
      h.allocation = allocPct;
      h.amount = computedValue || null;
    } else {
      h.amount = computedValue;
      h.allocation = 0;
    }
    addHolding(h);
    searchResult.className = 'search-result hidden';
    searchInput.value = '';
  });
}

function fmtPrice(p, cur) {
  return (cur || '') + ' ' + parseFloat(p).toLocaleString(I18n.locale, { maximumFractionDigits: 2 });
}
// Bonds: quantity = nominal, price = % of nominal → value = nominal × price / 100.
function isBond(h) {
  return h && (h.category === 'Obbligazioni' || h.price_unit === 'pct_of_par');
}
function positionValue(h, qty, price) {
  return qty * price * (isBond(h) ? 0.01 : 1);
}
function fmtQuote(d) {
  if (!d.price) return '';
  return isBond(d)
    ? d.price.toLocaleString(I18n.locale, { maximumFractionDigits: 3 }) + '%'
    : fmtPrice(d.price, d.currency);
}
function fmtAmt(v) {
  return parseFloat(v || 0).toLocaleString(I18n.locale, { maximumFractionDigits: 0 });
}

// ── Holdings management ──────────────────────
function addHolding(h) {
  const existing = portfolio.find(x => x.ticker === h.ticker);
  if (existing) {
    if (inputMode === 'pct') existing.allocation = h.allocation;
    else existing.amount = h.amount;
    if (h.quantity != null) existing.quantity = h.quantity;
    if (h.purchase_price != null) existing.purchase_price = h.purchase_price;
    renderTable();
    updateTotal();
    return;
  }
  portfolio.push({ ...h, amount: h.amount ?? null });
  renderTable();
  updateTotal();
  renderPac();
}

function renderTable() {
  holdingsTbody.innerHTML = '';
  if (portfolio.length === 0) {
    holdingsTbody.innerHTML = `<tr class="empty-row"><td colspan="4" class="empty-cell">${I18n.t('dash.tbl.empty')}</td></tr>`;
    return;
  }
  const isPct = inputMode === 'pct';
  portfolio.forEach((h, i) => {
    const color = CAT_COLORS[h.category] || '#888';
    const inputVal = isPct ? (h.allocation || 0).toFixed(1) : (h.amount || 0);
    const calcPct = !isPct
      ? `<span class="holding-calc-pct">${(h.allocation || 0).toFixed(1)}%</span>`
      : '';
    const qtyInfo = h.quantity
      ? `<div style="font-size:11px;color:var(--muted);margin-top:2px">× ${h.quantity}${h.purchase_price ? ` · ${I18n.t('dash.tbl.pmc')} ` + fmtPrice(h.purchase_price, h.currency) : ''}</div>`
      : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <div class="holding-name">${h.name}</div>
        <div class="holding-ticker">${h.ticker}${h.isin ? ' · ' + h.isin : ''}${h.currency ? ' <span class="cur-tag">' + h.currency + '</span>' : ''}</div>
        ${qtyInfo}
      </td>
      <td><span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${catLabel(h.category)}</span></td>
      <td>
        <input class="holding-alloc-input" type="number" min="0" step="${isPct ? '0.1' : '100'}"
          value="${inputVal}" data-idx="${i}" />
        <span style="color:var(--muted);font-size:12px"> ${isPct ? '%' : baseCurrency}</span>
        ${calcPct}
        ${isPct ? `<span class="holding-derived" data-idx="${i}">${derivedLabel(h)}</span>` : ''}
      </td>
      <td><button class="btn-rm" data-idx="${i}">×</button></td>
    `;
    holdingsTbody.appendChild(tr);
  });

  holdingsTbody.querySelectorAll('.holding-alloc-input').forEach(inp => {
    inp.addEventListener('input', e => {
      const idx = +e.target.dataset.idx;
      if (inputMode === 'pct') {
        portfolio[idx].allocation = parseFloat(e.target.value || 0);
      } else {
        portfolio[idx].amount = parseFloat(e.target.value || 0);
      }
      updateTotal();
    });
  });
  holdingsTbody.querySelectorAll('.btn-rm').forEach(btn => {
    btn.addEventListener('click', e => {
      portfolio.splice(+e.target.dataset.idx, 1);
      renderTable();
      updateTotal();
    });
  });
}

function updateTotal() {
  const liqVal = parseFloat(liquiditaInp.value || 0);

  if (inputMode === 'amount') {
    const totalAmt = portfolio.reduce((s, h) => s + (parseFloat(h.amount) || 0), 0) + liqVal;
    if (totalAmt > 0) {
      portfolio.forEach(h => {
        h.allocation = ((parseFloat(h.amount) || 0) / totalAmt) * 100;
      });
    }
    // Refresh calc pct labels
    holdingsTbody.querySelectorAll('.holding-calc-pct').forEach((el, i) => {
      if (portfolio[i]) el.textContent = `${(portfolio[i].allocation || 0).toFixed(1)}%`;
    });
    totalPctEl.textContent = I18n.t('dash.total', { v: `${baseCurrency} ${fmtAmt(totalAmt)}` });
    totalPctEl.className = 'total-pct total-ok';
  } else {
    const tot = portfolio.reduce((s, h) => s + (parseFloat(h.allocation) || 0), 0) + liqVal;
    if (portfolioTotal > 0) {
      portfolio.forEach(h => { h.amount = round2(portfolioTotal * (parseFloat(h.allocation) || 0) / 100); });
      refreshDerived();
      ensureFxRates();
    }
    totalPctEl.textContent = I18n.t('dash.total', { v: `${tot.toFixed(1)}%` })
      + (portfolioTotal > 0 ? ` · € ${fmtAmt(portfolioTotal * tot / 100)}` : '');
    totalPctEl.className = 'total-pct ' + (Math.abs(tot - 100) < 0.5 ? 'total-ok' : 'total-warn');
  }
  totalRow.classList.toggle('hidden', inputMode !== 'pct');
  analyzeBtn.disabled = portfolio.length === 0;
  document.getElementById('deepAnalysisBtn').disabled = portfolio.length === 0;
  const _sbg = document.getElementById('saveBtnGroup');
  if (_sbg) _sbg.style.display = portfolio.length > 0 ? 'inline-flex' : 'none';

  // Show PAC section when portfolio has items
  const pacSection = document.getElementById('pacSection');
  if (pacSection) pacSection.style.display = portfolio.length > 0 ? 'block' : 'none';
}

liquiditaInp.addEventListener('input', updateTotal);

// ── Analyze ─────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
  const liqVal = parseFloat(liquiditaInp.value || 0);
  let liquiditaPct = liqVal;
  let liquiditaEur = inputMode === 'pct' ? portfolioTotal * liqVal / 100 : liqVal;
  if (inputMode === 'amount') {
    const totalAmt = portfolio.reduce((s, h) => s + (parseFloat(h.amount) || 0), 0) + liqVal;
    liquiditaPct = totalAmt > 0 ? (liqVal / totalAmt * 100) : 0;
  }

  const body = {
    holdings: portfolio.map(h => ({
      isin:           h.isin || '',
      name:           h.name,
      ticker:         h.ticker,
      yf_ticker:      h.yf_ticker || null,
      category:       h.category,
      allocation:     parseFloat(h.allocation) || 0,
      geography:      h.geography || null,
      currency:       h.currency || null,
      ter:            h.ter ?? null,
      amount:         h.amount ?? null,
      quantity:       h.quantity ?? null,
      purchase_price: h.purchase_price ?? null,
      purchase_date:  h.purchase_date ?? null,
    })),
    liquidita: liquiditaPct,
  };

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = I18n.t('dash.btn.analyzing');

  try {
    const res = await apiFetch(`${API}/api/portfolio/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(I18n.t('dash.err.analyze'));
    const data = await res.json();
    const terMap = data.ter_map || {};
    // Backend TERs win; implausible stored values (> 5 %, legacy unit bug) are dropped.
    const fixTer = h => (terMap[h.ticker] != null ? terMap[h.ticker] : (h.ter > 0 && h.ter <= 5 ? h.ter : null));
    const enrichedHoldings = body.holdings.map(h => ({ ...h, ter: fixTer(h) }));
    portfolio.forEach(h => { h.ter = fixTer(h); });  // persisted on the next "Salva"
    renderDashboard(data, enrichedHoldings, liquiditaPct, liquiditaEur);
    dashboard.classList.remove('hidden');
    document.getElementById('portfolioSummaryCard').classList.remove('hidden');
    dashboard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    fetchPerformance(enrichedHoldings, liquiditaEur);
  } catch (e) {
    alert(I18n.t('dash.err.prefix', { msg: e.message }));
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = I18n.t('dash.btn.analyze');
  }
});

// ── Demo ────────────────────────────────────
demoBtn.addEventListener('click', () => {
  inputMode = 'amount';
  renderModeLabels();
  liquiditaInp.value = 250;

  portfolio = [
    { isin: '', ticker: 'MSFT',    yf_ticker: 'MSFT',    name: 'Microsoft Corp.',                                    category: 'Azioni',        allocation: 0, amount: 5700,  geography: {'Nord America': 100},                                              currency: 'USD' },
    { isin: '', ticker: 'VST',     yf_ticker: 'VST',     name: 'Vistra Corp.',                                       category: 'Azioni',        allocation: 0, amount: 5050,  geography: {'Nord America': 100},                                              currency: 'USD' },
    { isin: '', ticker: 'ZETA',    yf_ticker: 'ZETA',    name: 'Zeta Global',                                        category: 'Azioni',        allocation: 0, amount: 4800,  geography: {'Nord America': 100},                                              currency: 'USD' },
    { isin: '', ticker: 'UNH',     yf_ticker: 'UNH',     name: 'UnitedHealth Group',                                 category: 'Azioni',        allocation: 0, amount: 6200,  geography: {'Nord America': 100},                                              currency: 'USD' },
    { isin: '', ticker: 'ETH-USD', yf_ticker: 'ETH-USD', name: 'Ethereum',                                           category: 'Criptovalute',  allocation: 0, amount: 4450,  geography: {'Globale': 100},                                                   currency: 'USD' },
    { isin: 'IE00BKM4GZ66', ticker: 'IWVL', yf_ticker: 'IWVL.L', name: 'iShares MSCI World Value Factor UCITS ETF', category: 'ETF Azionario', allocation: 0, amount: 6400,  geography: {'Nord America': 68, 'Europa': 20, 'Asia-Pacifico': 9, 'Altre': 3}, currency: 'USD', ter: 0.30 },
    { isin: 'IE00B3RBWM25', ticker: 'SWRD', yf_ticker: 'SWRD.L', name: 'iShares Core MSCI World UCITS ETF',         category: 'ETF Azionario', allocation: 0, amount: 10750, geography: {'Nord America': 68, 'Europa': 20, 'Asia-Pacifico': 9, 'Altre': 3}, currency: 'USD', ter: 0.20 },
    { isin: '', ticker: 'V',       yf_ticker: 'V',       name: 'Visa Inc.',                                          category: 'Azioni',        allocation: 0, amount: 2300,  geography: {'Nord America': 100},                                              currency: 'USD' },
    { isin: '', ticker: 'NVO',     yf_ticker: 'NVO',     name: 'Novo Nordisk',                                       category: 'Azioni',        allocation: 0, amount: 4100,  geography: {'Europa': 100},                                                    currency: 'DKK' },
  ];
  renderTable();
  updateTotal();
  analyzeBtn.click();
});

clearBtn.addEventListener('click', () => {
  portfolio = [];
  pac = [];
  setPortfolioTotal(0);
  renderTable();
  updateTotal();
  renderPac();
  dashboard.classList.add('hidden');
  document.getElementById('portfolioSummaryCard').classList.add('hidden');
  searchResult.className = 'search-result hidden';
  document.getElementById('plBanner').style.display = 'none';
  lastDashboard = null;
});

// ── Render Dashboard ────────────────────────
let lastDashboard = null;  // last rendered arguments, redrawn on language change

function renderDashboard(data, holdings, liq, liqEur = 0) {
  lastDashboard = [data, holdings, liq, liqEur];
  renderAllocationChart(data.category_pct);
  renderCategoryBars(data.category_pct);
  renderGeoChart(data.geography);
  renderHoldingsList(holdings, liq, data.total);
  renderClassExposure(data.category_pct);
  renderMetriche(data.metrics);
  renderCurrencyRisk(data.currency_exposure || {});
  renderCurrencyRisk(data.underlying_currency_exposure || {}, 'underlyingCurrencyRisk');
  renderPortfolioSummary(holdings, liqEur, liq); // liq = liquiditaPct
}

function renderAllocationChart(catPct) {
  const cats = Object.entries(catPct).filter(([, v]) => v > 0);
  const keys   = cats.map(([k]) => k);
  const labels = keys.map(catLabel);
  const values = cats.map(([, v]) => v);
  const colors = keys.map(k => CAT_COLORS[k] || '#888');

  if (allocationChart) allocationChart.destroy();
  const ctx = document.getElementById('allocationChart').getContext('2d');
  allocationChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: () => cssVar('--card'), borderWidth: 3 }] },
    options: {
      cutout: '65%',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` } } },
    },
  });
  document.getElementById('allocationLegend').innerHTML = labels.map((l, i) => `
    <div class="legend-item">
      <span class="legend-dot" style="background:${colors[i]}"></span>
      <span class="legend-label">${l}</span>
      <span class="legend-val" style="color:${colors[i]}">${values[i].toFixed(1)}%</span>
    </div>
  `).join('');
}

function renderCategoryBars(catPct) {
  const max = Math.max(...Object.values(catPct));
  document.getElementById('categoryBars').innerHTML = Object.entries(catPct)
    .filter(([, v]) => v > 0)
    .map(([cat, pct]) => {
      const color = CAT_COLORS[cat] || '#888';
      return `
        <div class="cat-bar-row">
          <div class="cat-bar-icon" style="background:${color}22;border:1px solid ${color}44">${CAT_ICONS[cat] || '📈'}</div>
          <span class="cat-bar-label">${catLabel(cat)}</span>
          <div class="cat-bar-track">
            <div class="cat-bar-fill" style="width:${(pct/max)*100}%;background:${color}"></div>
          </div>
          <span class="cat-bar-pct" style="color:${color}">${pct.toFixed(1)}%</span>
        </div>
      `;
    }).join('');
}

function renderGeoChart(geo) {
  const entries = Object.entries(geo).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const labels = entries.map(([k]) => geoLabel(k));
  const values = entries.map(([, v]) => v);
  const colors = entries.map(([k]) => GEO_COLORS[k] || '#94a3b8');

  if (geoChart) geoChart.destroy();
  const ctx = document.getElementById('geoChart').getContext('2d');
  geoChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.map(c => c + 'bb'),
        borderColor: colors,
        borderWidth: 1.5,
        borderRadius: 6,
      }]
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.x.toFixed(1)}%` } } },
      scales: {
        x: { display: false, max: 105 },
        y: { grid: { display: false }, ticks: { color: themeMuted, font: { size: 11 } } },
      },
    },
  });
}

function renderHoldingsList(holdings, liq, total) {
  const maxAlloc = Math.max(...holdings.map(h => h.allocation), liq || 0);
  let html = holdings.map(h => {
    const color = CAT_COLORS[h.category] || '#888';
    const pct = (h.allocation / total * 100).toFixed(1);
    const barW = (h.allocation / maxAlloc * 100).toFixed(1);
    let terBadge = '';
    if (h.ter != null && h.ter > 0) {
      const terColor = h.ter < 0.1 ? '#22d3a0' : h.ter <= 0.2 ? '#f59e0b' : '#f43f5e';
      terBadge = `<span style="font-size:10px;font-weight:600;color:${terColor}">TER ${h.ter.toFixed(2)}%</span>`;
    }
    return `
      <div class="hl-row">
        <div class="hl-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${h.ticker.slice(0,4)}</div>
        <div class="hl-info">
          <div class="hl-name">${h.name}</div>
          <div class="hl-ticker">${h.ticker}${h.currency ? ' · <span class="cur-tag">' + h.currency + '</span>' : ''}${terBadge ? ' &nbsp;' + terBadge : ''}</div>
        </div>
        <div class="hl-bar-wrap">
          <div class="hl-bar-track"><div class="hl-bar-fill" style="width:${barW}%;background:${color}"></div></div>
        </div>
        <span class="hl-pct">${pct}%</span>
      </div>
    `;
  }).join('');
  if (liq > 0) {
    const color = CAT_COLORS['Liquidità'];
    const pct = (liq / total * 100).toFixed(1);
    const barW = (liq / maxAlloc * 100).toFixed(1);
    html += `
      <div class="hl-row">
        <div class="hl-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">LIQ</div>
        <div class="hl-info"><div class="hl-name">${catLabel('Liquidità')}</div><div class="hl-ticker">${I18n.t('dash.hl.cashSub')}</div></div>
        <div class="hl-bar-wrap"><div class="hl-bar-track"><div class="hl-bar-fill" style="width:${barW}%;background:${color}"></div></div></div>
        <span class="hl-pct">${pct}%</span>
      </div>
    `;
  }
  document.getElementById('holdingsList').innerHTML = html;
}

function renderClassExposure(catPct) {
  const segments = Object.entries(catPct).filter(([, v]) => v > 0);
  document.getElementById('classExposure').innerHTML = segments.map(([cat, pct]) => {
    const color = CAT_COLORS[cat] || '#888';
    return `
      <div class="ceb-segment" style="flex:${pct};background:${color}">
        <span class="ceb-pct">${pct.toFixed(1)}%</span>
        <span class="ceb-name">${catLabel(cat)}</span>
      </div>
    `;
  }).join('');
}

let perfChart = null;

function renderMetriche(m) {
  const profiloEmoji = {
    'Conservativo': '🟢', 'Moderato': '🟡',
    'Moderatamente Aggressivo': '🟠', 'Aggressivo': '🔴',
  };
  const terVal   = m.ter_medio != null ? I18n.t('dash.met.terVal', { v: m.ter_medio.toFixed(2) }) : I18n.t('dash.na');
  const terColor = m.ter_medio != null ? 'var(--amber)' : 'var(--muted)';
  const terBox   = `
    <div class="metrica-box">
      <div class="metrica-icon">💸</div>
      <div class="metrica-label">${I18n.t('dash.met.ter')}</div>
      <div class="metrica-val" style="color:${terColor}">${terVal}</div>
    </div>`;
  document.getElementById('metriche').innerHTML = `
    <div class="metrica-box">
      <div class="metrica-icon">📈</div>
      <div class="metrica-label">${I18n.t('dash.met.return')}</div>
      <div class="metrica-val" style="color:var(--green)">${m.expected_return}</div>
    </div>
    <div class="metrica-box">
      <div class="metrica-icon">🛡️</div>
      <div class="metrica-label">${I18n.t('dash.met.vol')}</div>
      <div class="metrica-val" style="color:var(--amber)">${m.volatility}</div>
    </div>
    <div class="metrica-box">
      <div class="metrica-icon">📊</div>
      <div class="metrica-label">${I18n.t('dash.met.sharpe')}</div>
      <div class="metrica-val" style="color:var(--blue)">${m.sharpe}</div>
    </div>
    ${terBox}
    <div class="profilo-box">
      <div class="profilo-emoji">${profiloEmoji[m.aggressiveness] || '⚪'}</div>
      <div class="profilo-label" style="color:var(--amber)">${I18n.t('dash.met.profile', { p: labelOf(PROFILE_KEYS, m.aggressiveness) })}</div>
    </div>
  `;
}

async function fetchPerformance(holdings, liquidita) {
  const perfCard = document.getElementById('perfCard');

  const perfHoldings = holdings.filter(h => h.yf_ticker).map(h => {
    let amt = null;
    if (h.amount > 0) amt = h.amount;
    else if (h.quantity > 0 && h.purchase_price > 0) amt = h.quantity * h.purchase_price;
    return amt ? { yf_ticker: h.yf_ticker, amount: amt } : null;
  }).filter(Boolean);

  // Holdings excluded from the chart because they have no yf_ticker (or no amount)
  const excludedHoldings = holdings.filter(h => h.ticker !== 'CASH').filter(h => {
    const hasAmt = h.amount > 0 || (h.quantity > 0 && h.purchase_price > 0);
    return !h.yf_ticker || !hasAmt;
  });

  // Holdings with an amount but no Yahoo ticker (e.g. bonds) are held flat in the chart
  const unpricedAmount = excludedHoldings.reduce((sum, h) => {
    if (h.amount > 0) return sum + h.amount;
    if (h.quantity > 0 && h.purchase_price > 0) return sum + h.quantity * h.purchase_price;
    return sum;
  }, 0);

  _perfDataFull = null;
  if (!perfHoldings.length) {
    perfCard.classList.remove('hidden');
    perfMessage('dash.perf.needAmounts', 'var(--muted)');
    return;
  }

  const canvas = document.getElementById('perfChart');
  canvas.style.display = '';
  perfCard.classList.remove('hidden');
  _perfNote = null;
  document.getElementById('perfReturn').textContent = '⏳';

  try {
    const res  = await apiFetch(`${API}/api/portfolio/performance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: perfHoldings, liquidita, unpriced_amount: unpricedAmount }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    if (!data.dates.length) {
      perfMessage('dash.perf.noData', 'var(--muted)');
      return;
    }
    renderPerformanceChart(data, excludedHoldings);
  } catch {
    perfMessage('dash.perf.loadError', 'var(--red)');
  }
}

// Message in place of the performance chart (kept to be re-shown on language change).
function perfMessage(key, color) {
  _perfNote = { key, color };
  document.getElementById('perfReturn').textContent = '';
  document.getElementById('perfSummary').innerHTML =
    `<span style="color:${color};font-size:13px">${I18n.t(key)}</span>`;
  document.getElementById('perfChart').style.display = 'none';
}

function renderPerformanceChart(data, excludedHoldings) {
  _perfNote = null;
  _perfDataFull = data;
  _perfExcluded = excludedHoldings || [];
  _currentPeriodDays = 365;
  document.querySelectorAll('.period-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.days) === 365);
    b.onclick = () => {
      document.querySelectorAll('.period-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      _currentPeriodDays = parseInt(b.dataset.days);
      _renderPerfForPeriod(_currentPeriodDays);
    };
  });
  _renderPerfForPeriod(365);
}

function _renderPerfForPeriod(days) {
  if (!_perfDataFull) return;
  let dates  = _perfDataFull.dates;
  let values = _perfDataFull.values;
  if (days && dates.length > days) {
    dates  = dates.slice(-days);
    values = values.slice(-days);
  }
  const startVal = values.length > 0 ? values[0] : 0;
  const endVal   = values.length > 0 ? values[values.length - 1] : 0;
  const retPct   = startVal > 0 ? (endVal / startVal - 1) * 100 : 0;
  const isPos    = retPct >= 0;
  const color    = isPos ? '#22d3a0' : '#f43f5e';
  const sign     = isPos ? '+' : '';

  const retEl = document.getElementById('perfReturn');
  retEl.textContent = `${sign}${retPct.toFixed(2)}%`;
  retEl.style.color = color;

  const coveredPct = _perfDataFull.covered_pct ?? 100;
  const failedTickers = (_perfDataFull.failed_tickers || []);
  const allExcluded = [
    ..._perfExcluded.map(h => h.ticker || h.name).filter(Boolean),
    ...failedTickers,
  ];
  const coverageNote = coveredPct < 99
    ? `<span style="color:var(--amber);font-size:11px">
        ${I18n.t('dash.perf.coverage', { pct: coveredPct })}
        ${allExcluded.length ? I18n.t('dash.perf.flat', { list: allExcluded.join(', ') }) : ''}
       </span>`
    : `<span style="color:var(--muted);font-size:11px">${I18n.t('dash.perf.source')}</span>`;

  document.getElementById('perfSummary').innerHTML = `
    <span>${I18n.t('dash.perf.start')} <strong style="color:var(--text)">€${fmtAmt(startVal)}</strong></span>
    <span>${I18n.t('dash.perf.current')} <strong style="color:${color}">€${fmtAmt(endVal)}</strong></span>
    ${coverageNote}
  `;

  if (perfChart) perfChart.destroy();
  const ctx = document.getElementById('perfChart').getContext('2d');
  perfChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [{
        data: values,
        borderColor: color,
        backgroundColor: color + '18',
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: ctx => ` €${fmtAmt(ctx.parsed.y)}` },
      }},
      scales: {
        x: { ticks: { maxTicksLimit: 8, color: themeMuted, font: { size: 11 } }, grid: { color: themeGrid } },
        y: { ticks: { color: themeMuted, font: { size: 11 }, callback: v => '€' + fmtAmt(v) },
             grid: { color: themeGrid } },
      },
    },
  });
}

function renderCurrencyRisk(currencyExp, containerId = 'currencyRisk') {
  const container = document.getElementById(containerId);
  if (!container) return;

  const entries = Object.entries(currencyExp).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    container.innerHTML = `<p style="color:var(--muted);font-size:13px;padding:8px 0">${I18n.t('dash.cur.none')}</p>`;
    return;
  }

  const max = entries[0][1];
  container.innerHTML = entries.map(([cur, pct]) => {
    const color = CUR_COLORS[cur] || '#94a3b8';
    const flag = CUR_FLAGS[cur] || '🌍';
    return `
      <div class="cat-bar-row">
        <div class="cat-bar-icon" style="background:${color}22;border:1px solid ${color}44;font-size:17px;line-height:1">${flag}</div>
        <span class="cat-bar-label">${cur}</span>
        <div class="cat-bar-track">
          <div class="cat-bar-fill" style="width:${(pct/max)*100}%;background:${color}"></div>
        </div>
        <span class="cat-bar-pct" style="color:${color}">${pct.toFixed(1)}%</span>
      </div>
    `;
  }).join('');
}

function renderPortfolioSummary(holdings, liqEur, liqPct) {
  const container = document.getElementById('portfolioSummary');
  if (!container || holdings.length === 0) return;

  const totalEur  = holdings.reduce((s, h) => s + (h.amount || 0), 0) + (liqEur || 0);
  const totalPct  = holdings.reduce((s, h) => s + (h.allocation || 0), 0) + (liqPct || 0);
  const hasAmounts = totalEur > 0;

  const rows = holdings.map(h => {
    const color  = CAT_COLORS[h.category] || '#888';
    const pct    = (h.allocation || 0).toFixed(1);
    const amtStr = (h.amount || 0) > 0 ? `€${fmtAmt(h.amount)}` : '—';
    let terBadge = '';
    if (h.ter != null && h.ter > 0) {
      const terColor = h.ter < 0.1 ? '#22d3a0' : h.ter <= 0.2 ? '#f59e0b' : '#f43f5e';
      terBadge = `<span style="display:inline-block;margin-top:3px;font-size:10px;font-weight:600;color:${terColor}">TER ${h.ter.toFixed(2)}%</span>`;
    }
    return `
      <tr>
        <td style="padding:8px 6px;font-size:13px;font-weight:700;color:${color}">${h.ticker}</td>
        <td style="padding:8px 6px;font-size:13px;line-height:1.3">
          ${h.name.length > 38 ? h.name.slice(0, 38) + '…' : h.name}
          ${terBadge ? '<br>' + terBadge : ''}
        </td>
        <td style="padding:8px 6px"><span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${catLabel(h.category)}</span></td>
        <td style="padding:8px 6px;font-size:13px;text-align:right;color:var(--muted)">${pct}%</td>
        <td style="padding:8px 6px;font-size:14px;font-weight:600;text-align:right">${amtStr}</td>
      </tr>`;
  }).join('');

  const liqRow = ((liqEur || 0) > 0 || (liqPct || 0) > 0) ? `
    <tr>
      <td style="padding:8px 6px;font-size:13px;font-weight:700;color:#f59e0b">CASH</td>
      <td style="padding:8px 6px;font-size:13px;color:var(--muted)">${catLabel('Liquidità')}</td>
      <td style="padding:8px 6px"><span class="cat-badge" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b44">${catLabel('Liquidità')}</span></td>
      <td style="padding:8px 6px;font-size:13px;text-align:right;color:var(--muted)">${(liqPct || 0).toFixed(1)}%</td>
      <td style="padding:8px 6px;font-size:14px;font-weight:600;text-align:right">${(liqEur || 0) > 0 ? '€' + fmtAmt(liqEur) : '—'}</td>
    </tr>` : '';

  container.innerHTML = `
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-family:inherit">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:8px 6px;text-align:left;font-size:11px;color:var(--muted);font-weight:600">Ticker</th>
            <th style="padding:8px 6px;text-align:left;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.tbl.instrument')}</th>
            <th style="padding:8px 6px;text-align:left;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.tbl.category')}</th>
            <th style="padding:8px 6px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.sum.weight')}</th>
            <th style="padding:8px 6px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.sum.value')}</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
          ${liqRow}
          <tr style="border-top:2px solid var(--border)">
            <td colspan="3" style="padding:12px 6px;font-size:14px;font-weight:700;letter-spacing:0.03em">${I18n.t('dash.sum.total')}</td>
            <td style="padding:12px 6px;font-size:14px;font-weight:700;text-align:right">${totalPct.toFixed(1)}%</td>
            <td style="padding:12px 6px;font-size:17px;font-weight:700;text-align:right;color:var(--green,#22d3a0)">${hasAmounts ? '€' + fmtAmt(totalEur) : '—'}</td>
          </tr>
        </tbody>
      </table>
    </div>
    ${!hasAmounts ? `<p style="font-size:11px;color:var(--muted);margin-top:10px">${I18n.t('dash.sum.hint')}</p>` : ''}
  `;
}

// ── Init ────────────────────────────────────
renderModeLabels();
updateTotal();
checkSavedPortfolio();

// ════════════════════════════════════════════
// DOCUMENT IMPORT
// ════════════════════════════════════════════

let uploadedDocs = [];      // File objects
let extractedItems = [];    // items from LLM

// DOM refs (new)
const docToggleBtn     = document.getElementById('docToggleBtn');
const docImportBody    = document.getElementById('docImportBody');
const docToggleArrow   = document.getElementById('docToggleArrow');
const dropZone         = document.getElementById('dropZone');
const fileInput        = document.getElementById('fileInput');
const browseBtn        = document.getElementById('browseBtn');
const extractBtn       = document.getElementById('extractBtn');
const extractStatus    = document.getElementById('extractStatus');
const uploadedFilesList = document.getElementById('uploadedFilesList');
const extractModal     = document.getElementById('extractModal');
const extractedItemsList = document.getElementById('extractedItemsList');
const modalCloseBtn    = document.getElementById('modalCloseBtn');
const selectAllBtn     = document.getElementById('selectAllExtracted');
const deselectAllBtn   = document.getElementById('deselectAllExtracted');
const importSelectedBtn = document.getElementById('importSelectedBtn');
const importStatus     = document.getElementById('importStatus');
const saveBtn          = document.getElementById('saveBtn');
const loadBtn          = document.getElementById('loadBtn');
const toastContainer   = document.getElementById('toastContainer');

// ── Toggle upload panel ──────────────────────
docToggleBtn.addEventListener('click', () => {
  const hidden = docImportBody.classList.toggle('hidden');
  docToggleArrow.textContent = hidden ? '▼' : '▲';
});

// ── Drop zone ────────────────────────────────
browseBtn.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('click', (e) => { if (e.target !== browseBtn) fileInput.click(); });

fileInput.addEventListener('change', () => addFiles([...fileInput.files]));

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  addFiles([...e.dataTransfer.files]);
});

function addFiles(newFiles) {
  newFiles.forEach(f => {
    if (!uploadedDocs.find(x => x.name === f.name && x.size === f.size)) {
      uploadedDocs.push(f);
    }
  });
  renderFileChips();
  fileInput.value = '';
}

function renderFileChips() {
  uploadedFilesList.innerHTML = uploadedDocs.map((f, i) => `
    <div class="file-chip">
      📄 ${f.name}
      <span class="file-chip-rm" data-i="${i}" title="Rimuovi" data-i18n-attr="title:dash.doc.remove">×</span>
    </div>
  `).join('');
  I18n.apply(uploadedFilesList);
  uploadedFilesList.querySelectorAll('.file-chip-rm').forEach(el => {
    el.addEventListener('click', () => {
      uploadedDocs.splice(+el.dataset.i, 1);
      renderFileChips();
    });
  });
  extractBtn.style.display = uploadedDocs.length ? 'inline-flex' : 'none';
  extractStatus.textContent = '';
}

// ── Extract ──────────────────────────────────
extractBtn.addEventListener('click', async () => {
  if (!uploadedDocs.length) return;

  extractBtn.disabled = true;
  extractBtn.textContent = I18n.t('dash.doc.extracting');
  extractStatus.textContent = '';

  const form = new FormData();
  uploadedDocs.forEach(f => form.append('files', f));

  try {
    const res = await apiFetch(`${API}/api/extract-from-documents`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || I18n.t('dash.doc.extractError'));
    }
    const data = await res.json();
    extractedItems = data.items || [];
    if (!extractedItems.length) {
      extractStatus.textContent = I18n.t('dash.doc.none');
    } else {
      openExtractModal();
    }
  } catch (e) {
    extractStatus.textContent = '❌ ' + e.message;
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = I18n.t('dash.doc.extract');
  }
});

// ── Extraction modal ─────────────────────────
// Labels carry data-i18n keys, so a language change relabels the open modal
// without losing the ticked boxes and edited prices.
function openExtractModal() {
  extractedItemsList.innerHTML = extractedItems.map((item, i) => {
    const sub = [
      item.isin     ? `ISIN: ${item.isin}`             : '',
      item.ticker   ? `Ticker: ${item.ticker}`          : '',
      item.quantity != null ? `<span data-i18n="dash.ex.qty">Qtà</span>: ${item.quantity}`   : '',
      item.value    != null ? `<span data-i18n="dash.ex.value">Valore</span>: €${fmtAmt(item.value)}` : '',
    ].filter(Boolean).join(' · ');
    const pmcVal = item.purchase_price != null ? item.purchase_price : '';
    const pmcAttr = item.purchase_price != null ? 'placeholder=""'
      : 'placeholder="usa prezzo odierno" data-i18n-attr="placeholder:dash.ex.pmcPh"';
    return `
      <div class="extract-item">
        <input type="checkbox" id="ei${i}" data-i="${i}" checked />
        <div class="extract-item-info">
          <div class="extract-item-name">${item.name || item.isin || item.ticker || `<span data-i18n="dash.ex.item">Strumento</span> ${i + 1}`}</div>
          ${sub ? `<div class="extract-item-sub">${sub}</div>` : ''}
        </div>
        <div class="extract-item-pmc">
          <label style="font-size:11px;color:var(--muted)" data-i18n="dash.ex.pmc">P.acq €</label>
          <input type="number" id="pmc${i}" class="pmc-input" ${pmcAttr} value="${pmcVal}" step="any" min="0" />
        </div>
      </div>
    `;
  }).join('');
  I18n.apply(extractedItemsList);
  importStatus.textContent = '';
  extractModal.classList.remove('hidden');
}

modalCloseBtn.addEventListener('click', () => extractModal.classList.add('hidden'));
extractModal.addEventListener('click', e => { if (e.target === extractModal) extractModal.classList.add('hidden'); });

selectAllBtn.addEventListener('click', () => {
  extractedItemsList.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = true);
});
deselectAllBtn.addEventListener('click', () => {
  extractedItemsList.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = false);
});

// ── Import selected ──────────────────────────
importSelectedBtn.addEventListener('click', async () => {
  const checkedWithIdx = [...extractedItemsList.querySelectorAll('input[type=checkbox]:checked')]
    .map(c => ({ item: extractedItems[+c.dataset.i], idx: +c.dataset.i }));

  if (!checkedWithIdx.length) { importStatus.textContent = I18n.t('dash.ex.selectOne'); return; }

  const hasValues = checkedWithIdx.some(({ item: x }) => x.value != null && x.value > 0);
  if (hasValues && inputMode !== 'amount') {
    inputMode = 'amount';
    renderModeLabels();
  }

  importSelectedBtn.disabled = true;
  let ok = 0, fail = 0;
  for (const { item, idx } of checkedWithIdx) {
    importStatus.textContent = I18n.t('dash.ex.resolving', { q: item.isin || item.ticker || item.name });
    const q = item.isin || item.ticker;
    if (!q) { fail++; continue; }
    try {
      const res = await apiFetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error();
      const d = await res.json();
      const h = { ...d };

      // Purchase price: prefer user-edited input, then PDF value, then current price
      const pmcInput = document.getElementById('pmc' + idx);
      const pmcRaw = pmcInput ? parseFloat(pmcInput.value) : NaN;
      h.purchase_price = !isNaN(pmcRaw) && pmcRaw > 0
        ? pmcRaw
        : (item.purchase_price ?? d.price ?? null);

      if (item.quantity != null) h.quantity = item.quantity;

      if (inputMode === 'amount') {
        h.amount = item.value ?? (item.quantity > 0 && h.purchase_price ? positionValue(h, item.quantity, h.purchase_price) : 0);
        h.allocation = 0;
      } else {
        h.allocation = 0;
        h.amount = null;
      }
      addHolding(h);
      ok++;
    } catch {
      fail++;
    }
  }

  importStatus.textContent = '';
  importSelectedBtn.disabled = false;
  extractModal.classList.add('hidden');
  updateTotal();
  showToast(I18n.t(fail ? 'dash.toast.importedFail' : 'dash.toast.imported', { ok, fail }), ok > 0 ? 'success' : 'error');

  if (ok > 0) {
    docImportBody.classList.add('hidden');
    docToggleArrow.textContent = '▼';
  }
});

// ════════════════════════════════════════════
// SAVE / LOAD PORTFOLIO (DynamoDB)
// ════════════════════════════════════════════

const saveBtnGroup       = document.getElementById('saveBtnGroup');
const portfolioNameInput = document.getElementById('portfolioNameInput');
const portfolioListModal = document.getElementById('portfolioListModal');
const portfolioListClose = document.getElementById('portfolioListClose');
const portfolioListItems = document.getElementById('portfolioListItems');

saveBtn.addEventListener('click', savePortfolio);

async function savePortfolio() {
  const name   = portfolioNameInput.value.trim() || I18n.t('dash.save.defaultName');
  const liqVal = parseFloat(liquiditaInp.value || 0);
  const payload = {
    name,
    holdings:    portfolio,
    liquidita:   liqVal,
    inputMode,
    portfolioTotal,
    pac_entries: pac,
    savedAt:     new Date().toISOString(),
  };
  try {
    const res = await apiFetch(`${API}/api/portfolio/save`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    if (!res.ok) throw new Error();
    showToast(I18n.t('dash.toast.saved', { name }), 'success');
  } catch {
    showToast(I18n.t('dash.toast.saveError'), 'error');
  }
}

// ── Deep analysis hand-off (/analisi reads this snapshot) ──
function openDeepAnalysis(e) {
  if (e) e.preventDefault();
  if (portfolio.length) {
    const snapshot = {
      name:      portfolioNameInput.value.trim() || I18n.t('dash.save.currentName'),
      holdings:  portfolio,
      liquidita: parseFloat(liquiditaInp.value || 0),
      inputMode,
      portfolioTotal,
      savedAt:   new Date().toISOString(),
    };
    try { localStorage.setItem('analysis_portfolio', JSON.stringify(snapshot)); } catch { /* storage full/blocked */ }
  }
  window.location.href = '/analisi';
}
document.getElementById('deepAnalysisBtn').addEventListener('click', openDeepAnalysis);
document.getElementById('navDeepAnalysis').addEventListener('click', openDeepAnalysis);

loadBtn.addEventListener('click', openPortfolioList);
portfolioListClose.addEventListener('click', () => portfolioListModal.classList.add('hidden'));
portfolioListModal.addEventListener('click', e => {
  if (e.target === portfolioListModal) portfolioListModal.classList.add('hidden');
});

// Status lines carry data-i18n keys, so they follow a language change on their own.
const listNote = (key, text, color = 'var(--muted)') =>
  `<p style="color:${color};font-size:13px" data-i18n="${key}">${text}</p>`;
let savedList = null;  // last fetched list, redrawn on language change

async function openPortfolioList() {
  portfolioListModal.classList.remove('hidden');
  savedList = null;
  portfolioListItems.innerHTML = listNote('dash.list.loading', I18n.t('dash.list.loading'));
  try {
    const res   = await apiFetch(`${API}/api/portfolio/list`);
    const items = await res.json();
    if (!items.length) {
      portfolioListItems.innerHTML = listNote('dash.list.empty', I18n.t('dash.list.empty'));
      return;
    }
    savedList = items;
    renderPortfolioList();
  } catch {
    portfolioListItems.innerHTML = listNote('dash.list.loadError', I18n.t('dash.list.loadError'), 'var(--red)');
  }
}

function renderPortfolioList() {
  portfolioListItems.innerHTML = savedList.map(p => {
    const d = new Date(p.savedAt);
    const dateStr = isNaN(d) ? '' : d.toLocaleDateString(I18n.locale, { day:'2-digit', month:'short', year:'numeric' });
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;
                  padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
        <div>
          <div style="font-weight:600;font-size:14px">${p.name}</div>
          <div style="font-size:12px;color:var(--muted)">${dateStr} · ${I18n.t('dash.list.count', { n: p.holdings_count })}</div>
        </div>
        <div style="display:flex;gap:8px">
          <button onclick="loadPortfolio('${p.portfolio_id}')"
            style="background:var(--accent);border:none;border-radius:6px;padding:5px 12px;
                   color:#fff;font-size:12px;cursor:pointer">${I18n.t('dash.list.load')}</button>
          <button onclick="deletePortfolio('${p.portfolio_id}', this)"
            style="background:transparent;border:1px solid var(--red);border-radius:6px;padding:5px 12px;
                   color:var(--red);font-size:12px;cursor:pointer">${I18n.t('dash.list.delete')}</button>
        </div>
      </div>`;
  }).join('');
}

async function loadPortfolio(portfolioId) {
  try {
    const res  = await apiFetch(`${API}/api/portfolio/load/${portfolioId}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    applyLoadedPortfolio(data);
    portfolioListModal.classList.add('hidden');
    showToast(I18n.t('dash.toast.restored', { name: data.name || I18n.t('dash.toast.portfolio') }), 'success');
  } catch {
    showToast(I18n.t('dash.list.loadError'), 'error');
  }
}

async function deletePortfolio(portfolioId, btn) {
  btn.disabled = true;
  try {
    await apiFetch(`${API}/api/portfolio/saved/${portfolioId}`, { method: 'DELETE' });
    savedList = (savedList || []).filter(p => p.portfolio_id !== portfolioId);
    if (savedList.length) {
      renderPortfolioList();
    } else {
      savedList = null;
      portfolioListItems.innerHTML = listNote('dash.list.empty', I18n.t('dash.list.empty'));
    }
  } catch {
    btn.disabled = false;
    showToast(I18n.t('dash.toast.deleteError'), 'error');
  }
}

function applyLoadedPortfolio(data) {
  portfolio = data.holdings || [];
  pac = data.pac_entries || [];
  setPortfolioTotal(0);
  if ((data.inputMode || 'pct') !== inputMode) modeToggleBtn.click();
  liquiditaInp.value = data.liquidita ?? 0;  // after the toggle: it is already in the saved unit
  setPortfolioTotal(parseFloat(data.portfolioTotal) || 0);
  if (data.name && portfolioNameInput) portfolioNameInput.value = data.name;
  renderTable();
  updateTotal();
  renderPac();

  // Show P&L banner if any holding has quantity saved
  const plBanner = document.getElementById('plBanner');
  const plResult = document.getElementById('plResult');
  const hasQty = portfolio.some(h => h.quantity > 0);
  plBanner.style.display = hasQty ? 'block' : 'none';
  plResult.style.display = 'none';
  plResult.innerHTML = '';
}

function renderLoadBtn() {
  document.getElementById('loadBtn').textContent = savedCount
    ? I18n.t('dash.btn.loadCount', { n: savedCount })
    : I18n.t('dash.btn.load');
}

async function checkSavedPortfolio() {
  // On startup, show load button badge if portfolios exist
  renderLoadBtn();
  try {
    const res   = await apiFetch(`${API}/api/portfolio/list`);
    const items = await res.json();
    savedCount = items.length;
    renderLoadBtn();
  } catch { /* silently ignore */ }
}

// ── Toast helper ─────────────────────────────
function showToast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast${type ? ' ' + type : ''}`;
  el.textContent = msg;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ════════════════════════════════════════════
// PERFORMANCE / P&L
// ════════════════════════════════════════════

document.getElementById('valuateBtn').addEventListener('click', fetchPortfolioPerformance);

async function fetchPortfolioPerformance() {
  const btn = document.getElementById('valuateBtn');
  const plResult = document.getElementById('plResult');
  btn.disabled = true;
  btn.textContent = I18n.t('dash.pl.loading');
  plResult.style.display = 'none';
  try {
    const holdings = portfolio.filter(h => h.quantity > 0 && (h.yf_ticker || h.ticker));
    const res = await apiFetch(`${API}/api/portfolio/pl`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    renderPLResult(data);
  } catch {
    showToast(I18n.t('dash.pl.error'), 'error');
  } finally {
    btn.disabled = false;
    // From now on the button refreshes: the key swap keeps it right on language change.
    btn.dataset.i18n = 'dash.pl.refresh';
    btn.textContent = I18n.t('dash.pl.refresh');
  }
}

let lastPL = null;  // last P&L response, redrawn on language change

function renderPLResult(data) {
  lastPL = data;
  const plResult = document.getElementById('plResult');
  const money2 = v => v.toLocaleString(I18n.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtEur = v => v != null ? (v >= 0 ? '+' : '') + money2(v) + ' €' : I18n.t('dash.na');
  const fmtPct = v => v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) + '%' : '';
  const clr = v => v == null ? '' : v >= 0 ? 'var(--green)' : 'var(--red)';

  const rows = data.holdings.map(h => `
    <tr>
      <td style="padding:6px 8px;font-size:13px">${h.name || h.ticker}</td>
      <td style="padding:6px 8px;font-size:12px;color:var(--muted);text-align:right">× ${h.quantity}</td>
      <td style="padding:6px 8px;font-size:12px;color:var(--muted);text-align:right">${h.purchase_price != null ? fmtPrice(h.purchase_price, '') : '—'}</td>
      <td style="padding:6px 8px;font-size:13px;text-align:right">${fmtPrice(h.current_price, '')}</td>
      <td style="padding:6px 8px;font-size:13px;font-weight:600;text-align:right">${money2(h.current_value)} €</td>
      <td style="padding:6px 8px;font-size:13px;font-weight:600;color:${clr(h.pl_eur)};text-align:right">${fmtEur(h.pl_eur)} ${fmtPct(h.pl_pct)}</td>
    </tr>
  `).join('');

  const totalPl = data.total_pl_eur;
  const totalPct = data.total_pl_pct;

  plResult.style.display = 'block';
  plResult.innerHTML = `
    <div style="margin-bottom:10px;display:flex;gap:20px;flex-wrap:wrap">
      <div style="font-size:13px;color:var(--muted)">${I18n.t('dash.perf.current')} <strong style="color:var(--text)">${money2(data.total_value || 0)} €</strong></div>
      ${data.total_cost ? `<div style="font-size:13px;color:var(--muted)">${I18n.t('dash.pl.cost')} <strong style="color:var(--text)">${money2(data.total_cost)} €</strong></div>` : ''}
      ${totalPl != null ? `<div style="font-size:14px;font-weight:700;color:${clr(totalPl)}">P&L: ${fmtEur(totalPl)} ${fmtPct(totalPct)}</div>` : ''}
    </div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-family:inherit">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:6px 8px;text-align:left;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.tbl.instrument')}</th>
            <th style="padding:6px 8px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.pl.qty')}</th>
            <th style="padding:6px 8px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.pl.pmc')}</th>
            <th style="padding:6px 8px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.pl.price')}</th>
            <th style="padding:6px 8px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">${I18n.t('dash.pl.value')}</th>
            <th style="padding:6px 8px;text-align:right;font-size:11px;color:var(--muted);font-weight:600">P&L</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p style="font-size:11px;color:var(--muted);margin-top:8px">${I18n.t('dash.pl.note')}</p>
  `;
}

// ════════════════════════════════════════════
// PAC – PIANO DI ACCUMULO
// ════════════════════════════════════════════

const PAC_FREQ_KEYS = {
  monthly: 'dash.pac.freq.monthly', biweekly: 'dash.pac.freq.biweekly',
  weekly: 'dash.pac.freq.weekly', quarterly: 'dash.pac.freq.quarterly',
};

function pacNextDate(startDate, frequency) {
  const d = new Date(startDate);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  // Advance until next date >= today
  let next = new Date(d);
  while (next < today) {
    if (frequency === 'weekly')     next.setDate(next.getDate() + 7);
    else if (frequency === 'biweekly') next.setDate(next.getDate() + 14);
    else if (frequency === 'monthly')  next.setMonth(next.getMonth() + 1);
    else if (frequency === 'quarterly') next.setMonth(next.getMonth() + 3);
    else break;
  }
  return next.toISOString().split('T')[0];
}

function renderPac() {
  const section = document.getElementById('pacSection');
  const list = document.getElementById('pacList');

  if (pac.length === 0 && portfolio.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = portfolio.length > 0 ? 'block' : 'none';

  if (pac.length === 0) {
    list.innerHTML = `<p style="font-size:13px;color:var(--muted);margin:0">${I18n.t('dash.pac.empty')}</p>`;
    return;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  list.innerHTML = pac.map((e, i) => {
    const next = new Date(e.next_date);
    const daysLeft = Math.round((next - today) / 86400000);
    const dueLabel = daysLeft === 0 ? `<span style="color:var(--green);font-weight:700">${I18n.t('dash.pac.today')}</span>`
      : daysLeft < 0 ? `<span style="color:var(--red)">${I18n.t('dash.pac.overdue', { n: -daysLeft })}</span>`
      : daysLeft <= 7 ? `<span style="color:var(--amber)">${I18n.t('dash.pac.inDays', { n: daysLeft })}</span>`
      : `<span style="color:var(--muted)">${next.toLocaleDateString(I18n.locale, { day:'2-digit', month:'short', year:'numeric' })}</span>`;
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;
                  padding:10px 0;border-bottom:1px solid var(--border);flex-wrap:wrap">
        <div>
          <span style="font-size:14px;font-weight:600">${e.ticker}</span>
          ${e.name ? `<span style="font-size:12px;color:var(--muted)"> · ${e.name}</span>` : ''}
          <div style="font-size:12px;color:var(--muted);margin-top:2px">
            ${I18n.t('dash.pac.perInstalment', { amt: e.amount_per_installment })} · ${labelOf(PAC_FREQ_KEYS, e.frequency)}
          </div>
        </div>
        <div style="text-align:right">
          <div style="font-size:12px;color:var(--muted)">${I18n.t('dash.pac.next')}</div>
          <div style="font-size:13px">${dueLabel}</div>
        </div>
        <button onclick="removePacEntry(${i})"
          style="background:transparent;border:1px solid var(--red);border-radius:6px;padding:4px 10px;
                 color:var(--red);font-size:12px;cursor:pointer">${I18n.t('dash.list.delete')}</button>
      </div>
    `;
  }).join('');
}

function removePacEntry(idx) {
  pac.splice(idx, 1);
  renderPac();
}

// PAC form handlers
const addPacBtn    = document.getElementById('addPacBtn');
const pacForm      = document.getElementById('pacForm');
const pacCancelBtn = document.getElementById('pacCancelBtn');
const pacSaveBtn   = document.getElementById('pacSaveBtn');
const pacFormError = document.getElementById('pacFormError');

// Set default date to today
document.getElementById('pacStartDate').value = new Date().toISOString().split('T')[0];

addPacBtn.addEventListener('click', () => {
  pacForm.style.display = pacForm.style.display === 'none' ? 'block' : 'none';
  pacFormError.style.display = 'none';
});

pacCancelBtn.addEventListener('click', () => {
  pacForm.style.display = 'none';
});

pacSaveBtn.addEventListener('click', () => {
  const ticker    = document.getElementById('pacTicker').value.trim().toUpperCase();
  const name      = document.getElementById('pacName').value.trim();
  const amount    = parseFloat(document.getElementById('pacAmount').value || 0);
  const frequency = document.getElementById('pacFrequency').value;
  const startDate = document.getElementById('pacStartDate').value;

  pacFormError.style.display = 'none';
  if (!ticker) { pacFormError.textContent = I18n.t('dash.pac.errTicker'); pacFormError.style.display = 'block'; return; }
  if (amount <= 0) { pacFormError.textContent = I18n.t('dash.pac.errAmount'); pacFormError.style.display = 'block'; return; }
  if (!startDate) { pacFormError.textContent = I18n.t('dash.pac.errDate'); pacFormError.style.display = 'block'; return; }

  const next_date = pacNextDate(startDate, frequency);
  pac.push({ ticker, name, amount_per_installment: amount, frequency, start_date: startDate, next_date });

  // Reset form
  document.getElementById('pacTicker').value = '';
  document.getElementById('pacName').value = '';
  document.getElementById('pacAmount').value = '100';
  document.getElementById('pacStartDate').value = new Date().toISOString().split('T')[0];
  pacForm.style.display = 'none';
  renderPac();
  showToast(I18n.t('dash.pac.added', { ticker }), 'success');
});

// ════════════════════════════════════════════
// LANGUAGE CHANGE: redraw what JS rendered, from the state already in memory
// ════════════════════════════════════════════

window.addEventListener('langchange', () => {
  renderModeLabels();
  renderLoadBtn();
  renderTable();
  updateTotal();
  renderPac();
  if (lastSearchData && searchResult.className === 'search-result') {
    // Keep what the user already typed in the open search card.
    const ids = ['srValueInput', 'srQtyInput', 'srBuyPriceInput', 'srAllocInput'];
    const typed = ids.map(id => document.getElementById(id)?.value);
    renderSearchResult(lastSearchData);
    ids.forEach((id, i) => { const el = document.getElementById(id); if (el && typed[i] != null) el.value = typed[i]; });
  }
  if (lastDashboard) renderDashboard(...lastDashboard);
  if (_perfDataFull) _renderPerfForPeriod(_currentPeriodDays);
  else if (_perfNote) perfMessage(_perfNote.key, _perfNote.color);
  if (lastPL && document.getElementById('plResult').style.display !== 'none') renderPLResult(lastPL);
  if (savedList && !portfolioListModal.classList.contains('hidden')) renderPortfolioList();
});
