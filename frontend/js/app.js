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

// DOM refs
const $ = (id) => document.getElementById(id);
const screens = {
  auth: $("auth-screen"),
  register: $("register-screen"),
  dashboard: $("dashboard-screen"),
  send: $("send-screen"),
  receive: $("receive-screen"),
};

// Screen management
function showScreen(name) {
  Object.values(screens).forEach((s) => s.classList.remove("active"));
  if (screens[name]) screens[name].classList.add("active");
}

// Toast
function showToast(message, type = "info") {
  const container = $("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
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

    if (txs.length === 0) {
      list.innerHTML = '<div class="tx-empty">No transactions yet</div>';
      return;
    }

    list.innerHTML = txs
      .map((tx) => {
        const isSent = tx.sender_id === getCurrentUser()?.localId;
        const name = isSent ? tx.recipient_name || "User" : tx.sender_name || "User";
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

  try {
    const result = await registerUser(pin, name, phone || undefined);
    if (result.error) {
      showToast(result.error, "error");
      return;
    }
    showToast("Wallet created!", "success");
    showScreen("dashboard");
    refreshDashboard();
  } catch (e) {
    showToast("Registration failed", "error");
  }
}

async function handleSend() {
  const identifier = $("send-recipient").value.trim();
  const amountStr = $("send-amount").value.trim();
  const note = $("send-note").value.trim();

  if (!identifier) { showToast("Enter recipient email, phone, or UID", "error"); return; }
  if (!amountStr || parseFloat(amountStr) <= 0) { showToast("Enter a valid amount", "error"); return; }

  const amountCents = Math.round(parseFloat(amountStr) * 100);

  try {
    const lookup = await lookupUser(identifier);
    if (lookup.error) { showToast(lookup.error, "error"); return; }

    $("confirm-recipient").textContent = lookup.displayName || lookup.uid;
    $("confirm-amount").textContent = `${amountStr} BC`;
    $("confirm-note").textContent = note ? `Note: ${note}` : "";

    $("confirm-dialog").classList.add("active");

    return new Promise((resolve) => {
      const submit = $("confirm-submit");
      const cancel = $("confirm-cancel");

      const cleanup = () => {
        $("confirm-dialog").classList.remove("active");
        submit.onclick = null;
        cancel.onclick = null;
      };

      submit.onclick = async () => {
        cleanup();
        const result = await sendMoney(lookup.uid, amountCents, note || undefined);
        if (result.error) {
          showToast(result.error, "error");
        } else {
          showToast(`Sent ${amountStr} BC successfully!`, "success");
          $("send-recipient").value = "";
          $("send-amount").value = "";
          $("send-note").value = "";
          showScreen("dashboard");
          refreshDashboard();
        }
        resolve(result);
      };

      cancel.onclick = () => {
        cleanup();
        resolve(null);
      };
    });
  } catch (e) {
    showToast("Failed to look up recipient", "error");
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
      refreshDashboard();
    } else {
      showScreen("register");
    }
  } else {
    showScreen("auth");
  }

  // Watch auth state changes
  auth.onIdTokenChanged?.(async (user) => {
    if (!user) {
      showScreen("auth");
    }
  });
}

// Event bindings
document.addEventListener("DOMContentLoaded", () => {
  init();

  // Auth toggle
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

  // Auth submit
  $("auth-submit").onclick = async () => {
    $("auth-error").style.display = "none";
    const email = $("auth-email").value;
    const password = $("auth-password").value;
    if (!email || !password) { showToast("Fill in all fields", "error"); return; }
    $("auth-submit").disabled = true;
    $("auth-submit").textContent = "Loading...";
    try {
      await handleAuth(email, password);
    } catch (e) { /* handled in handleAuth */ }
    $("auth-submit").disabled = false;
    $("auth-submit").textContent = "Sign In";
  };

  // Register submit
  $("register-submit").onclick = () => handleRegister();

  // Enter key support
  $("auth-password").onkeydown = (e) => { if (e.key === "Enter") $("auth-submit").click(); };
  $("reg-pin-confirm").onkeydown = (e) => { if (e.key === "Enter") $("register-submit").click(); };

  // Logout
  $("logout-btn").onclick = async () => {
    if (authFns) {
      await authFns.signOut(auth);
      showScreen("auth");
    }
  };

  // Navigation
  $("action-send").onclick = () => { showScreen("send"); $("send-recipient").focus(); };
  $("action-receive").onclick = () => {
    const user = getCurrentUser();
    $("receive-uid").textContent = user?.uid || "---";
    showScreen("receive");
  };
  $("send-back").onclick = () => { showScreen("dashboard"); refreshDashboard(); };
  $("receive-back").onclick = () => showScreen("dashboard");

  // Send
  $("send-submit").onclick = handleSend;
  $("send-amount").onkeydown = (e) => { if (e.key === "Enter") handleSend(); };

  // Receive copy
  $("receive-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("receive-uid").textContent);
      showToast("UID copied!", "success");
    } catch {
      showToast("Could not copy", "error");
    }
  };
});
