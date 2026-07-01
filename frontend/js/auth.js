import { API_BASE } from "./firebase-config.js";

let currentUser = null;
let idToken = null;
let _onChange = null;
let _pending = null;

export function getCurrentUser() {
  return currentUser;
}

export function getIdToken() {
  return idToken;
}

export function onAuthChange(cb) {
  _onChange = cb;
  if (_pending) {
    const p = _pending;
    _pending = null;
    cb(p);
  }
}

async function handleUser(user) {
  let data;
  if (user) {
    idToken = await user.getIdToken();
    currentUser = { uid: user.uid, email: user.email, displayName: user.displayName };
    const registered = await checkRegistration();
    data = { user: currentUser, registered };
  } else {
    currentUser = null;
    idToken = null;
    data = { user: null, registered: false };
  }
  if (_onChange) {
    _onChange(data);
  } else {
    _pending = data;
  }
}

export async function initAuth(app) {
  const { getAuth, onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut, GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  const auth = getAuth(app);

  onAuthStateChanged(auth, handleUser);

  return { auth, signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut, GoogleAuthProvider, signInWithPopup };
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
