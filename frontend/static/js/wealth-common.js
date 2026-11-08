/* ═══════════════════════════════════════
   PortfolioLab – shared by /altri-investimenti and /patrimonio
   Category labels, fixed category → color slot (color follows the entity,
   never its rank) and number formatting. Labels and number/date formats
   follow the interface language (read at call time, so they are current
   after 'langchange').
═══════════════════════════════════════ */
window.Wealth = (function () {
  const t = (k, v) => I18n.t(k, v);
  // Keys are the backend's `kind` values; only the label is translated.
  const CATEGORIES = {
    portfolio:      { icon: '📈', slot: 1, get label() { return t('wl.cat.portfolio'); } },
    life_insurance: { icon: '🛡️', slot: 3, get label() { return t('wl.cat.life_insurance'); } },
    pension_fund:   { icon: '🏖️', slot: 7, get label() { return t('wl.cat.pension_fund'); } },
    real_estate:    { icon: '🏠', slot: 4, get label() { return t('wl.cat.real_estate'); } },
    private:        { icon: '🔒', slot: 5, get label() { return t('wl.cat.private'); } },
    other:          { icon: '📦', slot: 2, get label() { return t('wl.cat.other'); } },
  };
  const BRANCHES = {
    get ramo_i() { return t('wl.branch.ramo_i'); },
    get ramo_iii() { return t('wl.branch.ramo_iii'); },
    get multiramo() { return t('wl.branch.multiramo'); },
    get tcm() { return t('wl.branch.tcm'); },
    get other() { return t('wl.branch.other'); },
  };

  const color = cat => `var(--series-${CATEGORIES[cat]?.slot ?? 8})`;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // Integer formatter, rebuilt when the language (locale) changes.
  let nf0 = null, nf0Locale = null;
  const int = v => {
    if (nf0Locale !== I18n.locale) {
      nf0Locale = I18n.locale;
      nf0 = new Intl.NumberFormat(nf0Locale, { maximumFractionDigits: 0, useGrouping: 'always' });
    }
    return nf0.format(v);
  };
  const eur = v => (v == null ? '—' : `${v < 0 ? '−' : ''}€ ${int(Math.abs(v))}`);
  const signed = v => (v == null ? '—'
    : `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${v > 0 ? '+' : ''}${eur(v)}</span>`);
  const num = (v, digits = 1) => v.toLocaleString(I18n.locale, { maximumFractionDigits: digits });
  const pct = v => `${num(v)}%`;
  const fmtDate = s => (s ? new Date(s).toLocaleDateString(I18n.locale, { month: 'short', year: 'numeric' }) : '—');

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

  return { CATEGORIES, BRANCHES, color, esc, eur, signed, num, pct, fmtDate, showUsername, postSummary };
})();
