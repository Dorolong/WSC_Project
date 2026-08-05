const VB_W = 1000;
const VB_H = 700;

let bounds = null;
let routeLon = [];
let routeLat = [];

function project(lon, lat) {
  const x = ((lon - bounds.minx) / (bounds.maxx - bounds.minx)) * VB_W;
  const y = ((bounds.maxy - lat) / (bounds.maxy - bounds.miny)) * VB_H;
  return [x, y];
}

function pointsToPath(pts) {
  if (pts.length === 0) return "";
  return `M ${pts.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L ")}`;
}

function projectedPath(lonValues, latValues) {
  return pointsToPath(lonValues.map((lon, i) => project(lon, latValues[i])));
}

export async function initRouteMap() {
  const res = await fetch("/api/sim/route");
  const data = await res.json();
  bounds = data.bounds;
  routeLon = data.lon || [];
  routeLat = data.lat || [];

  if (data.bg_image) {
    document.getElementById("routeBg").src = data.bg_image;
  }
  document.getElementById("routeBgPath").setAttribute("d", projectedPath(routeLon, routeLat));
  setRouteProgress(0);
}

export function setRouteProgress(frac, finalRoute) {
  if (!bounds) return;
  const pct = Math.max(0, Math.min(1, frac || 0));
  const lonValues = finalRoute?.lon || routeLon;
  const latValues = finalRoute?.lat || routeLat;
  const count = Math.max(1, Math.floor(pct * lonValues.length));
  document.getElementById("routeDrivenPath").setAttribute("d", projectedPath(lonValues.slice(0, count), latValues.slice(0, count)));
  document.getElementById("routePct").textContent = `${Math.round(pct * 100)}%`;
}
