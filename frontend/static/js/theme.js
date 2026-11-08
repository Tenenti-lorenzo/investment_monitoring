/* ═══════════════════════════════════════
   PortfolioLab – Light / dark theme
   Loaded synchronously in <head> so the saved theme is applied before the
   first paint (no flash). Choice persists in localStorage; without one the
   OS preference wins. A toggle button is added to the navbar (or floats in
   the corner on pages without one, e.g. /login).
═══════════════════════════════════════ */
window.Theme = (function () {
  const KEY = 'theme';
  const root = document.documentElement;

  const saved = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const preferred = () =>
    window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  const current = () => root.dataset.theme || 'dark';

  function apply(theme) {
    root.dataset.theme = theme;
    document.querySelectorAll('.theme-toggle').forEach(b => {
      b.textContent = theme === 'dark' ? '☀️' : '🌙';
      const it = theme === 'dark' ? 'Passa al tema chiaro' : 'Passa al tema scuro';
      b.title = window.I18n ? I18n.t(theme === 'dark' ? 'theme.toLight' : 'theme.toDark') : it;
      b.setAttribute('aria-label', b.title);
    });
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
  }

  function toggle() {
    const next = current() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, next); } catch { /* ignore */ }
    apply(next);
  }

  function mountToggle() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle';
    btn.addEventListener('click', toggle);
    const host = document.querySelector('.nav-cta');
    if (host) host.prepend(btn);
    else { btn.classList.add('theme-toggle-floating'); document.body.appendChild(btn); }
    apply(current());
  }

  window.addEventListener('langchange', () => apply(current()));  // translated tooltip

  root.dataset.theme = saved() || preferred();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountToggle);
  else mountToggle();

  return { current, toggle };
})();
