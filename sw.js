// FamilyOS Service Worker v2 — Cache-First + Push Notifications
const CACHE = 'familyos-v2';
const STATIC = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  'https://fonts.googleapis.com/css2?family=Rubik:wght@300;400;500;600;700;800;900&display=swap'
];

// ── Install ──
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(STATIC))
      .then(() => self.skipWaiting())
  );
});

// ── Activate ──
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ──
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // data.json — network first (always fresh)
  if (url.pathname.endsWith('data.json')) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }
  // static assets — cache first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
      if (res && res.ok && e.request.method === 'GET') {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match('./index.html')))
  );
});

// ── Push Notifications ──
self.addEventListener('push', e => {
  let data = { title: 'FamilyOS', body: '📅 אירוע קרוב', icon: './icons/icon-192.png' };
  try {
    if (e.data) {
      const parsed = e.data.json();
      data = { ...data, ...parsed };
    }
  } catch(_) {}

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body:    data.body,
      icon:    data.icon || './icons/icon-192.png',
      badge:   './icons/icon-192.png',
      tag:     data.tag || 'familyos-event',
      renotify: true,
      vibrate: [200, 100, 200],
      data:    { url: data.url || './' },
      actions: data.actions || [],
      dir:     'rtl',
      lang:    'he',
    })
  );
});

// ── Notification Click ──
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || './';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      const existing = list.find(c => c.url.includes('familyos') && 'focus' in c);
      if (existing) return existing.focus();
      return clients.openWindow(url);
    })
  );
});

// ── Background Sync (refresh data) ──
self.addEventListener('sync', e => {
  if (e.tag === 'familyos-refresh') {
    e.waitUntil(
      fetch('./data.json?t=' + Date.now())
        .then(r => r.json())
        .catch(() => {})
    );
  }
});
