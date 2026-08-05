import { SUPABASE_URL, SUPABASE_ANON_KEY } from "../sync-config.js";
import { setAccessToken, setTokenProvider } from "./state.js";
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

  // API 호출 때마다 "지금 유효한 토큰"을 꺼내갈 수 있게 등록한다.
  // 로그인 시점의 토큰을 붙잡아두면 1시간 뒤 만료되어 이후 호출이
  // 전부 401이 된다 - state.js의 apiHeaders() 주석 참고.
  //
  // getSession()만으로는 부족하다. 페이지를 열 때 localStorage에 남아있던
  // 세션이 이미 만료됐어도 getSession()은 그 만료된 토큰을 그대로 돌려주고,
  // supabase-js의 자동 갱신은 조금 뒤에야 돈다. 그래서 페이지 로드 직후
  // 첫 API 호출만 401이 나는 현상이 있었다(로그상 로드당 정확히 1회).
  // 만료가 임박했거나 이미 지났으면 여기서 직접 갱신한다.
  setTokenProvider(async () => {
    const { data } = await supabaseClient.auth.getSession();
    const session = data.session;
    if (!session) return null;

    const now = Math.floor(Date.now() / 1000);
    const needsRefresh = !session.expires_at || session.expires_at - now < 60;
    if (!needsRefresh) return session.access_token;

    try {
      const { data: refreshed, error } = await supabaseClient.auth.refreshSession();
      if (error || !refreshed.session) return session.access_token;
      return refreshed.session.access_token;
    } catch (e) {
      // 갱신 실패는 조용히 넘긴다 - 만료된 토큰이라도 보내보고,
      // 서버가 401을 주면 사용자가 다시 로그인하면 된다.
      return session.access_token;
    }
  });

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
