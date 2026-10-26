/* Passphrase entry for evidence only. Emergency queue/gesture never calls this. */
(function () {
  'use strict';
   var owner = null, configured = null, busy = false, unlockToken = null, lockEpoch = 0;
  var token = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? 'demo-device' : '';
  var form = document.getElementById('vault-form'), panel = document.getElementById('vault-panel');
  var content = document.getElementById('diary-private'), status = document.getElementById('vault-status');
  var input = document.getElementById('vault-passphrase'), confirmation = document.getElementById('vault-confirmation');
  var button = document.getElementById('vault-submit');
  function privateHeaders(extra,grant) {
    var headers = Object.assign({},extra || {});
    if (grant) headers['X-Vault-Unlock'] = grant;
    return headers;
  }
  async function request(action,body,keepalive,grant) {
    var controller = new AbortController(), timer = setTimeout(function () { controller.abort(); },5000);
    try {
      var response = await fetch('/api/vault'+(action ? '/'+action : ''),{
        method:body ? 'POST' : 'GET',credentials:'same-origin',cache:'no-store',keepalive:!!keepalive,signal:controller.signal,
        headers:privateHeaders({'Content-Type':'application/json','X-Device-Token':token},grant),body:body ? JSON.stringify(body) : undefined});
      if (!response.ok) throw new Error('server_vault_unavailable');
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function locked() {
    var oldGrant = unlockToken; unlockToken = null; lockEpoch++;
    content.hidden = true; panel.hidden = false; input.value = ''; confirmation.value = '';
    status.textContent = 'Diary locked. Enter your vault passphrase. Saved queue records have not been removed.';
    if (oldGrant && navigator.onLine !== false) request('lock',{},true,oldGrant).catch(function () {});
  }
  window.CWVaultUI = {owner:function () { return owner; },
    headers:function (extra) { return privateHeaders(extra,unlockToken); },
    unlocked:function () { return owner !== null && CWVault.unlocked(owner); }};
  window.addEventListener('vault-locked',locked);
  window.addEventListener('online',function () {
    // An offline-only passphrase unlock cannot mint server authority. Ask again
    // after reconnect rather than persist the phrase or reuse browser cookies.
    if (!unlockToken && owner !== null && CWVault.unlocked(owner)) CWVault.lock();
  });
  form.addEventListener('submit',async function (event) {
    event.preventDefault(); if (busy || owner === null) return;
    var phrase = input.value, confirmationValue = confirmation.value, epoch = lockEpoch;
    input.value = ''; confirmation.value = ''; busy = true; button.disabled = true;
    try {
      if (await CWQueue.captureOwner() !== owner) throw new Error('account_changed');
      var local = CWVault.configured(owner);
      if (navigator.onLine !== false) {
        var server = await request('',null);
        var grant = await request(server.configured ? 'unlock' : 'setup',server.configured ?
          {passphrase:phrase} : {passphrase:phrase,confirmation:confirmationValue});
        if (epoch !== lockEpoch) {
          request('lock',{},true,grant.unlock_token).catch(function () {});
          throw new Error('unlock_cancelled');
        }
        unlockToken = grant.unlock_token;
        configured = true;
      } else if (!local) throw new Error('initial_setup_requires_connection');
      if (local) await CWVault.unlock(owner,phrase);
      else await CWVault.setup(owner,phrase);
      if (epoch !== lockEpoch) throw new Error('unlock_cancelled');
      await CWDiary.migrateVault(owner);
      if (epoch !== lockEpoch) throw new Error('unlock_cancelled');
      content.hidden = false; panel.hidden = true;
      window.dispatchEvent(new CustomEvent('vault-unlocked'));
      document.getElementById('diary-note').focus();
    } catch (_) {
      CWVault.lock();
      status.textContent = 'Could not unlock or finish protecting the diary. Check your passphrase, connection and storage. Existing records are retained.';
    } finally { phrase = null; busy = false; button.disabled = owner === null; }
  });
  document.addEventListener('DOMContentLoaded',async function () {
    try {
      await CWQueue.ready; owner = await CWQueue.captureOwner();
      if (navigator.onLine !== false) configured = (await request('',null)).configured;
      confirmation.parentElement.hidden = CWVault.configured(owner) || configured === true;
      button.disabled = false;
      status.textContent = CWVault.configured(owner) || configured ? 'Enter your separate diary-vault passphrase.' :
        'Create a strong diary-vault passphrase (15–128 characters). Keep it separately; it is not your four-digit screen PIN. Initial setup needs a connection.';
    } catch (_) { status.textContent = 'Reconnect your private device before setting up the diary vault.'; }
  });
})();
