const CACHE = "bradpay-v1";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/css/style.css",
  "/js/firebase-config.js",
  "/js/auth.js",
  "/js/wallet.js",
  "/js/app.js",
  "/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.url.startsWith("http")) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request)
          .then((response) => {
            if (response && response.status === 200) {
              const clone = response.clone();
              caches.open(CACHE).then((cache) => {
                cache.put(event.request, clone);
              });
            }
            return response;
          })
          .catch(() => cached);

        return cached || fetchPromise;
      })
    );
  }
});

self.addEventListener("sync", (event) => {
  if (event.tag === "sync-transactions") {
    event.waitUntil(syncOfflineTransactions());
  }
});

async function syncOfflineTransactions() {
  const cache = await caches.open(CACHE);
  const pending = await cache.match("/pending-transactions");
  if (!pending) return;

  const txs = await pending.json();
  for (const tx of txs) {
    try {
      const resp = await fetch("/api/transactions/send", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${tx.idToken}` },
        body: JSON.stringify(tx.data),
      });
      if (resp.ok) {
        const idx = txs.indexOf(tx);
        txs.splice(idx, 1);
      }
    } catch (e) {
      console.error("Sync failed for tx:", tx.offlineId, e);
    }
  }
  const response = new Response(JSON.stringify(txs));
  await cache.put("/pending-transactions", response);
}
