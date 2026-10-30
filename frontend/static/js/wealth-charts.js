/* ═══════════════════════════════════════
   PortfolioLab – Chart.js renderers for /altri-investimenti
   Exposes window.WealthCharts. Colors come from the CSS tokens in analisi.css
   (validated categorical palette, fixed order); context gray for "paid in".
   Labels are read from the dictionary at build time, so a rebuild picks up
   the current language.
═══════════════════════════════════════ */

(function () {
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = {};
  const readTokens = () => Object.assign(C, {
    s: [1, 2, 3, 4, 5, 6, 7, 8].map(i => css(`--series-${i}`)),
    context: css('--context'), grid: css('--grid'), muted: css('--muted'),
    tooltip: css('--tooltip-bg'), border: css('--border'),
  });
  const alpha = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  };
  function themeDefaults() {
    readTokens();
    Chart.defaults.color = C.muted;
    Chart.defaults.borderColor = C.grid;
    Chart.defaults.plugins.tooltip.backgroundColor = C.tooltip;
    Chart.defaults.plugins.tooltip.borderColor = C.border;
  }
  themeDefaults();
  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 4;
  Chart.defaults.elements.bar.borderRadius = 4;

  const { eur } = Wealth;
  const t = k => I18n.t(k);
  const charts = {};
  const builders = {};
  // Theme switch: rebuild with the new tokens (dataset colors are baked in at build time).
  window.addEventListener('themechange', () => {
    themeDefaults();
    Object.values(builders).forEach(b => b());
  });
  function draw(id, build) {
    builders[id] = () => {
      if (charts[id]) charts[id].destroy();
      const el = document.getElementById(id);
      if (!el) { delete builders[id]; return; }
      const config = build();
      config.options = { responsive: true, maintainAspectRatio: false, ...config.options };
      charts[id] = new Chart(el, config);
    };
    builders[id]();
  }

  const lineTooltip = { mode: 'index', intersect: false };
  const yEur = { ticks: { callback: v => eur(v) } };
  const line = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, ...extra });

  // Branch → fixed series slot (color follows the policy type).
  const BRANCH_SLOT = { ramo_i: 0, ramo_iii: 1, multiramo: 2, tcm: 3, other: 4 };
  const branchColor = b => C.s[BRANCH_SLOT[b] ?? 4];

  /** Paid premiums vs surrender value, one pair of bars per policy. */
  function policyBars(id, policies) {
    draw(id, () => ({
      type: 'bar',
      data: {
        labels: policies.map(p => p.name),
        datasets: [
          { label: t('wl.ch.paid'), data: policies.map(p => p.paid_so_far), backgroundColor: C.context },
          { label: t('wl.ch.surrender'), data: policies.map(p => p.current_value), backgroundColor: C.s[0] },
        ],
      },
      options: {
        datasets: { bar: { borderColor: 'transparent', borderWidth: 2, maxBarThickness: 36 } },
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw)}` } } },
        scales: { x: { grid: { display: false } }, y: { ...yEur, beginAtZero: true } },
      },
    }));
  }

  /** One policy to maturity: projected value, premiums paid, guaranteed floor. */
  function policyProjection(id, p) {
    draw(id, () => {
      const fullGuarantee = p.guaranteed && p.guaranteed.every((g, i) => g === p.paid[i]);  // Ramo I
      const ds = [
        line(t('wl.ch.estimated'), p.value, branchColor(p.branch)),
        line(fullGuarantee ? t('wl.ch.paidGuaranteed') : t('wl.ch.paid'), p.paid, C.context,
          { borderWidth: 1.5, ...(fullGuarantee ? { borderDash: [5, 4] } : {}) }),
      ];
      if (p.guaranteed && !fullGuarantee) ds.push(line(t('wl.ch.guaranteed'), p.guaranteed, C.context, { borderDash: [5, 4], borderWidth: 1.5 }));
      return {
        type: 'line',
        data: { labels: p.years, datasets: ds },
        options: {
          interaction: lineTooltip,
          plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw)}` } } },
          scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } }, y: yEur },
        },
      };
    });
  }

  /** Monte Carlo fan for one pension line: 5–95 and 25–75 bands, median, contributions. */
  function pensionFan(id, sim, sc) {
    draw(id, () => {
      const band = (label, data, fill, a) => ({ label, data, borderWidth: 0, pointRadius: 0,
        backgroundColor: alpha(C.s[0], a), fill });
      // Band datasets keep internal ids as labels (legend filter); names are for display.
      const names = { p5: t('wl.ch.p5'), p25: t('wl.ch.p25'), b95: t('wl.ch.p95'), b75: t('wl.ch.p75') };
      return {
        type: 'line',
        data: { labels: sim.years, datasets: [
          band('p5', sc.p5, false, 0),
          band('b95', sc.p95, 0, 0.14),
          band('p25', sc.p25, false, 0),
          band('b75', sc.p75, 2, 0.28),
          line(t('wl.ch.median'), sc.p50, C.s[0]),
          line(t('wl.ch.contributed'), sim.paid, C.context, { borderWidth: 1.5 }),
        ] },
        options: {
          interaction: lineTooltip,
          plugins: {
            legend: { labels: {
              filter: i => !['p5', 'p25'].includes(i.text),
              generateLabels: chart => Chart.defaults.plugins.legend.labels.generateLabels(chart).map(l => ({
                ...l, text: l.text === 'b95' ? t('wl.ch.band95') : l.text === 'b75' ? t('wl.ch.band75') : l.text,
              })),
            } },
            tooltip: { callbacks: { label: c => `${names[c.dataset.label] || c.dataset.label}: ${eur(c.raw)}` } },
          },
          scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } }, y: yEur },
        },
      };
    });
  }

  window.WealthCharts = { branchColor, policyBars, policyProjection, pensionFan };
})();
