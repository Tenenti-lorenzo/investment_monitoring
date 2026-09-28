/* ═══════════════════════════════════════
   PortfolioLab – Session (sliding 30-minute expiry)
   The backend returns a fresh token in X-Refreshed-Token on every
   authenticated call, so the session only ends after 30 minutes of
   inactivity. User activity (click/keys/scroll) near the expiry pings
   /api/auth/me to keep the token alive; an idle page logs out on its own.
═══════════════════════════════════════ */
window.Session = (function () {
  const TOKEN_KEY = 'auth_token';
  const USER_KEY = 'auth_username';
  const REFRESH_HEADER = 'X-Refreshed-Token';
  const RENEW_BEFORE_MS = 25 * 60 * 1000;  // activity renews once 5+ minutes have passed
  const CHECK_EVERY_MS = 30 * 1000;

  const read = k => { try { return localStorage.getItem(k); } catch { return null; } };
  const token = () => read(TOKEN_KEY) || '';

  function expiresAt(t = token()) {
    try {
      const payload = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return payload.exp * 1000;
    } catch { return 0; }
  }
  const valid = () => expiresAt() > Date.now();

  function logout() {
    try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch { /* ignore */ }
    window.location.href = '/login';
  }

  async function apiFetch(url, opts = {}) {
    const res = await fetch(url, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${token()}` } });
    if (res.status === 401) {
      logout();
      throw new Error('Sessione scaduta');
    }
    const fresh = res.headers.get(REFRESH_HEADER);
    if (fresh) try { localStorage.setItem(TOKEN_KEY, fresh); } catch { /* ignore */ }
    return res;
  }

  // Protected pages: redirect now if the token is missing/expired, then watch it.
  function guard() {
    if (!valid()) { logout(); return; }
    let renewing = false;
    const onActivity = () => {
      const left = expiresAt() - Date.now();
      if (renewing || left > RENEW_BEFORE_MS) return;
      if (left <= 0) { logout(); return; }
      renewing = true;
      apiFetch('/api/auth/me').catch(() => {}).finally(() => { renewing = false; });
    };
    ['click', 'keydown', 'scroll', 'touchstart'].forEach(e =>
      window.addEventListener(e, onActivity, { passive: true, capture: true }));
    setInterval(() => { if (!valid()) logout(); }, CHECK_EVERY_MS);
  }

  return { token, valid, logout, apiFetch, guard };
})();
