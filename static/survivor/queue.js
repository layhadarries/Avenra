/* Cape Weather: offline alert queue (Stage 2)
        - IndexedDB only, no libraries.
   Write first, send second: queueAlert() must resolve before survivor.js attempts to send. */
(function (global) {
  "use strict";

  var DB_NAME = "cape-weather-queue";
  var STORE = "alerts";
  var DEVICE_TOKEN = "demo-device";
  var SEND_TIMEOUT_MS = 15000;   // generous: survives a Render cold start
  var BACKOFF_STEPS_MS = [5000, 15000, 30000];

  var dbPromise = null;
  var flushing = false;
  var backoffTimer = null;
  var backoffIndex = 0;
  var listeners = [];

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore(STORE, { keyPath: "client_id" });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
    return dbPromise;
  }

  function store(mode) {
    return openDb().then(function (db) { return db.transaction(STORE, mode).objectStore(STORE); });
  }

  function queueAlert(item) {
    // item: {client_id, lat, lng, client_ts}
    return store("readwrite").then(function (s) {
      return new Promise(function (resolve, reject) {
        var req = s.put(item);
        req.onsuccess = function () { resolve(); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function removeAlert(clientId) {
    return store("readwrite").then(function (s) {
      return new Promise(function (resolve, reject) {
        var req = s.delete(clientId);
        req.onsuccess = function () { resolve(); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function allAlerts() {
    return store("readonly").then(function (s) {
      return new Promise(function (resolve, reject) {
        var req = s.getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function queueSize() {
    return allAlerts().then(function (items) { return items.length; });
  }

  function sendOne(item) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, SEND_TIMEOUT_MS);
    return fetch("/api/alerts", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      keepalive: true,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", "X-Device-Token": DEVICE_TOKEN },
      body: JSON.stringify(item)
    }).then(function (res) {
      clearTimeout(timer);
      if (!res.ok) throw new Error("http " + res.status);
      return res.json();
    }, function (err) {
      clearTimeout(timer);
      throw err;
    });
  }

  function emit(event) {
    listeners.forEach(function (fn) {
      try { fn(event); } catch (_e) { /* a bad listener must never break the queue */ }
    });
  }


  function onFlushed(fn) { listeners.push(fn); }

  // Don't trust navigator.onLine alone: a failed or timed-out request is what counts as offline.
  // The same client_id is reused on every send, so a server-side duplicate (200) is treated as success.
  function flushQueue() {
    if (flushing) return Promise.resolve();
    flushing = true;

    return allAlerts().then(function (items) {
      if (!items.length) return;
      return items.reduce(function (chain, item) {
        return chain.then(function () {
          return sendOne(item).then(function (receipt) {
            return removeAlert(item.client_id).then(function () {
              backoffIndex = 0;
              emit({ type: "sent", client_id: item.client_id, receipt: receipt });
            });
          });
        });
      }, Promise.resolve());
    }).catch(function () {
      scheduleBackoff();
    }).then(function () {
      flushing = false;
    });
  }

  function scheduleBackoff() {
    clearTimeout(backoffTimer);
    var wait = BACKOFF_STEPS_MS[Math.min(backoffIndex, BACKOFF_STEPS_MS.length - 1)];
    backoffIndex = Math.min(backoffIndex + 1, BACKOFF_STEPS_MS.length - 1);
    backoffTimer = setTimeout(flushQueue, wait);
  }

  // Flush triggers: online event, page load, foregrounding, and a 15s timer while the queue isn't empty.
  global.addEventListener("online", flushQueue);
  global.addEventListener("load", flushQueue);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") flushQueue();
  });
  setInterval(function () {
    queueSize().then(function (n) { if (n > 0) flushQueue(); });
  }, 15000);

  global.CWQueue = {
    queueAlert: queueAlert,
    flushQueue: flushQueue,
    queueSize: queueSize,
    onFlushed: onFlushed
  };
})(window);