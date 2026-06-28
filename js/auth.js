import { API_BASE } from "./firebase-config.js";

let currentUser = null;
let idToken = null;

export function getCurrentUser() {
  return currentUser;
}

export function getIdToken() {
  return idToken;
}

export async function initAuth(app) {
  const { getAuth, onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut } = await import("firebase/auth");
  const auth = getAuth(app);

  return new Promise((resolve) => {
    onAuthStateChanged(auth, async (user) => {
      if (user) {
        idToken = await user.getIdToken();
        currentUser = { uid: user.uid, email: user.email, displayName: user.displayName };
        const registered = await checkRegistration();
        resolve({ user: currentUser, registered, auth, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut });
      } else {
        currentUser = null;
        idToken = null;
        resolve({ user: null, registered: false, auth, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut });
      }
    });
  });
}

async function checkRegistration() {
  try {
    const resp = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${idToken}` },
    });
    if (resp.ok) return true;
    if (resp.status === 404) return false;
    return false;
  } catch {
    return false;
  }
}

export async function registerUser(pin, displayName, phone) {
  const resp = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
    body: JSON.stringify({ pin, displayName, phone }),
  });
  return resp.json();
}

export async function apiGet(path) {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  });
  return resp.json();
}

export async function apiPost(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
    body: JSON.stringify(body),
  });
  return resp.json();
}
