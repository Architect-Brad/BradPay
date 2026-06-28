import { apiGet, apiPost } from "./auth.js";

export async function getBalance() {
  return apiGet("/transactions/balance");
}

export async function sendMoney(recipient, amount, note) {
  return apiPost("/transactions/send", {
    recipient,
    amount,
    note,
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
  const d = new Date(dateStr + "Z");
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
