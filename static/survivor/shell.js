/* Public shell only: no credentials, private storage, geolocation or alert requests. */
(function () {
  'use strict';
  var connection = document.getElementById('connection-state');
  var offline = document.getElementById('offline-state');
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
    .then(function () { return navigator.serviceWorker.ready; })
    .then(function () { offline.textContent = 'This page is ready to open offline after your first visit.'; })
    .catch(function () { offline.textContent = 'Offline opening could not be enabled. Try reloading when connected.'; });
})();
