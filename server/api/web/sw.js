/* Minimal service worker: keeps the app openable offline, but prefers the
   network so updates always load while the local backend is running.
   API calls are never cached. Bump CACHE to force-refresh the shell. */
const CACHE = "lip-shell-v2";
const SHELL = ["/", "/app.js", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return; // network only
  // Network-first: fresh when online, cached shell when offline.
  e.respondWith(
    fetch(e.request).then((res) => {
      if (res.ok && url.origin === location.origin) {
        const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request).then((hit) => hit || caches.match("/")))
  );
});
