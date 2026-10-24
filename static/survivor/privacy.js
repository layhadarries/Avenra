/* Prototype device authority; individual enrolment remains a release gate. */
(function () {
  'use strict';
  var keys = ['location_sharing', 'shelter_referral_sharing', 'diary_sharing'];
  var labels = {case_viewed: 'Viewed your case', diary_viewed: 'Viewed shared diary entries', diary_photo_viewed: 'Viewed a shared photo'};
  var banner = document.getElementById('status-banner'), list = document.getElementById('access-list');
  var more = document.getElementById('access-more'), refresh = document.getElementById('privacy-refresh');
  var generation = 0, controllers = [], cursor = null, ids = new Set(), historyBusy = false, saving = false, departed = false;
  function input(key) { return document.getElementById('consent-' + key); }
  function message(text) { banner.textContent = text; banner.hidden = !text; }
  function unknown() {
    keys.forEach(function (key) {
      input(key).disabled = true; input(key).checked = false;
      document.getElementById('title-' + key).textContent = 'Setting unavailable';
      document.getElementById('desc-' + key).textContent = 'Current sharing state has not been confirmed.';
    });
  }
  function request(url, options) {
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 10000);
    controllers.push(ctrl);
    options = Object.assign({credentials: 'same-origin', cache: 'no-store'}, options || {});
    options.headers = Object.assign({'X-Device-Token': 'demo-device'}, options.headers || {}); options.signal = ctrl.signal;
    function clean() { clearTimeout(timer); controllers = controllers.filter(function (x) { return x !== ctrl; }); }
    return fetch(url, options).then(function (response) {
      if (!response.ok) throw new Error('unavailable'); return response.json();
    }).then(function (body) { clean(); return body; }, function (error) { clean(); throw error; });
  }
  function applyConsents(body) {
    if (!body || !Array.isArray(body.consents)) throw new Error('invalid_response');
    var rows = keys.map(function (key) {
      var matches = body.consents.filter(function (row) { return row && row.item === key; });
      if (matches.length !== 1 || typeof matches[0].active !== 'boolean' || typeof matches[0].label !== 'string' || typeof matches[0].granted_to !== 'string') throw new Error('invalid_response');
      return matches[0];
    });
    rows.forEach(function (row) {
      input(row.item).checked = row.active; input(row.item).disabled = false;
      document.getElementById('title-' + row.item).textContent = row.label;
      document.getElementById('desc-' + row.item).textContent = 'Shared with: ' + row.granted_to;
    });
  }
  function clearHistory(text) {
    list.replaceChildren(); cursor = null; ids.clear(); more.hidden = true; more.disabled = true;
    if (text) { var row = document.createElement('p'); row.textContent = text; list.appendChild(row); }
  }
  function history(first, token) {
    if (historyBusy) return;
    historyBusy = true; more.disabled = true;
    var url = '/api/my-access?limit=20' + (!first && cursor ? '&cursor=' + encodeURIComponent(cursor) : '');
    request(url).then(function (body) {
      if (token !== generation || departed) return;
      if (!body || !Array.isArray(body.events) || !(body.next_cursor === null || (typeof body.next_cursor === 'string' && body.next_cursor.length > 0))) throw new Error('invalid_response');
      var rows = body.events.map(function (entry) {
        if (!entry || !Number.isInteger(entry.id) || typeof entry.actor_name !== 'string' || !Object.prototype.hasOwnProperty.call(labels, entry.action)) throw new Error('invalid_response');
        var row = document.createElement('div'), actor = document.createElement('div'), action = document.createElement('div'), time = document.createElement('div');
        row.className = 'access-row'; row.dataset.eventId = String(entry.id);
        actor.className = 'access-actor'; actor.textContent = entry.actor_name;
        action.className = 'access-action'; action.textContent = labels[entry.action];
        time.className = 'access-time'; var stamp = new Date(entry.viewed_at);
        time.textContent = typeof entry.viewed_at === 'string' && Number.isFinite(stamp.getTime()) ? stamp.toLocaleString('en-ZA') : 'Time unavailable';
        var detail = document.createElement('div'); detail.append(actor, action); row.append(detail, time);
        return {id: entry.id, node: row};
      });
      if (first) clearHistory('');
      rows.forEach(function (row) { if (!ids.has(row.id)) { ids.add(row.id); list.appendChild(row.node); } });
      if (!ids.size) clearHistory('No viewing activity recorded yet.');
      cursor = body.next_cursor; more.hidden = cursor === null; more.disabled = cursor === null;
    }).catch(function () {
      if (token === generation && !departed) clearHistory('Activity history could not be loaded. Reconnect and refresh.');
    }).then(function () { if (token === generation) historyBusy = false; });
  }
  function reload() {
    if (saving || departed) return;
    generation++; var token = generation;
    controllers.forEach(function (ctrl) { ctrl.abort(); }); controllers = []; historyBusy = false;
    unknown(); clearHistory('Loading activity history…'); message('Loading current sharing settings…');
    request('/api/consents').then(function (body) {
      if (token !== generation || departed) return;
      applyConsents(body); message('');
    }).catch(function () {
      if (token === generation && !departed) { unknown(); message('Current sharing settings could not be loaded. Reconnect and refresh; sharing status is unknown.'); }
    });
    history(true, token);
  }
  keys.forEach(function (key) {
    input(key).setAttribute('aria-labelledby', 'title-' + key);
    input(key).addEventListener('change', function () {
      if (saving || departed) return;
      saving = true; var token = generation, active = input(key).checked;
      keys.forEach(function (item) { input(item).disabled = true; }); refresh.disabled = true; message('Saving change…');
      request('/api/consents', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({item: key, active: active})}).then(function (body) {
        if (token !== generation || departed) return;
        applyConsents(body); if (input(key).checked !== active) throw new Error('unconfirmed_change'); message('Change saved.');
      }).catch(function () {
        if (token !== generation || departed) return;
        unknown(); message('Could not confirm the change. The server may have saved it. Reconnect and refresh to check the current setting.');
      }).then(function () { if (token === generation) { saving = false; refresh.disabled = false; } });
    });
  });
  more.addEventListener('click', function () { if (cursor && !departed) history(false, generation); });
  refresh.addEventListener('click', reload);
  function clearPrivate() {
    generation++; saving = false; historyBusy = false;
    controllers.forEach(function (ctrl) { ctrl.abort(); }); controllers = [];
    unknown(); clearHistory(''); message(''); refresh.disabled = false;
  }
  function quickExit(event) { if (event) event.preventDefault(); departed = true; clearPrivate(); location.replace('/survivor/cover.html'); }
  document.getElementById('quick-exit').addEventListener('click', quickExit);
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') quickExit(event); });
  window.addEventListener('pagehide', function () { departed = true; clearPrivate(); });
  window.addEventListener('pageshow', function (event) { if (event.persisted) { departed = false; reload(); } });
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') clearPrivate(); else if (!departed) reload(); });
  window.addEventListener('online', reload);
  window.addEventListener('offline', function () { clearPrivate(); message('Connection unavailable. Current sharing status has not been confirmed.'); });
  reload();
})();
