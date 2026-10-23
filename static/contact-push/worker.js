/* Separate scope. Never cache contact API responses or invitation/ack tokens. */
self.addEventListener('push', event => {
  let target = '/contact-push/';
  try {
    const payload = event.data.json();
    // Only a narrow same-origin capability link; never accept arbitrary navigation.
    if (typeof payload.url === 'string' && /^\/contact-push\/#ack=[A-Za-z0-9_-]{43}$/.test(payload.url)) target = payload.url;
  } catch (_) {}
  event.waitUntil(self.registration.showNotification('Notification', {
    body: 'You have a new notification.', icon: '/survivor/icons/icon-192.png',
    data: {url: target}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const path = event.notification.data && event.notification.data.url;
  const target = typeof path === 'string' && /^\/contact-push\/(#ack=[A-Za-z0-9_-]{43})?$/.test(path) ? path : '/contact-push/';
  event.waitUntil(self.clients.openWindow(target));
});
