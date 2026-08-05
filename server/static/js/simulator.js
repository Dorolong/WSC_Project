import { apiHeaders } from "./state.js";
import { renderSimulationChart } from "./charts.js";
import { getCurrentUser, getSupabaseClient } from "./auth.js";
import { initRouteMap, setRouteProgress } from "./route-map.js";

let simRunId = null;
let simTimer = null;
let vehicleConfigProvider = () => ({});
let lastResult = null;
let lastCfg = null;
let lastParams = {};

function setBar(id, pct) {
  document.getElementById(id).style.width = `${pct}%`;
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}

function analysisText(result) {
  if (result.reason === "완주") {
    return `Finished with minimum SOC ${(result.final_soc * 100).toFixed(1)}%.`;
  }
  if ((result.reason || "").includes("SOC")) {
    return `Stopped because of SOC condition: ${result.reason}`;
  }
  if ((result.reason || "").includes("마감시각")) {
    return `Stopped because the pace missed a close time: ${result.reason}`;
  }
  if ((result.reason || "").includes("구간 평균속도")) {
    return `Stopped because a control-stop leg average speed was too low: ${result.reason}`;
  }
  return `Stopped: ${result.reason || "-"}`;
}

async function finishRun(data) {
  const result = data.result;
  lastResult = result;
  setBar("simBar", 100);
  setRouteProgress(result.completion_ratio || 1, result.route);
  setText("simStatus", "Done");
  setText("simText", result.reason || "Simulation complete.");

  document.getElementById("simMetrics").innerHTML = [
    metric("Average Speed", `${result.avg_speed_kmh.toFixed(1)} km/h`),
    metric("Max Speed", `${result.max_speed_kmh.toFixed(1)} km/h`),
    metric("Distance", `${(result.final_dist_m / 1000).toFixed(0)} km`),
    metric("Min SOC", `${(result.final_soc * 100).toFixed(1)}%`),
    metric("Avg Consumption", `${result.avg_consumption_w.toFixed(1)} W`),
    metric("Avg Generation", `${result.avg_generation_w.toFixed(1)} W`),
  ].join("");
  document.getElementById("simAnalysis").textContent = analysisText(result);
  document.getElementById("simResultCard").hidden = false;

  await renderSimulationChart(simRunId, await apiHeaders());
  document.getElementById("simCsvBtn").hidden = false;
  document.getElementById("simSaveBtn").hidden = false;
}

async function downloadCsv() {
  if (!simRunId) return;
  const res = await fetch(`/api/sim/runs/${simRunId}/csv`, { headers: await apiHeaders() });
  if (!res.ok) throw new Error("CSV is not ready.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "sim_result.csv";
  a.click();
  URL.revokeObjectURL(url);
}

async function pollSimulation() {
  if (!simRunId) return;
  try {
    const res = await fetch(`/api/sim/runs/${simRunId}`, { headers: await apiHeaders() });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Simulation status failed.");

    if (data.status === "queued") {
      setText("simStatus", "Queued");
      setText("simText", `Queue position ${data.position || 1}`);
      setBar("simBar", 0);
      setRouteProgress(0);
    } else if (data.status === "running") {
      const pct = data.progress_pct || 0;
      setText("simStatus", "Running");
      setText("simText", `Running simulation ${pct}%`);
      setBar("simBar", pct);
      setRouteProgress(pct / 100);
    } else if (data.status === "finalizing") {
      setText("simStatus", "Finalizing");
      setText("simText", "Preparing results...");
    } else if (data.status === "done") {
      clearInterval(simTimer);
      await finishRun(data);
    } else if (data.status === "error") {
      clearInterval(simTimer);
      setText("simStatus", "Error");
      setText("simText", data.result?.error || "Simulation failed.");
    } else if (data.status === "lost" || data.status === "interrupted") {
      clearInterval(simTimer);
      setText("simStatus", "Interrupted");
      setText("simText", data.detail || "Simulation was interrupted by a server restart.");
    }
  } catch (e) {
    document.getElementById("simErr").textContent = e.message;
  }
}

async function resumeSimulation() {
  try {
    const res = await fetch("/api/sim/my-active-run", { headers: await apiHeaders() });
    const data = await res.json();
    if (!res.ok || !data.run_id) return;
    simRunId = data.run_id;
    document.getElementById("simResultCard").hidden = false;
    await pollSimulation();
    if (simTimer) clearInterval(simTimer);
    simTimer = setInterval(pollSimulation, 1500);
  } catch (e) {
    // The next explicit run can recover from transient auth/network failures.
  }
}

async function startSimulation() {
  const btn = document.getElementById("simRunBtn");
  const errEl = document.getElementById("simErr");
  errEl.textContent = "";
  btn.disabled = true;
  document.getElementById("simResultCard").hidden = true;
  document.getElementById("simCsvBtn").hidden = true;
  document.getElementById("simSaveBtn").hidden = true;
  setBar("simBar", 0);
  setRouteProgress(0);

  try {
    lastCfg = vehicleConfigProvider();
    lastParams = {};
    const res = await fetch("/api/sim/runs", {
      method: "POST",
      headers: await apiHeaders(),
      body: JSON.stringify({ cfg: lastCfg, params: lastParams }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Simulation request failed.");
    simRunId = data.run_id;
    pollSimulation();
    if (simTimer) clearInterval(simTimer);
    simTimer = setInterval(pollSimulation, 1500);
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function saveResult() {
  if (!lastResult) return;
  const client = await getSupabaseClient();
  const user = await getCurrentUser();
  const { error } = await client.from("simulation_runs").insert({
    user_id: user.id,
    params: lastParams,
    vehicle_cfg: lastCfg,
    completion_ratio: lastResult.completion_ratio,
    avg_speed_kmh: lastResult.avg_speed_kmh,
    final_soc: lastResult.final_soc,
    final_dist_m: lastResult.final_dist_m,
  });
  if (error) throw error;
  setText("simText", "Result saved.");
}

export function setVehicleConfigProvider(provider) {
  vehicleConfigProvider = provider;
}

export function initSimulator() {
  initRouteMap().catch((e) => {
    document.getElementById("simErr").textContent = e.message;
  });
  resumeSimulation();
  document.getElementById("simRunBtn").addEventListener("click", startSimulation);
  document.getElementById("simCsvBtn").addEventListener("click", () => {
    downloadCsv().catch((e) => {
      document.getElementById("simErr").textContent = e.message;
    });
  });
  document.getElementById("simSaveBtn").addEventListener("click", () => {
    saveResult().catch((e) => {
      document.getElementById("simErr").textContent = e.message;
    });
  });
}
