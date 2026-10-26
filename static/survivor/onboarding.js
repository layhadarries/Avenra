/* Hidden entry and optional account setup. Never persist names or contacts locally. */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  var modal = $('cv-modal'), lock = window.CWUnlock;
  var run = 0, entered = '', draft = '', confirmation = '', confirming = false;
  var device = null, busy = false, abort = null, previousFocus = null;
  function enterApp() {
    // Display-only re-entry after the existing PIN/device verification. Evidence
    // still requires its separate server-verified vault grant.
    try { localStorage.removeItem('clear-sky-exited-v1'); } catch (_) {}
    location.replace('/survivor/');
  }
  function active(version) { return version === run && !modal.hidden; }
  function headers() {
    return /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? {'X-Device-Token':'demo-device'} : {};
  }
  function dots(id, count) {
    $(id).querySelectorAll('.pin-dot').forEach(function (dot, index) { dot.classList.toggle('is-filled', index < count); });
  }
  function step(number) {
    document.querySelectorAll('[data-ob]').forEach(function (element) { element.hidden = Number(element.dataset.ob) !== number; });
    $('ob-progress').querySelectorAll('.ob-bar').forEach(function (bar, index) { bar.classList.toggle('is-active', index < number); });
    $('cv-sheet-title').textContent = ['Choose your screen lock', 'About you', 'Trusted contacts', 'Location & finish'][number - 1];
    var first = document.querySelector('[data-ob="' + number + '"] input, [data-ob="' + number + '"] button');
    if (first) first.focus();
  }
  function close() {
    run++;
    if (abort) abort.abort();
    modal.hidden = true;
    entered = draft = confirmation = '';
    device = null;
    busy = false;
    modal.querySelectorAll('input').forEach(function (input) { input.value = ''; });
    dots('pin-dots', 0); dots('ob-pin-dots', 0);
    if (previousFocus && previousFocus.focus) previousFocus.focus();
  }
  function keypad(id, digit, back) {
    ['1','2','3','4','5','6','7','8','9','Cancel','0','⌫'].forEach(function (value) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'pin-key' + (value.length > 1 || value === '⌫' ? ' is-muted' : '');
      button.textContent = value;
      button.addEventListener('click', function () {
        if (value === 'Cancel') close();
        else if (!busy) { if (value === '⌫') back(); else digit(value); }
      });
      $(id).appendChild(button);
    });
  }
  keypad('pin-pad', async function (digit) {
    if (entered.length >= 4) return;
    entered += digit;
    dots('pin-dots', entered.length);
    if (entered.length !== 4) return;
    var version = run;
    busy = true;
    try {
      var valid = await lock.verifyPin(entered);
      if (!active(version)) return;
      if (valid) { enterApp(); return; }
      $('pin-err').textContent = 'Incorrect alert code. Try again.';
    } catch (error) {
      if (active(version)) $('pin-err').textContent = error.message || 'Screen lock could not be checked.';
    } finally {
      if (active(version)) { entered = ''; dots('pin-dots', 0); busy = false; }
    }
  }, function () { entered = entered.slice(0, -1); dots('pin-dots', entered.length); });
  keypad('ob-pin-pad', function (digit) {
    $('ob-pin-err').textContent = '';
    if (!confirming) {
      draft += digit;
      dots('ob-pin-dots', draft.length);
      if (draft.length === 4) {
        confirming = true;
        $('ob-pin-prompt').textContent = 'Enter the same 4-digit PIN again to confirm.';
        dots('ob-pin-dots', 0);
      }
    } else {
      confirmation += digit;
      dots('ob-pin-dots', confirmation.length);
      if (confirmation.length === 4) {
        if (confirmation === draft) step(2);
        else {
          draft = confirmation = ''; confirming = false;
          $('ob-pin-err').textContent = 'PINs did not match. Choose your PIN again.';
          $('ob-pin-prompt').textContent = 'Choose a 4-digit screen PIN, or use device unlock below.';
          dots('ob-pin-dots', 0);
        }
      }
    }
  }, function () {
    if (confirming) { confirmation = confirmation.slice(0, -1); dots('ob-pin-dots', confirmation.length); }
    else { draft = draft.slice(0, -1); dots('ob-pin-dots', draft.length); }
  });

  async function deviceAction(enroll) {
    if (busy) return;
    var version = run, errorId = enroll ? 'ob-pin-err' : 'pin-err';
    busy = true; abort = new AbortController();
    $(errorId).textContent = 'Follow the verification prompt on your device…';
    try {
      if (enroll) {
        var credential = await lock.enrollDevice(abort.signal);
        if (!active(version)) return;
        device = credential; draft = confirmation = '';
        step(2);
      } else {
        await lock.unlockDevice(abort.signal);
        if (active(version)) enterApp();
      }
      if (active(version)) $(errorId).textContent = '';
    } catch (_) {
      if (active(version)) $(errorId).textContent = 'Device unlock was not completed. Try again or use your screen PIN.';
    } finally { if (active(version)) busy = false; }
  }
  $('ob-device-unlock').addEventListener('click', function () { deviceAction(true); });
  $('device-unlock').addEventListener('click', function () { deviceAction(false); });
  $('ob-next-2').addEventListener('click', function () { step(3); });
  $('ob-next-3').addEventListener('click', function () {
    for (var index = 1; index <= 2; index++) {
      var name = $('ob-c' + index + '-name').value.trim(), phone = $('ob-c' + index + '-phone').value.trim();
      if (!!name !== !!phone) {
        $('ob-existing-contacts').textContent = 'Enter both a name and number for each new contact, or leave both blank.';
        return;
      }
    }
    step(4);
  });
  $('ob-back-3').addEventListener('click', function () { step(2); });
  $('ob-back-4').addEventListener('click', function () { step(3); });
  $('ob-gps-btn').addEventListener('click', function () {
    var version = run;
    if (!navigator.geolocation) { $('ob-gps-status').textContent = 'Location is unavailable. You can continue without it.'; return; }
    $('ob-gps-status').textContent = 'Requesting permission…';
    navigator.geolocation.getCurrentPosition(
      function () { if (active(version)) $('ob-gps-status').textContent = 'Permission available. Sharing remains your choice.'; },
      function () { if (active(version)) $('ob-gps-status').textContent = 'Skipped. You can continue without location.'; },
      {enableHighAccuracy:false, timeout:8000, maximumAge:300000}
    );
  });
  async function finish(skipDetails) {
    if (busy) return;
    var version = run;
    busy = true; $('ob-finish').disabled = true; $('ob-skip-save').disabled = true;
    $('ob-save-status').textContent = 'Saving…';
    try {
      if (!skipDetails) {
        var payload = {contacts:[]}, name = $('ob-name').value.trim();
        if (name) payload.name = name;
        for (var index = 1; index <= 2; index++) {
          var contactName = $('ob-c' + index + '-name').value.trim(), phone = $('ob-c' + index + '-phone').value.trim();
          if (contactName || phone) payload.contacts.push({name:contactName, phone:phone});
        }
        if (payload.name || payload.contacts.length) {
          var response = await fetch('/api/onboarding', {method:'POST', credentials:'same-origin', cache:'no-store',
            headers:Object.assign({'Content-Type':'application/json'}, headers()), body:JSON.stringify(payload)});
          if (!active(version)) return;
          var body = await response.json();
          if (!response.ok) {
            if (response.status === 401) throw new Error('Account details were not saved. A private connection link from your support contact is needed first.');
            throw new Error(body.message || 'Account details were not saved. Check your connection and try again.');
          }
        }
      }
      if (!active(version)) return;
      if (draft) await lock.setPin(draft, function () { return active(version); });
      if (!active(version)) return;
      if (device) lock.saveDevice(device);
      enterApp();
    } catch (error) {
      if (active(version)) {
        $('ob-save-status').textContent = error.message || 'Setup could not finish. Check your connection and retry.';
        $('ob-skip-save').hidden = false;
      }
    } finally {
      if (active(version)) { busy = false; $('ob-finish').disabled = false; $('ob-skip-save').disabled = false; }
    }
  }
  $('ob-finish').addEventListener('click', function () { finish(false); });
  $('ob-skip-save').addEventListener('click', function () { finish(true); });
  $('cv-modal-close').addEventListener('click', close);
  modal.addEventListener('click', function (event) { if (event.target === modal) close(); });
  document.addEventListener('keydown', function (event) {
    if (modal.hidden) return;
    if (event.key === 'Escape') { close(); return; }
    if (event.key === 'Tab') {
      var focusable = Array.from(modal.querySelectorAll('button:not(:disabled), input, a[href]')).filter(function (element) { return element.getClientRects().length; });
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    var pad = !$('view-pin').hidden && lock.hasPin() ? $('pin-pad') : (!$('view-setup').hidden && !document.querySelector('[data-ob="1"]').hidden ? $('ob-pin-pad') : null);
    if (!pad) return;
    var value = event.key === 'Backspace' ? '⌫' : event.key;
    if (/^[0-9]$/.test(value) || value === '⌫') {
      event.preventDefault();
      Array.from(pad.querySelectorAll('button')).find(function (button) { return button.textContent === value; }).click();
    }
  });
  window.addEventListener('pagehide', close);
  window.CWOnboarding = {open:async function () {
    previousFocus = document.activeElement;
    run++; var version = run;
    entered = draft = confirmation = ''; confirming = false; device = null; busy = false;
    modal.hidden = false;
    $('pin-err').textContent = $('ob-pin-err').textContent = $('ob-save-status').textContent = '';
    dots('pin-dots', 0); dots('ob-pin-dots', 0);
    var returning = lock.hasPin() || lock.hasDevice();
    $('view-pin').hidden = !returning; $('view-setup').hidden = returning;
    $('device-unlock').hidden = !lock.hasDevice();
    $('pin-pad').hidden = $('pin-dots').hidden = !lock.hasPin();
    $('pin-instructions').textContent = lock.hasPin() ? 'Enter your 4-digit alert code, or use device unlock if set up.' : 'Use this browser’s saved device unlock to continue.';
    if (returning) { $('cv-sheet-title').textContent = 'Weather Alert Code'; $('cv-modal-close').focus(); return; }
    $('ob-pin-prompt').textContent = 'Step 1 of 4: Choose a 4-digit screen PIN, or use device unlock below.';
    $('ob-finish').disabled = $('ob-skip-save').disabled = false;
    $('ob-skip-save').hidden = true;
    $('ob-device-unlock').hidden = true;
    step(1);
    lock.supported().then(function (available) {
      if (active(version)) {
        $('ob-device-unlock').hidden = !available;
        if (!available) $('ob-device-help').textContent = 'Fingerprint or face unlock is unavailable in this browser. Your screen PIN works without it.';
      }
    });
    try {
      var response = await fetch('/api/onboarding', {credentials:'same-origin', cache:'no-store', headers:headers()});
      if (!active(version)) return;
      if (!response.ok) throw new Error('not_connected');
      var body = await response.json();
      if (!active(version)) return;
      if (!$('ob-name').value) $('ob-name').value = body.name || '';
      $('ob-connection').textContent = 'This browser is privately connected. Details are shared only under your account permissions.';
      $('ob-existing-contacts').textContent = body.contacts.length ? body.contacts.length + ' existing contact(s) will be kept. Add only new contacts below.' : 'No trusted contacts saved yet.';
    } catch (_) {
      if (active(version)) $('ob-connection').textContent = 'Private connection could not be confirmed. A name and contacts can only be saved after pairing and while connected.';
    }
  }};
})();
