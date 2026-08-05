"""
Run one WSC simulation as a child process for the FastAPI launcher.

Usage:
    python server/sim_runner.py <run_id> <payload_json_path>
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from Functions.Vehicle_Function import read_path, run_simulation
from mpc.mpc_controller import mpc_default_params
from shared.cfg_serde import cfg_from_jsonable


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DIR = os.path.join(PROJECT_ROOT, "outputs", "sim_runs")
ENV_NEEDED_COLS = [
    "shortwave_radiation",
    "shortwave_radiation_std",
    "wind_speed_10m",
    "wind_speed_10m_std",
    "wind_direction_10m",
]


def _write_json(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_context():
    route = read_path("2027 BWSC TRACK.csv")
    env_data = pd.read_csv("outputs/env_data.csv")
    env_data = env_data.set_index(["total_distance_m", "DY", "HR"])
    env_data = env_data[ENV_NEEDED_COLS]

    dist_vals = env_data.index.get_level_values("total_distance_m").unique().sort_values().to_numpy()
    nearest_map = {
        d: dist_vals[np.abs(dist_vals - d).argmin()]
        for d in route["total_distance_m"]
    }
    env_dict = env_data.to_dict("index")
    rad_max = env_data["shortwave_radiation"].max()

    lights_df = pd.read_csv("Configs/traffic_lights_2025.csv")
    light_dists = lights_df["distance_km"].to_numpy()
    light_types = lights_df["type"].to_numpy()

    speed_limits_df = pd.read_csv("Configs/speed_limits_2025.csv")
    speed_limit_dists = speed_limits_df["distance_km"].to_numpy()
    speed_limit_vals = speed_limits_df["speed_limit_kmh"].to_numpy()

    route_np = {
        "dist": route["total_distance_m"].to_numpy(),
        "lat": route["lat"].to_numpy(),
        "lon": route["lon"].to_numpy(),
        "slope": route["slope"].to_numpy(),
        "theta": route["theta"].to_numpy(),
        "is_downhill": route["is_downhill"].to_numpy(),
        "is_uphill": route["is_uphill"].to_numpy(),
    }
    return route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limit_dists, speed_limit_vals


def make_figure_json(df, cfg):
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("SOC", "Power [W]", "Speed [km/h]"),
        vertical_spacing=0.08,
    )

    fig.add_trace(go.Scatter(x=df["dist"] / 1000, y=df["soc"], name="SOC", line=dict(color="steelblue")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["dist"] / 1000, y=df["P_batt"], name="Consumption", line=dict(color="tomato")), row=2, col=1)
    fig.add_trace(go.Scatter(x=df["dist"] / 1000, y=df["P_gen"], name="Generation", line=dict(color="orange")), row=2, col=1)
    fig.add_trace(
        go.Scatter(x=df["dist"] / 1000, y=df["v"] * 3.6, name="Instant Speed", line=dict(color="lightblue"), opacity=0.4),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=df["dist"] / 1000, y=df["v"].expanding().mean() * 3.6, name="Cumulative Avg", line=dict(color="orange")),
        row=3,
        col=1,
    )

    for _, grp in df.groupby("DY"):
        x = grp["dist"].max() / 1000
        for row in [1, 2, 3]:
            fig.add_vline(x=x, line_dash="dash", line_color="gray", line_width=1, row=row, col=1)

    for cs_dist in cfg.race.Control_Stop_2025.keys():
        idx = (df["dist"] - cs_dist).abs().idxmin()
        fig.add_annotation(
            x=cs_dist / 1000,
            y=df.loc[idx, "soc"],
            ax=0,
            ay=-30,
            arrowhead=2,
            arrowcolor="red",
            arrowsize=1,
            showarrow=True,
            text="",
            row=1,
            col=1,
        )

    fig.update_xaxes(title_text="Distance [km]", row=3, col=1)
    fig.update_layout(height=800, showlegend=True)
    return json.loads(fig.to_json())


def final_route_points(df, route_np):
    final_idx = int(np.searchsorted(route_np["dist"], df["dist"].max()))
    final_idx = min(final_idx, len(route_np["dist"]) - 1)
    return {
        "lon": route_np["lon"][:final_idx + 1:5].tolist() + [float(route_np["lon"][final_idx])],
        "lat": route_np["lat"][:final_idx + 1:5].tolist() + [float(route_np["lat"][final_idx])],
    }


def main():
    if len(sys.argv) != 3:
        print("Usage: python server/sim_runner.py <run_id> <payload_json_path>", file=sys.stderr)
        sys.exit(2)

    run_id = sys.argv[1]
    payload_path = sys.argv[2]
    os.makedirs(RUN_DIR, exist_ok=True)
    progress_path = os.path.join(RUN_DIR, f"{run_id}_progress.json")
    result_path = os.path.join(RUN_DIR, f"{run_id}.json")
    csv_path = os.path.join(RUN_DIR, f"{run_id}.csv")
    figure_path = os.path.join(RUN_DIR, f"{run_id}_figure.json")

    started_at = datetime.now(timezone.utc).isoformat()
    _write_json(progress_path, {"pct": 0.0, "started_at": started_at})

    try:
        with open(payload_path, encoding="utf-8") as f:
            payload = json.load(f)

        cfg = cfg_from_jsonable(payload.get("cfg"))
        params = {**mpc_default_params, **payload.get("params", {})}
        context = load_context()

        last_write = 0.0

        def progress_cb(pct):
            nonlocal last_write
            now = time.time()
            if now - last_write >= 0.5 or pct >= 1:
                _write_json(progress_path, {"pct": float(pct), "started_at": started_at})
                last_write = now

        df, reason = run_simulation(*((params,) + context + (cfg,)), progress_cb=progress_cb)
        df.to_csv(csv_path, index=False)
        _write_json(figure_path, make_figure_json(df, cfg))

        summary = {
            "status": "done",
            "user_id": payload.get("user_id"),
            "reason": reason,
            "completion_ratio": float(df["dist"].max() / cfg.race.total_distance),
            "avg_speed_kmh": float(df["v"].mean() * 3.6),
            "max_speed_kmh": float(df["v"].max() * 3.6),
            "final_soc": float(df["soc"].min()),
            "final_dist_m": float(df["dist"].max()),
            "avg_consumption_w": float(df[df["P_batt"] > 0]["P_batt"].mean()),
            "avg_generation_w": float(df["P_gen"].mean()),
            "max_grade_pct": float(df["slope"].abs().max() * 100),
            "route": final_route_points(df, context[0]),
        }
        _write_json(result_path, summary)
        _write_json(progress_path, {"pct": 1.0, "started_at": started_at})
    except Exception as exc:
        _write_json(result_path, {"status": "error", "error": str(exc)})
        raise
    finally:
        try:
            os.remove(payload_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
