/* ═══════════════════════════════════════
   PortfolioLab – shared by /altri-investimenti and /patrimonio
   Category labels, fixed category → color slot (color follows the entity,
   never its rank) and number formatting.
═══════════════════════════════════════ */
window.Wealth = (function () {
  const CATEGORIES = {
    portfolio:      { label: 'Portafogli di mercato', icon: '📈', slot: 1 },
    life_insurance: { label: 'Polizze vita',          icon: '🛡️', slot: 3 },
    pension_fund:   { label: 'Fondi pensione',        icon: '🏖️', slot: 7 },
    real_estate:    { label: 'Immobili',              icon: '🏠', slot: 4 },
    private:        { label: 'Private markets',       icon: '🔒', slot: 5 },
    other:          { label: 'Altro',                 icon: '📦', slot: 2 },
  };
  const BRANCHES = {
    ramo_i: 'Ramo I', ramo_iii: 'Ramo III', multiramo: 'Multiramo', tcm: 'TCM', other: 'Altro',
  };

  const color = cat => `var(--series-${CATEGORIES[cat]?.slot ?? 8})`;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf0 = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0, useGrouping: 'always' });
  const eur = v => (v == null ? '—' : `${v < 0 ? '−' : ''}€ ${nf0.format(Math.abs(v))}`);
  const signed = v => (v == null ? '—'
    : `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${v > 0 ? '+' : ''}${eur(v)}</span>`);
  const pct = v => `${v.toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`;
  const fmtDate = s => (s ? new Date(s).toLocaleDateString('it-IT', { month: 'short', year: 'numeric' }) : '—');

  function showUsername() {
    try {
      const u = localStorage.getItem('auth_username');
      if (u) document.getElementById('navUsername').textContent = '👤 ' + u;
    } catch { /* ignore */ }
  }

  async function postSummary(portfolioIds) {
    const res = await Session.apiFetch('/api/wealth/summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ portfolio_ids: portfolioIds }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  }

  return { CATEGORIES, BRANCHES, color, esc, eur, signed, pct, fmtDate, showUsername, postSummary };
})();
