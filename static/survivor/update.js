/* Explicit public-shell update. Never touch cookies, localStorage or IndexedDB. */
(function () {
  'use strict';
  var button = document.getElementById('update-app');
  var status = document.getElementById('update-status');
  var link = document.getElementById('open-app');

  function installed(registration) {
    if (registration.waiting) return Promise.resolve(registration.waiting);
    var worker = registration.installing;
    if (!worker) return Promise.resolve(null);
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { finish(new Error('update_timeout')); }, 30000);
      function finish(error, value) {
        clearTimeout(timer);
        worker.removeEventListener('statechange', changed);
        if (error) reject(error); else resolve(value);
      }
      function changed() {
        if (worker.state === 'installed' || worker.state === 'activated') finish(null, worker);
        if (worker.state === 'redundant') finish(new Error('update_failed'));
      }
      worker.addEventListener('statechange', changed);
      changed();
    });
  }

  function activate(worker) {
    if (!worker || worker.state === 'activated') return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { finish(new Error('activation_timeout')); }, 15000);
      function finish(error) {
        clearTimeout(timer);
        worker.removeEventListener('statechange', changed);
        if (error) reject(error); else resolve();
      }
      function changed() {
        if (worker.state === 'activated') finish();
        if (worker.state === 'redundant') finish(new Error('activation_failed'));
      }
      worker.addEventListener('statechange', changed);
      worker.postMessage({type: 'ACTIVATE_PUBLIC_SHELL_UPDATE'});
      changed();
    });
  }

  button.addEventListener('click', async function () {
    if (!('serviceWorker' in navigator)) {
      status.textContent = 'This browser does not use an offline app cache. Open the updated app below.';
      link.hidden = false;
      return;
    }
    button.disabled = true;
    status.textContent = 'Downloading app files…';
    try {
      var registration = await navigator.serviceWorker.register('/survivor/service-worker.js', {
        scope: '/survivor/', updateViaCache: 'none'
      });
      await registration.update();
      await activate(await installed(registration));
      status.textContent = 'Your app files are up to date. Saved items have not been removed.';
      link.hidden = false;
      button.hidden = true;
    } catch (_) {
      status.textContent = 'The update could not finish. Check your connection and try again. Saved items have not been removed.';
      button.disabled = false;
    }
  });
})();
