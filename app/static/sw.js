"use strict";
const OFFLINE_CACHE_PREFIX = "compac-offline-";
const OFFLINE_CACHE = `${OFFLINE_CACHE_PREFIX}v1`;
// Only public offline assets and icons. Never add APIs, user data, or writes.
const OFFLINE_ASSETS = [
  "/offline.html", "/static/offline.css", "/static/offline.js", "/static/icon.svg",
  "/static/icons/icon-192.png", "/static/icons/icon-512.png",
  "/static/icons/maskable-512.png", "/static/icons/apple-touch-icon-180.png",
];
const ASSET_PATHS = new Set(OFFLINE_ASSETS);
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then((cache) => cache.addAll(OFFLINE_ASSETS)));
});
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(OFFLINE_CACHE_PREFIX) && name !== OFFLINE_CACHE).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener("message", (event) => {
  if (event.data?.type === "COMPAC_ACTIVATE_UPDATE") event.waitUntil(self.skipWaiting());
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname === "/api" || url.pathname.startsWith("/api/")) return;
  if (ASSET_PATHS.has(url.pathname) && !url.search) {
    event.respondWith(caches.open(OFFLINE_CACHE).then(async (cache) => (await cache.match(request)) || fetch(request)));
    return;
  }
  if (request.mode === "navigate") {
    // Online documents are never cached; Retry revisits the original URL.
    event.respondWith(fetch(request).catch(async () => {
      const cache = await caches.open(OFFLINE_CACHE);
      return (await cache.match("/offline.html")) || Response.error();
    }));
  }
});
