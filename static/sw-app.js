const CACHE = 'nitohr-app-v2';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE && !k.startsWith('kiosk-')).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Don't touch kiosk pages — kiosk has its own SW at /kiosk/ scope
  if (url.pathname.startsWith('/kiosk/')) return;
  if (url.pathname.startsWith('/api/kiosk/')) return;

  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.origin !== self.location.origin) return;

  // Static + media: cache-first
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/media/')) {
    e.respondWith(
      caches.match(e.request).then(hit => {
        if (hit) return hit;
        return fetch(e.request).then(res => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return res;
        });
      })
    );
    return;
  }

  // HTML: network-first, cache fallback
// Auth pages: always network, never cache
  var authPaths = ['/login', '/logout', '/forgot-password', '/password-reset'];
  for (var i = 0; i < authPaths.length; i++) {
    if (url.pathname.indexOf(authPaths[i]) === 0) {
      return; // SW lets the browser handle it directly — no cache
    }
  }

  // HTML: network-first, cache fallback
  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});