/* Nocturne service worker — เปิดได้แม้ไม่มีเน็ต
   ตัวแอป: เน็ตก่อน (ได้เวอร์ชันใหม่ทันที) · ภาพไพ่/ไอคอน/ฟอนต์: แคชก่อน
   ภาพไพ่ 78 ใบ (~4.8 MB) ทยอยโหลดเก็บหลังติดตั้ง ไม่บล็อกการเปิดแอป */
const CACHE = 'nocturne-v2';
const SHELL = ['./', './index.html', './cards.js', './manifest.json',
  './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png', './icons/favicon-64.png'];
const KEYS = [];
for (let i = 0; i < 22; i++) KEYS.push('m' + String(i).padStart(2, '0'));
for (const s of ['w', 'c', 's', 'p']) for (let i = 1; i <= 14; i++) KEYS.push(s + String(i).padStart(2, '0'));
const CARD_URLS = ['./cards/ink/back.webp', ...KEYS.map(k => './cards/ink/' + k + '.webp')];   /* default deck; Rider-Waite cached on first use */

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()).catch(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
  caches.open(CACHE).then(async c => { for (const u of CARD_URLS) { if (!(await c.match(u))) { try { await c.add(u); } catch (_) {} } } });
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const font = /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname);
  if (url.origin !== location.origin && !font) return;
  const isPage = req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html') || url.pathname.endsWith('cards.js');
  if (isPage) {
    e.respondWith(fetch(req).then(res => { const cp = res.clone(); caches.open(CACHE).then(c => c.put(req, cp)); return res; })
      .catch(() => caches.match(req).then(h => h || caches.match('./index.html'))));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
    if (res && (res.status === 200 || res.type === 'opaque')) { const cp = res.clone(); caches.open(CACHE).then(c => c.put(req, cp)); }
    return res;
  })));
});
