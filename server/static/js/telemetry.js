import { renderTelemetryChart } from "./charts.js";
import { apiHeaders, getAccessToken } from "./state.js";

const terminalStatuses = new Set(["done", "error", "lost", "interrupted"]);

let initialized = false;
let pollTimer = null;
let currentRunId = null;
let currentLogId = null;
let signals = [];

function el(id) {
  return document.getElementById(id);
}

function setProgress(status, text, pct = null) {
  el("telemetryStatus").textContent = status;
  el("telemetryText").textContent = text;
  el("telemetryBar").style.width = pct == null ? "0%" : `${pct}%`;
}

function setError(message = "") {
  el("telemetryErr").textContent = message;
}

async function loadSignals() {
  const res = await fetch("/api/telemetry/signals");
  if (!res.ok) throw new Error("Failed to load telemetry signals.");
  const data = await res.json();
  signals = data.primary || [];
  const select = el("telemetrySignalSelect");
  select.innerHTML = "";
  signals.forEach((signal) => {
    const option = document.createElement("option");
    option.value = signal.can_id;
    option.textContent = `${signal.can_id} ${signal.group} ${signal.name}`;
    select.appendChild(option);
  });
}

async function loadLogs() {
  const headers = await apiHeaders();
  const res = await fetch("/api/telemetry/logs", { headers });
  if (!res.ok) throw new Error("Failed to load telemetry logs.");
  const data = await res.json();
  renderLogList(data.logs || []);
}

function renderLogList(logs) {
  const box = el("telemetryLogList");
  box.innerHTML = "";
  if (!logs.length) {
    box.textContent = "No telemetry logs yet.";
    return;
  }
  logs.forEach((log) => {
    const line = document.createElement("div");
    line.className = "log-line";

    const row = document.createElement("button");
    row.type = "button";
    row.className = "log-row";
    row.textContent = `${log.file_name || log.id} · ${statusLabel(log.status)} · ${log.frame_count || 0} frames`;
    row.addEventListener("click", () => openLog(log.id));
    line.appendChild(row);

    // 실패한 업로드가 계속 쌓이는데 지울 방법이 없었다.
    const del = document.createElement("button");
    del.type = "button";
    del.className = "log-delete";
    del.textContent = "Delete";
    del.title = "이 업로드 기록을 삭제합니다";
    del.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deleteLog(log.id, log.file_name);
    });
    line.appendChild(del);

    box.appendChild(line);
  });
}

function statusLabel(status) {
  const map = {
    queued: "Queued",
    running: "Running",
    done: "Done",
    error: "Error",
    lost: "Lost",
    interrupted: "Interrupted",
  };
  return map[status] || status || "-";
}

async function deleteLog(logId, fileName) {
  if (!window.confirm(`${fileName || logId} 기록을 삭제할까요? 저장된 프레임도 함께 지워집니다.`)) return;
  setError();
  try {
    const headers = await apiHeaders();
    const res = await fetch(`/api/telemetry/logs/${logId}`, { method: "DELETE", headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Telemetry delete failed.");
    if (currentLogId === logId) {
      currentLogId = null;
      el("telemetryChartCard").hidden = true;
    }
    await loadLogs();
  } catch (e) {
    setError(e.message);
  }
}

async function uploadLog() {
  setError();
  const fileInput = el("telemetryFile");
  const file = fileInput.files?.[0];
  if (!file) {
    setError("Choose a canlog.csv file first.");
    return;
  }
  const headers = await apiHeaders();
  const token = headers.Authorization;
  if (!getAccessToken()) {
    setError("Sign in again before uploading.");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  el("telemetryUploadBtn").disabled = true;
  setProgress("Uploading", "Sending log file...", 8);
  try {
    const res = await fetch("/api/telemetry/logs", {
      method: "POST",
      headers: { Authorization: token },
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Telemetry upload failed.");
    currentRunId = data.run_id;
    setProgress("Queued", "Waiting for parser worker...", 15);
    pollRun(currentRunId);
    await loadLogs();
  } catch (e) {
    setError(e.message);
    setProgress("Ready.", "Upload failed.", 0);
  } finally {
    el("telemetryUploadBtn").disabled = false;
  }
}

async function pollRun(runId) {
  if (pollTimer) window.clearTimeout(pollTimer);
  const headers = await apiHeaders();
  const res = await fetch(`/api/telemetry/logs/${runId}`, { headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    setError(data.detail || "Telemetry status failed.");
    return;
  }
  const status = data.status;
  if (status === "queued") {
    setProgress("Queued", `Queue position ${data.position || 1}`, 20);
  } else if (status === "running") {
    setProgress("Running", `${data.frame_count || 0} frames parsed`, 55);
  } else if (status === "finalizing") {
    setProgress("Finalizing", "Writing summary...", 90);
  } else if (status === "done") {
    setProgress("Done", `${data.result?.frame_count || 0} frames saved`, 100);
    await loadLogs();
    await openLog(runId);
    return;
  } else {
    setProgress(status || "Stopped", data.detail || data.result?.error || "Telemetry run ended.", 0);
    await loadLogs();
    return;
  }
  if (!terminalStatuses.has(status)) {
    pollTimer = window.setTimeout(() => pollRun(runId), 2000);
  }
}

async function openLog(logId) {
  currentLogId = logId;
  el("telemetryChartCard").hidden = false;
  const select = el("telemetrySignalSelect");
  if (!select.value && signals.length) {
    select.value = signals[0].can_id;
  }
  await loadSeries();
}

async function loadSeries() {
  if (!currentLogId) return;
  const select = el("telemetrySignalSelect");
  const signal = signals.find((item) => item.can_id === select.value) || signals[0];
  if (!signal) return;
  const headers = await apiHeaders();
  const res = await fetch(`/api/telemetry/logs/${currentLogId}/series?can_id=${encodeURIComponent(signal.can_id)}&limit=2000`, { headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Telemetry series failed.");
  const frames = data.frames || [];
  el("telemetryChartTitle").textContent = `${signal.can_id} ${signal.name}`;
  el("telemetryFrameCount").textContent = `${frames.length} frames`;
  renderTelemetryChart(el("telemetryChart"), frames, signal);
}

export function initTelemetry() {
  if (initialized) return;
  initialized = true;
  el("telemetryUploadBtn").addEventListener("click", uploadLog);
  el("telemetryRefreshBtn").addEventListener("click", () => loadLogs().catch((e) => setError(e.message)));
  el("telemetrySignalSelect").addEventListener("change", () => loadSeries().catch((e) => setError(e.message)));
  loadSignals()
    .then(loadLogs)
    .catch((e) => setError(e.message));
}
