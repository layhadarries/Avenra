/* Cache public shell assets only
Private pages and APIs always use the network */

const CACHE_NAME = "cape-weather-shell-v2";
const SHELL_ASSETS = [
    "/survivor/",
    "/survivor/index.html",
    "/survivor/cover.html",
    "/survivor/survivor.js",
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
        caches.keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((key) => key !== CACHE_NAME)
                        .map((oldKey) => caches.delete(oldKey))
                )
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    if (event.request.method !== "GET" || url.origin !== self.location.origin) {
        return;
    }

    // Live alert calls always go to the network - never cached
    if (url.pathname.startsWith("/api/")) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
});
