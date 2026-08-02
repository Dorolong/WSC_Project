"""
실행 코드
"""

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import optuna

from Functions.Vehicle_Function import read_path, run_simulation
from mpc.mpc_controller import mpc_default_params
from Configs.Vehicle_Params import race

# 데이터 가져오기
route = read_path("2027 BWSC TRACK.csv")
env_data = pd.read_csv("outputs/env_data.csv")
env_data = env_data.set_index(["total_distance_m", "DY", "HR"])

# 거리 10km 격자 전처리
# .to_numpy(): pandas Index 그대로 두면 compute_lookahead()의 매 스텝
# dist_vals - future_dist_m 연산이 pandas 내부 타입체크/dtype추론을
# 거쳐 numpy 배열 연산보다 훨씬 느려짐 (프로파일링으로 확인, 전체
# 실행시간의 70%+ 차지)
dist_vals = env_data.index.get_level_values("total_distance_m").unique().sort_values().to_numpy()
nearest_map = {
    d: dist_vals[np.abs(dist_vals - d).argmin()]
    for d in route["total_distance_m"]
}
env_dict = env_data.to_dict("index")
rad_max = env_data["shortwave_radiation"].max()

# 트라이얼마다 완전히 다른 날씨를 뽑으면 "누가 더 쉬운 날씨를 만났나"로
# 결과가 왜곡되니(common random numbers), 고정된 K개 날씨를 미리 만들어서
# 모든 트라이얼이 동일한 조건으로 평가받게 함.
# CS leg 단위로 z(표준정규분포 난수)를 공유해서 흔듦: 포인트마다 완전히
# 독립적으로 흔들면(예전 방식) 바로 옆 지점끼리도 일사량이 뜬금없이
# 튀는 비현실적인 노이즈가 됨. 실제 날씨는 공간/시간으로 어느 정도
# 뭉쳐서(전선 단위로) 움직이므로, 같은 leg 안에서는 "이번엔 대체로
# 맑은/흐린 leg"처럼 일관되게 흔들리고 leg가 바뀌면 다시 새로 흔들리게 함.
cs_boundaries = sorted(race.Control_Stop_2025.keys()) + [race.total_distance]
n_segments = len(cs_boundaries)
dist_arr = env_data.index.get_level_values("total_distance_m").to_numpy()
seg_idx = np.clip(np.searchsorted(cs_boundaries, dist_arr, side="right"), 0, n_segments - 1)

weather_seeds = [1, 2, 3, 4, 5]
env_dicts_fixed = []
for seed in weather_seeds:
    rng = np.random.default_rng(seed=seed)
    env_data_s = env_data.copy()

    z_per_segment = rng.standard_normal(n_segments)
    z_shared = z_per_segment[seg_idx]

    env_data_s["shortwave_radiation"] = (
        env_data["shortwave_radiation"] + z_shared * env_data["shortwave_radiation_std"]
    ).clip(lower=0)
    env_data_s["wind_speed_10m"] = (
        env_data["wind_speed_10m"] + z_shared * env_data["wind_speed_10m_std"]
    ).clip(lower=0)
    env_dicts_fixed.append(env_data_s.to_dict("index"))

route_np = {
    "dist":         route["total_distance_m"].to_numpy(),
    "lat":          route["lat"].to_numpy(),
    "lon":          route["lon"].to_numpy(),
    "slope":        route["slope"].to_numpy(),
    "theta":        route["theta"].to_numpy(),
    "is_downhill":  route["is_downhill"].to_numpy(),
    "is_uphill":    route["is_uphill"].to_numpy(),
}

is_downhill = route_np["is_downhill"]
is_uphill   = route_np["is_uphill"]
theta_arr   = route_np["theta"]

change_idx = np.where()

# 신호등 위치 정보
lights_df = pd.read_csv("Configs/traffic_lights_2025.csv")
light_dists = lights_df["distance_km"].to_numpy()
light_types = lights_df["type"].to_numpy()

# 법정 최고속도 정보
speed_limits_df = pd.read_csv("Configs/speed_limits_2025.csv")
speed_limit_dists = speed_limits_df["distance_km"].to_numpy()
speed_limit_vals  = speed_limits_df["speed_limit_kmh"].to_numpy()

def objective(trial):

    params = {
        **mpc_default_params,    # 기본 고정값
        "v_min" : trial.suggest_int("v_min", 20, 60),
        "v_soc_high": trial.suggest_int("v_soc_high", 60, 100),
        "soc_ramp_high": trial.suggest_float("soc_ramp_high", 0.5, 1.0),
        "soc_ramp_low": trial.suggest_float("soc_ramp_low", 0.0, 0.5),
        "slope_k": trial.suggest_int("slope_k", 0, 150),
        "radi_para": trial.suggest_int("radi_para", 0, 40),
        "radi_risk": trial.suggest_float("radi_risk", 0.0, 1.0),
        "energy_v": trial.suggest_float("energy_v", 0, 20),
        "winddir_para": trial.suggest_int("winddir_para", 0, 20),
        "margin_total": trial.suggest_float("margin_total", 0.1, 0.6),
        "margin_next_cs": trial.suggest_float("margin_next_cs", 0.1, 0.6),
        "soc_cutoff": trial.suggest_float("soc_cutoff", 0.00, 0.20),
    }

    # 고정된 K개 날씨 전부에 대해 평가 후 평균 (common random numbers)
    scores = []
    for env_dict_k in env_dicts_fixed:
        df, _reason = run_simulation(params, route_np, env_dict_k, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limit_dists, speed_limit_vals, progress_cb=None)
        race_ratio = df["dist"].max() / race.total_distance
        # 완주 시 속도로 목적 값 반환, 미완주 시 ratio-2 [-1, -2] 클리핑
        if df["dist"].max() >= race.total_distance:
            scores.append(df["v"].mean() * 3.6)
        else:
            scores.append(race_ratio - 2)

    return sum(scores) / len(scores)

optuna.logging.set_verbosity(optuna.logging.INFO)
study = optuna.create_study(
    study_name="WSC_MPC_Opt_test",
    storage="sqlite:///outputs/optuna_study_test.db",
    load_if_exists=True,
    direction="maximize",
    sampler=optuna.samplers.TPESampler(multivariate=True, group=True))

# objective가 고정 K개 날씨 평균이라도 여전히 CMA-ES보다 TPE가 안전해서
# (위 create_study에서 이미 설정됨) 그대로 사용.
# 파라미터 이름 전면 개편(LV 번호 -> 역할 기반) + LV4/LV7 병합으로 예전 study와
# 파라미터 키가 호환되지 않아 enqueue_trial 없이 새로 탐색
study.optimize(objective, n_trials=2)  # 트라이얼당 계산량이 K=5배가 되어 트라이얼 수는 축소

print("Best Value:", study.best_value)
print("Best params:", study.best_params)

best_params = {**mpc_default_params, **study.best_params}
df, reason = run_simulation(best_params, route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limit_dists, speed_limit_vals, progress_cb=None)
print("종료 사유:", reason)
df.to_csv("outputs/Optuna_result.csv", index=False)



"""
is_down = route_np["is_downhill"]
dist_m  = route_np["dist"]
theta_arr = route_np["theta"]

change_idx = np.where(np.diff(is_down.astype(int)) != 0)[0] + 1
bounds = np.concatenate(([0], change_idx, [len(is_down)]))

downhill_start_dists, downhill_end_dists, downhill_theta = [], [], []
for k in range(len(bounds) - 1):
    s, e = bounds[k], bounds[k+1] - 1
    if is_down[s]:
        downhill_start_dists.append(dist_m[s])
        downhill_end_dists.append(dist_m[e])
        downhill_theta.append(theta_arr[s:e+1].mean())   # 세그먼트 대표 경사각

downhill_start_dists = np.array(downhill_start_dists)
downhill_end_dists   = np.array(downhill_end_dists)
downhill_theta       = np.array(downhill_theta)

def compute_downhill_cap(step, const):
    curr_dist = step["curr_dist"]     # [m]
    starts = const["downhill_start_dists"]
    ends   = const["downhill_end_dists"]
    thetas = const["downhill_theta"]

    idx = np.searchsorted(starts, curr_dist, side="right")
    if idx >= len(starts) or curr_dist >= starts[idx]:
        return np.inf   # 앞으로 진입할 내리막 없음 (또는 이미 그 안에 있음)

    seg_start, seg_end, theta = starts[idx], ends[idx], thetas[idx]
    L = seg_end - seg_start

    # a_coast: 현재 속도(prev_v) 기준, cal_drive_res()의 저항력 계산과 동일한 식
    v = step["prev_v"]
    F_aero  = 0.5 * physics.Air_Density * physics.Cd * physics.A_f * v * abs(v)
    F_roll  = physics.Crr * physics.mass * physics.a_g * m.cos(theta)
    F_slope = physics.mass * physics.a_g * m.sin(theta)
    a_coast = (F_aero + F_roll + F_slope) / physics.mass

    # 세그먼트 끝 지점의 상한 속도 (법정속도/최고속도 중 작은 값)
    v_exit_cap_kmh = min(step["speed_limit"], drive.v_max)   # 근사치로 현재 speed_limit 사용
    v_exit_cap = v_exit_cap_kmh / 3.6

    # 역산: 세그먼트 진입 시 이 이하 속도여야 끝에서 상한 안 넘음
    v_entry_max = m.sqrt(max(v_exit_cap**2 - 2 * a_coast * L, 0))

    return v_entry_max * 3.6   # km/h (mpc_speed 클립 단위와 맞춤)

run_simulation() 루프 안, compute_speed_limit() 호출 옆에:

step["downhill_v_cap"] = compute_downhill_cap(step, const)
mpc_speed()의 speed_limit 클립 옆에:

v = min(v, step["downhill_v_cap"])
"""