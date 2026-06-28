import { apiGet, apiPost } from "./auth.js";

export async function getBalance() {
  return apiGet("/transactions/balance");
}

export async function sendMoney(recipient, amount, note, pin) {
  return apiPost("/transactions/send", {
    recipient,
    amount,
    note,
    pin,
    offlineId: generateOfflineId(),
  });
}

export async function getHistory(limit = 50) {
  return apiGet(`/transactions/history?limit=${limit}`);
}

export async function lookupUser(identifier) {
  return apiPost("/transactions/lookup", { identifier });
}

function generateOfflineId() {
  return `offline-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

export function formatAmount(cents) {
  return (cents / 100).toFixed(2);
}

export function formatDate(dateStr) {
  const d = new Date(dateStr + (dateStr.endsWith("Z") || dateStr.endsWith("+") ? "" : "Z"));
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function generateQR(text, size = 280) {
  const canvas = document.createElement("canvas");
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(text)}`;

  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      canvas.width = size;
      canvas.height = size;
      canvas.getContext("2d").drawImage(img, 0, 0, size, size);
      resolve(canvas);
    };
    img.onerror = () => {
      // Fallback: use inline QR
      const { generateQR: inlineQR } = { generateQR: null };
      reject(new Error("QR server unavailable"));
    };
    img.src = qrUrl;

    // Timeout fallback after 3s
    setTimeout(() => {
      if (!img.complete) reject(new Error("QR timeout"));
    }, 3000);
  });
}
