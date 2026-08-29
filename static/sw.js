// Service worker do SimuladoPH.
// Objetivo: deixar o app "instalavel" e carregar rapido em visitas repetidas.
// O banco de questoes fica sempre na AWS — aqui so cacheamos o "casco" do app.

const CACHE = 'simuladoph-v1';
const SHELL = ['/', '/static/icon.svg', '/static/manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // CDNs (tailwind/alpine) vao direto pra rede

  // Navegacoes e paginas: rede primeiro, cai pro cache se estiver offline.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => { caches.open(CACHE).then((c) => c.put(req, res.clone())); return res; })
        .catch(() => caches.match(req).then((m) => m || caches.match('/')))
    );
    return;
  }

  // Assets estaticos (imagens das questoes, etc): cache primeiro, atualiza em segundo plano.
  e.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
