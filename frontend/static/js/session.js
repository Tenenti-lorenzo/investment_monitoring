/* ═══════════════════════════════════════
   PortfolioLab – Session (rotating token, 15-minute idle expiry)
   Every authenticated call returns a new token in X-Refreshed-Token and the
   server invalidates the previous one, so the stored token must always be
   replaced. The session ends after 15 minutes without activity: user activity
   (click/keys/scroll) pings /api/auth/me once the token is a few minutes old;
   an idle page logs out on its own. Logout also revokes the session server-side.
═══════════════════════════════════════ */
window.Session = (function () {
  const TOKEN_KEY = 'auth_token';
  const USER_KEY = 'auth_username';
  const REFRESH_HEADER = 'X-Refreshed-Token';
  const RENEW_BEFORE_MS = 12 * 60 * 1000;  // activity renews once 3+ minutes have passed
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

  function clear() {
    try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch { /* ignore */ }
  }

  // Expired/revoked session: just leave.
  function expire() { clear(); window.location.href = '/login'; }

  // User logout: revoke server-side first (keepalive survives the navigation).
  function logout() {
    const t = token();
    if (t) fetch('/api/auth/logout', { method: 'POST', keepalive: true, headers: { Authorization: `Bearer ${t}` } })
      .catch(() => {});
    expire();
  }

  async function apiFetch(url, opts = {}) {
    const res = await fetch(url, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${token()}` } });
    if (res.status === 401) {
      expire();
      throw new Error('Sessione scaduta');
    }
    const fresh = res.headers.get(REFRESH_HEADER);
    if (fresh) try { localStorage.setItem(TOKEN_KEY, fresh); } catch { /* ignore */ }
    return res;
  }

  // Protected pages: redirect now if the token is missing/expired, then watch it.
  function guard() {
    if (!valid()) { expire(); return; }
    let renewing = false;
    const onActivity = () => {
      const left = expiresAt() - Date.now();
      if (renewing || left > RENEW_BEFORE_MS) return;
      if (left <= 0) { expire(); return; }
      renewing = true;
      apiFetch('/api/auth/me').catch(() => {}).finally(() => { renewing = false; });
    };
    ['click', 'keydown', 'scroll', 'touchstart'].forEach(e =>
      window.addEventListener(e, onActivity, { passive: true, capture: true }));
    setInterval(() => { if (!valid()) expire(); }, CHECK_EVERY_MS);
  }

  return { token, valid, logout, apiFetch, guard };
})();
