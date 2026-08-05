export async function renderSimulationChart(runId, headers) {
  const chartEl = document.getElementById("simChart");
  chartEl.textContent = "Loading chart...";
  const res = await fetch(`/api/sim/runs/${runId}/figure`, { headers });
  if (!res.ok) throw new Error("Figure is not ready.");
  const fig = await res.json();
  if (!window.Plotly) throw new Error("Plotly failed to load.");
  window.Plotly.newPlot(chartEl, fig.data || [], fig.layout || {}, { responsive: true });
}
