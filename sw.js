// Basit service worker: uygulama kabuğunu önbelleğe alır, ilan verisi (Supabase)
// ve diğer alan adları her zaman ağdan gelir.
const SURUM = "kamu-ilan-v3";
const KABUK = ["./", "./index.html", "./manifest.json", "./icons/icon-192.png", "./icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SURUM).then((c) => c.addAll(KABUK)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((adlar) => Promise.all(adlar.filter((a) => a !== SURUM).map((a) => caches.delete(a))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const istek = e.request;
  if (istek.method !== "GET") return;
  const url = new URL(istek.url);
  if (url.origin !== self.location.origin) return; // Supabase, CDN vb. dokunma

  // Sayfa gezintisi: önce ağ, çevrimdışıysa önbellek
  if (istek.mode === "navigate") {
    e.respondWith(
      fetch(istek)
        .then((r) => {
          const kopya = r.clone();
          caches.open(SURUM).then((c) => c.put("./index.html", kopya));
          return r;
        })
        .catch(() => caches.match("./index.html"))
    );
    return;
  }

  // Statik dosyalar: önce önbellek
  e.respondWith(caches.match(istek).then((c) => c || fetch(istek)));
});
