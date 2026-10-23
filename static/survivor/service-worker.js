/* Cache public shell assets only. Private pages and APIs always use the network. */
const CACHE_PREFIX = 'avenra-pwa-shell-';
const CACHE_NAME = CACHE_PREFIX + 'v2';
const SHELL_ASSETS = [
  '/survivor/', '/survivor/index.html', '/survivor/shell.js',
  '/survivor/manifest.json', '/survivor/icons/icon-192.png',
  '/survivor/icons/icon-512.png', '/static/css/style.css'
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS)));
  // Activate after existing tabs close; never force-replace an active flow.
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key =>
    key !== CACHE_NAME && (key.startsWith(CACHE_PREFIX) || key === 'cape-weather-shell-v1')
  ).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
      url.search || event.request.headers.has('Authorization') || !SHELL_ASSETS.includes(url.pathname)) return;
  event.respondWith(caches.open(CACHE_NAME).then(async cache =>
    (await cache.match(url.pathname)) || fetch(event.request)));
});
