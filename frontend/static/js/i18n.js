/* ═══════════════════════════════════════
   PortfolioLab – Interface language
   Loaded in <head> right after theme.js. Italian is the source language and
   stays in the HTML: elements carry a key and the original text is restored
   when a translation is missing. Dictionaries (static/i18n/*.js) register
   other languages through I18n.add(). A language picker is added next to the
   theme toggle; the choice persists in localStorage, else the browser
   language wins (when supported).

   Markup:
     data-i18n="key"              → textContent
     data-i18n-html="key"         → innerHTML (our own dictionary strings only)
     data-i18n-attr="attr:key;…"  → attributes (placeholder, title, aria-label)
     <html data-i18n-title="key"> → document.title
   JS: I18n.t('key', { var: … }) with {var} placeholders; I18n.locale for Intl
   formatting; 'langchange' event (re-render dynamic content on it).
═══════════════════════════════════════ */
window.I18n = (function () {
  const KEY = 'lang';
  const LANGS = { it: 'Italiano', en: 'English', fr: 'Français', de: 'Deutsch', es: 'Español', ja: '日本語' };
  // BCP 47 locale for Intl number/date formatting in the chosen language.
  const LOCALES = { it: 'it-IT', en: 'en-GB', fr: 'fr-FR', de: 'de-DE', es: 'es-ES', ja: 'ja-JP' };
  const dict = Object.fromEntries(Object.keys(LANGS).map(l => [l, {}]));
  const original = new WeakMap();  // element → { text, html, attrs } in Italian
  let originalTitle = null;
  let ready = false;

  const saved = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const fromBrowser = () => (navigator.languages || [navigator.language || ''])
    .map(l => String(l).slice(0, 2).toLowerCase()).find(l => l in LANGS);
  let lang = [saved(), fromBrowser(), 'it'].find(l => l && l in LANGS);

  function lookup(key) {
    return dict[lang][key] ?? dict.it[key];
  }
  function fill(s, vars) {
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s;
  }
  /** Translated string; falls back to Italian, then to `key` itself. */
  function t(key, vars) {
    return fill(lookup(key) ?? key, vars);
  }

  function remember(el) {
    if (!original.has(el)) original.set(el, { text: el.textContent, html: el.innerHTML, attrs: {} });
    return original.get(el);
  }

  function apply(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(el => {
      const o = remember(el);
      el.textContent = lang === 'it' ? (dict.it[el.dataset.i18n] ?? o.text) : (lookup(el.dataset.i18n) ?? o.text);
    });
    root.querySelectorAll('[data-i18n-html]').forEach(el => {
      const o = remember(el);
      el.innerHTML = lang === 'it' ? (dict.it[el.dataset.i18nHtml] ?? o.html) : (lookup(el.dataset.i18nHtml) ?? o.html);
    });
    root.querySelectorAll('[data-i18n-attr]').forEach(el => {
      const o = remember(el);
      el.dataset.i18nAttr.split(';').forEach(pair => {
        const [attr, key] = pair.split(':').map(s => s.trim());
        if (!attr || !key) return;
        if (!(attr in o.attrs)) o.attrs[attr] = el.getAttribute(attr) ?? '';
        el.setAttribute(attr, (lang === 'it' ? dict.it[key] : lookup(key)) ?? o.attrs[attr]);
      });
    });
    const root_ = document.documentElement;
    root_.lang = lang;
    if (root_.dataset.i18nTitle) {
      if (originalTitle === null) originalTitle = document.title;
      document.title = (lang === 'it' ? dict.it[root_.dataset.i18nTitle] : lookup(root_.dataset.i18nTitle)) ?? originalTitle;
    }
    document.querySelectorAll('.lang-select').forEach(s => {
      s.value = lang;
      s.setAttribute('aria-label', t('lang.label'));
      s.title = t('lang.label');
    });
  }

  function set(next) {
    if (!(next in LANGS) || next === lang) return;
    lang = next;
    try { localStorage.setItem(KEY, next); } catch { /* ignore */ }
    apply();
    window.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
  }

  /** Register translations: { en: { key: '…' }, fr: {…}, … }. */
  function add(pack) {
    Object.entries(pack).forEach(([l, strings]) => { if (dict[l]) Object.assign(dict[l], strings); });
    if (ready) apply();
  }

  function mountSelect() {
    const sel = document.createElement('select');
    sel.className = 'lang-select';
    sel.innerHTML = Object.entries(LANGS).map(([code, name]) => `<option value="${code}">${name}</option>`).join('');
    sel.addEventListener('change', () => set(sel.value));
    const host = document.querySelector('.nav-cta');
    if (host) host.prepend(sel);
    else { sel.classList.add('lang-select-floating'); document.body.appendChild(sel); }
  }

  function init() {
    mountSelect();
    ready = true;
    apply();
  }
  document.documentElement.lang = lang;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  return { t, set, add, apply, get lang() { return lang; }, get locale() { return LOCALES[lang]; }, LANGS };
})();
