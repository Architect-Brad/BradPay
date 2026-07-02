import { getIdToken, getCurrentUser } from "./auth.js";
import { formatAmount, formatDate } from "./wallet.js";
import { queueRequest } from "./sync.js";

const $ = (id) => document.getElementById(id);

let currentOrderType = "buy";

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function setLoading(el, loading) {
  if (loading) {
    el.disabled = true;
    el.dataset.text = el.textContent;
    el.innerHTML = '<span class="spinner spinner-sm" style="display:inline-block;"></span>';
  } else {
    el.disabled = false;
    el.textContent = el.dataset.text || el.textContent;
  }
}

export async function initTrade() {
  bindTradeTabs();
  bindOrderTypeToggle();
  bindOrderSubmit();
  await refreshTradeScreen();
}

export async function refreshTradeScreen() {
  await Promise.all([
    refreshTradeBalance(),
    refreshOrderBook(),
    refreshMyOrders(),
    refreshTradeHistory(),
  ]);
}

function bindTradeTabs() {
  document.querySelectorAll(".trade-tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".trade-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll(".trade-panel").forEach((p) => p.classList.remove("active"));
      const panel = $(`tab-${tab.dataset.tab}`);
      if (panel) panel.classList.add("active");
      if (tab.dataset.tab === "orderbook") refreshOrderBook();
      if (tab.dataset.tab === "myorders") refreshMyOrders();
      if (tab.dataset.tab === "history") refreshTradeHistory();
    };
  });
}

function bindOrderTypeToggle() {
  const buyBtn = $("order-type-buy");
  const sellBtn = $("order-type-sell");
  buyBtn.onclick = () => {
    currentOrderType = "buy";
    buyBtn.className = "btn btn-sm";
    sellBtn.className = "btn btn-sm btn-secondary";
    $("order-submit").textContent = "Place Buy Order";
    $("order-submit").className = "btn btn-success btn-full";
  };
  sellBtn.onclick = () => {
    currentOrderType = "sell";
    sellBtn.className = "btn btn-sm";
    buyBtn.className = "btn btn-sm btn-secondary";
    $("order-submit").textContent = "Place Sell Order";
    $("order-submit").className = "btn btn-danger btn-full";
  };
}

function bindOrderSubmit() {
  $("order-submit").onclick = async () => {
    const price = parseInt($("order-price").value);
    const amount = parseInt($("order-amount").value);
    if (!price || price <= 0) { showToast("Enter a valid price", "error"); return; }
    if (!amount || amount <= 0) { showToast("Enter a valid amount", "error"); return; }

    const btn = $("order-submit");
    setLoading(btn, true);
    try {
      const token = await getIdToken();
      const body = { type: currentOrderType, price, amount };

      if (!navigator.onLine) {
        queueRequest("/api/trade/orders", "POST", body, { Authorization: `Bearer ${token}` });
        showToast("Order queued — will submit when online", "info");
        setLoading(btn, false);
        return;
      }

      const resp = await fetch("/api/trade/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (data.error) {
        showToast(data.error, "error");
      } else {
        const trades = data.trades || [];
        const msg = trades.length > 0
          ? `${currentOrderType === "buy" ? "Buy" : "Sell"} order matched! ${trades.length} trade(s) executed.`
          : `${currentOrderType === "buy" ? "Buy" : "Sell"} order placed`;
        showToast(msg, trades.length > 0 ? "success" : "info");
        $("order-price").value = "";
        $("order-amount").value = "";
        await refreshTradeScreen();
      }
    } catch {
      showToast("Failed to place order", "error");
    } finally {
      setLoading(btn, false);
    }
  };
}

async function refreshTradeBalance() {
  try {
    const token = await getIdToken();
    const resp = await fetch("/api/trade/balance", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const data = await resp.json();
    if (data.available !== undefined) {
      $("trade-available-balance").textContent = formatAmount(data.available);
      $("trade-locked-balance").textContent = formatAmount(data.locked);
    }
  } catch { /* ignore */ }
}

async function refreshOrderBook() {
  try {
    const resp = await fetch("/api/trade/orderbook");
    const data = await resp.json();
    const bids = data.bids || [];
    const asks = data.asks || [];

    const asksContainer = $("ob-asks");
    const bidsContainer = $("ob-bids");
    const spreadEl = $("ob-spread");

    if (asks.length === 0) {
      asksContainer.innerHTML = '<div class="ob-empty">No sell orders</div>';
    } else {
      asksContainer.innerHTML = asks.slice(0, 10).map((a) =>
        `<div class="ob-row ask">
          <span class="ob-price">${a.price}¢</span>
          <span class="ob-amount">${formatAmount(a.amount)}</span>
          <span class="ob-total">${formatAmount(Math.round(a.price * a.amount / 100))}</span>
        </div>`
      ).join("");
    }

    if (bids.length === 0) {
      bidsContainer.innerHTML = '<div class="ob-empty">No buy orders</div>';
    } else {
      bidsContainer.innerHTML = bids.slice(0, 10).map((b) =>
        `<div class="ob-row bid">
          <span class="ob-price">${b.price}¢</span>
          <span class="ob-amount">${formatAmount(b.amount)}</span>
          <span class="ob-total">${formatAmount(Math.round(b.price * b.amount / 100))}</span>
        </div>`
      ).join("");
    }

    if (bids.length > 0 && asks.length > 0) {
      const bestBid = bids[0].price;
      const bestAsk = asks[0].price;
      const spread = bestAsk - bestBid;
      spreadEl.innerHTML = `<span class="ob-spread-label">Spread: ${spread}¢ · Best Bid: ${bestBid}¢ · Best Ask: ${bestAsk}¢</span>`;
    } else {
      spreadEl.innerHTML = '<span class="ob-spread-label">No active market</span>';
    }
  } catch { /* ignore */ }
}

async function refreshMyOrders() {
  const container = $("my-orders-list");
  const loading = $("my-orders-loading");
  if (loading) loading.style.display = "flex";

  try {
    const token = await getIdToken();
    const resp = await fetch("/api/trade/orders", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const data = await resp.json();
    const orders = data.orders || [];

    if (loading) loading.style.display = "none";

    if (orders.length === 0) {
      container.innerHTML = '<div class="tx-empty"><div class="icon">📋</div><div>No orders yet</div></div>';
      return;
    }

    container.innerHTML = orders.map((o) => {
      const isBuy = o.type === "buy";
      return `
        <div class="order-item ${isBuy ? "buy" : "sell"}">
          <div class="order-header">
            <span class="order-type-badge ${isBuy ? "buy" : "sell"}">${isBuy ? "BUY" : "SELL"}</span>
            <span class="order-status status-${o.status}">${o.status}</span>
            ${(o.status === "open" || o.status === "partial") ? `<button class="btn-ghost cancel-order" data-id="${o.id}" style="font-size:12px;padding:2px 8px;">✕</button>` : ""}
          </div>
          <div class="order-details">
            <span>${o.price}¢ × KES ${formatAmount(o.amount)}</span>
            <span>Filled: ${formatAmount(o.filled || 0)} / ${formatAmount(o.amount)}</span>
          </div>
        </div>`;
    }).join("");

    container.querySelectorAll(".cancel-order").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        try {
          const token = await getIdToken();
          const resp = await fetch(`/api/trade/orders/${id}`, {
            method: "DELETE",
            headers: { "Authorization": `Bearer ${token}` },
          });
          const data = await resp.json();
          showToast(data.message || "Order cancelled", "success");
          await Promise.all([
            refreshMyOrders(),
            refreshTradeBalance(),
            refreshOrderBook(),
          ]);
        } catch {
          showToast("Failed to cancel", "error");
        }
      };
    });
  } catch {
    if (loading) loading.style.display = "none";
    container.innerHTML = '<div class="tx-empty"><div class="icon">⚠️</div><div>Failed to load orders</div></div>';
  }
}

async function refreshTradeHistory() {
  const container = $("trade-history-list");
  const loading = $("trade-history-loading");
  if (loading) loading.style.display = "flex";

  try {
    const token = await getIdToken();
    const resp = await fetch("/api/trade/trades", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const data = await resp.json();
    const trades = data.trades || [];

    if (loading) loading.style.display = "none";

    if (trades.length === 0) {
      container.innerHTML = '<div class="tx-empty"><div class="icon">📊</div><div>No trades yet</div></div>';
      return;
    }

    const user = getCurrentUser();
    container.innerHTML = trades.map((t) => {
      const isBuyer = t.buyer_uid === (user?.uid || user?.firebase_uid);
      return `
        <div class="trade-record">
          <div class="trade-record-header">
            <span class="trade-side-label ${isBuyer ? "buy" : "sell"}">${isBuyer ? "BOUGHT" : "SOLD"}</span>
            <span class="trade-record-date">${formatDate(t.created_at)}</span>
          </div>
          <div class="trade-record-details">
            <span>KES ${formatAmount(t.amount)} @ ${t.price}¢</span>
            <span>Total: ${formatAmount(Math.round(t.price * t.amount / 100))}¢</span>
          </div>
        </div>`;
    }).join("");
  } catch {
    if (loading) loading.style.display = "none";
    container.innerHTML = '<div class="tx-empty"><div class="icon">⚠️</div><div>Failed to load trades</div></div>';
  }
}
