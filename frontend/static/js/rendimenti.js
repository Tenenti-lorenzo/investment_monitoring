/* ═══════════════════════════════════════
   PortfolioLab – Rendimenti titoli di Stato (page /rendimenti)
   Loads /api/bonds/sovereign-yields once (all maturities), then the
   10/20/30Y selector only re-colours the D3 world map and re-renders
   the sortable country list client-side.
═══════════════════════════════════════ */

(function () {
  const ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json';
  const ANTARCTICA = '010';
  const NA_FILL = 'var(--border)';  // follows the light/dark theme
  const RAMP = ['#1e3a8a', '#3b82f6', '#22d3a0', '#f59e0b', '#f43f5e'];

  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = d => new Intl.NumberFormat('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d });
  const nf2 = nf(2), nf0 = nf(0);
  const pct = v => (v == null ? '—' : `${nf2.format(v)}%`);
  const bps = (v, signed = true) => (v == null ? '—'
    : `<span class="${!signed ? '' : v > 0 ? 'neg' : v < 0 ? 'pos' : ''}">${v > 0 ? '+' : ''}${nf0.format(v)} bp</span>`);

  const state = { data: null, tenor: 10, sort: { key: 'yield', dir: -1 }, selected: null, color: null };
  let atlasPromise = null;

  // ── Data helpers ──────────────────────────────
  const ty = (c, t = state.tenor) => c[`y${t}`];
  const slope = c => (c.y30 && c.y10 && c.y30.source === c.y10.source
    ? Math.round((c.y30.yield_pct - c.y10.yield_pct) * 100) : null);
  const byNumeric = () => new Map(state.data.countries.map(c => [c.iso_numeric, c]));
  const fmtDate = s => {
    if (!s) return '—';
    const d = new Date(s);
    if (isNaN(d)) return esc(s);
    return s.length <= 10 ? d.toLocaleDateString('it-IT', { month: 'short', year: 'numeric' })
      : d.toLocaleString('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  };

  function buildColorScale() {
    const vals = state.data.countries.map(c => ty(c)?.yield_pct).filter(v => v != null).sort(d3.ascending);
    if (!vals.length) return null;
    // Clip the tails so a single outlier (e.g. Turkey) does not flatten everyone else.
    const lo = vals.length >= 15 ? d3.quantileSorted(vals, 0.05) : vals[0];
    const hi = vals.length >= 15 ? d3.quantileSorted(vals, 0.95) : vals[vals.length - 1];
    const interp = d3.interpolateRgbBasis(RAMP);
    return d3.scaleSequential(interp).domain([lo, hi === lo ? lo + 1 : hi]).clamp(true);
  }

  // ── KPIs ──────────────────────────────────────
  function renderKpis() {
    const find = iso => state.data.countries.find(c => c.iso2 === iso);
    const kpi = (label, iso) => {
      const t = find(iso) && ty(find(iso));
      return `<div class="kpi"><div class="kpi-label">${label}</div>
        <div class="kpi-value">${pct(t?.yield_pct)}</div>
        <div class="kpi-sub">${t ? `oggi ${bps(t.change_bps)}` : 'n.d.'}</div></div>`;
    };
    const it = find('IT') && ty(find('IT'));
    $('ydKpis').innerHTML = kpi(`Treasury USA ${state.tenor}A`, 'US') + kpi(`Bund ${state.tenor}A`, 'DE')
      + kpi(`BTP ${state.tenor}A`, 'IT')
      + `<div class="kpi"><div class="kpi-label">Spread BTP–Bund</div>
          <div class="kpi-value">${it?.spread_vs_bund_bps == null ? '—' : `${nf0.format(it.spread_vs_bund_bps)} bp`}</div>
          <div class="kpi-sub">${state.data.countries.filter(c => ty(c)).length} paesi con dati a ${state.tenor} anni</div></div>`;
  }

  // ── Map ───────────────────────────────────────
  async function renderMap() {
    atlasPromise = atlasPromise || d3.json(ATLAS_URL);
    const world = await atlasPromise;
    const features = topojson.feature(world, world.objects.countries).features.filter(f => f.id !== ANTARCTICA);
    const width = 960, height = 470;
    const projection = d3.geoNaturalEarth1().fitExtent([[4, 4], [width - 4, height - 4]], { type: 'FeatureCollection', features });
    const path = d3.geoPath(projection);
    const lookup = byNumeric();

    const svg = d3.select('#ydMap').attr('viewBox', `0 0 ${width} ${height}`);
    if (svg.select('g.countries').empty()) {
      svg.append('path').attr('class', 'graticule').attr('d', path(d3.geoGraticule10()));
      svg.append('g').attr('class', 'countries');
    }
    svg.select('g.countries').selectAll('path.country')
      .data(features, f => f.id)
      .join('path')
      .attr('class', f => {
        const c = lookup.get(f.id);
        return `country${c && ty(c) ? ' has-data' : ''}${c && c.iso2 === state.selected ? ' selected' : ''}`;
      })
      .attr('d', path)
      .style('fill', f => {
        const t = lookup.get(f.id) && ty(lookup.get(f.id));
        return t && state.color ? state.color(t.yield_pct) : NA_FILL;
      })
      .on('mousemove', (ev, f) => showTooltip(ev, lookup.get(f.id), f))
      .on('mouseleave', hideTooltip)
      .on('click', (_, f) => { const c = lookup.get(f.id); if (c) select(c.iso2, true); });
  }

  function showTooltip(ev, c, f) {
    const tip = $('ydTooltip');
    const name = c ? c.name : (f.properties?.name || '');
    const row = (label, t) => `<div class="yd-tt-row"><span>${label}</span><span>${t ? pct(t.yield_pct) : '—'}</span></div>`;
    const cur = c && ty(c);
    tip.innerHTML = `<strong>${esc(name)}</strong>`
      + (c ? row('10 anni', c.y10) + row('20 anni', c.y20) + row('30 anni', c.y30)
        + (cur ? `<div class="yd-tt-row"><span>Var. giorno</span><span>${bps(cur.change_bps)}</span></div>
          <div class="yd-tt-row"><span>Spread vs Bund</span><span>${bps(cur.spread_vs_bund_bps, false)}</span></div>` : '')
        : '<div class="yd-tt-row"><span>Nessun dato</span><span></span></div>');
    const box = $('ydMap').parentElement.getBoundingClientRect();
    const x = ev.clientX - box.left, y = ev.clientY - box.top;
    tip.style.left = `${Math.min(x + 14, box.width - 190)}px`;
    tip.style.top = `${y + 14}px`;
    tip.classList.remove('hidden');
  }
  const hideTooltip = () => $('ydTooltip').classList.add('hidden');

  function renderLegend() {
    const s = state.color;
    $('ydLegendMin').textContent = s ? pct(s.domain()[0]) : '';
    $('ydLegendMax').textContent = s ? pct(s.domain()[1]) : '';
    $('ydLegendBar').style.background = s
      ? `linear-gradient(to right, ${d3.range(0, 1.01, 0.1).map(t => s.interpolator()(t)).join(',')})` : NA_FILL;
  }

  // ── List ──────────────────────────────────────
  const SORT_VALUE = {
    name: c => c.name,
    yield: c => ty(c)?.yield_pct,
    change: c => ty(c)?.change_bps,
    spread: c => ty(c)?.spread_vs_bund_bps,
    slope: c => slope(c),
    range: c => (ty(c)?.year_high_pct != null ? ty(c).year_high_pct - ty(c).year_low_pct : null),
    asof: c => ty(c)?.as_of,
  };

  function renderTable() {
    const { key, dir } = state.sort;
    const val = SORT_VALUE[key];
    const rows = [...state.data.countries].sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null && vb == null) return a.name.localeCompare(b.name);
      if (va == null) return 1;   // missing values always last
      if (vb == null) return -1;
      return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * dir;
    });
    $('ydRows').innerHTML = rows.map(c => {
      const t = ty(c);
      const swatch = t && state.color ? `<span class="yd-swatch" style="background:${state.color(t.yield_pct)}"></span>`
        : `<span class="yd-swatch" style="background:${NA_FILL}"></span>`;
      const range = t && t.year_low_pct != null ? `${pct(t.year_low_pct)} – ${pct(t.year_high_pct)}` : '—';
      const src = t && t.source !== 'CNBC' ? `<span class="yd-src">${esc(t.source)}</span>` : '';
      return `<tr data-iso="${esc(c.iso2)}" class="${t ? '' : 'na'}${c.iso2 === state.selected ? ' selected' : ''}">
        <td class="name">${swatch}${esc(c.name)}</td>
        <td><strong>${pct(t?.yield_pct)}</strong></td>
        <td>${bps(t?.change_bps)}</td>
        <td>${bps(t?.spread_vs_bund_bps, false)}</td>
        <td>${bps(slope(c), false)}</td>
        <td>${range}</td>
        <td>${t ? fmtDate(t.as_of) : '—'}${src}</td>
      </tr>`;
    }).join('');
    document.querySelectorAll('.yd-table th[data-sort]').forEach(th => {
      th.classList.toggle('sorted', th.dataset.sort === key);
      th.classList.toggle('asc', th.dataset.sort === key && dir === 1);
    });
    $('ydListTitle').textContent = `Lista paesi – scadenza ${state.tenor} anni`;
  }

  // ── Interaction ───────────────────────────────
  function select(iso2, scrollToRow) {
    state.selected = state.selected === iso2 ? null : iso2;
    d3.selectAll('#ydMap .country').classed('selected', f => {
      const c = byNumeric().get(f.id);
      return !!c && c.iso2 === state.selected;
    });
    document.querySelectorAll('#ydRows tr').forEach(tr => tr.classList.toggle('selected', tr.dataset.iso === state.selected));
    if (scrollToRow && state.selected) {
      document.querySelector(`#ydRows tr[data-iso="${CSS.escape(state.selected)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  function render() {
    state.color = buildColorScale();
    renderKpis();
    renderLegend();
    renderTable();
    renderMap().catch(e => { $('ydStatus').textContent = `Mappa non disponibile: ${e.message}`; });
  }

  async function load() {
    const status = $('ydStatus');
    status.classList.remove('error');
    status.textContent = 'Caricamento…';
    try {
      const res = await Session.apiFetch('/api/bonds/sovereign-yields');
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
      state.data = await res.json();
      status.textContent = `Aggiornato ${fmtDate(state.data.fetched_at)}${state.data.note ? ' · ' + state.data.note : ''}`;
      render();
    } catch (e) {
      status.classList.add('error');
      status.textContent = `Errore: ${e.message}`;
    }
  }

  document.querySelectorAll('.yd-tenors button').forEach(btn => btn.addEventListener('click', () => {
    state.tenor = Number(btn.dataset.tenor);
    document.querySelectorAll('.yd-tenors button').forEach(b => {
      b.classList.toggle('active', b === btn);
      b.setAttribute('aria-selected', String(b === btn));
    });
    if (state.data) render();
  }));
  document.querySelectorAll('.yd-table th[data-sort]').forEach(th => th.addEventListener('click', () => {
    const key = th.dataset.sort;
    state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : (key === 'name' ? 1 : -1) };
    if (state.data) renderTable();
  }));
  $('ydRows').addEventListener('click', ev => {
    const tr = ev.target.closest('tr[data-iso]');
    if (tr) select(tr.dataset.iso, false);
  });
  $('ydRefresh').addEventListener('click', load);

  try {
    const u = localStorage.getItem('auth_username');
    if (u) $('navUsername').textContent = '👤 ' + u;
  } catch { /* ignore */ }
  load();
})();
