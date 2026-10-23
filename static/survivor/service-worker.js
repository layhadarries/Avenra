const CACHE_NAME = "cape-weather-shell-v3";
const SHELL_ASSETS = [
    "/survivor/",
    "/survivor/index.html",
    "/survivor/cover.html",
    "/survivor/setup.html",
    "/survivor/survivor.js",
    "/survivor/queue.js",
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

    // Live alert and contact calls always go to the network. Never cached.
    if (url.pathname.startsWith("/api/")) {
        return;
    }

    event.respondWith(
        caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
});
