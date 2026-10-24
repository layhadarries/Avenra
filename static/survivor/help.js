/* Nearby filtering stays in memory; origin coordinates are not uploaded. */
(function () {
  'use strict';
  var list = document.getElementById('shelter-list'), status = document.getElementById('freshness-tag');
  var button = document.getElementById('help-locate'), radius = document.getElementById('help-radius');
  var fix = null, directory = null, generation = 0, controller = null;
  function valid(lat, lng) { return typeof lat === 'number' && typeof lng === 'number' && Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180; }
  function distance(lat, lng) {
    var rad = Math.PI / 180, x = Math.sin((lat - fix.lat) * rad / 2), y = Math.sin((lng - fix.lng) * rad / 2);
    var a = Math.min(1, Math.max(0, x*x + Math.cos(fix.lat*rad)*Math.cos(lat*rad)*y*y));
    return 6371.0088 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }
  function notice(text) { list.replaceChildren(); var p = document.createElement('p'); p.textContent = text; list.appendChild(p); }
  function render() {
    var km = Number(radius.value);
    if (!fix || !directory || (km !== 25 && km !== 50)) { notice('Choose your location to see nearby services.'); return; }
    var nearby = directory.filter(function (row) { return row && valid(row.lat, row.lng); })
      .map(function (row) { return {row: row, km: distance(row.lat, row.lng)}; })
      .filter(function (item) { return item.km <= km; })
      .sort(function (a, b) { return a.km - b.km || Number(a.row.id) - Number(b.row.id); });
    list.replaceChildren();
    nearby.forEach(function (item) {
      var row = item.row, card = document.createElement('article'); card.className = 'shelter-card';
      var title = document.createElement('h2'); title.className = 'shelter-name'; title.textContent = row.name;
      var dist = document.createElement('p'); dist.className = 'shelter-dist'; dist.textContent = item.km.toFixed(1) + ' km away';
      var availability = document.createElement('p'); availability.textContent = 'Contact the service to confirm availability. Placement is not guaranteed.';
      var hours = document.createElement('p'); hours.textContent = 'Hours: ' + (row.hours || 'Contact to confirm');
      var languages = document.createElement('p'); languages.textContent = 'Languages: ' + (row.languages || 'Contact to confirm');
      var access = document.createElement('p'); access.textContent = row.walk_ins ? 'Walk-ins listed; contact before travelling.' : 'Contact the service about access and referrals.';
      var link = document.createElement('a'); link.className = 'directions-btn'; link.textContent = 'Directions';
      link.href = 'https://maps.google.com/?q=' + encodeURIComponent(row.lat + ',' + row.lng); link.target = '_blank'; link.rel = 'noopener noreferrer';
      card.append(title, dist, availability, hours, languages, access, link); list.appendChild(card);
    });
    if (!nearby.length) notice('No listed services found within ' + km + ' km. Try 50 km or contact a support service directly.');
    status.textContent = 'Within ' + km + ' km · availability unconfirmed';
  }
  function locate() {
    generation++; var token = generation; fix = null; directory = null;
    if (controller) controller.abort();
    notice('Checking your location…'); status.textContent = 'Location needed'; button.disabled = true;
    if (!navigator.geolocation) { button.disabled = false; notice('Location is unavailable. Nearby results cannot be confirmed.'); return; }
    var finished = false, timer = setTimeout(failed, 5000);
    function failed() {
      if (token !== generation || finished) return;
      finished = true; clearTimeout(timer); button.disabled = false;
      notice('Location is unavailable. Allow location access and try again; no unfiltered directory is shown.');
    }
    navigator.geolocation.getCurrentPosition(function (position) {
      if (token !== generation || finished) return;
      if (!valid(position.coords.latitude, position.coords.longitude)) { failed(); return; }
      finished = true; clearTimeout(timer); fix = {lat: position.coords.latitude, lng: position.coords.longitude};
      controller = new AbortController(); var current = controller;
      var timeout = setTimeout(function () { current.abort(); }, 10000);
      fetch('/api/shelters', {headers: {'X-Device-Token': 'demo-device'}, credentials: 'same-origin', cache: 'no-store', signal: current.signal})
        .then(function (response) { if (!response.ok) throw new Error('unavailable'); return response.json(); })
        .then(function (body) {
          if (token !== generation) return;
          if (!body || !Array.isArray(body.shelters)) throw new Error('invalid_response'); directory = body.shelters; render();
        }).catch(function () {
          if (token !== generation) return;
          fix = null; directory = null; status.textContent = 'Directory unavailable'; notice('Could not load nearby services. Reconnect and try again.');
        }).then(function () { clearTimeout(timeout); if (token === generation) button.disabled = false; });
    }, failed, {enableHighAccuracy: false, timeout: 4000, maximumAge: 30000});
  }
  function clear() { generation++; if (controller) controller.abort(); fix = null; directory = null;
    button.disabled = false; status.textContent = 'Location needed'; notice('Choose your location to see nearby services.'); }
  button.addEventListener('click', locate); radius.addEventListener('change', render);
  window.addEventListener('pagehide', clear);
  window.addEventListener('pageshow', function (event) { if (event.persisted) clear(); });
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') clear(); });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { clear(); location.replace('/survivor/cover.html'); } });
  clear();
})();
