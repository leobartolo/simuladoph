// Service worker do SimuladoPH.
// Objetivo: deixar o app "instalavel" e carregar rapido em visitas repetidas.
// O banco de questoes fica sempre na AWS — aqui so cacheamos o "casco" do app.

// Só assets estáticos aqui — "/" responde 302 e o Cache API rejeita respostas redirecionadas.
const CACHE = 'simuladoph-v2';
const SHELL = ['/static/icon.svg', '/static/icon-192.png', '/manifest.webmanifest'];

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

  const cacheable = (res) => res && res.ok && !res.redirected && res.type === 'basic';

  // Navegacoes e paginas: rede primeiro, cai pro cache se estiver offline.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (cacheable(res)) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Assets estaticos (imagens das questoes, etc): cache primeiro, atualiza em segundo plano.
  e.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((res) => {
        if (cacheable(res)) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
