const CACHE_NAME = 'clear-sky-shell-v6';
const DATA_CACHE_NAME = 'clear-sky-data-v1';

const SHELL_ASSETS = [
  '/survivor/',
  '/survivor/index.html',
  '/survivor/cover.html',
  '/survivor/setup.html',
  '/survivor/help.html',
  '/survivor/help.js',
  '/survivor/shell.js',
  '/survivor/survivor.js',
  '/survivor/queue.js',
  '/survivor/manifest.json',
  '/survivor/icons/icon-192.png',
  '/survivor/icons/icon-512.png',
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
    .filter(key => key !== CACHE_NAME && key !== DATA_CACHE_NAME && (
      key.startsWith('clear-sky-shell-') || key.startsWith('clear-sky-shell-')))
    .map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // Network-first caching for shelter directory offline access
  if (url.pathname === '/api/shelters') {
    event.respondWith(
      fetch(event.request)
        .then(networkResponse => {
          if (networkResponse.ok) {
            const copy = networkResponse.clone();
            caches.open(DATA_CACHE_NAME).then(cache => cache.put(event.request, copy));
          }
          return networkResponse;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Live alerts, mutations, and non-whitelisted paths go to network
  if (url.search !== '' || !PUBLIC_PATHS.has(url.pathname)) return;

  // Cache-first for the static app shell
  event.respondWith(caches.open(CACHE_NAME)
    .then(cache => cache.match(event.request))
    .then(cached => cached || fetch(event.request)));
});
