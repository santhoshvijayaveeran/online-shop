const CACHE_NAME = 'online-shop-v1';
const STATIC_CACHE = 'static-v1';

const urlsToCache = [
    '/',
    '/offline/',
    '/static/css/style.css',
];

// Install - cache files
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Cache opened');
                return cache.addAll(urlsToCache);
            })
    );
    self.skipWaiting();
});

// Activate - delete old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames
                    .filter(name => name !== CACHE_NAME && name !== STATIC_CACHE)
                    .map(name => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

// Fetch - serve from cache or network
self.addEventListener('fetch', event => {
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Skip admin and API requests
    if (event.request.url.includes('/admin/')) return;

    event.respondWith(
        caches.match(event.request)
            .then(cachedResponse => {
                if (cachedResponse) {
                    return cachedResponse;
                }

                return fetch(event.request)
                    .then(response => {
                        // Cache successful responses
                        if (response && response.status === 200) {
                            const responseClone = response.clone();
                            caches.open(CACHE_NAME).then(cache => {
                                cache.put(event.request, responseClone);
                            });
                        }
                        return response;
                    })
                    .catch(() => {
                        // Offline fallback
                        return caches.match('/offline/');
                    });
            })
    );
});