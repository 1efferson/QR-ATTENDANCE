
const CACHE_NAME = 'qr-attendance-v2'; 

// Core assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting(); // Force the waiting service worker to become the active service worker
});

self.addEventListener('activate', event => {
  // Remove old caches that don't match the new CACHE_NAME
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim(); // Take control of all pages immediately
});

self.addEventListener('fetch', event => {
  // Only intercept GET requests. Let POST/PUT/DELETE go directly to the network.
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful GET responses for static assets only
        if (event.request.url.includes('/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(async () => {
        // If the network fails, check the cache
        const cachedResponse = await caches.match(event.request);
        
        // If it's in the cache, return it
        if (cachedResponse) {
          return cachedResponse;
        }

        // IMPORTANT: If not in cache and network failed, return a basic fallback response
        // instead of returning 'undefined' and causing a TypeError.
        return new Response('You are offline and this page is not cached.', {
          status: 503,
          statusText: 'Service Unavailable',
          headers: new Headers({ 'Content-Type': 'text/plain' })
        });
      })
  );
});