/* Experimental opt-in weather gesture. Durable capture never waits for GPS. */
(function () {
  'use strict';
  if (!document.body.classList.contains('cover') || !window.CWQueue || !window.CWTapDetector || typeof window.PointerEvent !== 'function') return;
  var PREF = 'clear-sky-weather-tap-v1', STATUS = 'clear-sky-weather-tap-status-v1';
  var OWNER = 'clear-sky-alert-owner-v1', queue = window.CWQueue;
  var owner = null, armed = false, current = null, submitting = false, bufferedReceipt = null;
  var pollTimer = null, pollController = null, verifyController = null, verification = 0;
  var output = document.getElementById('weather-tap-status');
  function read(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; } }
  function validOwner(value) { return Number.isSafeInteger(value) && value > 0; }
  function preference() {
    var value = read(PREF);
    return value && value.version === 1 && value.setup_version === 1 && value.enabled === true && validOwner(value.owner_id) ? value : null;
  }
  function savedOwner() { try { var value = localStorage.getItem(OWNER); return /^[1-9][0-9]*$/.test(value || '') ? Number(value) : null; } catch (_) { return null; } }
  function pairedPreference() { var pref = preference(); return pref && pref.owner_id === owner && savedOwner() === owner; }
  function foreground() { return !document.hidden && document.visibilityState === 'visible' && document.hasFocus(); }
  function show(message) { output.textContent = message; output.hidden = !message; }
  function remember() {
    try { localStorage.setItem(STATUS, JSON.stringify(current)); } catch (_) { /* Queue durability does not depend on this display metadata. */ }
  }
  function restore() {
    var value = read(STATUS);
    current = value && value.owner_id === owner && /^tap-[a-f0-9]{32}$/.test(value.client_id || '') &&
      ['queued','received','acknowledged','resolved'].includes(value.phase) &&
      (value.phase === 'queued' || Number.isSafeInteger(value.alert_id) && value.alert_id > 0) ? value : null;
  }
  function describe() {
    if (!armed || !pairedPreference() || !current) { show(''); return; }
    if (current.phase === 'queued') show('Last tap alert: Saved on this phone · waiting to send or confirm receipt.');
    else if (current.phase === 'received') show('Last tap alert: Received by Avenra · responder acknowledgement not yet confirmed.');
    else if (current.phase === 'acknowledged') show('Last tap alert: Acknowledged by a responder · help is not guaranteed.');
    else if (current.phase === 'resolved') show('Last tap alert: A responder marked it resolved · help is not guaranteed.');
  }
  function stopPoll() {
    clearTimeout(pollTimer); pollTimer = null;
    if (pollController) pollController.abort(); pollController = null;
  }
  function disarm(clearPreference) {
    if (window.CWEmergencyLocation) window.CWEmergencyLocation.clear();
    armed = false; owner = null; current = null; bufferedReceipt = null;
    detector.reset(); stopPoll(); document.body.classList.remove('weather-tap-enabled'); show('');
    if (clearPreference) { try { localStorage.removeItem(PREF); localStorage.removeItem(STATUS); } catch (_) {} }
  }
  function modalOpen() {
    return Array.from(document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')).some(function (element) {
      return element.getClientRects().length > 0 && !element.closest('[hidden], [inert]');
    });
  }
  var excluded = 'button,a,input,textarea,select,label,form,summary,details,dialog,[role="button"],[role="link"],[role="dialog"],[tabindex],[contenteditable]:not([contenteditable="false"]),[data-no-emergency-taps]';
  function allowed(event) {
    if (!armed || !pairedPreference() || !foreground() || modalOpen()) return false;
    if (!event.target || !event.target.closest || event.target.closest(excluded)) return false;
    var focus = document.activeElement;
    return !focus || !focus.matches('input,textarea,select,[contenteditable]:not([contenteditable="false"])');
  }
  function serverState(status) {
    if (status === 'acknowledged' || status === 'in_progress') return 'acknowledged';
    return status === 'resolved' ? 'resolved' : 'received';
  }
  async function poll() {
    stopPoll();
    if (!armed || !pairedPreference() || !foreground() || !current || current.phase !== 'received' || navigator.onLine === false) return;
    var attempt = current, requestOwner = owner, controller = new AbortController(); pollController = controller;
    var timeout = setTimeout(function () { controller.abort(); },5000);
    try {
      var response = await fetch('/api/alerts/' + attempt.alert_id + '/status', {credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if (response.status === 401 || response.status === 403) { disarm(true); return; }
      if (!response.ok) return;
      var body = await response.json();
      if (armed && pairedPreference() && owner === requestOwner && current === attempt &&
          ['new','acknowledged','in_progress','resolved'].includes(body.status)) {
        attempt.phase = serverState(body.status); remember(); describe();
      }
    } catch (_) { /* A failed status check is not an acknowledgement. */ }
    finally {
      clearTimeout(timeout);
      if (pollController === controller) {
        pollController = null;
        if (armed && pairedPreference() && foreground() && current === attempt && attempt.phase === 'received') pollTimer = setTimeout(poll,5000);
      }
    }
  }
  function received(receipt) {
    if (!current || receipt.client_id !== current.client_id || !Number.isSafeInteger(receipt.id) || receipt.id < 1) return;
    if (!armed) { bufferedReceipt = receipt; return; }
    if (!pairedPreference() || current.owner_id !== owner) return;
    current.alert_id = receipt.id; current.phase = serverState(receipt.status);
    if (window.CWEmergencyLocation) window.CWEmergencyLocation.received(receipt.client_id);
    remember(); describe(); poll();
  }
  async function trigger() {
    if (submitting || !armed || !pairedPreference() || !foreground() || modalOpen()) return;
    if (current && current.owner_id === owner && current.phase === 'queued') { describe(); queue.flushQueue(); return; }
    var attempt = current && current.phase === 'error' && current.owner_id === owner ? current : {
      owner_id:owner, client_id:'tap-' + Array.from(crypto.getRandomValues(new Uint8Array(16)),function (byte) { return byte.toString(16).padStart(2,'0'); }).join(''),
      client_ts:new Date().toISOString(),phase:'saving'
    };
    current = attempt; submitting = true; stopPoll(); show('Saving alert on this phone…');
    try {
      var fix = window.CWEmergencyLocation ? window.CWEmergencyLocation.start(attempt.owner_id,attempt.client_id) : null;
      // Synchronous snapshot only; CWQueue starts saving before any GPS request.
      await queue.queueAlert(Object.assign({client_id:attempt.client_id,client_ts:attempt.client_ts,owner_id:attempt.owner_id,
        lat:null,lng:null,location_accuracy:null,location_recorded_at:null},fix));
      if (current === attempt && !['received','acknowledged','resolved'].includes(attempt.phase)) {
        attempt.phase = 'queued'; remember(); describe();
      }
      queue.flushQueue();
    } catch (error) {
      if (current === attempt && !['received','acknowledged','resolved'].includes(attempt.phase)) {
        attempt.phase = 'error';
        if (error.status === 401 || error.status === 403 || error.status === 409) {
          disarm(true); show('Alert not confirmed saved · reconnect your device before using tap alerts.');
        } else if (armed && pairedPreference()) show('Could not confirm saving this alert · try again or use HELP. No receipt confirmed.');
      }
      // If an earlier ambiguous attempt is already queued, only its original ID retries.
      queue.flushQueue();
    } finally { submitting = false; }
  }
  var detector = window.CWTapDetector({clock:function () { return performance.now(); },activate:trigger});
  ['down','move','up','cancel'].forEach(function (name) {
    document.addEventListener('pointer' + name,function (event) {
      if (!event.isTrusted) { detector.reset(); return; }
      detector[name](event,allowed(event));
    }, {capture:true,passive:true});
  });
  ['scroll','wheel'].forEach(function (name) { document.addEventListener(name,function () { detector.reset(); },{capture:true,passive:true}); });
  ['blur','pagehide','hashchange','popstate'].forEach(function (name) { window.addEventListener(name,function () { detector.reset(); stopPoll(); }); });
  new MutationObserver(function (records) {
    if (records.some(function (record) { return record.target.matches('dialog,[role="dialog"],[aria-modal="true"],#cv-modal'); })) detector.reset();
  }).observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden','open']});
  queue.onFlushed(function (event) {
    if (event.type === 'sent') received(event.receipt);
    if (event.type === 'blocked' && current && event.client_id === current.client_id && armed && pairedPreference()) {
      show('Saved on this phone · waiting to send. Device access needs checking; no receipt confirmed.');
    }
  });
  async function verify() {
    var pref = preference(), revision = ++verification;
    detector.reset();
    if (!pref) { disarm(false); return; }
    if (verifyController) verifyController.abort();
    var controller = new AbortController(); verifyController = controller;
    var timeout = setTimeout(function () { controller.abort(); },3000), verified = null;
    try {
      if (navigator.onLine !== false) {
        var response = await fetch('/api/device',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if (revision !== verification) return;
        if (response.status === 401 || response.status === 403) { disarm(true); return; }
        if (!response.ok) throw new Error('unavailable');
        var body = await response.json();
        if (!body.paired || body.account_id !== pref.owner_id) { disarm(true); return; }
        verified = body.account_id;
      } else verified = savedOwner();
    } catch (_) { verified = savedOwner(); }
    finally { clearTimeout(timeout); }
    if (revision !== verification || !preference() || preference().owner_id !== pref.owner_id) return;
    if (verified !== pref.owner_id || savedOwner() !== pref.owner_id) { disarm(false); return; }
    owner = verified; armed = true; document.body.classList.add('weather-tap-enabled');
    if (!current || current.owner_id !== owner) restore();
    describe();
    if (bufferedReceipt) { var receipt = bufferedReceipt; bufferedReceipt = null; received(receipt); }
    else poll();
  }
  document.addEventListener('visibilitychange',function () { detector.reset(); if (document.hidden) stopPoll(); else verify(); });
  ['focus','pageshow','online','offline'].forEach(function (name) { window.addEventListener(name,verify); });
  window.addEventListener('storage',function (event) {
    if ([PREF,OWNER].includes(event.key) || event.key === null) verify();
  });
  var pref = preference();
  if (pref) { owner = pref.owner_id; restore(); }
  Promise.resolve(queue.ready).then(verify);
})();
