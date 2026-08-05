import { getCurrentUser, getSupabaseClient } from "./auth.js";

const dialog = () => document.getElementById("auxDialog");
const titleEl = () => document.getElementById("auxTitle");
const bodyEl = () => document.getElementById("auxBody");

function openAux(title, html) {
  titleEl().textContent = title;
  bodyEl().innerHTML = html;
  dialog().showModal();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function showReleaseNotes() {
  const res = await fetch("./data/release-notes.json");
  const notes = await res.json();
  openAux(
    "Release Notes",
    notes
      .map((note) => `
        <div class="note-item">
          <strong>v${note.version} · ${note.title}</strong>
          <p class="hint">${note.date}</p>
          ${(note.details || []).map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
        </div>
      `)
      .join("")
  );
}

async function showTutorial() {
  const client = await getSupabaseClient();
  const user = await getCurrentUser();
  openAux(
    "Tutorial",
    `
      <p>Run a simulation from the Simulator tab, inspect route progress and charts, then download the CSV if needed.</p>
      <p>Use Vehicle Settings to adjust the car model and save account-specific settings.</p>
      <p>Use Optuna Search for longer parameter exploration on the shared server.</p>
      <button class="btn" id="tutorialSeenBtn" type="button">Mark as Seen</button>
    `
  );
  document.getElementById("tutorialSeenBtn").addEventListener("click", async () => {
    await client.auth.updateUser({ data: { ...(user.user_metadata || {}), tutorial_seen: true } });
    dialog().close();
  });
}

async function showCode() {
  const url = "https://raw.githubusercontent.com/Dorolong/WSC_Project/main/Functions/Vehicle_Function.py";
  const res = await fetch(url);
  const text = await res.text();
  openAux("Code", `<pre class="code-block">${escapeHtml(text)}</pre>`);
}

function rowTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

async function showHistory() {
  const client = await getSupabaseClient();
  const user = await getCurrentUser();
  const [simRes, optunaRes] = await Promise.all([
    client
      .from("simulation_runs")
      .select("created_at, completion_ratio, avg_speed_kmh, final_soc, final_dist_m")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false })
      .limit(20),
    client
      .from("optuna_runs")
      .select("study_name, updated_at, n_trials_completed, n_trials_target, best_value, status, best_params")
      .eq("user_id", user.id)
      .order("updated_at", { ascending: false })
      .limit(20),
  ]);

  if (simRes.error) throw simRes.error;
  if (optunaRes.error) throw optunaRes.error;

  const simHtml = (simRes.data || [])
    .map((row) => `
      <div class="history-item">
        <strong>${rowTime(row.created_at)}</strong>
        <p class="hint">${(row.completion_ratio * 100).toFixed(1)}% · ${row.avg_speed_kmh.toFixed(1)} km/h · SOC ${(row.final_soc * 100).toFixed(1)}%</p>
      </div>
    `)
    .join("") || "<p class=\"hint\">No simulation history.</p>";

  const optunaHtml = (optunaRes.data || [])
    .map((row) => `
      <div class="history-item">
        <strong>${escapeHtml(row.study_name)}</strong>
        <p class="hint">${rowTime(row.updated_at)} · ${row.status} · ${row.n_trials_completed}/${row.n_trials_target} · ${row.best_value ?? "-"}</p>
      </div>
    `)
    .join("") || "<p class=\"hint\">No Optuna history.</p>";

  openAux("History", `<h2>Simulations</h2>${simHtml}<h2>Optuna</h2>${optunaHtml}`);
}

export function initAuxiliary() {
  document.getElementById("releaseNotesBtn").addEventListener("click", () => showReleaseNotes().catch((e) => openAux("Error", escapeHtml(e.message))));
  document.getElementById("tutorialBtn").addEventListener("click", () => showTutorial().catch((e) => openAux("Error", escapeHtml(e.message))));
  document.getElementById("historyBtn").addEventListener("click", () => showHistory().catch((e) => openAux("Error", escapeHtml(e.message))));
  document.getElementById("codeViewerBtn").addEventListener("click", () => showCode().catch((e) => openAux("Error", escapeHtml(e.message))));
  document.getElementById("auxClose").addEventListener("click", () => dialog().close());
}
