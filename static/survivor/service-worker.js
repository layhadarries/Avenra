/* Only public static shell assets are cached. */
const CACHE_NAME = 'clear-sky-shell-v9';
const SHELL_ASSETS = [
  '/survivor/', '/survivor/index.html', '/survivor/cover.html',
  '/survivor/setup.html', '/survivor/shell.js', '/survivor/survivor.js',
  '/survivor/queue.js', '/survivor/manifest.json',
  '/survivor/help.html', '/survivor/help.js',
  '/survivor/privacy.html', '/survivor/privacy.js',
  '/survivor/diary.html', '/survivor/diary.js',
  '/survivor/icons/icon-192.png', '/survivor/icons/icon-512.png', '/static/css/style.css'
];
const PUBLIC_PATHS = new Set(SHELL_ASSETS);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS)));
});
self.addEventListener('activate', event => {
  const prefixes = ['clear-sky-shell-', 'clear-sky-shell-', 'avenra-pwa-shell-',
    'clear-sky-data-', 'clear-sky-data-'];
  event.waitUntil(caches.keys().then(keys => Promise.all(keys
    .filter(key => key !== CACHE_NAME && prefixes.some(prefix => key.startsWith(prefix)))
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
      url.search !== '' || !PUBLIC_PATHS.has(url.pathname) ||
      (event.request.headers && event.request.headers.has('Authorization'))) return;
  event.respondWith(caches.open(CACHE_NAME).then(cache => cache.match(event.request))
    .then(cached => cached || fetch(event.request)));
});
