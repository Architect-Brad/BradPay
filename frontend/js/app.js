import { firebaseConfig } from "./firebase-config.js";
import { initAuth, registerUser, getIdToken, getCurrentUser } from "./auth.js";
import { getBalance, sendMoney, getHistory, lookupUser, formatAmount, formatDate } from "./wallet.js";

const { initializeApp } = await import("firebase/app");
const app = initializeApp(firebaseConfig);

// State
let auth = null;
let authFns = null;
let isRegisterMode = false;
let currentBalance = 0;
let pollInterval = null;

// DOM refs
const $ = (id) => document.getElementById(id);
const screens = {
  auth: $("auth-screen"),
  register: $("register-screen"),
  dashboard: $("dashboard-screen"),
  send: $("send-screen"),
  receive: $("receive-screen"),
};

function showScreen(name) {
  Object.values(screens).forEach((s) => s.classList.remove("active"));
  if (screens[name]) screens[name].classList.add("active");
  if (name === "dashboard") {
    refreshDashboard();
    startPolling();
  } else {
    stopPolling();
  }
}

function showToast(message, type = "info") {
  const container = $("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function setLoading(el, loading) {
  if (loading) {
    el.disabled = true;
    el.dataset.text = el.textContent;
    el.innerHTML = '<span class="spinner" style="width:18px;height:18px;border-width:2px;"></span>';
  } else {
    el.disabled = false;
    el.textContent = el.dataset.text || el.textContent;
  }
}

// Polling for real-time updates
function startPolling() {
  stopPolling();
  pollInterval = setInterval(refreshDashboard, 10000);
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

// Dashboard
async function refreshDashboard() {
  try {
    const bal = await getBalance();
    currentBalance = bal.balance || 0;
    $("balance-amount").textContent = formatAmount(currentBalance);

    const txData = await getHistory();
    const list = $("tx-list");
    const txs = txData.transactions || [];
    const user = getCurrentUser();

    if (txs.length === 0) {
      list.innerHTML = '<div class="tx-empty">No transactions yet</div>';
      return;
    }

    list.innerHTML = txs
      .map((tx) => {
        const senderUid = tx.sender_uid || tx.sender_id;
        const isSent = senderUid === user?.uid;
        const name = isSent
          ? (tx.recipient_name || tx.recipientName || "User")
          : (tx.sender_name || tx.senderName || "User");
        return `
          <div class="tx-item">
            <div class="tx-icon ${isSent ? "sent" : "received"}">${isSent ? "↑" : "↓"}</div>
            <div class="tx-info">
              <div class="tx-name">${isSent ? "To: " : "From: "}${escapeHtml(name)}</div>
              <div class="tx-date">${formatDate(tx.created_at)}</div>
            </div>
            <div class="tx-amount ${isSent ? "sent" : "received"}">
              ${isSent ? "-" : "+"}${formatAmount(tx.amount)}
            </div>
          </div>`;
      })
      .join("");
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

// Auth flow
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
  const pin = $("reg-pin").value;
  const pinConfirm = $("reg-pin-confirm").value;
  const name = $("reg-name").value;
  const phone = $("reg-phone").value;

  if (!name) { showToast("Name is required", "error"); return; }
  if (pin !== pinConfirm) { showToast("PINs don't match", "error"); return; }
  if (pin.length < 4) { showToast("PIN must be at least 4 digits", "error"); return; }

  setLoading($("register-submit"), true);
  try {
    const result = await registerUser(pin, name, phone || undefined);
    if (result.error) { showToast(result.error, "error"); return; }
    showToast("Wallet created!", "success");
    showScreen("dashboard");
  } catch (e) {
    showToast("Registration failed", "error");
  } finally {
    setLoading($("register-submit"), false);
  }
}

// Live recipient lookup on input
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
    $("confirm-amount").textContent = `${amountStr} BC`;
    $("confirm-note").textContent = note ? `Note: ${note}` : "";
    $("confirm-pin").value = "";
    $("confirm-pin-error").textContent = "";
    $("confirm-pin-error").style.display = "none";
    $("confirm-submit").disabled = true;
    $("confirm-dialog").classList.add("active");
    $("confirm-pin").focus();

    // Enable submit when PIN is entered
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
          showToast(`Sent ${amountStr} BC successfully!`, "success");
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

// QR Code
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
    // Fallback: draw simple placeholder
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

// Init
async function init() {
  const result = await initAuth(app);
  auth = result.auth;
  authFns = result;

  if (result.user) {
    if (result.registered) {
      showScreen("dashboard");
      renderQR();
    } else {
      showScreen("register");
    }
  } else {
    showScreen("auth");
  }
}

// Event bindings
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
  $("reg-pin-confirm").onkeydown = (e) => { if (e.key === "Enter") $("register-submit").click(); };

  $("logout-btn").onclick = async () => {
    if (authFns) {
      await authFns.signOut(auth);
      stopPolling();
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
  $("send-back").onclick = () => { showScreen("dashboard"); };
  $("receive-back").onclick = () => showScreen("dashboard");

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
});
