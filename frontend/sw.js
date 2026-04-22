const CACHE_NAME = 'cardboard-v2';
const API_CACHE_NAME = 'cardboard-api-v1';

const SHELL_ASSETS = [
  '/',
  '/js/api.js',
  '/js/app.js',
  '/js/ui.js',
  '/js/theme.js',
  '/js/ui-helpers.js',
  '/js/confetti.js',
  '/css/style.css',
];

// API GET paths to cache for offline read access (stale-while-revalidate)
const CACHEABLE_API_PREFIXES = [
  '/api/games/',
  '/api/stats',
  '/api/collection/stats',
  '/api/players/',
];

function isCacheableApi(pathname) {
  return CACHEABLE_API_PREFIXES.some(p => pathname.startsWith(p));
}

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  if (url.pathname.startsWith('/api/')) {
    if (e.request.method === 'GET' && isCacheableApi(url.pathname)) {
      // Stale-while-revalidate for cacheable API GET endpoints
      e.respondWith(
        caches.open(API_CACHE_NAME).then((cache) => {
          const networkFetch = fetch(e.request).then((resp) => {
            if (resp.ok) cache.put(e.request, resp.clone());
            return resp;
          }).catch(() => cache.match(e.request));
          return cache.match(e.request).then((cached) => cached || networkFetch);
        })
      );
    } else {
      // Network-only for mutating API calls (POST/PATCH/DELETE)
      e.respondWith(fetch(e.request));
    }
    return;
  }

  // Stale-while-revalidate for static assets and images
  e.respondWith(
    caches.match(e.request).then((cached) => {
      const networkFetch = fetch(e.request).then((resp) => {
        if (resp.ok && e.request.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        }
        return resp;
      });
      return cached || networkFetch;
    })
  );
});
