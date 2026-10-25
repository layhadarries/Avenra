/* Evaluation queue. Retries while a page is open, or when it is reopened.
   IndexedDB contains sensitive pending payloads: individual auth and storage
   protection remain release requirements. No closed-app delivery guarantee. */
(function (global) {
  'use strict';
  var DB_NAME = 'clear-sky-queue', STORE = 'alerts';
  var DEVICE_TOKEN = 'demo-device'; // Evaluation only; never a production credential.
  var dbPromise = null, flushPromise = null, flushAgain = false, retryTimer = null, retryIndex = 0;
  var listeners = [], BACKOFF = [5000, 15000, 30000];
  function emit(event) {
    listeners.forEach(function (fn) { try { fn(event); } catch (_) {} });
  }
  function openDb() {
    if (!dbPromise) {
      dbPromise = new Promise(function (resolve, reject) {
        var req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = function () {
          if (!req.result.objectStoreNames.contains(STORE))
            req.result.createObjectStore(STORE, {keyPath: 'client_id'});
        };
        req.onerror = function () { dbPromise = null; reject(new Error('storage_unavailable')); };
        req.onblocked = function () { dbPromise = null; reject(new Error('storage_unavailable')); };
        req.onsuccess = function () {
          var db = req.result;
          if (typeof navigator !== 'undefined' && navigator.storage && navigator.storage.persist) {
            navigator.storage.persist().catch(function () {});
          }
          db.onversionchange = function () { db.close(); dbPromise = null; };
          migrateLegacy(db).then(function () { resolve(db); }, function (error) { db.close(); dbPromise = null; reject(error); });
        };
      });
    }
    return dbPromise;
  }
  // Recover records written under the accidental merged database rename.
  // Copy commits before legacy removal; crashes can replay an ID, never lose it.
  function migrateLegacy(target) {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open('cape-weather-queue', 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains(STORE))
          req.result.createObjectStore(STORE, {keyPath: 'client_id'});
      };
      req.onerror = req.onblocked = function () { reject(new Error('storage_unavailable')); };
      req.onsuccess = function () {
        var legacy = req.result;
        function fail() { legacy.close(); reject(new Error('storage_unavailable')); }
        if (!legacy.objectStoreNames.contains(STORE)) { legacy.close(); resolve(); return; }
        var read = legacy.transaction(STORE, 'readonly'), items = [];
        read.objectStore(STORE).getAll().onsuccess = function (event) { items = event.target.result || []; };
        read.onerror = read.onabort = fail;
        read.oncomplete = function () {
          if (!items.length) { legacy.close(); resolve(); return; }
          var copy = target.transaction(STORE, 'readwrite'), store = copy.objectStore(STORE);
          copy.onerror = copy.onabort = fail;
          items.forEach(function (item) {
            var existing = store.get(item.client_id);
            existing.onsuccess = function () {
              if (existing.result === undefined) store.put(item);
              else if (JSON.stringify(existing.result) !== JSON.stringify(item)) copy.abort();
            };
          });
          copy.oncomplete = function () {
            var remove = legacy.transaction(STORE, 'readwrite');
            remove.onerror = remove.onabort = fail;
            items.forEach(function (item) { remove.objectStore(STORE).delete(item.client_id); });
            remove.oncomplete = function () { legacy.close(); resolve(); };
          };
        };
      };
    });
  }
  function transaction(mode, operation) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx, result;
        try {
          tx = db.transaction(STORE, mode);
          tx.oncomplete = function () { resolve(result); };
          tx.onabort = tx.onerror = function () { reject(new Error('storage_unavailable')); };
          var req = operation(tx.objectStore(STORE));
          req.onsuccess = function () { result = req.result; };
          req.onerror = function () { reject(new Error('storage_unavailable')); };
        } catch (_) { if (tx) { try { tx.abort(); } catch (_) {} } reject(new Error('storage_unavailable')); }
      });
    });
  }
  function queueAlert(item) {
    return transaction('readwrite', function (store) { return store.put(item); })
      .then(function () { emit({type: 'queued', client_id: item.client_id}); });
  }
  function removeAlert(id) {
    return transaction('readwrite', function (store) { return store.delete(id); });
  }
  function allAlerts() {
    return transaction('readonly', function (store) { return store.getAll(); });
  }
  function request(url, options, timeout) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, timeout);
    options = Object.assign({credentials: 'same-origin', cache: 'no-store'}, options || {});
    options.headers = Object.assign({'X-Device-Token': DEVICE_TOKEN}, options.headers || {});
    options.signal = ctrl.signal;
    return fetch(url, options).then(function (response) {
      if (!response.ok) {
        var error = new Error('request_failed'); error.status = response.status; throw error;
      }
      return response.json();
    }).then(function (body) { clearTimeout(timer); return body; }, function (error) {
      clearTimeout(timer); throw error;
    });
  }
  function locationPermitted() {
    return request('/api/consents', {}, 3000).then(function (body) {
      return Array.isArray(body.consents) && body.consents.some(function (consent) {
        return consent.item === 'location_sharing' && (consent.active === true || consent.active === 1);
      });
    }, function () { return false; });
  }
  function sendOne(item) {
    return locationPermitted().then(function (allowed) {
      var payload = Object.assign({}, item);
      if (!allowed) {
        payload.lat = payload.lng = null;
        payload.location_accuracy = payload.location_recorded_at = null;
      }
      return request('/api/alerts', {
        method: 'POST', keepalive: true, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      }, 15000);
    }).then(function (receipt) {
      if (!receipt || !Number.isInteger(receipt.id) || receipt.id < 1 || receipt.client_id !== item.client_id)
        throw new Error('invalid_receipt');
      return removeAlert(item.client_id).then(function () {
        emit({type: 'sent', client_id: item.client_id, receipt: receipt});
      });
    });
  }
  function scheduleRetry() {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(flushQueue, BACKOFF[Math.min(retryIndex++, BACKOFF.length - 1)]);
  }
  function flushQueue() {
    if (flushPromise) { flushAgain = true; return flushPromise; }
    clearTimeout(retryTimer);
    flushPromise = allAlerts().then(function (items) {
      var transientFailure = false;
      return items.reduce(function (chain, item) {
        return chain.then(function () {
          return sendOne(item).catch(function (error) {
            // Keep rejected items. Do not hammer authentication/validation failures.
            if ([400, 401, 403, 404, 409, 422].indexOf(error.status) !== -1)
              emit({type: 'blocked', client_id: item.client_id});
            else transientFailure = true;
          });
        });
      }, Promise.resolve()).then(function () {
        if (transientFailure) scheduleRetry(); else retryIndex = 0;
      });
    }).catch(function () { emit({type: 'storage_error'}); }).then(function () {
      flushPromise = null;
      if (flushAgain) { flushAgain = false; return flushQueue(); }
    });
    return flushPromise;
  }
  global.addEventListener('online', flushQueue);
  global.addEventListener('load', flushQueue);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') flushQueue();
  });
  global.CWQueue = {
    queueAlert: queueAlert, flushQueue: flushQueue,
    queueSize: function () { return allAlerts().then(function (items) { return items.length; }); },
    onFlushed: function (fn) { listeners.push(fn); },
    locationPermitted: locationPermitted
  };
})(window);
