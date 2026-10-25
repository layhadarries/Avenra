/* Real emergency GPS only, memory-only and one-shot. Never reads weather storage. */
(function () {
  'use strict';
  var KEY = 'clear-sky-weather-tap-v1', generation = 0, recent = null, attempts = new Map();
  function foreground() { return !document.hidden && document.visibilityState === 'visible' && document.hasFocus(); }
  function preference(owner) {
    try {
      var pref = JSON.parse(localStorage.getItem(KEY) || 'null');
      return pref && pref.enabled === true && pref.location_enabled === true && pref.owner_id === owner;
    } catch (_) { return false; }
  }
  function active(attempt) {
    return attempts.get(attempt.id) === attempt && attempt.generation === generation && preference(attempt.owner) && foreground() && navigator.onLine !== false;
  }
  function suitable(fix) {
    return fix && Number.isFinite(fix.lat) && Math.abs(fix.lat) <= 90 && Number.isFinite(fix.lng) && Math.abs(fix.lng) <= 180 &&
      Number.isFinite(fix.location_accuracy) && fix.location_accuracy >= 0 && fix.location_accuracy <= 1000 &&
      Date.now() - Date.parse(fix.location_recorded_at) <= 120000 && Date.now() - Date.parse(fix.location_recorded_at) >= -10000;
  }
  async function request(url, options) {
    var controller = new AbortController(), timeout = setTimeout(function () { controller.abort(); },3000);
    try {
      var response = await fetch(url,Object.assign({credentials:'same-origin',cache:'no-store',signal:controller.signal},options));
      if (!response.ok) throw new Error('unavailable');
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  async function permission(attempt) {
    var value = await request('/api/alerts/location-permission',{});
    if (!active(attempt) || !value.allowed || value.owner_id !== attempt.owner) throw new Error('not_allowed');
    return value;
  }
  async function send(attempt) {
    if (!attempt.received || !attempt.fix || attempt.sending || !active(attempt)) return;
    attempt.sending = true;
    try {
      var current = await permission(attempt);
      if (current.grant !== attempt.grant || !suitable(attempt.fix)) return;
      await request('/api/alerts/by-client/' + encodeURIComponent(attempt.id) + '/location',{
        method:'POST',headers:{'Content-Type':'application/json','X-Queue-Owner':String(attempt.owner)},
        body:JSON.stringify(Object.assign({},attempt.fix,{location_consent_token:current.token}))});
    } catch (_) { /* Optional update failure never changes durable receipt or resends the alert. */ }
    finally { attempts.delete(attempt.id); }
  }
  async function acquire(attempt) {
    try {
      var allowed = await permission(attempt);
      attempt.grant = allowed.grant;
      var position = await new Promise(function (resolve,reject) {
        navigator.geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,maximumAge:0,timeout:10000});
      });
      if (!active(attempt)) return;
      var fix = {lat:position.coords.latitude,lng:position.coords.longitude,location_accuracy:position.coords.accuracy,
        location_recorded_at:new Date(position.timestamp).toISOString()};
      var current = await permission(attempt);
      if (current.grant !== allowed.grant || !suitable(fix)) return;
      attempt.fix = fix;
      recent = {owner:attempt.owner,grant:current.grant,token:current.token,issued:Date.now(),fix:fix};
      send(attempt);
    } catch (_) { attempts.delete(attempt.id); }
  }
  function clear() { generation++; recent = null; attempts.clear(); }
  window.CWEmergencyLocation = {
    start:function (owner,id) {
      if (!preference(owner) || !foreground() || navigator.onLine === false) return null;
      // No asynchronous work is awaited by the queue caller. GPS starts in a microtask.
      var attempt = {owner:owner,id:id,generation:generation};
      attempts.set(id,attempt);
      setTimeout(function () { attempts.delete(id); },120000);
      Promise.resolve().then(function () { if (active(attempt)) acquire(attempt); });
      return recent && recent.owner === owner && Date.now()-recent.issued < 110000 && suitable(recent.fix) ?
        Object.assign({},recent.fix,{location_consent_token:recent.token}) : null;
    },
    received:function (id) { var attempt = attempts.get(id); if (attempt) { attempt.received = true; send(attempt); } },
    clear:clear
  };
  ['pagehide','blur','offline','storage'].forEach(function (name) { window.addEventListener(name,clear); });
  document.addEventListener('visibilitychange',function () { if (document.hidden) clear(); });
})();
