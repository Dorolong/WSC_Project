import { apiHeaders, getAccessToken } from "./state.js";

let myRunId = null;

function setBar(id, pct) {
  document.getElementById(id).style.width = `${pct}%`;
}

function setLoadClass(el, pct) {
  el.className = pct < 50 ? "status-pill" : pct < 75 ? "status-pill warn" : "status-pill busy";
}

function setBarClass(el, pct) {
  el.className = pct < 50 ? "bar-fill" : pct < 75 ? "bar-fill warn" : "bar-fill busy";
}

export async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const pill = document.getElementById("statusPill");
    const bar = document.getElementById("statusBar");
    const text = document.getElementById("statusText");

    pill.textContent = `${data.level} ${data.occupancy_pct}%`;
    setLoadClass(pill, data.occupancy_pct);
    setBar("statusBar", data.occupancy_pct);
    setBarClass(bar, data.occupancy_pct);
    text.textContent = `Running ${data.active}/${data.max_concurrent}` + (data.queued > 0 ? ` · Queue ${data.queued}` : "");

    const runningEl = document.getElementById("runningList");
    const lines = [];
    (data.running || []).forEach((r) => lines.push(`Running: ${r.nickname}`));
    (data.queue || []).forEach((q, i) => lines.push(`Queue ${i + 1}: ${q.nickname}`));
    runningEl.innerHTML = lines.map((line) => `<p class="hint">${line}</p>`).join("");
  } catch (e) {
    // The next scheduled refresh can recover from transient failures.
  }
}

export async function resumeMyRun() {
  if (!getAccessToken()) return;
  try {
    const res = await fetch("/api/my-active-run", { headers: await apiHeaders() });
    const data = await res.json();
    if (!data.run_id) return;
    myRunId = data.run_id;
    document.getElementById("myRunCard").hidden = false;
    pollMyRun();
  } catch (e) {
    // The next scheduled refresh can recover from transient failures.
  }
}

function formatSeconds(sec) {
  if (sec === null || sec === undefined) return "";
  if (sec < 60) return "under 1 min";
  const mins = Math.round(sec / 60);
  if (mins < 60) return `about ${mins} min`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return `about ${hrs}h ${rem}m`;
}

async function startRun() {
  const nTrials = parseInt(document.getElementById("nTrials").value, 10);
  const errEl = document.getElementById("runErr");
  const btn = document.getElementById("runBtn");
  errEl.textContent = "";
  btn.disabled = true;

  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: await apiHeaders(),
      body: JSON.stringify({ n_trials: nTrials }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Run request failed.");
    }
    const data = await res.json();
    myRunId = data.run_id;
    document.getElementById("myRunCard").hidden = false;
    document.getElementById("myRunResult").hidden = true;
    pollMyRun();
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function pollMyRun() {
  if (!myRunId) return;
  try {
    const res = await fetch(`/api/runs/${myRunId}`, { headers: await apiHeaders() });
    const data = await res.json();
    const statusEl = document.getElementById("myRunStatus");
    const text = document.getElementById("myRunText");

    if (data.status === "queued") {
      statusEl.textContent = "Queued";
      setBar("myRunBar", 0);
      const waitStr = formatSeconds(data.estimated_wait_seconds);
      text.textContent = `Queue position ${data.position}` + (waitStr ? ` · Expected wait ${waitStr}` : "");
    } else if (data.status === "running") {
      statusEl.textContent = "Running";
      const pct = data.progress_pct ?? 0;
      setBar("myRunBar", pct);
      const remainStr = formatSeconds(data.estimated_remaining_seconds);
      text.textContent = `Trial ${data.trial_current ?? 0} / ${data.n_trials} (${pct}%)` + (remainStr ? ` · Remaining ${remainStr}` : "");
    } else if (data.status === "finalizing") {
      statusEl.textContent = "Finalizing";
      text.textContent = "Preparing results...";
    } else if (data.status === "done") {
      statusEl.textContent = "Done";
      setBar("myRunBar", 100);
      text.textContent = "Search complete.";
      showResult(data.result);
    } else if (data.status === "error") {
      statusEl.textContent = "Error";
      text.textContent = data.result?.error || "Search failed.";
    }
  } catch (e) {
    // The next scheduled refresh can recover from transient failures.
  }
}

function showResult(result) {
  const box = document.getElementById("myRunResult");
  box.hidden = false;
  const paramsHtml = Object.entries(result.best_params || {})
    .map(([k, v]) => `<div class="kv"><span>${k}</span><span>${typeof v === "number" ? v.toFixed(3) : v}</span></div>`)
    .join("");
  box.innerHTML = `
    <div class="kv"><span>Best Value</span><span>${Number(result.best_value).toFixed(3)}</span></div>
    <div class="kv"><span>Termination</span><span>${result.termination_reason ?? "-"}</span></div>
    <div class="section-label">Best Params</div>
    ${paramsHtml}
  `;
}

export function initOptuna() {
  document.getElementById("runBtn").addEventListener("click", startRun);
}
