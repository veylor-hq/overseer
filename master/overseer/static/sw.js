// Overseer Service Worker
const CACHE_NAME = 'veylor-overseer-v1';
const ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/css/style.css'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(clients.claim());
});

self.addEventListener('fetch', (e) => {
  // Pass network requests through directly for real-time monitoring freshness
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
