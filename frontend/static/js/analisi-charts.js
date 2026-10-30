/* ═══════════════════════════════════════
   PortfolioLab – Analisi approfondita: Chart.js renderers
   Exposes window.AnCharts. Colors come from the CSS tokens in analisi.css
   (validated dark categorical palette); status colors only for gain/loss.
   Texts come from static/i18n/analisi*.js; number formats follow I18n.locale.
═══════════════════════════════════════ */

(function () {
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = {};
  const readTokens = () => Object.assign(C, {
    s: [1, 2, 3, 4, 5, 6, 7, 8].map(i => css(`--series-${i}`)),
    good: css('--good'), critical: css('--critical'), context: css('--context'),
    grid: css('--grid'), muted: css('--muted'), surface: css('--card'),
    tooltip: css('--tooltip-bg'), border: css('--border'),
  });
  readTokens();
  const alpha = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  };

  // Fixed category → slot mapping: color follows the entity, never its rank.
  const CAT_SLOT = {
    'ETF Azionario': 0, 'Azioni': 1, 'ETF Obbligazionario': 2, 'Obbligazioni': 3,
    'Criptovalute': 4, 'Liquidità': 5, 'ETF Bilanciato': 6, 'ETF': 6,
  };
  const catColor = c => C.s[CAT_SLOT[c] ?? 7];

  const t = (k, v) => I18n.t(k, v);
  // Italian values sent by the backend (categories, regions, sectors, …) stay
  // identifiers; only their displayed label is translated. Unknown → as is.
  const LABEL_KEYS = {
    'ETF Azionario': 'an.val.etfEquity', 'ETF Obbligazionario': 'an.val.etfBond', 'ETF Bilanciato': 'an.val.etfBalanced',
    'Azioni': 'an.val.stocks', 'Obbligazioni': 'an.val.bonds', 'Obbligazione': 'an.val.bond',
    'Criptovalute': 'an.val.crypto', 'Cripto': 'an.val.cryptoShort', 'Liquidità': 'an.val.cash', 'Altro': 'an.val.other',
    'Nord America': 'an.val.northAmerica', 'Europa': 'an.val.europe', 'Asia-Pacifico': 'an.val.asiaPacific',
    'Mercati Emergenti': 'an.val.emerging', 'Europa Emergente': 'an.val.emergingEurope', 'Latam': 'an.val.latam',
    'Africa/ME': 'an.val.africaMe', 'Globale': 'an.val.global', 'Italia': 'an.val.italy', 'Altre': 'an.val.others',
    'Altre regioni': 'an.val.otherRegions', 'N/D': 'an.val.na',
    'Tecnologia': 'an.val.tech', 'Finanza': 'an.val.financials', 'Salute': 'an.val.health', 'Industria': 'an.val.industrials',
    'Beni voluttuari': 'an.val.consumerCyc', 'Comunicazioni': 'an.val.communication',
    'Beni di prima necessità': 'an.val.consumerDef', 'Energia': 'an.val.energy', 'Materiali': 'an.val.materials',
    'Utility': 'an.val.utilities', 'Immobiliare': 'an.val.realEstate',
    'BELOW B': 'an.val.belowB', 'OTHER': 'an.val.ratingOther',
    'Il tuo portafoglio': 'an.val.yourPortfolio', '100% azionario': 'an.val.allEquity',
    'Le posizioni sottostanti degli ETF includono solo le prime 10 partecipazioni pubblicate da Yahoo Finance: l\'overlap è un limite inferiore.': 'an.val.coverageNote',
  };
  const label = v => (LABEL_KEYS[v] ? t(LABEL_KEYS[v]) : v);

  let nf0, nf2, eurFmt, fixed;
  // Built for the current language and rebuilt on 'langchange'.
  function buildFormats() {
    const loc = I18n.locale;
    nf0 = new Intl.NumberFormat(loc, { maximumFractionDigits: 0, useGrouping: 'always' });
    nf2 = new Intl.NumberFormat(loc, { maximumFractionDigits: 2 });
    // Italian keeps "€ 1.234"; other languages use their own currency pattern.
    eurFmt = I18n.lang === 'it' ? null
      : new Intl.NumberFormat(loc, { style: 'currency', currency: 'EUR', minimumFractionDigits: 0, maximumFractionDigits: 0, useGrouping: 'always' });
    fixed = {};
  }
  buildFormats();
  const n2 = v => nf2.format(v);
  const fx = (v, d) => (fixed[d] ||= new Intl.NumberFormat(I18n.locale, { minimumFractionDigits: d, maximumFractionDigits: d })).format(v);
  const eur = v => `${v < 0 ? '−' : ''}${eurFmt ? eurFmt.format(Math.abs(v)) : `€ ${nf0.format(Math.abs(v))}`}`;
  const sgn = v => (v > 0 ? '+' : '');
  const pct = (v, d = 1) => `${sgn(v)}${fx(v, d).replace('-', '−')}%`;
  // Line dataset: legend swatch filled with the series color (Chart.js default is a gray box).
  const line = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, ...extra });

  function themeDefaults() {
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

  const charts = {};
  // Theme switch: re-read the tokens and repaint the charts already on screen.
  window.addEventListener('themechange', () => {
    readTokens();
    themeDefaults();
    Object.values(charts).forEach(c => c.update('none'));
  });
  // Runs before analisi.js's listener (script order), which then redraws the charts.
  window.addEventListener('langchange', buildFormats);
  function draw(id, config) {
    if (charts[id]) charts[id].destroy();
    const el = document.getElementById(id);
    if (!el) return null;
    config.options = { responsive: true, maintainAspectRatio: false, ...config.options };
    charts[id] = new Chart(el, config);
    return charts[id];
  }

  const timeX = { ticks: { maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } };
  const lineTooltip = { mode: 'index', intersect: false };

  /** Vertical/horizontal reference hairlines: [{axis:'x'|'y', value, color}] */
  const refLines = lines => ({
    id: 'refLines',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales } = chart;
      ctx.save();
      lines.forEach(l => {
        const sc = l.axis === 'x' ? scales.x : scales.y;
        const p = sc.getPixelForValue(l.value);
        ctx.strokeStyle = l.color || C.muted;
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (l.axis === 'x') { ctx.moveTo(p, a.top); ctx.lineTo(p, a.bottom); }
        else { ctx.moveTo(a.left, p); ctx.lineTo(a.right, p); }
        ctx.stroke();
      });
      ctx.restore();
    },
  });

  // ── 1. Value vs invested ──────────────────────
  function value(curve) {
    draw('chValue', {
      type: 'line',
      data: {
        labels: curve.dates,
        datasets: [
          line(t('an.ch.market'), curve.value, C.s[0],
            { fill: { target: 1, above: alpha(C.good, 0.14), below: alpha(C.critical, 0.16) } }),
          line(t('an.kpi.invested'), curve.invested, C.context, { stepped: true }),
        ],
      },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw)}` } } },
        scales: { x: timeX, y: { ticks: { callback: v => eur(v) } } },
      },
    });
  }

  // ── 2. TWR vs benchmark ───────────────────────
  function twr(curve, benchName) {
    const ds = [line(t('an.ch.twr'), curve.twr_index, C.s[0])];
    if (curve.benchmark_index.some(v => v != null)) {
      ds.push(line(benchName || t('an.th.benchmark'), curve.benchmark_index, C.context, { borderWidth: 1.5 }));
    }
    draw('chTwr', {
      type: 'line',
      data: { labels: curve.dates, datasets: ds },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${n2(c.raw)}` } } },
        scales: { x: timeX },
      },
      plugins: [refLines([{ axis: 'y', value: 100, color: C.context }])],
    });
  }

  // ── 3. Drawdown ───────────────────────────────
  function drawdownChart(curve) {
    draw('chDrawdown', {
      type: 'line',
      data: { labels: curve.dates, datasets: [{ label: t('an.ch.drawdown'), data: curve.drawdown,
        borderColor: C.critical, borderWidth: 1.5, fill: { target: 'origin', below: alpha(C.critical, 0.18) } }] },
      options: {
        interaction: lineTooltip,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${pct(c.raw)}` } } },
        scales: { x: timeX, y: { max: 0, ticks: { callback: v => `${v}%` } } },
      },
    });
  }

  // ── 4. P&L by asset class ─────────────────────
  function classPL(classes) {
    const rows = classes.filter(c => c.category !== 'Liquidità');
    draw('chClassPL', {
      type: 'bar',
      data: { labels: rows.map(c => label(c.category)), datasets: [{ label: 'P&L €', data: rows.map(c => c.pl_eur),
        backgroundColor: rows.map(c => (c.pl_eur >= 0 ? C.good : C.critical)), barPercentage: 0.6 }] },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: c => `${sgn(c.raw)}${eur(c.raw)} (${rows[c.dataIndex].pl_pct == null ? '—' : pct(rows[c.dataIndex].pl_pct)})`,
        } } },
        scales: { x: { ticks: { callback: v => eur(v) } }, y: { grid: { display: false } } },
      },
      plugins: [refLines([{ axis: 'x', value: 0, color: C.muted }])],
    });
  }

  // ── 5. Waterfall: invested → drivers → current value ──
  function waterfallSteps(summary, holdings) {
    const byClass = {};
    let fxSum = 0;
    holdings.forEach(h => {
      byClass[h.category] = (byClass[h.category] || 0) + h.price_effect;
      fxSum += h.fx_effect;
    });
    let drivers = Object.entries(byClass).map(([k, v]) => ({ label: label(k), v }));
    if (Math.abs(fxSum) >= 0.5) drivers.push({ label: t('an.th.fxEffect'), v: fxSum });
    drivers.sort((a, b) => b.v - a.v);
    if (drivers.length > 7) {  // keep 6 largest by size, fold the rest into "Altro"
      const bySize = [...drivers].sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
      const keep = new Set(bySize.slice(0, 6));
      const other = drivers.filter(d => !keep.has(d)).reduce((s, d) => s + d.v, 0);
      drivers = drivers.filter(d => keep.has(d)).concat([{ label: label('Altro'), v: other }]);
    }
    return drivers;
  }

  function waterfall(summary, holdings) {
    const drivers = waterfallSteps(summary, holdings);
    const labels = [t('an.kpi.invested')], data = [[0, summary.invested]], colors = [C.context];
    let cum = summary.invested;
    drivers.forEach(d => {
      labels.push(d.label); data.push([cum, cum + d.v]); cum += d.v;
      colors.push(d.v >= 0 ? C.good : C.critical);
    });
    labels.push(t('an.kpi.value')); data.push([0, summary.current_value]); colors.push(C.s[0]);
    const lows = data.slice(1, -1).flat();
    const minCum = Math.min(summary.invested, summary.current_value, ...lows);
    draw('chWaterfall', {
      type: 'bar',
      data: { labels, datasets: [{ label: t('an.ch.bridge'), data, backgroundColor: colors, barPercentage: 0.7 }] },
      options: {
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => {
          const [a, b] = c.raw; const i = c.dataIndex;
          if (i === 0 || i === labels.length - 1) return eur(b);
          const pp = summary.invested ? (b - a) / summary.invested * 100 : 0;
          return `${sgn(b - a)}${eur(b - a)} (${t('an.unit.pp', { v: pct(pp, 2) })})`;
        } } } },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 30 } },
          // Bridge axis: starts near the lowest step so small drivers stay visible.
          y: { min: Math.max(0, Math.floor(minCum * 0.85 / 1000) * 1000), ticks: { callback: v => eur(v) } },
        },
      },
    });
    return drivers;
  }

  // ── 6. Allocation over time (stacked area) ────
  function allocTime(aot) {
    const series = [...aot.series].sort((a, b) => (CAT_SLOT[a.name] ?? 7) - (CAT_SLOT[b.name] ?? 7));
    draw('chAllocTime', {
      type: 'line',
      data: { labels: aot.dates, datasets: series.map((s, i) => ({
        label: label(s.name), data: s.values, borderColor: C.surface, borderWidth: 1,
        backgroundColor: catColor(s.name), fill: i === 0 ? 'origin' : '-1',
      })) },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${n2(c.raw ?? 0)}%` } } },
        scales: { x: timeX, y: { stacked: true, min: 0, max: 100, ticks: { callback: v => `${v}%` } } },
      },
    });
  }

  function drift(classes) {
    draw('chDrift', {
      type: 'bar',
      data: { labels: classes.map(c => label(c.category)), datasets: [{ label: t('an.ch.drift'),
        data: classes.map(c => c.drift_pp),
        backgroundColor: classes.map(c => (c.drift_pp >= 0 ? C.s[0] : C.s[1])), barPercentage: 0.6 }] },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => {
          const r = classes[c.dataIndex];
          return t('an.ch.driftTip', { v: pct(r.drift_pp), target: n2(r.weight_target_pct), now: n2(r.weight_now_pct) });
        } } } },
        scales: { x: { suggestedMin: -6, suggestedMax: 6, ticks: { callback: v => `${v}` } }, y: { grid: { display: false } } },
      },
      plugins: [refLines([
        { axis: 'x', value: 0, color: C.muted },
        { axis: 'x', value: 5, color: C.context }, { axis: 'x', value: -5, color: C.context },
      ])],
    });
  }

  // ── 7. Rolling correlation ────────────────────
  function rollingCorr(corr) {
    draw('chRollCorr', {
      type: 'line',
      data: { labels: corr.rolling_dates, datasets: [line(t('an.ch.rollCorr', { n: corr.window_days }), corr.rolling_avg, C.s[0])] },
      options: {
        interaction: lineTooltip,
        plugins: { legend: { display: false } },
        scales: { x: timeX, y: { min: -1, max: 1 } },
      },
      plugins: [refLines([{ axis: 'y', value: 0.7, color: C.critical }, { axis: 'y', value: 0, color: C.context }])],
    });
  }

  // ── 8. Efficient frontier ─────────────────────
  function frontier(f) {
    const xy = p => ({ x: p.vol, y: p.ret });
    draw('chFrontier', {
      type: 'scatter',
      data: { datasets: [
        // `order`: lower is drawn on top — markers above the frontier above the cloud.
        { label: t('an.ch.cloud'), data: f.cloud.map(xy), backgroundColor: alpha(C.context, 0.45), pointRadius: 2, pointHoverRadius: 3, order: 5 },
        line(t('an.ch.frontier'), f.frontier.map(xy), C.s[0], { showLine: true, pointRadius: 0, order: 4 }),
        { label: t('an.ch.minVol'), data: [xy(f.min_vol.point)], backgroundColor: C.s[2], pointStyle: 'triangle', pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 2 },
        { label: t('an.ch.maxSharpe'), data: [xy(f.max_sharpe.point)], backgroundColor: C.s[3], pointStyle: 'rectRot', pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 1 },
        { label: label('Il tuo portafoglio'), data: [xy(f.current)], backgroundColor: C.s[1], pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 0 },
      ] },
      options: {
        plugins: { tooltip: { callbacks: { label: c => t('an.ch.frontierTip', { name: c.dataset.label, vol: n2(c.raw.x), ret: n2(c.raw.y) }) } } },
        scales: {
          x: { title: { display: true, text: t('an.ch.axVol') } },
          y: { title: { display: true, text: t('an.ch.axRet') } },
        },
      },
    });
  }

  // ── 9. Return distribution ────────────────────
  function distribution(d) {
    draw('chDist', {
      type: 'bar',
      data: { labels: d.centers.map(c => fx(c, 2)), datasets: [
        line(t('an.ch.normal'), d.normal, C.context, { type: 'line', borderWidth: 1.5, tension: 0.3 }),
        { label: t('an.ch.observed'), data: d.counts, backgroundColor: C.s[0], barPercentage: 1, categoryPercentage: 0.92, borderRadius: 2 },
      ] },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { title: c => t('an.ch.distTip', { v: c[0].label }) } } },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0 } } },
      },
    });
  }

  // ── 10. Monte Carlo fan ───────────────────────
  function monteCarlo(mc) {
    const labels = mc.months.map(m => (m % 12 === 0 ? t('an.mc.yearShort', { n: m / 12 }) : ''));
    // `tip`: percentile named in the tooltip; `edge`: lower band edge, kept out of the legend.
    const band = (label, data, fill, a, tip, edge = false) => ({ label, data, borderWidth: 0, pointRadius: 0,
      backgroundColor: alpha(C.s[0], a), fill, tip, edge });
    draw('chMonteCarlo', {
      type: 'line',
      data: { labels, datasets: [
        band('p5', mc.p5, false, 0, t('an.mc.p5'), true),
        band(t('an.ch.band90'), mc.p95, 0, 0.14, t('an.mc.p95')),
        band('p25', mc.p25, false, 0, t('an.mc.p25'), true),
        band(t('an.ch.band50'), mc.p75, 2, 0.28, t('an.mc.p75')),
        line(t('an.ch.median'), mc.p50, C.s[0]),
        line(t('an.ch.initial'), mc.months.map(() => mc.initial), C.context, { borderWidth: 1 }),
      ] },
      options: {
        interaction: lineTooltip,
        plugins: {
          legend: { labels: { filter: (i, data) => !data.datasets[i.datasetIndex].edge } },
          tooltip: { callbacks: {
            title: c => t('an.ch.month', { n: mc.months[c[0].dataIndex] }),
            label: c => `${c.dataset.tip || c.dataset.label}: ${eur(c.raw)}`,
          } },
        },
        scales: { x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 0 } },
          y: { ticks: { callback: v => eur(v) } } },
      },
    });
  }

  // ── 11. Alternative allocations ───────────────
  function alternatives(alt) {
    const colors = [C.s[0], C.s[1], C.s[2], C.s[3], C.s[4]];
    draw('chAlternatives', {
      type: 'line',
      data: { labels: alt.dates, datasets: alt.items.map((a, i) =>
        line(label(a.name), a.values, colors[i % colors.length], { borderWidth: i === 0 ? 2.5 : 1.5 })) },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw)}` } } },
        scales: { x: timeX, y: { ticks: { callback: v => eur(v) } } },
      },
    });
  }

  window.AnCharts = {
    C, catColor, alpha, eur, pct, n2, label,
    value, twr, drawdown: drawdownChart, classPL, waterfall, allocTime, drift,
    rollingCorr, frontier, distribution, monteCarlo, alternatives,
  };
})();
