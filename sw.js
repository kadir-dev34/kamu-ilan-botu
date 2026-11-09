// sw.js - Service Worker (Arka Plan Yöneticisi)
const CACHE_NAME = 'kamu-ilanlari-v1';

// Uygulama kurulduğunda çalışır
self.addEventListener('install', (event) => {
    console.log('[Service Worker] Kuruldu ve PWA aktif!');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[Service Worker] Aktif edildi!');
});

// İnternet trafiğini dinler (İleride çevrimdışı çalışma özelliği eklenebilir)
self.addEventListener('fetch', (event) => {
    // Şimdilik standart ağ isteğine izin veriyoruz
});