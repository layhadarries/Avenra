
/* Clear Sky: survivor panic flow (Stage 2).
   States: ready -> holding -> countdown -> sending -> sent | queued.
   Write first, send second: every alert is saved to CWQueue before the network attempt. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  var state = 'ready', pending = null, exited = false, statusTimer = null;
  var holdTimer = null, tickTimer = null, countdownTimer = null;
  var views = ['ready', 'countdown', 'sending', 'sent', 'queued', 'error'];
  function setState(next) {
    state = next;
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
    if (!$('share-alert-location').checked || !navigator.geolocation) return Promise.resolve(null);
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
    }).then(function (data) {
      // Sent immediately 
      // Ask the queue to clear this entry: the same client_id makes that
      // request idempotent even if the server already saw it once
      window.CWQueue.flushQueue();
      onSent(data);
    }, onQueued);
  }

  function onSent(data) {
    if (state !== "sending" && state !== "queued") return;  // ignore a late echo once Done was pressed
    setState("sent");
    if (updateStatusDisplay(data)) return;
    startStatusPoll(data.id);
  }

  // alert is already safely written to IndexedDB
  // queue.js keeps retrying on its own,
  // with no retry button and no "failed" wording — its saved, not lost
  function onQueued() {
    setState("queued");
  }

  // fires whenever queue.js delivers any queued alert, including ones sent while this screen
  // wasn't open
  // -only react if it's the alert currently on screen
  if (window.CWQueue && window.CWQueue.onFlushed) {
    window.CWQueue.onFlushed(function (evt) {
      if (evt.type === "sent" && pending && evt.client_id === pending.clientId) {
        onSent(evt.receipt);
      }
    });
  }

  // ---------------------------------------------------------------- status

  var statusAlertId = null;

  function updateStatusDisplay(body) {
    var statusEl = $("help-status");
    if (!statusEl) return false;

    // Stage 3 referral lifecycle:
    // 1. Referral accepted -> Show shelter name and hours + Directions
    // 2. Referral pending / placed -> Show "Looking for a place for you"
    // 3. Acknowledged by responder -> "Someone has seen your alert"
    // 4. Default -> "Waiting"
    if (body.referral && body.referral.status === "accepted") {
      var name = body.referral.shelter_name || "Safe shelter";
      var hours = body.referral.hours ? " (" + body.referral.hours + ")" : "";
      var mapsQuery = encodeURIComponent(name + ", Cape Town");
      var directionsUrl = "https://maps.google.com/?q=" + mapsQuery;

      statusEl.innerHTML =
        '<div style="color: var(--green); font-weight: 700; margin-bottom: 0.35rem;">' +
          escapeHtml(name) + " has a place for you" + escapeHtml(hours) +
        "</div>" +
        '<a href="' + directionsUrl + '" target="_blank" rel="noopener noreferrer" class="btn btn-primary" style="margin-top: 0.5rem; text-decoration: none; display: inline-block;">' +
          "Get Directions" +
        "</a>";
      return true; // Stop polling
    }

    if ((body.referral && body.referral.status === "sent") || body.status === "placed") {
      statusEl.textContent = "Help status: Looking for a place for you";
      return false;
    }

    if (body.status === "acknowledged") {
      statusEl.textContent = "Help status: Someone has seen your alert";
      return false;
    }

    statusEl.textContent = "Help status: Waiting";
    return false;
  }

  function escapeHtml(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function startStatusPoll(id) {
    statusAlertId = id;
    clearInterval(timers.status);

    function checkStatus() {
      if (state !== "sent" || statusAlertId == null) return;

      request("/api/alerts/" + statusAlertId + "/status")
        .then(function (data) {
          if (state === "sent" && statusAlertId === id) {
            var isFinished = updateStatusDisplay(data);
            if (isFinished) {
              clearInterval(timers.status);
              timers.status = null;
            }
          }
        })
        .catch(function () { /* keep polling, the next tick retries */ });
    }

    timers.status = setInterval(checkStatus, STATUS_POLL_MS);
    checkStatus();
  }

  doneBtn.addEventListener("click", function () { if (state === "sent") resetToReady(); });
  queuedDoneBtn.addEventListener("click", function () {
    // Leaving the Queued screen does not cancel delivery: queue.js keeps trying in the background
    if (state === "queued") resetToReady();
  });
  function quickExit(event) {
    if (event) event.preventDefault();
    clearTimers();
    pending = null;
    setState("ready");
    location.replace("/survivor/cover.html");
  }

  quitBtn.addEventListener("click", quickExit);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") quickExit(e); });

  // ---------------------------------------------------------------- start

  setState("ready");
  warmUpLocation();
})();
