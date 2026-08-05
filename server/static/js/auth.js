import { SUPABASE_URL, SUPABASE_ANON_KEY } from "../sync-config.js";
import { setAccessToken } from "./state.js";
import { resumeMyRun, refreshStatus } from "./optuna.js";

let supabaseClient = null;
let userEmail = null;
let statusTimer = null;
let myRunTimer = null;
const authenticatedCallbacks = [];

const SAVED_EMAIL_KEY = "wscOptunaSavedEmail";

async function getClient() {
  if (supabaseClient) return supabaseClient;
  const mod = await import("https://esm.sh/@supabase/supabase-js@2");
  supabaseClient = mod.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return supabaseClient;
}

export async function getSupabaseClient() {
  return getClient();
}

export async function getCurrentUser() {
  const client = await getClient();
  const { data, error } = await client.auth.getUser();
  if (error) throw error;
  return data.user;
}

function showGate() {
  document.getElementById("app").hidden = true;
  document.getElementById("gate").hidden = false;
}

function showApp() {
  document.getElementById("gate").hidden = true;
  document.getElementById("app").hidden = false;
  document.getElementById("loggedInAs").textContent = userEmail ? `Signed in as ${userEmail}` : "";

  refreshStatus();
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(refreshStatus, 4000);

  resumeMyRun();
  if (myRunTimer) clearInterval(myRunTimer);
  myRunTimer = setInterval(resumeMyRun, 3000);
  authenticatedCallbacks.forEach((callback) => callback());
}

export async function tryAutoLogin() {
  const saved = localStorage.getItem(SAVED_EMAIL_KEY);
  if (saved) {
    document.getElementById("email").value = saved;
    document.getElementById("rememberEmail").checked = true;
  }

  const client = await getClient();
  const { data } = await client.auth.getSession();
  if (data.session) {
    setAccessToken(data.session.access_token);
    userEmail = data.session.user.email;
    showApp();
  }
}

async function login() {
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const remember = document.getElementById("rememberEmail").checked;
  const errEl = document.getElementById("gateErr");
  errEl.textContent = "";

  if (!email || !password) {
    errEl.textContent = "Enter email and password.";
    return;
  }

  try {
    const client = await getClient();
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    setAccessToken(data.session.access_token);
    userEmail = data.session.user.email;
    if (remember) localStorage.setItem(SAVED_EMAIL_KEY, email);
    else localStorage.removeItem(SAVED_EMAIL_KEY);
    showApp();
  } catch (e) {
    errEl.textContent = e.message || "Sign in failed.";
  }
}

async function logout() {
  const client = await getClient();
  await client.auth.signOut();
  setAccessToken(null);
  userEmail = null;
  if (statusTimer) clearInterval(statusTimer);
  if (myRunTimer) clearInterval(myRunTimer);
  document.getElementById("myRunCard").hidden = true;
  document.getElementById("password").value = "";
  showGate();
}

export function initAuth() {
  document.getElementById("loginBtn").addEventListener("click", login);
  document.getElementById("logoutBtn").addEventListener("click", logout);
  tryAutoLogin();
}

export function onAuthenticated(callback) {
  authenticatedCallbacks.push(callback);
}
