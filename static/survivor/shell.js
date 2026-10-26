/* Public shell and display-only exit guard. Never grants API/evidence authority. */
(function () {
  'use strict';
  const exitKey = 'clear-sky-exited-v1';
  function blocked() {
    try { return localStorage.getItem(exitKey) === '1'; } catch (_) { return true; }
  }
  function markExit() {
    try { localStorage.setItem(exitKey, '1'); } catch (_) {}
    if (window.CWVault) window.CWVault.lock();
  }
  function guardPrivacy() {
    if (location.pathname === '/survivor/privacy.html' && blocked()) {
      document.documentElement.style.visibility = 'hidden';
      location.replace('/survivor/cover.html');
      return true;
    }
    return false;
  }
  window.CWExit = {blocked: blocked};
  document.addEventListener('click', function (event) {
    if (event.target.closest('#quick-exit,#quick-exit-btn,[data-shell-exit]')) markExit();
  }, true);
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') markExit(); }, true);
  window.addEventListener('pageshow', guardPrivacy);
  window.addEventListener('storage', function (event) { if (event.key === exitKey) guardPrivacy(); });
  guardPrivacy();
  const destinations = new Set(['/survivor/','/survivor/help.html','/survivor/diary.html','/survivor/#more']);
  document.querySelectorAll('[data-shell-href]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (destinations.has(button.dataset.shellHref)) location.href = button.dataset.shellHref;
    });
  });
  document.querySelectorAll('[data-shell-exit]').forEach(function (button) {
    button.addEventListener('click', function () { location.replace('/survivor/cover.html'); });
  });
  const connection = document.getElementById('connection-state');
  const offline = document.getElementById('offline-state');
  if (!connection || !offline) return;
  function updateConnection() {
    connection.textContent = navigator.onLine ? 'Device appears online' : 'Device appears offline';
  }
  updateConnection();
  window.addEventListener('online', updateConnection);
  window.addEventListener('offline', updateConnection);
  if (!('serviceWorker' in navigator) || !window.isSecureContext) {
    offline.textContent = 'Offline opening is unavailable in this browser.';
    return;
  }
  navigator.serviceWorker.register('/survivor/service-worker.js', {scope:'/survivor/'})
    .then(() => navigator.serviceWorker.ready)
    .then(() => {
      offline.textContent = 'This page is ready to open offline after your first visit.';
    })
    .catch(() => {
      offline.textContent = 'Offline opening could not be enabled. Try reloading when connected.';
    });
})();
