const QUEUE_KEY = "bradpay-offline-queue";

export function getQueue() {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveQueue(q) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
}

export function queueRequest(url, method, body, headers = {}) {
  const q = getQueue();
  q.push({
    url,
    method,
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...headers },
    timestamp: Date.now(),
  });
  saveQueue(q);
  registerSync();
}

export function getQueueLength() {
  return getQueue().length;
}

export function clearQueue() {
  saveQueue([]);
}

export async function flushQueue() {
  const q = getQueue();
  if (!q.length) return 0;

  const remaining = [];
  let flushed = 0;

  for (const item of q) {
    try {
      const res = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body,
      });
      if (res.ok) {
        flushed++;
      } else {
        remaining.push(item);
      }
    } catch {
      remaining.push(item);
    }
  }

  saveQueue(remaining);
  if (remaining.length === 0 && "serviceWorker" in navigator) {
    const cache = await caches.open("bradpay-v2");
    await cache.put("/pending-queue", new Response("[]"));
  }
  return flushed;
}

async function registerSync() {
  try {
    if ("serviceWorker" in navigator && "SyncManager" in window) {
      const reg = await navigator.serviceWorker.ready;
      await reg.sync.register("sync-transactions");
    }
  } catch {
    // Background sync not supported — flush will happen on online event
  }
}

export function initNetworkListener(onStatusChange) {
  const update = () => {
    const online = navigator.onLine;
    if (online) {
      flushQueue().then((n) => {
        if (n > 0) {
          const ev = new CustomEvent("queue-flushed", { detail: n });
          window.dispatchEvent(ev);
        }
      });
    }
    onStatusChange?.(online);
  };

  window.addEventListener("online", update);
  window.addEventListener("offline", update);
  update();
}
