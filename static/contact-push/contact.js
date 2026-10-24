(function () {
  'use strict';
  const status = document.getElementById('status'), result = document.getElementById('result');
  const accept = document.getElementById('accept'), decline = document.getElementById('decline');
  const ack = document.getElementById('acknowledge'), test = document.getElementById('test'), stop = document.getElementById('stop');
  const fragment = new URLSearchParams(location.hash.slice(1));
  let invite = fragment.get('invite'), acknowledgement = fragment.get('ack'), config, subscriptions = [];
  // Bearer values never enter a URL path/query, localStorage or browser history after initial loading.
  history.replaceState(null, '', '/contact-push/');
  function request(path, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    return fetch(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},
      body: body ? JSON.stringify(body) : undefined, signal:controller.signal})
      .then(async response => { if (!response.ok) throw Error('request_failed'); return response.json(); })
      .finally(() => clearTimeout(timer));
  }
  function publicKey(text) {
    const raw = atob(text.replace(/-/g,'+').replace(/_/g,'/') + '='.repeat((4-text.length%4)%4));
    return Uint8Array.from(raw, char => char.charCodeAt(0));
  }
  async function refresh() {
    const body = await request('/api/contact-push/subscriptions');
    subscriptions = body.subscriptions;
    stop.hidden = !subscriptions.length;
    test.hidden = !subscriptions.length || !config.self_test_enabled;
  }
  accept.addEventListener('click', async () => {
    accept.disabled = true;
    let subscription;
    try {
      // Must follow a deliberate click. Never auto-prompt on page load.
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { result.textContent = 'Notifications were not enabled. No contact opt-in was saved.'; return; }
      const registration = await navigator.serviceWorker.register('/contact-push/worker.js', {scope:'/contact-push/'});
      await new Promise(resolve => {
        if (registration.active) return resolve();
        const worker = registration.installing || registration.waiting;
        worker.addEventListener('statechange', () => { if (worker.state === 'activated') resolve(); });
      });
      subscription = await registration.pushManager.getSubscription();
      if (!subscription) { subscription = await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:publicKey(config.public_key)} ); }
      await request('/api/contact-push/accept', {invite_token:invite,subscription:subscription.toJSON()});
      invite = null; accept.hidden = decline.hidden = true;
      status.textContent = 'Notifications enabled for this contact invitation.';
      await refresh();
    } catch (_) {
      // Do not unsubscribe an existing device: it may serve another accepted invitation.
      // On uncertainty keep a newly created subscription as well; explicit Stop remains available.
      result.textContent = 'Could not confirm acceptance. Keep this invitation and try again. No delivery has been confirmed.';
    } finally { accept.disabled = false; }
  });
  decline.addEventListener('click', () => { invite = null; accept.hidden = decline.hidden = true; status.textContent = 'Invitation dismissed on this page. No notifications enabled.'; });
  ack.addEventListener('click', async () => {
    ack.disabled = true;
    try {
      await request('/api/contact-push/acknowledge', {token:acknowledgement});
      acknowledgement = null; ack.hidden = true;
      result.textContent = 'Your acknowledgement was recorded. This does not confirm that help has been dispatched.';
    } catch (_) { result.textContent = 'Acknowledgement was not confirmed. The link may have expired.'; }
    finally { ack.disabled = false; }
  });
  test.addEventListener('click', async () => {
    test.disabled = true;
    try {
      const body = await request('/api/contact-push/test', {subscription_id:subscriptions[0].id});
      result.textContent = body.outcome === 'accepted' ? 'Push service accepted the test. Check whether it actually appeared on your device.' : 'Test delivery is unconfirmed. Do not repeatedly resend.';
    } catch (_) { result.textContent = 'Test could not be confirmed, or was rate limited. Do not repeatedly resend.'; }
    finally { test.disabled = false; }
  });
  stop.addEventListener('click', async () => {
    stop.disabled = true;
    try {
      for (const entry of subscriptions) await request('/api/contact-push/unsubscribe', {subscription_id:entry.id});
      const registration = await navigator.serviceWorker.getRegistration('/contact-push/');
      const subscription = registration && await registration.pushManager.getSubscription();
      if (subscription) await subscription.unsubscribe();
      await refresh(); result.textContent = 'Notifications stopped on this browser.';
    } catch (_) { result.textContent = 'Could not confirm that all notifications stopped. You can also revoke notification permission in browser settings.'; }
    finally { stop.disabled = false; }
  });
  async function init() {
    ack.hidden = !acknowledgement;
    if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      status.textContent = 'Push notifications are unavailable in this browser. Use a supported browser over HTTPS.'; return;
    }
    config = await request('/api/contact-push/config');
    status.textContent = invite ? 'Review the invitation before enabling notifications.' : 'No new invitation is open.';
    accept.hidden = decline.hidden = !invite;
    await refresh();
  }
  init().catch(() => { status.textContent = 'Notification setup is unavailable. No changes were confirmed.'; });
})();
