const CACHE = "bradpay-v3";
const ASSETS = [
  "/",
  "/index.html",
  "/landing.html",
  "/terms.html",
  "/privacy.html",
  "/developers.html",
  "/agent.html",
  "/admin.html",
  "/css/style.css",
  "/js/firebase-config.js",
  "/js/auth.js",
  "/js/wallet.js",
  "/js/app.js",
  "/js/trade.js",
  "/js/daraja.js",
  "/js/qrcode.js",
  "/js/sync.js",
  "/manifest.json",
  "/img/favicon.svg",
  "/img/logo-icon.svg",
  "/img/logo.svg",
];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isAPI(url) {
  return url.pathname.startsWith("/api/");
}

function isMutation(req) {
  return req.method === "POST" || req.method === "PUT" || req.method === "DELETE" || req.method === "PATCH";
}

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res.ok) {
      const clone = res.clone();
      caches.open(CACHE).then((c) => c.put(req, clone));
    }
    return res;
  } catch {
    const cached = await caches.match(req);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

async function staleWhileRevalidate(req) {
  const cached = await caches.match(req);
  const fetchPromise = fetch(req)
    .then((res) => {
      if (res && res.status === 200) {
        const clone = res.clone();
        caches.open(CACHE).then((c) => c.put(req, clone));
      }
      return res;
    })
    .catch(() => cached);
  return cached || fetchPromise;
}

self.addEventListener("fetch", (e) => {
  const { request: req } = e;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (isAPI(url)) {
    if (isMutation(req)) {
      e.respondWith(networkFirst(req));
    } else {
      e.respondWith(networkFirst(req));
    }
    return;
  }
  e.respondWith(staleWhileRevalidate(req));
});

self.addEventListener("sync", (e) => {
  if (e.tag === "sync-transactions") {
    e.waitUntil(flushQueue());
  }
});

self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "flush-queue") {
    e.waitUntil(flushQueue());
  }
});

async function flushQueue() {
  const cache = await caches.open(CACHE);
  const pending = await cache.match("/pending-queue");
  if (!pending) return;
  const items = await pending.json();
  if (!items.length) return;

  const remaining = [];
  for (const item of items) {
    try {
      const res = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body,
      });
      if (!res.ok) remaining.push(item);
    } catch {
      remaining.push(item);
    }
  }
  const resp = new Response(JSON.stringify(remaining));
  await cache.put("/pending-queue", resp);

  if (remaining.length === 0) {
    const clients = await self.clients.matchAll();
    clients.forEach((c) => c.postMessage({ type: "queue-flushed" }));
  }
}
