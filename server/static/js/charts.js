export async function renderSimulationChart(runId, headers) {
  const chartEl = document.getElementById("simChart");
  chartEl.textContent = "Loading chart...";
  const res = await fetch(`/api/sim/runs/${runId}/figure`, { headers });
  if (!res.ok) throw new Error("Figure is not ready.");
  const fig = await res.json();
  if (!window.Plotly) throw new Error("Plotly failed to load.");
  window.Plotly.newPlot(chartEl, fig.data || [], fig.layout || {}, { responsive: true });
}

export function renderTelemetryChart(chartEl, frames, signal) {
  if (!window.Plotly) throw new Error("Plotly failed to load.");
  const x = frames.map((row) => row.timestamp_text || row.frame_index);
  const traces = [
    {
      x,
      y: frames.map((row) => row.seg_one),
      type: "scatter",
      mode: "lines",
      name: signal?.seg_one_field || "segment one",
    },
  ];
  if (signal?.seg_two_field) {
    traces.push({
      x,
      y: frames.map((row) => row.seg_two),
      type: "scatter",
      mode: "lines",
      name: signal.seg_two_field,
    });
  }
  window.Plotly.newPlot(
    chartEl,
    traces,
    {
      margin: { t: 24, r: 16, b: 48, l: 56 },
      xaxis: { title: "Frame" },
      yaxis: { title: signal?.seg_one_unit || signal?.seg_two_unit || "Value" },
      legend: { orientation: "h" },
    },
    { responsive: true }
  );
}
