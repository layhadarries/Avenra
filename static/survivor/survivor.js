/* Stage 2 panic flow. Evaluation authentication only. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  var state = 'ready', pending = null, exited = false, statusTimer = null;
  var holdTimer = null, tickTimer = null, countdownTimer = null;
  var views = ['ready', 'countdown', 'sending', 'sent', 'queued', 'error'];
  function setState(next, force) {
    state = next;
    if (!force && $('view-more') && !$('view-more').hidden) return;
    var view = next === 'holding' ? 'ready' : next;
    views.forEach(function (name) { $('view-' + name).hidden = name !== view; });
    if ($('view-more')) $('view-more').hidden = true;
    $('panic-btn').style.setProperty('--p', '0');
  }
  function clearTimers() {
    clearTimeout(holdTimer); clearTimeout(countdownTimer);
    clearInterval(tickTimer); clearInterval(statusTimer);
    holdTimer = tickTimer = countdownTimer = statusTimer = null;
  }
  function reset() { clearTimers(); pending = null; setState('ready'); }
  function newId() {
    var bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }
  function getLocation() {
    // Explicit per-alert choice plus current server consent; unknown/offline means no GPS.
    var shareBox = $('share-alert-location') || $('share-location-toggle');
    if (!shareBox || !shareBox.checked || !navigator.geolocation) return Promise.resolve(null);
    return window.CWQueue.locationPermitted().then(function (allowed) {
      if (!allowed || exited) return null;
      return new Promise(function (resolve) {
        var finished = false;
        var timer = setTimeout(function () { done(null); }, 4000);
        function done(value) { if (!finished) { finished = true; clearTimeout(timer); resolve(value); } }
        navigator.geolocation.getCurrentPosition(function (position) {
          var coords = position.coords, stamp = new Date(position.timestamp);
          if (!Number.isFinite(coords.latitude) || !Number.isFinite(coords.longitude)) return done(null);
          done({lat: coords.latitude, lng: coords.longitude,
            location_accuracy: Number.isFinite(coords.accuracy) && coords.accuracy >= 0 ? coords.accuracy : null,
            location_recorded_at: Number.isFinite(stamp.getTime()) ? stamp.toISOString() : null});
        }, function () { done(null); }, {enableHighAccuracy: true, timeout: 4000, maximumAge: 30000});
      });
    }).catch(function () { return null; });
  }
  function startHold(event) {
    if (state !== 'ready' || exited) return;
    if (event.cancelable) event.preventDefault();
    pending = {clientId: newId(), clientTs: new Date().toISOString(), phase: 'preparing'};
    setState('holding');
    var start = Date.now();
    tickTimer = setInterval(function () {
      $('panic-btn').style.setProperty('--p', String(Math.min(100, (Date.now() - start) / 10)));
    }, 50);
    holdTimer = setTimeout(startCountdown, 1000);
  }
  function cancelHold() { if (state === 'holding') reset(); }
  function startCountdown() {
    if (state !== 'holding' || !pending || exited) return;
    clearTimers(); setState('countdown');
    var left = 5;
    function paint() { $('countdown-text').textContent = left + ' seconds to undo'; $('countdown-fill').style.width = left / 5 * 100 + '%'; }
    paint(); tickTimer = setInterval(function () { left = Math.max(0, left - 1); paint(); }, 1000);
    countdownTimer = setTimeout(sendAlert, 5000); $('undo-btn').focus();
  }
  function sendAlert() {
    if (!pending || exited) return;
    clearTimers(); setState('sending');
    var attempt = pending;
    getLocation().then(function (fix) {
      // Exit before queueing cancels preparation. After saving starts, let it commit.
      if (exited || pending !== attempt) return;
      var payload = Object.assign({client_id: attempt.clientId, client_ts: attempt.clientTs,
        lat: null, lng: null, location_accuracy: null, location_recorded_at: null}, fix || {});
      attempt.phase = 'saving';
      return window.CWQueue.queueAlert(payload).then(function () {
        attempt.phase = 'saved';
        if (!exited && pending === attempt) setState('queued');
        return window.CWQueue.flushQueue();
      });
    }).catch(function () {
      if (exited || pending !== attempt) return;
      $('save-error').textContent = 'Could not confirm this alert was saved. Try again. No receipt has been confirmed.';
      setState('error');
    });
  }
  function showStatus(body) {
    var referral = body.referral, message = 'Help status: Waiting';
    if (referral && referral.status === 'placed') {
      message = 'Help status: Placement confirmed with ' + (referral.shelter_name || 'the selected service') + '.';
    } else if (referral && referral.status === 'accepted') {
      message = 'Help status: Referral accepted by ' + (referral.shelter_name || 'the selected service') + '. Placement is not yet confirmed.';
    } else if (referral && referral.status === 'sent') {
      message = 'Help status: Your referral is awaiting a response. Placement is not yet confirmed.';
    } else if (referral && referral.status === 'declined') {
      message = 'Help status: This service could not accept the referral. Placement is not confirmed.';
    } else if (body.status === 'resolved') {
      message = 'Help status: A responder marked this alert resolved.';
    } else if (body.status === 'acknowledged' || body.status === 'in_progress') {
      message = 'Help status: Someone has seen your alert';
    }
    $('help-status').textContent = message;
  }
  function onSent(receipt) {
    if (exited || !pending || receipt.client_id !== pending.clientId) return;
    clearInterval(statusTimer); setState('sent'); showStatus(receipt);
    var attempt = pending, busy = false;
    function poll() {
      if (busy || exited || pending !== attempt || state !== 'sent') return;
      busy = true;
      var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 10000);
      fetch('/api/alerts/' + receipt.id + '/status', {cache: 'no-store', credentials: 'same-origin',
        headers: {'X-Device-Token': ((typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) ? 'demo-device' : '')}, signal: ctrl.signal})
        .then(function (response) { if (!response.ok) throw new Error('unavailable'); return response.json(); })
        .then(function (body) {
          if (!exited && pending === attempt && state === 'sent' && body && typeof body.status === 'string') showStatus(body);
        }).catch(function () {}).then(function () { busy = false; clearTimeout(timer); });
    }
    statusTimer = setInterval(poll, 5000); poll();
  }
  window.CWQueue.onFlushed(function (event) {
    if (event.type === 'sent') onSent(event.receipt);
    if (event.type === 'blocked' && !exited && pending && pending.clientId === event.client_id) {
      setState('queued');
      $('queue-message').textContent = 'Saved on this phone, but the service could not accept it. Reopen after access is restored. Help has not been confirmed.';
    }
  });
  function quickExit(event) {
    if (event) event.preventDefault();
    exited = true; clearTimers(); pending = null;
    location.replace('/survivor/cover.html');
  }
  $('panic-btn').addEventListener('pointerdown', startHold);
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (name) { $('panic-btn').addEventListener(name, cancelHold); });
  $('panic-btn').addEventListener('contextmenu', function (event) { event.preventDefault(); });
  // Keyboard and assistive technology can trigger the same hold/countdown flow.
  $('panic-btn').addEventListener('keydown', function (event) { if (event.key === ' ' || event.key === 'Enter') startHold(event); });
  $('panic-btn').addEventListener('keyup', cancelHold);
  $('panic-btn').addEventListener('blur', cancelHold);
  $('undo-btn').addEventListener('click', function () { if (state === 'countdown') reset(); });
  ['done-btn', 'queued-done-btn', 'error-done-btn'].forEach(function (id) { $(id).addEventListener('click', reset); });
  var qeBtn = $('quick-exit') || $('quick-exit-btn');
  if (qeBtn) qeBtn.addEventListener('click', quickExit);
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') quickExit(event); });
  window.addEventListener('pagehide', function () { exited = true; clearTimers(); pending = null; });
  window.addEventListener('pageshow', function (event) { if (event.persisted && exited) location.replace('/survivor/cover.html'); });
  window.CWPanic = {showHome: function () { if (!exited) setState(state, true); }};
  setState('ready');
})();
