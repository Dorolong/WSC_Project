"""
실행 코드

이 파일은 두 가지 방식으로 쓰입니다:
1. CLI: `python scripts/main.py` — 기존처럼 그대로 동작
2. 웹 런처(server/study_runner.py)에서 build_objective()를 import해서
   재사용 — 탐색 공간/시뮬레이션 셋업 코드를 두 군데서 중복 관리하지
   않기 위함. objective()의 파라미터 범위를 바꾸면 CLI든 웹이든 항상
   같은 곳(이 파일)만 고치면 됩니다.
"""

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import optuna

from Functions.Vehicle_Function import read_path, run_simulation
from mpc.mpc_controller import mpc_default_params
from Configs.Vehicle_Params import build_default_cfg


def build_objective():
    """
    경로/환경 데이터를 불러오고 objective(trial) 함수를 만들어 반환합니다.
    반환값: (objective_fn, context)
    context에는 최종 best_params로 한 번 더 시뮬레이션 돌릴 때 필요한
    값들(cfg, route_np, dist_vals 등)이 들어있어서, 호출부에서
    "Best 결과 CSV로 저장" 같은 후처리도 그대로 할 수 있습니다.
    """
    # 차량 제원(physics/solar/cell/pack/power/drive/race) 묶음. run_simulation()이
    # cfg를 인자로 요구하는 구조라(전역 싱글턴 대신 - app.py의 멀티유저 격리
    # 문제 수정, progress/28 참고) 여기서 만들어서 넘겨줌. 웹 런처에서 여러
    # 사용자가 동시에 build_objective()를 각자 호출해도, cfg가 매번 새로
    # 만들어지는 지역 변수라 서로 안 섞입니다.
    cfg = build_default_cfg()
    race = cfg.race

    # 데이터 가져오기
    route = read_path("2027 BWSC TRACK.csv")
    env_data = pd.read_csv("outputs/env_data.csv")
    env_data = env_data.set_index(["total_distance_m", "DY", "HR"])

    # run_simulation()이 실제로 읽는 컬럼만 남기고 나머지는 버립니다.
    # env_data.csv엔 temperature_2m, surface_pressure, lat/lon 등도 같이
    # 들어있는데, Vehicle_Function.py의 env_row[...] 사용처를 다 확인해보니
    # 실제로 쓰는 건 이 4개뿐이었어요. 안 쓰는 컬럼까지 그대로 딕셔너리로
    # 바꾸면(to_dict) 메모리를 꽤 잡아먹어서 - 이 5개(K개 날씨) 사본을 동시에
    # 들고 있어야 하는 objective()에서 특히 부담이 커요(1GB 메모리 서버 대응).
    # 이 리스트를 바꿔야 할 일이 생기면(Vehicle_Function.py에서 새 필드를
    # 쓰게 되면) 여기도 같이 추가해줘야 해요.
    ENV_NEEDED_COLS = ["shortwave_radiation", "shortwave_radiation_std", "wind_speed_10m", "wind_speed_10m_std", "wind_direction_10m"]
    env_data = env_data[ENV_NEEDED_COLS]

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

    # 내리막 세그먼트 경계 배열 추출 (progress/33 "1순위" 1번, 참고 구현은
    # 파일 맨 아래 문자열 블록에 있던 것을 여기로 옮김 - 1회성 계산)
    # 주의: 아직 이 배열들을 쓰는 compute_downhill_cap()은 미구현 상태라
    # (Vehicle_Function.py, 사용자 직접 작성 예정) 지금은 계산만 해두고
    # 사용은 안 함 - objective()에 영향 없음.
    change_idx = np.where(np.diff(is_downhill.astype(int)) != 0)[0] + 1
    bounds = np.concatenate(([0], change_idx, [len(is_downhill)]))

    downhill_start_dists, downhill_end_dists, downhill_theta = [], [], []
    for k in range(len(bounds) - 1):
        s, e = bounds[k], bounds[k + 1] - 1
        if is_downhill[s]:
            downhill_start_dists.append(route_np["dist"][s])
            downhill_end_dists.append(route_np["dist"][e])
            downhill_theta.append(theta_arr[s:e + 1].mean())  # 세그먼트 대표 경사각

    downhill_start_dists = np.array(downhill_start_dists)
    downhill_end_dists = np.array(downhill_end_dists)
    downhill_theta = np.array(downhill_theta)

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
            df, _reason = run_simulation(params, route_np, env_dict_k, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limit_dists, speed_limit_vals, cfg, progress_cb=None)
            race_ratio = df["dist"].max() / race.total_distance
            # 완주 시 속도로 목적 값 반환, 미완주 시 ratio-2 [-1, -2] 클리핑
            if df["dist"].max() >= race.total_distance:
                scores.append(df["v"].mean() * 3.6)
            else:
                scores.append(race_ratio - 2)

        return sum(scores) / len(scores)

    context = {
        "cfg": cfg,
        "race": race,
        "route_np": route_np,
        "env_dict": env_dict,
        "dist_vals": dist_vals,
        "nearest_map": nearest_map,
        "rad_max": rad_max,
        "light_dists": light_dists,
        "light_types": light_types,
        "speed_limit_dists": speed_limit_dists,
        "speed_limit_vals": speed_limit_vals,
    }
    return objective, context


def run_best_params_simulation(best_params, context, output_csv=None):
    """탐색이 끝난 뒤 best_params로 한 번 더 시뮬레이션을 돌려 결과 df를 만듭니다."""
    params = {**mpc_default_params, **best_params}
    df, reason = run_simulation(
        params, context["route_np"], context["env_dict"], context["dist_vals"],
        context["nearest_map"], context["rad_max"], context["light_dists"],
        context["light_types"], context["speed_limit_dists"], context["speed_limit_vals"],
        context["cfg"], progress_cb=None,
    )
    if output_csv:
        df.to_csv(output_csv, index=False)
    return df, reason


def run_cli():
    """기존 커맨드라인 실행 진입점 (`python scripts/main.py`)."""
    objective, context = build_objective()

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

    df, reason = run_best_params_simulation(study.best_params, context, output_csv="outputs/Optuna_result.csv")
    print("종료 사유:", reason)


if __name__ == "__main__":
    run_cli()
