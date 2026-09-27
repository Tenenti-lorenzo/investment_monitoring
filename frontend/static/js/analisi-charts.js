/* ═══════════════════════════════════════
   PortfolioLab – Analisi approfondita: Chart.js renderers
   Exposes window.AnCharts. Colors come from the CSS tokens in analisi.css
   (validated dark categorical palette); status colors only for gain/loss.
═══════════════════════════════════════ */

(function () {
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = {
    s: [1, 2, 3, 4, 5, 6, 7, 8].map(i => css(`--series-${i}`)),
    good: css('--good'), critical: css('--critical'), context: css('--context'),
    grid: css('--grid'), muted: css('--muted'), surface: css('--card'),
  };
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

  const nf0 = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0, useGrouping: 'always' });
  const nf2 = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 2 });
  const eur = v => `${v < 0 ? '−' : ''}€ ${nf0.format(Math.abs(v))}`;
  const sgn = v => (v > 0 ? '+' : '');
  const pct = (v, d = 1) => `${sgn(v)}${v.toFixed(d).replace('.', ',').replace('-', '−')}%`;
  // Line dataset: legend swatch filled with the series color (Chart.js default is a gray box).
  const line = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, ...extra });

  Chart.defaults.color = C.muted;
  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = C.grid;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.tooltip.backgroundColor = '#0b0d14';
  Chart.defaults.plugins.tooltip.borderColor = '#252840';
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 4;
  Chart.defaults.elements.bar.borderRadius = 4;

  const charts = {};
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
          line('Valore di mercato', curve.value, C.s[0],
            { fill: { target: 1, above: alpha(C.good, 0.14), below: alpha(C.critical, 0.16) } }),
          line('Capitale investito', curve.invested, C.context, { stepped: true }),
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
    const ds = [line('Portafoglio (TWR)', curve.twr_index, C.s[0])];
    if (curve.benchmark_index.some(v => v != null)) {
      ds.push(line(benchName || 'Benchmark', curve.benchmark_index, C.context, { borderWidth: 1.5 }));
    }
    draw('chTwr', {
      type: 'line',
      data: { labels: curve.dates, datasets: ds },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${nf2.format(c.raw)}` } } },
        scales: { x: timeX },
      },
      plugins: [refLines([{ axis: 'y', value: 100, color: C.context }])],
    });
  }

  // ── 3. Drawdown ───────────────────────────────
  function drawdownChart(curve) {
    draw('chDrawdown', {
      type: 'line',
      data: { labels: curve.dates, datasets: [{ label: 'Drawdown', data: curve.drawdown,
        borderColor: C.critical, borderWidth: 1.5, fill: { target: 'origin', below: alpha(C.critical, 0.18) } }] },
      options: {
        interaction: lineTooltip,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `Drawdown: ${pct(c.raw)}` } } },
        scales: { x: timeX, y: { max: 0, ticks: { callback: v => `${v}%` } } },
      },
    });
  }

  // ── 4. P&L by asset class ─────────────────────
  function classPL(classes) {
    const rows = classes.filter(c => c.category !== 'Liquidità');
    draw('chClassPL', {
      type: 'bar',
      data: { labels: rows.map(c => c.category), datasets: [{ label: 'P&L €', data: rows.map(c => c.pl_eur),
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
    let fx = 0;
    holdings.forEach(h => {
      byClass[h.category] = (byClass[h.category] || 0) + h.price_effect;
      fx += h.fx_effect;
    });
    let drivers = Object.entries(byClass).map(([k, v]) => ({ label: k, v }));
    if (Math.abs(fx) >= 0.5) drivers.push({ label: 'Effetto cambio', v: fx });
    drivers.sort((a, b) => b.v - a.v);
    if (drivers.length > 7) {  // keep 6 largest by size, fold the rest into "Altro"
      const bySize = [...drivers].sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
      const keep = new Set(bySize.slice(0, 6));
      const other = drivers.filter(d => !keep.has(d)).reduce((s, d) => s + d.v, 0);
      drivers = drivers.filter(d => keep.has(d)).concat([{ label: 'Altro', v: other }]);
    }
    return drivers;
  }

  function waterfall(summary, holdings) {
    const drivers = waterfallSteps(summary, holdings);
    const labels = ['Capitale investito'], data = [[0, summary.invested]], colors = [C.context];
    let cum = summary.invested;
    drivers.forEach(d => {
      labels.push(d.label); data.push([cum, cum + d.v]); cum += d.v;
      colors.push(d.v >= 0 ? C.good : C.critical);
    });
    labels.push('Valore attuale'); data.push([0, summary.current_value]); colors.push(C.s[0]);
    const lows = data.slice(1, -1).flat();
    const minCum = Math.min(summary.invested, summary.current_value, ...lows);
    draw('chWaterfall', {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Ponte', data, backgroundColor: colors, barPercentage: 0.7 }] },
      options: {
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => {
          const [a, b] = c.raw; const i = c.dataIndex;
          if (i === 0 || i === labels.length - 1) return eur(b);
          const pp = summary.invested ? (b - a) / summary.invested * 100 : 0;
          return `${sgn(b - a)}${eur(b - a)} (${pct(pp, 2)} p.p.)`;
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
        label: s.name, data: s.values, borderColor: C.surface, borderWidth: 1,
        backgroundColor: catColor(s.name), fill: i === 0 ? 'origin' : '-1',
      })) },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${nf2.format(c.raw ?? 0)}%` } } },
        scales: { x: timeX, y: { stacked: true, min: 0, max: 100, ticks: { callback: v => `${v}%` } } },
      },
    });
  }

  function drift(classes) {
    draw('chDrift', {
      type: 'bar',
      data: { labels: classes.map(c => c.category), datasets: [{ label: 'Drift p.p.',
        data: classes.map(c => c.drift_pp),
        backgroundColor: classes.map(c => (c.drift_pp >= 0 ? C.s[0] : C.s[1])), barPercentage: 0.6 }] },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => {
          const r = classes[c.dataIndex];
          return `${pct(r.drift_pp)} p.p. (target ${nf2.format(r.weight_target_pct)}% → ora ${nf2.format(r.weight_now_pct)}%)`;
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
      data: { labels: corr.rolling_dates, datasets: [line(`Correlazione media (${corr.window_days} gg)`, corr.rolling_avg, C.s[0])] },
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
        { label: 'Portafogli simulati', data: f.cloud.map(xy), backgroundColor: alpha(C.context, 0.45), pointRadius: 2, pointHoverRadius: 3, order: 5 },
        line('Frontiera efficiente', f.frontier.map(xy), C.s[0], { showLine: true, pointRadius: 0, order: 4 }),
        { label: 'Minima volatilità', data: [xy(f.min_vol.point)], backgroundColor: C.s[2], pointStyle: 'triangle', pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 2 },
        { label: 'Massimo Sharpe', data: [xy(f.max_sharpe.point)], backgroundColor: C.s[3], pointStyle: 'rectRot', pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 1 },
        { label: 'Il tuo portafoglio', data: [xy(f.current)], backgroundColor: C.s[1], pointRadius: 9, pointHoverRadius: 11, borderColor: C.surface, borderWidth: 2, order: 0 },
      ] },
      options: {
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: vol ${nf2.format(c.raw.x)}%, rend. ${nf2.format(c.raw.y)}%` } } },
        scales: {
          x: { title: { display: true, text: 'Volatilità annua %' } },
          y: { title: { display: true, text: 'Rendimento annuo atteso %' } },
        },
      },
    });
  }

  // ── 9. Return distribution ────────────────────
  function distribution(d) {
    draw('chDist', {
      type: 'bar',
      data: { labels: d.centers.map(c => c.toFixed(2).replace('.', ',')), datasets: [
        line('Normale equivalente', d.normal, C.context, { type: 'line', borderWidth: 1.5, tension: 0.3 }),
        { label: 'Giorni osservati', data: d.counts, backgroundColor: C.s[0], barPercentage: 1, categoryPercentage: 0.92, borderRadius: 2 },
      ] },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { title: c => `Rendimento ≈ ${c[0].label}%` } } },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0 } } },
      },
    });
  }

  // ── 10. Monte Carlo fan ───────────────────────
  function monteCarlo(mc) {
    const labels = mc.months.map(m => (m % 12 === 0 ? `${m / 12}a` : ''));
    const band = (label, data, fill, a) => ({ label, data, borderWidth: 0, pointRadius: 0,
      backgroundColor: alpha(C.s[0], a), fill });
    draw('chMonteCarlo', {
      type: 'line',
      data: { labels, datasets: [
        band('p5', mc.p5, false, 0),
        band('5°–95° percentile', mc.p95, 0, 0.14),
        band('p25', mc.p25, false, 0),
        band('25°–75° percentile', mc.p75, 2, 0.28),
        line('Mediana', mc.p50, C.s[0]),
        line('Valore iniziale', mc.months.map(() => mc.initial), C.context, { borderWidth: 1 }),
      ] },
      options: {
        interaction: lineTooltip,
        plugins: {
          legend: { labels: { filter: i => !['p5', 'p25'].includes(i.text) } },
          tooltip: { callbacks: {
            title: c => `Mese ${mc.months[c[0].dataIndex]}`,
            label: c => `${c.dataset.label === 'p5' ? '5° percentile' : c.dataset.label === 'p25' ? '25° percentile'
              : c.dataset.label.startsWith('5°') ? '95° percentile' : c.dataset.label.startsWith('25°') ? '75° percentile'
              : c.dataset.label}: ${eur(c.raw)}`,
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
        line(a.name, a.values, colors[i % colors.length], { borderWidth: i === 0 ? 2.5 : 1.5 })) },
      options: {
        interaction: lineTooltip,
        plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${eur(c.raw)}` } } },
        scales: { x: timeX, y: { ticks: { callback: v => eur(v) } } },
      },
    });
  }

  window.AnCharts = {
    C, catColor, alpha, eur, pct, nf2,
    value, twr, drawdown: drawdownChart, classPL, waterfall, allocTime, drift,
    rollingCorr, frontier, distribution, monteCarlo, alternatives,
  };
})();
