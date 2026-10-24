
/* Cape Weather: survivor panic flow (Stage 2).
   States: ready -> holding -> countdown -> sending -> sent | queued.
   Write first, send second: every alert is saved to CWQueue before the network attempt. */
(function () {
  "use strict";

  var DEVICE_TOKEN = "demo-device";
  var HOLD_MS = 1000;
  var COUNTDOWN_S = 5;
  var LOCATION_TIMEOUT_MS = 4000;
  var REQUEST_TIMEOUT_MS = 25000;
  var STATUS_POLL_MS = 5000;

  function $(id) { return document.getElementById(id); }

  var panicBtn = $("panic-btn");
  var undoBtn = $("undo-btn");
  var doneBtn = $("done-btn");
  var queuedDoneBtn = $("queued-done-btn");
  var quitBtn = $("quick-exit");
  var countdownText = $("countdown-text");
  var countdownFill = $("countdown-fill");
  var helpStatus = $("help-status");

  var VIEWS = {
    ready: $("view-ready"),
    countdown: $("view-countdown"),
    sending: $("view-sending"),
    sent: $("view-sent"),
    queued: $("view-queued")
  };
  var VIEW_FOR = {
    ready: "ready", holding: "ready", countdown: "countdown",
    sending: "sending", sent: "sent", queued: "queued"
  };

  var state = "ready";
  var timers = { hold: null, holdTick: null, countdown: null, countdownTick: null, status: null };
  var pending = null;  // { clientId, clientTs, location (Promise, never rejects), payload }

  function round6(n) { return Math.round(n * 1e6) / 1e6; }

  function newClientId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  function clearTimers() {
    clearTimeout(timers.hold);
    clearInterval(timers.holdTick);
    clearTimeout(timers.countdown);
    clearInterval(timers.countdownTick);
    clearInterval(timers.status);
    Object.keys(timers).forEach(function (k) { timers[k] = null; });
  }

  function setState(next) {
    state = next;
    var show = VIEW_FOR[next];
    Object.keys(VIEWS).forEach(function (k) { VIEWS[k].hidden = (k !== show); });
    if (next !== "holding") panicBtn.style.setProperty("--p", "0");
  }

  function resetToReady() {
    clearTimers();
    pending = null;
    setState("ready");
  }

  function getLocation() {
    return new Promise(function (resolve) {
      if (!("geolocation" in navigator)) { resolve(null); return; }
      var settled = false;
      function done(value) { if (!settled) { settled = true; resolve(value); } }
      var giveUp = setTimeout(function () { done(null); }, LOCATION_TIMEOUT_MS);
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          clearTimeout(giveUp);
          done({ lat: round6(pos.coords.latitude), lng: round6(pos.coords.longitude) });
        },
        function () { clearTimeout(giveUp); done(null); },
        { enableHighAccuracy: true, timeout: LOCATION_TIMEOUT_MS, maximumAge: 30000 }
      );
    });
  }

  function warmUpLocation() {
    if (!("geolocation" in navigator)) return;
    navigator.geolocation.getCurrentPosition(function () {}, function () {}, {
      enableHighAccuracy: false, timeout: 10000, maximumAge: 300000
    });
  }

  function request(url, options) {
    var opts = Object.assign({ credentials: "same-origin", cache: "no-store" }, options || {});
    opts.headers = Object.assign({ "X-Device-Token": DEVICE_TOKEN }, (options && options.headers) || {});
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, REQUEST_TIMEOUT_MS);
    opts.signal = ctrl.signal;
    return fetch(url, opts).then(function (res) {
      clearTimeout(timer);
      if (!res.ok) throw new Error("http " + res.status);
      return res.json();
    }, function (err) {
      clearTimeout(timer);
      throw err;
    });
  }

  // ---------------------------------------------------------------- hold

  function startHold(e) {
    if (state !== "ready") return;
    if (e.cancelable) e.preventDefault();

    pending = { clientId: newClientId(), clientTs: new Date().toISOString(), location: getLocation(), payload: null };
    setState("holding");

    var started = Date.now();
    timers.holdTick = setInterval(function () {
      var pct = Math.min(100, (Date.now() - started) / HOLD_MS * 100);
      panicBtn.style.setProperty("--p", pct.toFixed(1));
    }, 50);
    timers.hold = setTimeout(startCountdown, HOLD_MS);
  }

  function cancelHold() {
    if (state !== "holding") return;
    clearTimers();
    pending = null;
    setState("ready");
  }

  panicBtn.addEventListener("pointerdown", startHold);
  ["pointerup", "pointerleave", "pointercancel"].forEach(function (ev) { panicBtn.addEventListener(ev, cancelHold); });
  panicBtn.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  // ---------------------------------------------------------------- countdown

  function paintCountdown(left) {
    countdownText.textContent = left + (left === 1 ? " second" : " seconds") + " to undo";
    countdownFill.style.width = (left / COUNTDOWN_S * 100) + "%";
  }

  function startCountdown() {
    if (state !== "holding" || !pending) return;
    clearInterval(timers.holdTick);
    clearTimeout(timers.hold);
    timers.holdTick = null;
    timers.hold = null;

    setState("countdown");
    var left = COUNTDOWN_S;
    paintCountdown(left);

    timers.countdownTick = setInterval(function () { left -= 1; if (left > 0) paintCountdown(left); }, 1000);
    timers.countdown = setTimeout(function () {
      clearInterval(timers.countdownTick);
      timers.countdownTick = null;
      sendAlert();
    }, COUNTDOWN_S * 1000);

    undoBtn.focus();
  }

  // Undo stops the timer and makes no network call
  // ! nothing is queued before this point
  undoBtn.addEventListener("click", function () {
    if (state === "countdown") resetToReady();
  });

  // ---------------------------------------------------------------- send

  function sendAlert() {
    if (!pending) return;
    setState("sending");

    pending.location.then(function (fix) {
      pending.payload = {
        client_id: pending.clientId,
        lat: fix ? fix.lat : null,
        lng: fix ? fix.lng : null,
        client_ts: pending.clientTs
      };
      // Write first: the alert is safe on this phone before any network attempt
      return window.CWQueue.queueAlert(pending.payload).then(function () {
        return request("/api/alerts", {
          method: "POST",
          keepalive: true,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(pending.payload)
        });
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

  // ---------------------------------------------------------------- quick exit

  // Clears on-screen state only  
  // - queued alert is untouched in IndexedDB and still delivers
  // because cover.html also loads queue.js
  // - in-flight send uses keepalive, so it completes too
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
