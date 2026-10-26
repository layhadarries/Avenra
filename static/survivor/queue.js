/* Durable owner-bound queue. Public-key sealed payloads never need a vault PIN.
   Without a cached key, new capture stores only minimal, GPS-free metadata.
   No closed-app delivery guarantee; IDs/ownership/activity metadata remain visible. */
(function (global) {
  'use strict';
  var DB_NAME = 'clear-sky-queue', STORE = 'alerts';
  var DEVICE_TOKEN = ((typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) ? 'demo-device' : ''); // Evaluation only; never a production credential.
  var dbPromise = null, flushPromise = null, flushAgain = false, retryTimer = null, retryIndex = 0;
  var listeners = [], BACKOFF = [5000, 15000, 30000];
  var PUBLIC_KEY = 'clear-sky-alert-public-key-v1', publicKey = null;
  function rememberPublic(value) {
    if (!value || !/^[a-f0-9]{64}$/.test(value.kid || '') || typeof value.spki !== 'string' || value.spki.length > 2048) return;
    publicKey = {kid:value.kid,spki:value.spki};
    try { localStorage.setItem(PUBLIC_KEY,JSON.stringify(publicKey)); } catch (_) {}
  }
  function cachedPublic() {
    if (!publicKey) { try { rememberPublic(JSON.parse(localStorage.getItem(PUBLIC_KEY) || 'null')); } catch (_) {} }
    return publicKey;
  }
  function encode(bytes) {
    bytes = new Uint8Array(bytes); var result = '';
    for (var offset = 0; offset < bytes.length; offset += 8192) result += String.fromCharCode.apply(null,bytes.subarray(offset,offset+8192));
    return btoa(result);
  }
  function decode(text) { return Uint8Array.from(atob(text),function (character) { return character.charCodeAt(0); }); }
  async function sealPayload(item,allowMinimal) {
    if (item.sealed_alert) return item;
    var record = cachedPublic();
    try {
      if (!record || !crypto.subtle) throw new Error('sealing_key_unavailable');
      var rsa = await crypto.subtle.importKey('spki',decode(record.spki),{name:'RSA-OAEP',hash:'SHA-256'},false,['wrapKey']);
      var bindingOwner = validOwner(item.owner_id) ? item.owner_id : 0;
      var purpose = bindingOwner ? 'alert' : 'legacy-unbound';
      var payload = Object.assign({},item), location = {client_id:item.client_id};
      delete payload.owner_id;
      ['lat','lng','location_accuracy','location_recorded_at','location_consent_token'].forEach(function (name) {
        location[name] = payload[name]; delete payload[name];
      });
      async function part(value,purpose) {
        var aes = await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
        var iv = crypto.getRandomValues(new Uint8Array(12));
        var wrapped = await crypto.subtle.wrapKey('raw',aes,rsa,{name:'RSA-OAEP'});
        var aad = new TextEncoder().encode(JSON.stringify([1,bindingOwner,item.client_id,purpose]));
        var ciphertext = await crypto.subtle.encrypt({name:'AES-GCM',iv:iv,additionalData:aad},aes,new TextEncoder().encode(JSON.stringify(value)));
        return {version:1,kid:record.kid,owner_id:bindingOwner,iv:encode(iv),wrapped_key:encode(wrapped),ciphertext:encode(ciphertext)};
      }
      var result = {client_id:item.client_id,sealed_alert:await part(payload,purpose)};
      if (Object.prototype.hasOwnProperty.call(item,'owner_id')) result.owner_id = item.owner_id;
      if (location.lat !== null && location.lat !== undefined && location.lng !== null && location.lng !== undefined)
        result.sealed_location = await part(location,purpose+'-location');
      return result;
    } catch (_) {
      if (!allowMinimal) throw new Error('queue_protection_incomplete');
      // Emergency availability wins over optional GPS. Never persist sensitive
      // unencrypted location/token/time merely because crypto/key cache failed.
      emit({type:'privacy_limited',client_id:item.client_id});
      return {client_id:item.client_id,owner_id:item.owner_id,client_ts:null,
        lat:null,lng:null,location_accuracy:null,location_recorded_at:null};
    }
  }
  function protectExisting(item) {
    if (item.sealed_alert) return Promise.resolve(item);
    return sealPayload(item,false).then(function (sealed) {
      return openDb().then(function (db) { return new Promise(function (resolve,reject) {
        var tx = db.transaction(STORE,'readwrite'), store = tx.objectStore(STORE), read = store.get(item.client_id);
        read.onsuccess = function () {
          if (JSON.stringify(read.result) !== JSON.stringify(item)) { tx.abort(); return; }
          try { store.put(sealed); } catch (_) { try { tx.abort(); } catch (_) {} }
        };
        tx.oncomplete = function () { resolve(sealed); };
        tx.onabort = tx.onerror = function () { reject(new Error('queue_protection_incomplete')); };
      }); });
    }).catch(function () { emit({type:'privacy_limited',client_id:item.client_id}); return item; });
  }
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
    // Non-secret account metadata. The HttpOnly cookie remains the authority.
  var OWNER_KEY = 'clear-sky-alert-owner-v1';
  var activeOwner = null;

  function ownershipError(message) {
    var error = new Error(message);
    error.status = 409;
    return error;
  }

  function validOwner(value) {
    return Number.isSafeInteger(value) && value > 0;
  }

  function savedOwner() {
    try {
      var value = localStorage.getItem(OWNER_KEY);
      if (!value || !/^[1-9][0-9]*$/.test(value)) return null;
      var owner = Number(value);
      return validOwner(owner) ? owner : null;
    } catch (_) {
      return null;
    }
  }

  function refreshOwner() {
    return request('/api/device', {}, 3000).then(function (body) {
      if (!body || !validOwner(body.account_id)) {
        throw ownershipError('device_identity_unavailable');
      }

      var owner = body.account_id;
      try {
        localStorage.setItem(OWNER_KEY, String(owner));
      } catch (_) {}

      // An open page must not silently switch to another person's account.
      if (activeOwner !== null && activeOwner !== owner) {
        throw ownershipError('account_changed_reload_required');
      }

      activeOwner = owner;
      rememberPublic(body.sealing_key);
      return owner;
    }, function (error) {
      if (error.status === 401 || error.status === 403) {
        activeOwner = null;
        try { localStorage.removeItem(OWNER_KEY); } catch (_) {}
      }
      throw error;
    });
  }

  function captureOwner() {
    function offlineOwner() {
      var owner = activeOwner || savedOwner();
      if (!validOwner(owner)) {
        throw ownershipError('connect_device_before_offline_capture');
      }
      activeOwner = owner;
      return owner;
    }

    if (navigator.onLine === false) {
      return Promise.resolve().then(offlineOwner);
    }

    return refreshOwner().catch(function (error) {
      // Never override an authentication failure or identity mismatch.
      if (error.status && error.status < 500) throw error;
      return offlineOwner();
    });
  }
    function queueAlert(item) {
    if (
      !item ||
      typeof item.client_id !== 'string' ||
      !item.client_id.trim()
    ) {
      return Promise.reject(ownershipError('client_id_required'));
    }

    // Copy immediately so later caller mutations cannot alter this capture.
    var captured = Object.assign({}, item);

    return captureOwner().then(function (owner) {
      if (
        Object.prototype.hasOwnProperty.call(captured, 'owner_id') &&
        captured.owner_id !== owner
      ) {
        throw ownershipError('queue_owner_mismatch');
      }

      var bound = Object.assign({}, captured, {owner_id: owner});

      return sealPayload(bound,true).then(function (sealed) { return openDb().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, 'readwrite');
          var store = tx.objectStore(STORE);
          var failure = null;

          tx.oncomplete = function () { resolve(); };
          tx.onerror = tx.onabort = function () {
            reject(failure || new Error('storage_unavailable'));
          };

          var existing = store.get(bound.client_id);
          existing.onsuccess = function () {
            // Never overwrite or adopt an existing pending record.
            if (existing.result !== undefined) {
              failure = ownershipError('queued_record_already_exists');
              tx.abort();
              return;
            }
            try { store.put(sealed); }
            catch (_) { try { tx.abort(); } catch (_) {} }
          };
        });
      }); }).then(function () {
        emit({type: 'queued', client_id: bound.client_id});
      });
    });
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
    if (!validOwner(item.owner_id)) {
      return Promise.reject(
        ownershipError('legacy_queue_owner_unknown')
      );
    }

    return refreshOwner().then(function (owner) {
      if (owner !== item.owner_id) {
        throw ownershipError('queue_owner_mismatch');
      }
      return protectExisting(item);
    }).then(function (protectedItem) {
      item = protectedItem;
      return locationPermitted();
    }).then(function (allowed) {
      var payload = Object.assign({}, item);
      delete payload.owner_id;

      if (payload.sealed_alert) {
        payload.suppress_location = !allowed;
        if (!allowed) delete payload.sealed_location;
      } else if (!allowed) {
        payload.lat = payload.lng = null;
        payload.location_accuracy = payload.location_recorded_at = null;
      }

      return request('/api/alerts', {
        method: 'POST',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          'X-Queue-Owner': String(item.owner_id)
        },
        body: JSON.stringify(payload)
      }, 15000);
    }).then(function (receipt) {
      if (
        !receipt ||
        !Number.isInteger(receipt.id) ||
        receipt.id < 1 ||
        receipt.client_id !== item.client_id
      ) {
        throw new Error('invalid_receipt');
      }

      return removeAlert(item.client_id).then(function () {
        emit({
          type: 'sent',
          client_id: item.client_id,
          receipt: receipt
        });
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
          // Protection does not adopt an owner or authorize a send. Even blocked
          // legacy/foreign records retain their IDs and ownership metadata.
          return protectExisting(item).then(sendOne).catch(function (error) {
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
    var ownerReady = refreshOwner().catch(function () {
    return null;
  });
  global.CWQueue = {
    ready: ownerReady,
    captureOwner: captureOwner,
    refreshOwner: refreshOwner,
    queueAlert: queueAlert, flushQueue: flushQueue,
    queueSize: function () { return allAlerts().then(function (items) { return items.length; }); },
    onFlushed: function (fn) { listeners.push(fn); },
    locationPermitted: locationPermitted,
    publicSealingKey: function () { var value = cachedPublic(); return value ? Object.assign({},value) : null; }
  };
})(window);
