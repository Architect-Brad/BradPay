import { getIdToken, getCurrentUser } from "./auth.js";
import { formatAmount } from "./wallet.js";
import { queueRequest } from "./sync.js";

const $ = (id) => document.getElementById(id);

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

function formatPhone(phone) {
  let p = phone.replace(/[^0-9]/g, '');
  if (p.startsWith('0')) p = '254' + p.substring(1);
  if (p.startsWith('+')) p = p.substring(1);
  if (!p.startsWith('254')) p = '254' + p;
  return p;
}

export async function initDaraja() {
  bindDeposit();
  bindWithdraw();
}

export async function refreshDaraja() {
  await refreshKESBalance();
}

async function refreshKESBalance() {
  try {
    const token = await getIdToken();
    const resp = await fetch("/api/daraja/balance", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    const data = await resp.json();
    const kes = data.kes_balance ?? data.balance ?? 0;
    const el = $("kes-balance-amount");
    if (el) el.textContent = `KES ${formatAmount(kes)}`;
    const w = $("withdraw-kes-balance");
    if (w) w.textContent = `KES ${formatAmount(kes)}`;
  } catch { /* ignore */ }
}

function bindDeposit() {
  $("deposit-submit").onclick = async () => {
    const amountStr = $("deposit-amount").value;
    const phone = $("deposit-phone").value;
    
    if (!amountStr || parseInt(amountStr) < 10) {
      showToast("Minimum deposit is KES 10", "error"); return;
    }
    if (!phone || phone.length < 9) {
      showToast("Enter a valid M-PESA phone number", "error"); return;
    }

    const amountCents = Math.round(parseFloat(amountStr) * 100);
    const formattedPhone = formatPhone(phone);
    
    const btn = $("deposit-submit");
    const statusEl = $("deposit-status");
    setLoading(btn, true);
    statusEl.style.display = "none";

    try {
      const token = await getIdToken();
      const body = { amount: amountCents, phone: formattedPhone };

      if (!navigator.onLine) {
        queueRequest("/api/daraja/stkpush", "POST", body, { Authorization: `Bearer ${token}` });
        showToast("Deposit queued — will send when online", "info");
        statusEl.innerHTML = `<div style="color:var(--warning);padding:12px;background:rgba(245,158,11,0.1);border-radius:8px;">📦 Deposit queued — will process when back online</div>`;
        statusEl.style.display = "block";
        $("deposit-amount").value = "";
        $("deposit-phone").value = "";
        setLoading(btn, false);
        return;
      }

      const resp = await fetch("/api/daraja/stkpush", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      if (data.error) {
        showToast(data.error, "error");
        statusEl.innerHTML = `<div style="color:var(--danger);padding:12px;background:rgba(239,68,68,0.1);border-radius:8px;">${data.error}</div>`;
      } else {
        showToast("Check your phone. Enter M-PESA PIN to confirm.", "success");
        statusEl.innerHTML = `<div style="color:var(--success);padding:12px;background:rgba(34,197,94,0.1);border-radius:8px;">
          ✅ STK Push sent!<br>
          Check your phone and enter your M-PESA PIN.<br>
          <small>Checkout ID: ${data.checkout_id?.substring(0, 20)}...</small>
        </div>`;
        $("deposit-amount").value = "";
        $("deposit-phone").value = "";
      }
      statusEl.style.display = "block";
    } catch (e) {
      showToast("Failed to initiate deposit", "error");
      statusEl.innerHTML = `<div style="color:var(--danger);padding:12px;background:rgba(239,68,68,0.1);border-radius:8px;">Network error. Try again.</div>`;
      statusEl.style.display = "block";
    } finally {
      setLoading(btn, false);
    }
  };
}

function bindWithdraw() {
  $("withdraw-submit").onclick = async () => {
    const amountStr = $("withdraw-amount").value;
    const phone = $("withdraw-phone").value;
    
    if (!amountStr || parseInt(amountStr) < 10) {
      showToast("Minimum withdrawal is KES 10", "error"); return;
    }
    if (!phone || phone.length < 9) {
      showToast("Enter a valid M-PESA phone number", "error"); return;
    }

    const amountCents = Math.round(parseFloat(amountStr) * 100);
    const formattedPhone = formatPhone(phone);
    
    const btn = $("withdraw-submit");
    const statusEl = $("withdraw-status");
    setLoading(btn, true);
    statusEl.style.display = "none";

    try {
      const token = await getIdToken();
      const body = { amount: amountCents, phone: formattedPhone };

      if (!navigator.onLine) {
        queueRequest("/api/daraja/b2c", "POST", body, { Authorization: `Bearer ${token}` });
        showToast("Withdrawal queued — will send when online", "info");
        statusEl.innerHTML = `<div style="color:var(--warning);padding:12px;background:rgba(245,158,11,0.1);border-radius:8px;">📦 Withdrawal queued — will process when back online</div>`;
        statusEl.style.display = "block";
        $("withdraw-amount").value = "";
        $("withdraw-phone").value = "";
        setLoading(btn, false);
        return;
      }

      const resp = await fetch("/api/daraja/b2c", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      if (data.error) {
        showToast(data.error, "error");
        statusEl.innerHTML = `<div style="color:var(--danger);padding:12px;background:rgba(239,68,68,0.1);border-radius:8px;">${data.error}</div>`;
      } else {
        showToast("Withdrawal initiated! Money sent to M-PESA.", "success");
        statusEl.innerHTML = `<div style="color:var(--success);padding:12px;background:rgba(34,197,94,0.1);border-radius:8px;">
          ✅ Withdrawal initiated!<br>
          KES ${formatAmount(amountCents)} sent to ${phone}.<br>
          <small>Conversation ID: ${data.conversation_id?.substring(0, 20)}...</small>
        </div>`;
        $("withdraw-amount").value = "";
        $("withdraw-phone").value = "";
        refreshKESBalance();
      }
      statusEl.style.display = "block";
    } catch (e) {
      showToast("Failed to initiate withdrawal", "error");
      statusEl.innerHTML = `<div style="color:var(--danger);padding:12px;background:rgba(239,68,68,0.1);border-radius:8px;">Network error. Try again.</div>`;
      statusEl.style.display = "block";
    } finally {
      setLoading(btn, false);
    }
  };
}
