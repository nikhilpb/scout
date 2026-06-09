/* Minimal service worker: cache the static shell, let pages hit the network. */
var CACHE = "scout-shell-v1";
var SHELL = [
  "/static/app.css",
  "/static/app.js",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(SHELL);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE; }).map(function (k) {
          return caches.delete(k);
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/static/") || SHELL.indexOf(url.pathname) !== -1) {
    event.respondWith(
      caches.match(event.request).then(function (cached) {
        return cached || fetch(event.request);
      })
    );
  }
  // Pages always go to the network: digests are written server-side and
  // staleness is worse than a brief loading spinner on a personal LAN/tailnet.
});
