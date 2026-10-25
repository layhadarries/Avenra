/* Explicit, verified, account-bound opt-in. No alert is sent by this setup. */
(function () {
  'use strict';
  var KEY = 'clear-sky-weather-tap-v1', STATUS = 'clear-sky-weather-tap-status-v1';
  var checkbox = document.getElementById('tap-understood'), enable = document.getElementById('tap-enable');
  var status = document.getElementById('tap-setup-status'), owner = null, busy = false, operation = 0;
  async function pairedOwner() {
    var controller = new AbortController(), timeout = setTimeout(function () { controller.abort(); },5000);
    try {
      // No demo header: setup requires an actual paired cookie, even in local tests.
      var response = await fetch('/api/device',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error('pairing_required');
      var body = await response.json();
      if (!body.paired || !Number.isSafeInteger(body.account_id) || body.account_id <= 0) throw new Error('pairing_required');
      return body.account_id;
    } finally { clearTimeout(timeout); }
  }
  function controls() { enable.disabled = busy || !owner || !checkbox.checked; }
  checkbox.addEventListener('change',function () {
    if (busy && !checkbox.checked) { operation++; busy = false; status.textContent = 'Enable request cancelled. Use Disable to turn off an existing opt-in.'; }
    controls();
  });
  enable.addEventListener('click',async function () {
    if (busy || !owner || !checkbox.checked) return;
    var revision = ++operation;
    busy = true; controls();
    try {
      var verified = await pairedOwner();
      if (revision !== operation || !checkbox.checked) return;
      if (verified !== owner || await CWQueue.refreshOwner() !== owner) throw new Error('account_changed');
      await CWQueue.queueSize();
      if (revision !== operation || !checkbox.checked) return;
      var value = JSON.stringify({version:1,setup_version:1,enabled:true,owner_id:owner,
        location_enabled:document.getElementById('tap-location').checked});
      localStorage.setItem(KEY,value);
      if (localStorage.getItem(KEY) !== value) throw new Error('storage_unavailable');
      status.textContent = 'Four-tap alerts are ON for this connected account. Open the weather page to use them. Experimental; not field-proven.';
    } catch (_) {
      if (revision !== operation) return;
      status.textContent = 'Could not enable tap alerts. Confirm your private connection and browser storage, then reload this setup. No alert was sent.';
      owner = null; checkbox.disabled = true;
    } finally { if (revision === operation) { busy = false; controls(); } }
  });
  document.getElementById('tap-disable').addEventListener('click',function () {
    operation++; busy = false;
    try {
      localStorage.removeItem(KEY); localStorage.removeItem(STATUS);
      checkbox.checked = false; controls();
      status.textContent = 'Weather tap alerts are OFF. Saved alerts and other app data have not been removed.';
    } catch (_) { status.textContent = 'Could not confirm tap alerts were disabled. Check browser storage and try again.'; }
  });
  (async function () {
    if (typeof window.PointerEvent !== 'function' || !window.crypto || !crypto.getRandomValues) {
      status.textContent = 'This browser does not support weather tap alerts. Keep using the normal HELP button.';
      return;
    }
    try {
      owner = await pairedOwner();
      await CWQueue.ready;
      if (await CWQueue.refreshOwner() !== owner) throw new Error('account_changed');
      checkbox.disabled = false;
      var saved = JSON.parse(localStorage.getItem(KEY) || 'null');
      document.getElementById('tap-location').checked = !!(saved && saved.owner_id === owner && saved.location_enabled === true);
      status.textContent = saved && saved.enabled === true && saved.setup_version === 1 && saved.owner_id === owner ?
        'Four-tap alerts are currently ON for this connected account.' : 'Four-tap alerts are OFF. Read the explanation and explicitly opt in to enable them.';
      controls();
    } catch (_) { owner = null; controls(); status.textContent = 'Tap alerts are unavailable until this browser is privately paired and the connection can be verified. Use a private invitation from your support contact.'; }
  })();
})();
