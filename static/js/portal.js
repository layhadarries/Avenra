/* Shared staff session boundary. No private records are stored in browser storage. */
(function () {
  'use strict';
  class PortalSession {
    constructor() {
      this.stopped = false;
      this.requests = new Set();
      this.listeners = new Set();
      this.signature = document.querySelector('meta[name="access-signature"]').content;
      this.checking = false;
      this.channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('avenra-staff-session') : null;
      if (this.channel) this.channel.onmessage = () => this.expire();
      document.querySelector('form[action="/logout"]')?.addEventListener('submit', () => {
        this.channel?.postMessage('logout');
        this.clear();
        try { localStorage.setItem('avenra-logout', String(Date.now())); } catch (_) { /* BroadcastChannel and polling remain available. */ }
      });
      window.addEventListener('storage', e => { if (e.key === 'avenra-logout') this.expire(); });
      window.addEventListener('pagehide', () => this.clear());
      window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) this.check();
      });
      this.timer = setInterval(() => this.check(), 5000);
      const expiresAt = Number(document.querySelector('meta[name="session-expires"]').content);
      this.expiry = setTimeout(() => this.expire(), Math.max(0, expiresAt * 1000 - Date.now()));
    }
    onClear(fn) { this.listeners.add(fn); }
    clear() {
      if (this.stopped) return;
      this.stopped = true;
      clearInterval(this.timer); clearTimeout(this.expiry);
      this.requests.forEach(c => c.abort()); this.requests.clear();
      this.listeners.forEach(fn => fn());
      document.querySelector('main')?.replaceChildren();
      document.querySelector('.topbar-user')?.replaceChildren();
      document.title = 'Avenra partner portal';
    }
    expire() { this.clear(); location.replace('/login'); }
    async request(url, options = {}) {
      if (this.stopped) throw new Error('Access ended.');
      const controller = new AbortController();
      this.requests.add(controller);
      const timeout = setTimeout(() => controller.abort(), 12000);
      const headers = new Headers(options.headers || {});
      headers.set('Accept', 'application/json');
      if (!['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) {
        headers.set('X-CSRFToken', document.querySelector('meta[name="csrf-token"]').content);
      }
      try {
        const response = await fetch(url, {...options, headers, credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
        if (this.stopped) throw new Error('Access ended.');
        if (response.status === 401) { this.expire(); throw new Error('Sign in again.'); }
        return response;
      } finally {
        clearTimeout(timeout); this.requests.delete(controller);
      }
    }
    async json(url, options = {}) {
      const response = await this.request(url, options);
      const data = await response.json();
      if (this.stopped) throw new Error('Access ended.');
      if (!response.ok) throw new Error(data.message || String(data.error || 'Request failed').replaceAll('_', ' '));
      return data;
    }
    async check() {
      if (this.stopped || this.checking) return;
      this.checking = true;
      try {
        const session = await this.json('/api/session');
        if (this.signature !== session.access_signature) {
          this.clear(); location.reload();
        }
      } catch (_) {
        // Detailed case views must not leave stale consent-controlled evidence
        // visible when permission revalidation cannot reach the server.
        if (document.querySelector('[data-case-view]') && !this.stopped) {
          this.clear();
          const main = document.querySelector('main');
          const message = document.createElement('p');
          message.textContent = 'Access could not be rechecked. Reconnect and reload to view this case.';
          main?.append(message);
        }
      } finally { this.checking = false; }
    }
  }
  window.Portal = new PortalSession();
})();
