/* Service worker — ทำให้แอปเปิดได้แม้ไม่มีเน็ต (จุดขายหลักที่ลูกค้าสั่งไว้: "ไม่ต้องออนไลน์") */
const CACHE = 'chatmockup-v1';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-192.png',
  './icons/icon-maskable-512.png',
  './icons/apple-touch-icon.png',
  './icons/favicon-64.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())   // ถ้าไฟล์ใดโหลดไม่ได้ ก็ยังติดตั้งต่อ ไม่ให้ทั้งแอปพัง
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* cache-first: เปิดเร็วและใช้ได้ออฟไลน์ · ถ้าเน็ตมีก็อัปเดตแคชไว้ใช้รอบหน้า */
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (new URL(req.url).origin !== location.origin) return;   // ไม่ยุ่งกับของนอกโดเมน

  e.respondWith(
    caches.match(req).then(hit => {
      if (hit) return hit;
      return fetch(req).then(res => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match('./index.html'));
    })
  );
});
