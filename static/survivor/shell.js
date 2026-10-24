/* Public connection/cache status only. No identity, alerts or private storage. */
(function () {
  'use strict';
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
