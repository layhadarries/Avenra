/* Explicit public-shell cache. APIs, private routes and writes use the network. */
const CACHE_NAME = 'cape-weather-shell-v5';
const SHELL_ASSETS = [
  '/survivor/', '/survivor/index.html', '/survivor/cover.html',
  '/survivor/setup.html', '/survivor/shell.js', '/survivor/survivor.js',
  '/survivor/queue.js', '/survivor/manifest.json',
  '/survivor/icons/icon-192.png', '/survivor/icons/icon-512.png',
  '/static/css/style.css'
];
const PUBLIC_PATHS = new Set(SHELL_ASSETS);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME)
    .then(cache => cache.addAll(SHELL_ASSETS))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys
    .filter(key => key !== CACHE_NAME && (
      key.startsWith('cape-weather-shell-') || key.startsWith('clear-sky-shell-')))
    .map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
      url.search !== '' || !PUBLIC_PATHS.has(url.pathname)) return;
  event.respondWith(caches.open(CACHE_NAME)
    .then(cache => cache.match(event.request))
    .then(cached => cached || fetch(event.request)));
});
