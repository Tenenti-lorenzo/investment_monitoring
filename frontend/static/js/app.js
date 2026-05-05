/* ═══════════════════════════════════════
   PortfolioLab – Frontend App Logic
═══════════════════════════════════════ */

const API = '';

// ── Auth helpers ─────────────────────────────
function _authToken() { return localStorage.getItem('auth_token') || ''; }

async function apiFetch(url, opts = {}) {
  opts.headers = {
    ...(opts.headers || {}),
    'Authorization': `Bearer ${_authToken()}`,
  };
  const res = await fetch(url, opts);
  if (res.status === 401) {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_username');
    window.location.href = '/login';
    throw new Error('Sessione scaduta');
  }
  return res;
}

const CAT_COLORS = {
  'ETF Azionario':       '#8b5cf6',
  'ETF Obbligazionario': '#06b6d4',
  'ETF':                 '#8b5cf6',
  'Azioni':              '#3b82f6',
  'Criptovalute':        '#22d3a0',
  'Liquidità':           '#f59e0b',
};
const CAT_ICONS = {
  'ETF Azionario':       '📊',
  'ETF Obbligazionario': '📋',
  'ETF':                 '📊',
  'Azioni':              '👤',
  'Criptovalute':        '₿',
  'Liquidità':           '💰',
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

// ── State ──────────────────────────────────
let portfolio = [];   // { isin, ticker, yf_ticker, name, category, allocation, amount, geography, currency }
let lastSearchData = null;
let allocationChart = null;
let geoChart = null;
let inputMode = 'pct'; // 'pct' | 'amount'
let baseCurrency = 'EUR';

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

// ── Mode toggle ──────────────────────────────
modeToggleBtn.addEventListener('click', () => {
  if (inputMode === 'pct') {
    inputMode = 'amount';
    modeToggleBtn.textContent = '% Inserisci percentuali';
    modeToggleBtn.classList.add('mode-amount-active');
    allocHeader.textContent = `Importo (${baseCurrency})`;
    liquiditaLbl.textContent = `💰 Liquidità (${baseCurrency})`;
  } else {
    inputMode = 'pct';
    modeToggleBtn.textContent = `${baseCurrency} Inserisci importi`;
    modeToggleBtn.classList.remove('mode-amount-active');
    allocHeader.textContent = 'Allocazione %';
    liquiditaLbl.textContent = '💰 Liquidità (investibile)';
  }
  renderTable();
  updateTotal();
});

// ── Search ──────────────────────────────────
searchBtn.addEventListener('click', doSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

async function doSearch() {
  const q = searchInput.value.trim();
  if (!q) return;

  searchResult.className = 'search-result loading';
  searchResult.innerHTML = '<span class="spinner"></span> Ricerca in corso…';

  try {
    const res = await apiFetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Strumento non trovato');
    }
    const data = await res.json();
    lastSearchData = data;
    renderSearchResult(data);
  } catch (e) {
    searchResult.className = 'search-result error';
    searchResult.innerHTML = `❌ ${e.message}`;
  }
}

function renderSearchResult(d) {
  const color = CAT_COLORS[d.category] || '#888';
  const isPct = inputMode === 'pct';
  const mismatchWarn = d.isin_mismatch
    ? `<div class="sr-warn">⚠️ Verifica: l'ISIN potrebbe essere stato risolto in modo errato. Controlla il ticker restituito.</div>`
    : '';

  searchResult.className = 'search-result';
  searchResult.innerHTML = `
    <div class="sr-info">
      <div class="sr-name">${d.name}</div>
      <div class="sr-ticker">${d.ticker}${d.exch ? ' · ' + d.exch : ''}${d.currency ? ' · ' + d.currency : ''}${d.price ? ' · ' + fmtPrice(d.price, d.currency) : ''}${d.ter != null ? ' · <span style="color:var(--amber)">TER ' + d.ter.toFixed(2) + '%</span>' : ''}</div>
      ${d.sector ? `<div class="sr-meta">${d.sector}${d.industry ? ' · ' + d.industry : ''}</div>` : ''}
      ${d.fundFamily ? `<div class="sr-meta">${d.fundFamily}</div>` : ''}
      ${mismatchWarn}
    </div>
    <span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${d.category}</span>
    <div class="sr-alloc-wrap">
      <input type="number" id="srAllocInput" min="0" step="${isPct ? '0.1' : '100'}"
        value="${isPct ? '10' : '1000'}" />
      <span>${isPct ? '%' : baseCurrency}</span>
    </div>
    <button class="btn btn-primary sr-add-btn" id="srAddBtn">+ Aggiungi</button>
  `;
  document.getElementById('srAddBtn').addEventListener('click', () => {
    const val = parseFloat(document.getElementById('srAllocInput').value || 0);
    if (val <= 0) { alert('Inserisci un valore > 0'); return; }
    const h = { ...lastSearchData };
    if (inputMode === 'pct') {
      h.allocation = val;
      h.amount = null;
    } else {
      h.amount = val;
      h.allocation = 0;
    }
    addHolding(h);
    searchResult.className = 'search-result hidden';
    searchInput.value = '';
  });
}

function fmtPrice(p, cur) {
  return (cur || '') + ' ' + parseFloat(p).toLocaleString('it-IT', { maximumFractionDigits: 2 });
}
function fmtAmt(v) {
  return parseFloat(v || 0).toLocaleString('it-IT', { maximumFractionDigits: 0 });
}

// ── Holdings management ──────────────────────
function addHolding(h) {
  const existing = portfolio.find(x => x.ticker === h.ticker);
  if (existing) {
    if (inputMode === 'pct') existing.allocation = h.allocation;
    else existing.amount = h.amount;
    renderTable();
    updateTotal();
    return;
  }
  portfolio.push({ ...h, amount: h.amount ?? null });
  renderTable();
  updateTotal();
}

function renderTable() {
  holdingsTbody.innerHTML = '';
  if (portfolio.length === 0) {
    holdingsTbody.innerHTML = '<tr class="empty-row"><td colspan="4" class="empty-cell">Cerca un ISIN o Ticker per aggiungere al portafoglio</td></tr>';
    return;
  }
  const isPct = inputMode === 'pct';
  portfolio.forEach((h, i) => {
    const color = CAT_COLORS[h.category] || '#888';
    const inputVal = isPct ? (h.allocation || 0).toFixed(1) : (h.amount || 0);
    const calcPct = !isPct
      ? `<span class="holding-calc-pct">${(h.allocation || 0).toFixed(1)}%</span>`
      : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <div class="holding-name">${h.name}</div>
        <div class="holding-ticker">${h.ticker}${h.isin ? ' · ' + h.isin : ''}${h.currency ? ' <span class="cur-tag">' + h.currency + '</span>' : ''}</div>
      </td>
      <td><span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${h.category}</span></td>
      <td>
        <input class="holding-alloc-input" type="number" min="0" step="${isPct ? '0.1' : '100'}"
          value="${inputVal}" data-idx="${i}" />
        <span style="color:var(--muted);font-size:12px"> ${isPct ? '%' : baseCurrency}</span>
        ${calcPct}
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
    totalPctEl.textContent = `Totale: ${baseCurrency} ${fmtAmt(totalAmt)}`;
    totalPctEl.className = 'total-pct total-ok';
  } else {
    const tot = portfolio.reduce((s, h) => s + (parseFloat(h.allocation) || 0), 0) + liqVal;
    totalPctEl.textContent = `Totale: ${tot.toFixed(1)}%`;
    totalPctEl.className = 'total-pct ' + (Math.abs(tot - 100) < 0.5 ? 'total-ok' : 'total-warn');
  }
  analyzeBtn.disabled = portfolio.length === 0;
  const _sbg = document.getElementById('saveBtnGroup');
  if (_sbg) _sbg.style.display = portfolio.length > 0 ? 'inline-flex' : 'none';
}

liquiditaInp.addEventListener('input', updateTotal);

// ── Analyze ─────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
  const liqVal = parseFloat(liquiditaInp.value || 0);
  let liquiditaPct = liqVal;
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
  analyzeBtn.textContent = '⏳ Analisi…';

  try {
    const res = await apiFetch(`${API}/api/portfolio/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error('Errore analisi');
    const data = await res.json();
    renderDashboard(data, body.holdings, liquiditaPct);
    dashboard.classList.remove('hidden');
    dashboard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    fetchPerformance(body.holdings, liqVal);
  } catch (e) {
    alert('Errore: ' + e.message);
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = '📊 Genera Dashboard';
  }
});

// ── Demo ────────────────────────────────────
demoBtn.addEventListener('click', () => {
  inputMode = 'amount';
  modeToggleBtn.textContent = '% Inserisci percentuali';
  modeToggleBtn.classList.add('mode-amount-active');
  allocHeader.textContent = `Importo (${baseCurrency})`;
  liquiditaLbl.textContent = `💰 Liquidità (${baseCurrency})`;
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
  renderTable();
  updateTotal();
  dashboard.classList.add('hidden');
  searchResult.className = 'search-result hidden';
});

// ── Render Dashboard ────────────────────────
function renderDashboard(data, holdings, liq) {
  renderAllocationChart(data.category_pct);
  renderCategoryBars(data.category_pct);
  renderGeoChart(data.geography);
  renderHoldingsList(holdings, liq, data.total);
  renderClassExposure(data.category_pct);
  renderMetriche(data.metrics);
  renderCurrencyRisk(data.currency_exposure || {});
}

function renderAllocationChart(catPct) {
  const cats = Object.entries(catPct).filter(([, v]) => v > 0);
  const labels = cats.map(([k]) => k);
  const values = cats.map(([, v]) => v);
  const colors = labels.map(l => CAT_COLORS[l] || '#888');

  if (allocationChart) allocationChart.destroy();
  const ctx = document.getElementById('allocationChart').getContext('2d');
  allocationChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#161929', borderWidth: 3 }] },
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
          <span class="cat-bar-label">${cat}</span>
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
  const labels = entries.map(([k]) => k);
  const values = entries.map(([, v]) => v);
  const colors = labels.map(l => GEO_COLORS[l] || '#94a3b8');

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
        y: { grid: { display: false }, ticks: { color: '#7880a0', font: { size: 11 } } },
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
    return `
      <div class="hl-row">
        <div class="hl-badge" style="background:${color}22;color:${color};border:1px solid ${color}44">${h.ticker.slice(0,4)}</div>
        <div class="hl-info">
          <div class="hl-name">${h.name}</div>
          <div class="hl-ticker">${h.ticker}${h.currency ? ' · <span class="cur-tag">' + h.currency + '</span>' : ''}</div>
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
        <div class="hl-info"><div class="hl-name">Liquidità</div><div class="hl-ticker">Cash · EUR</div></div>
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
        <span class="ceb-name">${cat}</span>
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
  const terVal   = m.ter_medio != null ? `${m.ter_medio.toFixed(2)}%/anno` : 'N/D';
  const terColor = m.ter_medio != null ? 'var(--amber)' : 'var(--muted)';
  const terBox   = `
    <div class="metrica-box">
      <div class="metrica-icon">💸</div>
      <div class="metrica-label">TER Medio ponderato</div>
      <div class="metrica-val" style="color:${terColor}">${terVal}</div>
    </div>`;
  document.getElementById('metriche').innerHTML = `
    <div class="metrica-box">
      <div class="metrica-icon">📈</div>
      <div class="metrica-label">Rendimento atteso (annuo)</div>
      <div class="metrica-val" style="color:var(--green)">${m.expected_return}</div>
    </div>
    <div class="metrica-box">
      <div class="metrica-icon">🛡️</div>
      <div class="metrica-label">Volatilità attesa (annua)</div>
      <div class="metrica-val" style="color:var(--amber)">${m.volatility}</div>
    </div>
    <div class="metrica-box">
      <div class="metrica-icon">📊</div>
      <div class="metrica-label">Sharpe Ratio atteso</div>
      <div class="metrica-val" style="color:var(--blue)">${m.sharpe}</div>
    </div>
    ${terBox}
    <div class="profilo-box">
      <div class="profilo-emoji">${profiloEmoji[m.aggressiveness] || '⚪'}</div>
      <div class="profilo-label" style="color:var(--amber)">Profilo: ${m.aggressiveness}</div>
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

  if (!perfHoldings.length) {
    perfCard.classList.remove('hidden');
    document.getElementById('perfReturn').textContent = '';
    document.getElementById('perfSummary').innerHTML =
      '<span style="color:var(--muted);font-size:13px">Aggiungi importi EUR (o quantità × prezzo) alle posizioni per vedere l\'andamento storico.</span>';
    const canvas = document.getElementById('perfChart');
    canvas.style.display = 'none';
    return;
  }

  const canvas = document.getElementById('perfChart');
  canvas.style.display = '';
  perfCard.classList.remove('hidden');
  document.getElementById('perfReturn').textContent = '⏳';

  try {
    const res  = await apiFetch(`${API}/api/portfolio/performance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: perfHoldings, liquidita }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    if (!data.dates.length) {
      document.getElementById('perfReturn').textContent = '';
      document.getElementById('perfSummary').innerHTML =
        '<span style="color:var(--muted);font-size:13px">Nessun dato storico disponibile per questi strumenti.</span>';
      canvas.style.display = 'none';
      return;
    }
    renderPerformanceChart(data);
  } catch {
    document.getElementById('perfReturn').textContent = '';
    document.getElementById('perfSummary').innerHTML =
      '<span style="color:var(--red);font-size:13px">Errore nel caricamento dei dati storici.</span>';
    canvas.style.display = 'none';
  }
}

function renderPerformanceChart(data) {
  const isPos   = data.return_pct >= 0;
  const color   = isPos ? '#22d3a0' : '#f43f5e';
  const sign    = isPos ? '+' : '';
  const retEl   = document.getElementById('perfReturn');
  retEl.textContent = `${sign}${data.return_pct.toFixed(2)}%`;
  retEl.style.color = color;

  document.getElementById('perfSummary').innerHTML = `
    <span>Valore iniziale: <strong style="color:var(--text)">€${fmtAmt(data.initial_value)}</strong></span>
    <span>Valore attuale: <strong style="color:${color}">€${fmtAmt(data.current_value)}</strong></span>
    <span style="color:var(--muted);font-size:11px">Basato su prezzi Yahoo Finance — ultimi 12 mesi</span>
  `;

  if (perfChart) perfChart.destroy();
  const ctx = document.getElementById('perfChart').getContext('2d');
  perfChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.dates,
      datasets: [{
        data: data.values,
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
        x: { ticks: { maxTicksLimit: 8, color: '#7880a0', font: { size: 11 } }, grid: { color: '#1e2238' } },
        y: { ticks: { color: '#7880a0', font: { size: 11 },
               callback: v => '€' + fmtAmt(v) },
             grid: { color: '#1e2238' } },
      },
    },
  });
}

function renderCurrencyRisk(currencyExp) {
  const container = document.getElementById('currencyRisk');
  if (!container) return;

  const entries = Object.entries(currencyExp).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    container.innerHTML = '<p style="color:var(--muted);font-size:13px;padding:8px 0">Nessun dato valutario disponibile</p>';
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

// ── Init ────────────────────────────────────
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
      <span class="file-chip-rm" data-i="${i}" title="Rimuovi">×</span>
    </div>
  `).join('');
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
  extractBtn.textContent = '⏳ Analisi in corso…';
  extractStatus.textContent = '';

  const form = new FormData();
  uploadedDocs.forEach(f => form.append('files', f));

  try {
    const res = await apiFetch(`${API}/api/extract-from-documents`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Errore estrazione');
    }
    const data = await res.json();
    extractedItems = data.items || [];
    if (!extractedItems.length) {
      extractStatus.textContent = 'Nessuno strumento trovato nel documento.';
    } else {
      openExtractModal();
    }
  } catch (e) {
    extractStatus.textContent = '❌ ' + e.message;
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = '🤖 Estrai con AI';
  }
});

// ── Extraction modal ─────────────────────────
function openExtractModal() {
  extractedItemsList.innerHTML = extractedItems.map((item, i) => {
    const sub = [
      item.isin           ? `ISIN: ${item.isin}`                                    : '',
      item.ticker         ? `Ticker: ${item.ticker}`                                : '',
      item.quantity       != null ? `Qtà: ${item.quantity}`                         : '',
      item.purchase_price != null ? `P.acq: €${fmtAmt(item.purchase_price)}`       : '',
      item.value          != null ? `Valore: €${fmtAmt(item.value)}`                : '',
      item.purchase_date  ? `Data acq: ${item.purchase_date}`                       : '',
    ].filter(Boolean).join(' · ');
    return `
      <div class="extract-item">
        <input type="checkbox" id="ei${i}" data-i="${i}" checked />
        <div class="extract-item-info">
          <div class="extract-item-name">${item.name || item.isin || item.ticker || 'Strumento ' + (i+1)}</div>
          ${sub ? `<div class="extract-item-sub">${sub}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
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
  const checked = [...extractedItemsList.querySelectorAll('input[type=checkbox]:checked')]
    .map(c => extractedItems[+c.dataset.i]);

  if (!checked.length) { importStatus.textContent = 'Seleziona almeno uno strumento.'; return; }

  const hasValues = checked.some(x => x.value != null && x.value > 0);
  if (hasValues && inputMode !== 'amount') {
    inputMode = 'amount';
    modeToggleBtn.textContent = '% Inserisci percentuali';
    modeToggleBtn.classList.add('mode-amount-active');
    allocHeader.textContent = `Importo (${baseCurrency})`;
    liquiditaLbl.textContent = `💰 Liquidità (${baseCurrency})`;
  }

  importSelectedBtn.disabled = true;
  let ok = 0, fail = 0;
  for (const item of checked) {
    importStatus.textContent = `Risolvo ${item.isin || item.ticker || item.name}…`;
    const q = item.isin || item.ticker;
    if (!q) { fail++; continue; }
    try {
      const res = await apiFetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error();
      const d = await res.json();
      const h = { ...d };
      if (inputMode === 'amount') {
        h.amount = item.value ?? item.quantity ?? 0;
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
  showToast(`Importati ${ok} strumenti${fail ? `, ${fail} non trovati` : ''}.`, ok > 0 ? 'success' : 'error');

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
  const name   = portfolioNameInput.value.trim() || 'Il mio portafoglio';
  const liqVal = parseFloat(liquiditaInp.value || 0);
  const payload = {
    name,
    holdings:  portfolio,
    liquidita: liqVal,
    inputMode,
    savedAt:   new Date().toISOString(),
  };
  try {
    const res = await apiFetch(`${API}/api/portfolio/save`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    if (!res.ok) throw new Error();
    showToast(`"${name}" salvato.`, 'success');
  } catch {
    showToast('Errore nel salvataggio.', 'error');
  }
}

loadBtn.addEventListener('click', openPortfolioList);
portfolioListClose.addEventListener('click', () => portfolioListModal.classList.add('hidden'));
portfolioListModal.addEventListener('click', e => {
  if (e.target === portfolioListModal) portfolioListModal.classList.add('hidden');
});

async function openPortfolioList() {
  portfolioListModal.classList.remove('hidden');
  portfolioListItems.innerHTML = '<p style="color:var(--muted);font-size:13px">Caricamento…</p>';
  try {
    const res   = await apiFetch(`${API}/api/portfolio/list`);
    const items = await res.json();
    if (!items.length) {
      portfolioListItems.innerHTML = '<p style="color:var(--muted);font-size:13px">Nessun portafoglio salvato.</p>';
      return;
    }
    portfolioListItems.innerHTML = items.map(p => {
      const d = new Date(p.savedAt);
      const dateStr = isNaN(d) ? '' : d.toLocaleDateString('it-IT', { day:'2-digit', month:'short', year:'numeric' });
      return `
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
          <div>
            <div style="font-weight:600;font-size:14px">${p.name}</div>
            <div style="font-size:12px;color:var(--muted)">${dateStr} · ${p.holdings_count} strumenti</div>
          </div>
          <div style="display:flex;gap:8px">
            <button onclick="loadPortfolio('${p.portfolio_id}')"
              style="background:var(--accent);border:none;border-radius:6px;padding:5px 12px;
                     color:#fff;font-size:12px;cursor:pointer">Carica</button>
            <button onclick="deletePortfolio('${p.portfolio_id}', this)"
              style="background:transparent;border:1px solid var(--red);border-radius:6px;padding:5px 12px;
                     color:var(--red);font-size:12px;cursor:pointer">Elimina</button>
          </div>
        </div>`;
    }).join('');
  } catch {
    portfolioListItems.innerHTML = '<p style="color:var(--red);font-size:13px">Errore nel caricamento.</p>';
  }
}

async function loadPortfolio(portfolioId) {
  try {
    const res  = await apiFetch(`${API}/api/portfolio/load/${portfolioId}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    applyLoadedPortfolio(data);
    portfolioListModal.classList.add('hidden');
    showToast(`"${data.name || 'Portafoglio'}" ripristinato.`, 'success');
  } catch {
    showToast('Errore nel caricamento.', 'error');
  }
}

async function deletePortfolio(portfolioId, btn) {
  btn.disabled = true;
  try {
    await apiFetch(`${API}/api/portfolio/saved/${portfolioId}`, { method: 'DELETE' });
    btn.closest('div[style]').remove();
    if (!portfolioListItems.children.length) {
      portfolioListItems.innerHTML = '<p style="color:var(--muted);font-size:13px">Nessun portafoglio salvato.</p>';
    }
  } catch {
    btn.disabled = false;
    showToast('Errore nella eliminazione.', 'error');
  }
}

function applyLoadedPortfolio(data) {
  portfolio = data.holdings || [];
  liquiditaInp.value = data.liquidita ?? 0;
  if ((data.inputMode || 'pct') !== inputMode) modeToggleBtn.click();
  if (data.name && portfolioNameInput) portfolioNameInput.value = data.name;
  renderTable();
  updateTotal();
}

async function checkSavedPortfolio() {
  // On startup, show load button badge if portfolios exist
  try {
    const res   = await apiFetch(`${API}/api/portfolio/list`);
    const items = await res.json();
    if (items.length) loadBtn.textContent = `📂 Carica salvato (${items.length})`;
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
