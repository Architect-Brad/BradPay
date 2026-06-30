import { firebaseConfig } from "./firebase-config.js";
import { initAuth, registerUser, getIdToken, getCurrentUser } from "./auth.js";
import { getBalance, sendMoney, getHistory, lookupUser, formatAmount, formatDate } from "./wallet.js";
import { initTrade, refreshTradeScreen } from "./trade.js";
import { initDaraja, refreshDaraja } from "./daraja.js";

const { initializeApp } = await import("firebase/app");
const app = initializeApp(firebaseConfig);

let auth = null;
let authFns = null;
let isRegisterMode = false;
let currentBalance = 0;
let pollInterval = null;
let screenStack = [];

const $ = (id) => document.getElementById(id);
const screens = {};

function registerScreen(name, el) {
  screens[name] = el;
}

function showScreen(name, push = true) {
  const prev = document.querySelector(".screen.active");
  if (prev && prev.id !== name + "-screen") {
    prev.classList.add("slide-left");
    setTimeout(() => prev.classList.remove("slide-left"), 300);
  }
  Object.values(screens).forEach((s) => s.classList.remove("active"));
  const target = screens[name];
  if (target) target.classList.add("active");

  if (push && name !== "auth" && name !== "register") {
    screenStack.push(name);
  }

  if (name === "dashboard") {
    refreshDashboard();
    startPolling();
  } else if (name === "ledger") {
    refreshLedger();
    stopPolling();
  } else if (name === "trade") {
    refreshTradeScreen();
    stopPolling();
  } else if (name === "deposit" || name === "withdraw") {
    refreshDaraja();
    stopPolling();
  } else {
    stopPolling();
  }
}

function goBack() {
  if (screenStack.length > 1) {
    screenStack.pop();
    const prev = screenStack[screenStack.length - 1];
    showScreen(prev, false);
  } else {
    showScreen("dashboard", false);
  }
}

// DOM registration
registerScreen("auth", $("auth-screen"));
registerScreen("register", $("register-screen"));
registerScreen("dashboard", $("dashboard-screen"));
registerScreen("send", $("send-screen"));
registerScreen("receive", $("receive-screen"));
registerScreen("deposit", $("deposit-screen"));
registerScreen("withdraw", $("withdraw-screen"));
registerScreen("ledger", $("ledger-screen"));
registerScreen("trade", $("trade-screen"));

function showToast(message, type = "info") {
  const container = $("toast-container");
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

function startPolling() {
  stopPolling();
  pollInterval = setInterval(refreshDashboard, 10000);
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

// ── Dashboard ──
async function refreshDashboard() {
  try {
    const bal = await getBalance();
    currentBalance = bal.balance || 0;
    $("balance-amount").textContent = formatAmount(currentBalance);
    refreshDaraja();

    const txData = await getHistory();
    const list = $("tx-list");
    const txs = txData.transactions || [];
    const user = getCurrentUser();

    const loading = $("tx-loading");
    if (loading) loading.style.display = "none";

    if (txs.length === 0) {
      list.innerHTML = '<div class="tx-empty"><div class="icon">📭</div><div>No transactions yet</div><div style="font-size:12px;color:var(--text3)">Send or receive to get started</div></div>';
      return;
    }

    list.innerHTML = txs
      .map((tx) => {
        const senderUid = tx.sender_uid || tx.sender_id;
        const isSent = senderUid === user?.uid;
        const name = isSent
          ? (tx.recipient_name || tx.recipientName || "User")
          : (tx.sender_name || tx.senderName || "User");
        const note = tx.note || tx.noteText || "";
        return `
          <div class="tx-item" data-tx-id="${tx.id || tx.tx_ref || ""}">
            <div class="tx-icon ${isSent ? "sent" : "received"}">${isSent ? "↑" : "↓"}</div>
            <div class="tx-info">
              <div class="tx-name">${isSent ? "To: " : "From: "}${escapeHtml(name)}</div>
              <div class="tx-date">${formatDate(tx.created_at)}${note ? ` · ${escapeHtml(note)}` : ""}</div>
            </div>
            <div class="tx-amount ${isSent ? "sent" : "received"}">
              ${isSent ? "-" : "+"}${formatAmount(tx.amount)}
            </div>
          </div>`;
      })
      .join("");

    // Tap to expand transaction detail
    list.querySelectorAll(".tx-item").forEach((el) => {
      el.onclick = () => {
        const wasExpanded = el.classList.contains("expanded");
        list.querySelectorAll(".tx-item.expanded").forEach((e) => {
          const detail = e.querySelector(".tx-detail");
          if (detail) detail.remove();
          e.classList.remove("expanded");
        });
        if (!wasExpanded) {
          const idx = Array.from(list.children).indexOf(el);
          const tx = txs[idx];
          if (!tx) return;
          const senderUid = tx.sender_uid || tx.sender_id;
          const isSent = senderUid === user?.uid;
          const detail = document.createElement("div");
          detail.className = "tx-detail";
          const rows = [
            { label: "Transaction ID", value: tx.tx_ref || tx.id || "—" },
            { label: "Type", value: isSent ? "Sent" : "Received" },
            { label: isSent ? "Recipient" : "Sender", value: escapeHtml(isSent ? (tx.recipient_name || tx.recipientUid || "—") : (tx.sender_name || tx.senderUid || "—")) },
            { label: "Amount", value: `${isSent ? "-" : "+"}KES ${formatAmount(tx.amount)}` },
            { label: "Date", value: formatDate(tx.created_at) },
            { label: "Note", value: tx.note || tx.noteText || "—" },
            { label: "Status", value: tx.status || "completed" },
          ];
          if (tx.fee) rows.push({ label: "Fee", value: `KES ${formatAmount(tx.fee)}` });
          detail.innerHTML = rows.map((r) =>
            `<div class="tx-detail-row"><span class="tx-detail-label">${r.label}</span><span class="tx-detail-value">${r.value}</span></div>`
          ).join("");
          el.appendChild(detail);
          el.classList.add("expanded");
        }
      };
    });
  } catch (e) {
    console.error("Dashboard refresh failed:", e);
  }
}

function escapeHtml(str) {
  if (!str) return "Unknown";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ── Ledger / Block Explorer ──
async function refreshLedger() {
  const list = $("block-list");
  const loading = $("block-loading");
  if (loading) loading.style.display = "flex";

  try {
    const resp = await fetch("/api/ledger/status");
    const status = await resp.json();
    $("ledger-blocks").textContent = status.blocks || 0;
    $("ledger-valid").textContent = status.valid ? "✓ Valid" : "✗ Invalid";
    const statEl = document.querySelector(".ledger-stat.valid");
    if (statEl) {
      statEl.classList.remove("valid", "invalid");
      statEl.classList.add(status.valid ? "valid" : "invalid");
    }

    // Pending bar
    const pending = status.pending_transactions || 0;
    const pendingBar = $("ledger-pending-bar");
    if (pending > 0) {
      pendingBar.style.display = "flex";
      $("pending-count").textContent = pending;
    } else {
      pendingBar.style.display = "none";
    }

    const chainResp = await fetch("/api/ledger/chain?per_page=20");
    const data = await chainResp.json();
    const chain = data.chain || [];

    if (loading) loading.style.display = "none";

    if (chain.length === 0) {
      list.innerHTML = '<div class="tx-empty"><div class="icon">⛓️</div><div>No blocks yet</div></div>';
      return;
    }

    const reversed = [...chain].reverse();
    list.innerHTML = reversed
      .map((block) => {
        const isGenesis = block.index === 0;
        const txCount = (block.transactions || []).length;
        const hash = block.hash || "";
        const prevHash = block.previous_hash || "";
        return `
          <div class="block-item ${isGenesis ? "genesis" : ""}">
            <div class="block-header">
              <span class="block-index">#${block.index} ${isGenesis ? '<span class="block-genesis-label">Genesis</span>' : ""}</span>
              <span class="block-timestamp">${new Date(block.timestamp).toLocaleString()}</span>
            </div>
            <div class="block-tx-count">${txCount} transaction${txCount !== 1 ? "s" : ""}${!isGenesis ? ` · Nonce: ${block.nonce}` : ""}</div>
            <div class="block-hash">Hash: ${hash.substring(0, 32)}…</div>
            ${!isGenesis ? `<div class="block-hash" style="margin-top:2px;">Prev: ${prevHash.substring(0, 32)}…</div>` : ""}
            ${txCount > 0 ? `<div style="margin-top:6px;"><a class="tx-proof-link" data-block="${block.index}">View transactions →</a></div>` : ""}
          </div>`;
      })
      .join("");

    // Click proof link to show txs in block
    list.querySelectorAll(".tx-proof-link").forEach((link) => {
      link.onclick = async (e) => {
        e.stopPropagation();
        const blockIdx = link.dataset.block;
        const blockResp = await fetch(`/api/ledger/block/${blockIdx}`);
        const blockData = await blockResp.json();
        const block = blockData.block;
        if (!block || !block.transactions || block.transactions.length === 0) {
          showToast("No transactions in block", "info");
          return;
        }
        showToast(`Block #${blockIdx}: ${block.transactions.length} transactions recorded on-chain`, "success");
      };
    });
  } catch (e) {
    console.error("Ledger refresh failed:", e);
    if (loading) loading.style.display = "none";
    list.innerHTML = '<div class="tx-empty"><div class="icon">⚠️</div><div>Failed to load ledger</div><div style="font-size:12px;color:var(--text3)">Check connection</div></div>';
  }
}

async function mineBlock() {
  const btn = $("ledger-mine-btn");
  setLoading(btn, true);
  try {
    const resp = await fetch("/api/ledger/mine", { method: "POST" });
    const data = await resp.json();
    if (resp.ok) {
      showToast(data.message || "Block mined!", "success");
    } else {
      showToast(data.error || "Failed to mine", "error");
    }
    refreshLedger();
  } catch {
    showToast("Failed to mine block", "error");
  } finally {
    setLoading(btn, false);
  }
}

// ── Auth ──
async function handleAuth(email, password) {
  try {
    if (!authFns) return;
    const { signInWithEmailAndPassword, createUserWithEmailAndPassword } = authFns;
    if (isRegisterMode) {
      await createUserWithEmailAndPassword(auth, email, password);
    } else {
      await signInWithEmailAndPassword(auth, email, password);
    }
  } catch (e) {
    const msg = e.code === "auth/user-not-found" ? "Account not found" :
                e.code === "auth/wrong-password" ? "Wrong password" :
                e.code === "auth/email-already-in-use" ? "Email already in use" :
                e.code === "auth/weak-password" ? "Password too weak (min 6 chars)" :
                e.message || "Authentication failed";
    const errorEl = isRegisterMode ? $("register-error") : $("auth-error");
    errorEl.textContent = msg;
    errorEl.style.display = "block";
    throw e;
  }
}

async function handleRegister() {
  const email = $("reg-email").value.trim();
  const password = $("reg-password").value;
  const name = $("reg-name").value.trim();
  const phone = $("reg-phone").value.trim();
  const pin = $("reg-pin").value;
  const pinConfirm = $("reg-pin-confirm").value;

  if (!email) { showToast("Email is required", "error"); return; }
  if (!password || password.length < 6) { showToast("Password must be at least 6 characters", "error"); return; }
  if (!name) { showToast("Name is required", "error"); return; }
  if (pin !== pinConfirm) { showToast("PINs don't match", "error"); return; }
  if (pin.length < 4) { showToast("PIN must be at least 4 digits", "error"); return; }

  setLoading($("register-submit"), true);
  try {
    const { createUserWithEmailAndPassword } = authFns;
    await createUserWithEmailAndPassword(auth, email, password);
  } catch (e) {
    const msg = e.code === "auth/email-already-in-use" ? "Email already in use" :
                e.code === "auth/weak-password" ? "Password too weak (min 6 chars)" :
                e.message || "Account creation failed";
    $("register-error").textContent = msg;
    $("register-error").style.display = "block";
    setLoading($("register-submit"), false);
    return;
  }

  // Auth state change will fire and init() will call checkRegistration()
  // Wait a tick for the token to be set, then register the wallet
  setTimeout(async () => {
    try {
      const result = await registerUser(pin, name, phone || undefined);
      if (result.error) {
        showToast(result.error, "error");
        setLoading($("register-submit"), false);
        return;
      }
      showToast("Wallet created!", "success");
      showScreen("dashboard");
    } catch (e) {
      showToast("Registration failed", "error");
    } finally {
      setLoading($("register-submit"), false);
    }
  }, 500);
}

// ── Send / Recipient Lookup ──
let lookupTimeout = null;
$("send-recipient").oninput = () => {
  clearTimeout(lookupTimeout);
  const info = $("send-recipient-info");
  info.style.display = "none";
  lookupTimeout = setTimeout(async () => {
    const val = $("send-recipient").value.trim();
    if (val.length < 3) return;
    try {
      const result = await lookupUser(val);
      if (result.error) {
        info.textContent = "❌ User not found";
        info.className = "recipient-info error";
      } else {
        info.innerHTML = `✅ ${escapeHtml(result.displayName || result.uid)}${result.email ? ` (${escapeHtml(result.email)})` : ""}`;
        info.className = "recipient-info success";
      }
      info.style.display = "block";
    } catch { /* ignore */ }
  }, 500);
};

async function handleSend() {
  const identifier = $("send-recipient").value.trim();
  const amountStr = $("send-amount").value.trim();
  const note = $("send-note").value.trim();

  if (!identifier) { showToast("Enter recipient email, phone, or UID", "error"); return; }
  if (!amountStr || parseFloat(amountStr) <= 0) { showToast("Enter a valid amount", "error"); return; }

  const amountCents = Math.round(parseFloat(amountStr) * 100);

  setLoading($("send-submit"), true);
  try {
    const lookup = await lookupUser(identifier);
    if (lookup.error) { showToast(lookup.error, "error"); return; }

    $("confirm-recipient").textContent = lookup.displayName || lookup.uid;
    $("confirm-amount").textContent = `KES ${amountStr}`;
    $("confirm-note").textContent = note ? `Note: ${note}` : "";
    $("confirm-pin").value = "";
    $("confirm-pin-error").textContent = "";
    $("confirm-pin-error").style.display = "none";
    $("confirm-submit").disabled = true;
    $("confirm-dialog").classList.add("active");
    $("confirm-pin").focus();

    $("confirm-pin").oninput = () => {
      const pin = $("confirm-pin").value;
      $("confirm-submit").disabled = pin.length < 4;
      $("confirm-pin-error").style.display = "none";
    };

    return new Promise((resolve) => {
      const submit = $("confirm-submit");
      const cancel = $("confirm-cancel");

      const cleanup = () => {
        $("confirm-dialog").classList.remove("active");
        submit.onclick = null;
        cancel.onclick = null;
      };

      submit.onclick = async () => {
        const pin = $("confirm-pin").value;
        if (pin.length < 4) { showToast("Enter your PIN", "error"); return; }

        setLoading(submit, true);
        const result = await sendMoney(lookup.uid, amountCents, note || undefined, pin);
        setLoading(submit, false);
        cleanup();

        if (result.error) {
          if (result.error.toLowerCase().includes("pin")) {
            $("confirm-pin-error").textContent = result.error;
            $("confirm-pin-error").style.display = "block";
            $("confirm-dialog").classList.add("active");
            return;
          }
          showToast(result.error, "error");
        } else {
          showToast(`Sent KES ${amountStr} successfully!`, "success");
          $("send-recipient").value = "";
          $("send-amount").value = "";
          $("send-note").value = "";
          $("send-recipient-info").style.display = "none";
          showScreen("dashboard");
        }
        resolve(result);
      };

      cancel.onclick = () => {
        cleanup();
        resolve(null);
      };

      $("confirm-pin").onkeydown = (e) => {
        if (e.key === "Enter" && !submit.disabled) submit.click();
      };
    });
  } catch (e) {
    showToast("Failed to look up recipient", "error");
  } finally {
    setLoading($("send-submit"), false);
  }
}

// ── QR Code ──
async function renderQR() {
  const canvas = $("qr-canvas");
  const user = getCurrentUser();
  if (!user) return;
  const uid = user.uid;
  $("receive-uid").textContent = uid;

  try {
    const resp = await fetch(
      `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(uid)}`,
      { mode: "cors" }
    );
    const blob = await resp.blob();
    const img = new Image();
    img.onload = () => {
      canvas.width = 240;
      canvas.height = 240;
      canvas.getContext("2d").drawImage(img, 0, 0);
    };
    img.src = URL.createObjectURL(blob);
  } catch {
    canvas.width = 240;
    canvas.height = 240;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, 240, 240);
    ctx.fillStyle = "#334155";
    ctx.font = "14px system-ui";
    ctx.textAlign = "center";
    ctx.fillText("QR unavailable", 120, 120);
    ctx.fillText("Share UID below", 120, 140);
  }
}

// ── Init ──
async function init() {
  const result = await initAuth(app);
  auth = result.auth;
  authFns = result;

  $("dashboard-user-name").textContent = result.user?.displayName
    ? `Welcome, ${result.user.displayName}`
    : "Welcome";

  // Don't override if user already navigated away from initial screen
  const activeId = document.querySelector(".screen.active")?.id;
  if (activeId && activeId !== "auth-screen" && activeId !== "register-screen") {
    return;
  }

  if (result.user) {
    if (result.registered) {
      screenStack = ["dashboard"];
      showScreen("dashboard", false);
      renderQR();
      initTrade();
      initDaraja();
    } else {
      showScreen("register");
    }
  } else {
    showScreen("auth");
  }
}

// ── Event Bindings ──
document.addEventListener("DOMContentLoaded", () => {
  init();

  $("auth-toggle").onclick = () => {
    isRegisterMode = true;
    showScreen("register");
    $("auth-error").style.display = "none";
  };
  $("register-toggle").onclick = () => {
    isRegisterMode = false;
    showScreen("auth");
    $("register-error").style.display = "none";
  };

  $("auth-submit").onclick = async () => {
    $("auth-error").style.display = "none";
    const email = $("auth-email").value;
    const password = $("auth-password").value;
    if (!email || !password) { showToast("Fill in all fields", "error"); return; }
    setLoading($("auth-submit"), true);
    try {
      await handleAuth(email, password);
    } catch (e) { /* handled in handleAuth */ }
    setLoading($("auth-submit"), false);
    $("auth-submit").textContent = "Sign In";
  };
  $("auth-password").onkeydown = (e) => { if (e.key === "Enter") $("auth-submit").click(); };

  $("register-submit").onclick = () => handleRegister();
  $("reg-password").onkeydown = (e) => { if (e.key === "Enter") $("register-submit").click(); };

  $("logout-btn").onclick = async () => {
    if (authFns) {
      await authFns.signOut(auth);
      stopPolling();
      screenStack = [];
      showScreen("auth");
    }
  };

  $("action-send").onclick = () => {
    showScreen("send");
    $("send-recipient").focus();
    $("send-recipient-info").style.display = "none";
  };
  $("action-receive").onclick = () => {
    renderQR();
    showScreen("receive");
  };
  $("action-deposit").onclick = () => {
    showScreen("deposit");
  };
  $("action-withdraw").onclick = () => {
    showScreen("withdraw");
  };
  $("action-ledger").onclick = () => {
    showScreen("ledger");
  };
  $("action-trade").onclick = () => {
    refreshTradeScreen();
    showScreen("trade");
  };
  $("send-back").onclick = goBack;
  $("receive-back").onclick = goBack;
  $("deposit-back").onclick = goBack;
  $("withdraw-back").onclick = goBack;
  $("ledger-back").onclick = goBack;
  $("trade-back").onclick = goBack;

  $("send-submit").onclick = handleSend;
  $("send-amount").onkeydown = (e) => { if (e.key === "Enter") handleSend(); };

  $("receive-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("receive-uid").textContent);
      showToast("UID copied!", "success");
    } catch {
      showToast("Could not copy", "error");
    }
  };

  $("ledger-mine-btn").onclick = mineBlock;
});
