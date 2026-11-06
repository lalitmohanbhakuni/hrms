const CACHE = 'kiosk-v4';

const FACE_MODELS = [
  '/static/vendor/face-api/models/tiny_face_detector_model-weights_manifest.json',
  '/static/vendor/face-api/models/tiny_face_detector_model-shard1',
  '/static/vendor/face-api/models/face_landmark_68_model-weights_manifest.json',
  '/static/vendor/face-api/models/face_landmark_68_model-shard1',
  '/static/vendor/face-api/models/face_recognition_model-weights_manifest.json',
  '/static/vendor/face-api/models/face_recognition_model-shard1',
  '/static/vendor/face-api/models/face_recognition_model-shard2',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache =>
      Promise.all(
        FACE_MODELS.map(url =>
          fetch(url)
            .then(res => { if (res.ok) return cache.put(url, res); })
            .catch(err => console.warn('Precache miss:', url, err))
        )
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Skip non-GET, API calls, and cross-origin (CDN) requests
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.origin !== self.location.origin) return;

  const isStatic = url.pathname.startsWith('/static/');

  if (isStatic) {
    // Cache-first for static assets
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

  // Network-first for HTML, cache fallback if offline
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
      .then(res => res || fetch(e.request))
  );
});