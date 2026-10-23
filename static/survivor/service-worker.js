// cache the app shell on install and serve from cache first 
// so the page opens offline in airplane mode !!

const CACHE_NAME = "cape-weather-shell-v1";
const SHELL_ASSETS = [
    "/survivor/",
    "/survivor/index.html",
    "/survivor/manifest.json",
    "/survivor/icons/icon-192.png",
    "/survivor/icons/icon-512.png",
    "/static/css/style.css"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((oldKey) => caches.delete(oldKey))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            return cachedResponse || fetch(event.request);
        })
    );
});