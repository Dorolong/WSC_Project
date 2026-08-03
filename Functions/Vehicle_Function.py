"""
공식 모음 및 시뮬레이션

Functions:
    cal_drive_res()                 - 주행 저항 및 배터리 전력 계산 [W]
    gen_solar()                     - 태양광 발전량 계산 [W]
    update_soc()                    - SOC 업데이트
    cs_arrive()                     - Control Stop 도착 확인 및 처리
    cs_stop_time_cal()              - Control Stop 정차 시간 [s]
    cs_stop_simulation()            - Control Stop 충전 시뮬레이션
    read_path()                     - 코스 데이터 추출 및 정리
    cal_route_vector()              - 차량 진행방향 계산
    drivable_hours_until()          - 사용 가능 시간 계산
    compute_lookahead()             - 미래 상황 예측
    compute_required_pace()         - 필요 페이스 계산      
    compute_motor_derating()        - DC 전압에 따른 디레이팅 예측
    calender_handler()              - 날짜 변경 및 시간 경과 처리
    control_stop_handler()          - Control Stop 도착 시 행동
    compute_vehicle_energy()        - 차량 소비 에너지 계산
    run_simulation()                - 전체 주행 시뮬레이션
"""

# 표준 라이브러리
# cos(), sin(), radians()
import math as m

# 서드 파티
# interp()
import numpy as np
# read_csv(), DataFrame()
import pandas as pd

# 로컬
# mpc_speed(), mpc_default_params
from mpc.mpc_controller import *
# physics, solar, cell, pack, power, race, simpara
from Configs.Vehicle_Params import *

def cal_drive_res(step, dt, wind_spd, wind_dir, car_dir, const):     # [W]

    # 변수 선언
    v           = step["v"]
    prev_v      = step["prev_v"]
    theta       = step["theta"]
    a           = (v - prev_v) / dt if dt > 0 else 0.0

    # 설정값 선언 (호출자의 cfg에서 옴 - 세션별로 독립적)
    physics = const["physics"]
    drive   = const["drive"]
    power   = const["power"]

    # 풍향 고려
    angle_diff = wind_dir - car_dir
    headwind = wind_spd * m.cos(m.radians(angle_diff))
    v_eff = v + headwind

    # 주행 저항 계산
    F_aero = 0.5 * physics.Air_Density * physics.Cd * physics.A_f * v_eff * abs(v_eff)    # [N]
    F_roll = physics.Crr * physics.mass * physics.a_g * m.cos(theta)            # [N]
    F_slope = physics.mass * physics.a_g * m.sin(theta)                         # [N]
    F_acc = physics.mass * a                                                    # [N]

    # 총 소모 전력 계산
    F_tot = F_aero + F_roll + F_slope + F_acc           # [N]
    P_tot = F_tot * v                                   # [W]

    drive_eff_tot = physics.Drive_eff * drive.motor_eff * drive.inverter_eff

    # Drive or Regen
    if P_tot >= 0:
        P_drive = P_tot / drive_eff_tot              # 구동, 양수
        P_batt = P_drive + power.P_LV_race

    else:
        P_regen = P_tot * power.Regen_eff            # 회생, 음수
        P_batt = P_regen + power.P_LV_race
    
    return P_batt, a

def gen_solar(shortwave_radiation, const):

    # 설정값 선언
    solar = const["solar"]

    # Solar Power
    P_gen = shortwave_radiation * solar.A_Solar * solar.Solar_eff   #[W]

    return P_gen

def update_soc(soc, step, dt, const):

    # 변수 선언
    P_batt      = step["P_batt"]
    P_gen       = step["P_gen"]

    # 설정값 선언
    cell = const["cell"]
    pack = const["pack"]

    # 셀/팩 전압 추정
    V_cell = np.interp(soc, cell.ocv_soc, cell.ocv_V)
    V_pack = V_cell * pack.HV_S

    # 충전 상한선 설정, 1C 충전 가정
    I_max_chg = cell.Capa_batt * pack.HV_P / 1000               # [A], 팩 최대 충전 전류
    P_max_chg = V_pack * I_max_chg + I_max_chg**2 * pack.HV_Req # [W], 팩 실질 충전 전력

    # P_net Clipping
    P_net = np.clip(P_gen - P_batt,
                    -V_pack**2 / (4 * pack.HV_Req),
                    P_max_chg)

    ans = V_pack**2 + 4 * pack.HV_Req * P_net
    I = (-V_pack + np.sqrt(ans)) / (2 * pack.HV_Req)
    V_terminal = V_pack + I * pack.HV_Req

    P_loss = I**2 * pack.HV_Req

    # 실 소비전력 계산
    P_real = P_net - P_loss

    # 구간 최소 포인트 간 에너지 소비량 [Wh]
    # dt는 구간 거리 / 구간 요구 속도
    dE = P_real * dt / 3600

    # SOC 업데이트(에너지 절대변화량 계산)
    soc_new = soc + dE / pack.HV_Energy

    return max(0.0, min(1.0, soc_new)), V_terminal

def cs_arrive(curr_dist, control_stops, visited_cs):

    for cs_dist in control_stops:
        if cs_dist not in visited_cs and abs(curr_dist - cs_dist) < 20:
            return cs_dist
    return None

def cs_stop_time_cal(soc, const):
    race = const["race"]
    Comp_const = race.cs_stop_max - race.cs_stop_min
    cs_stop = race.cs_stop_max - soc * Comp_const
    return cs_stop

def cs_stop_simulation(soc, Accum_s, nearest_diff, env_data, const):
    power = const["power"]
    stop_time = 0
    cs_stop = cs_stop_time_cal(soc, const)
    dt_cs = 300     # 5분 단위
    while stop_time < cs_stop:
        dt_stop = min(dt_cs, cs_stop - stop_time)
        total_s = 8 * 3600 + Accum_s
        DY = 23 + int(total_s // 86400)
        HR = int((total_s % 86400) // 3600)

        env_cs = env_data.get((nearest_diff, DY, HR))
        if env_cs is not None:
            P_gen_cs = gen_solar(env_cs["shortwave_radiation"], const)
            P_gen_cs_real = P_gen_cs * power.cs_chg_eff
            soc, _ = update_soc(soc, {"P_batt": power.P_LV_chg, "P_gen": P_gen_cs_real}, dt_stop, const)
        else:
            break

        Accum_s += dt_stop
        stop_time += dt_stop
    return Accum_s, soc

def read_path(Datasheet):
    df = pd.read_csv(Datasheet)

    # 행 새로 정렬, 인덱스 새로 부여
    df = df.sort_values("total_distance_m").reset_index(drop=True)

    # 고도 변화량 계산, 0번 인덱스는 0으로 처리
    delta_ele = df["ele"].diff().fillna(0)
    
    # 거리 변화량 계산, 0번 인덱스는 1으로 처리해 다음 나눗셈 계산
    delta_dist = df["total_distance_m"].diff().fillna(1)
    delta_dist = delta_dist.replace(0, np.nan)
    
    # 경사도 데이터 생성
    df["slope"] = delta_ele / delta_dist
    df["slope"] = df["slope"].fillna(0)
    df["slope"] = df["slope"].clip(-0.1, 0.1)   # 10% 내외 클리핑
    
    # 내리막/오르막 판단
    window_pts = round(500 / delta_dist.median())   # 한 번에 몇 개를 smoothing 할건지?
    slope_smooth = df["slope"].rolling(window=window_pts, center=True, min_periods=1).mean()

    # 소각 근사 -> Crr * cos(theta) + sin(theta) = Crr + slope
    decision_coeff = slope_smooth + physics.Crr
    
    # 경사 임계값
    threshold = 0.003
    df["is_downhill"] = decision_coeff < -threshold
    df["is_uphill"] = decision_coeff > threshold

    # 경사도 열 생성
    df["theta"] = np.arctan(df["slope"])

    return df[["total_distance_m", "lat", "lon", "ele", "slope", "theta", "is_downhill", "is_uphill"]]

def cal_route_vector(step):

    # 변수 선언
    lat1, lon1 = step["prev_lat"], step["prev_lon"]
    lat2, lon2 = step["curr_lat"], step["curr_lon"]

    lat1, lat2 = m.radians(lat1), m.radians(lat2)
    dlon = m.radians(lon2 - lon1)
    x = m.sin(dlon) * m.cos(lat2)
    y = m.cos(lat1) * m.sin(lat2) - m.sin(lat1) * m.cos(lat2) * m.cos(dlon)

    return (m.degrees(m.atan2(x, y)) + 360) % 360

def drivable_hours_until(DY, HR, target_h):
    target_DY = 23 + int(target_h // 24)
    target_HR = target_h % 24

    if target_DY < DY:
        return 0   # 이미 마감 지남
    if target_DY == DY:
        return max(0, min(target_HR, 17) - max(HR, 8))
    
    today_left      = max(0, 17 - max(HR, 8))
    full_days       = max(0, target_DY - DY - 1)
    last_day_hours  = max(0, min(target_HR, 17) - 8)

    return today_left + full_days * 9 + last_day_hours

def compute_lookahead(step, const):
    
    # 변수 선언
    curr_dist           = step["curr_dist"]         # 현재 위치
    remaining_dist      = step["remaining_dist"]    # 남은 거리(다음 CS까지)
    gen_ratio           = step["gen_ratio"]         # 최대 발전량 대비 발전 비율
    prev_v              = step["prev_v"]            # 직전 스텝 속도
    Accum_s             = step["Accum_s"]           # 경과 누적 시간
    i                   = step["i"]                 # 현재 route 인덱스

    # 상수 선언
    env_data            = const["env_data"]         # 날씨 데이터
    dist_vals           = const["dist_vals"]        # 10km로 나눈 루트 정보
    rad_max             = const["rad_max"]          # 최대 일사량
    route_dist          = const["route_dist"]       # 20m로 나눈 루트 정보
    route_slope         = const["route_slope"]      # 루트 경사율
    n                   = const["n"]                # 총 인덱스 개수
    race                = const["race"]              # 레이스 설정

    # N 포인트 앞의 발전량 가중 평균
    target_spacing_km = 70                          # [km/h]
    N = max(1, round(remaining_dist / target_spacing_km))

    # 각 포인트 당 발전량, 가중치 리스트 생성
    gen_ratio_samples = [gen_ratio]
    weight_samples = [1.0]
    
    # N 포인트만큼 탐색
    for k in range(1, N + 1):
        offset_km = remaining_dist * (k / N)
        future_dist_m = min(curr_dist + offset_km * 1000, race.total_distance)
        future_h = 8 + Accum_s / 3600 + (offset_km / (prev_v * 3.6) if prev_v > 0 else 0)
        future_DY = 23 + int(future_h // 24)
        future_HR = int(future_h % 24)

        future_nearest = dist_vals[np.abs(dist_vals - future_dist_m).argmin()]
        future_row = env_data.get((future_nearest, future_DY, future_HR))
        gen_ratio_k = future_row["shortwave_radiation"]/rad_max if future_row is not None else gen_ratio

        gen_ratio_samples.append(gen_ratio_k)
        weight_samples.append(1 / (k + 1))
    
    # 발전량 가중평균 계산
    avg_gen_ratio = sum(g * w for g, w in zip(gen_ratio_samples, weight_samples)) / sum(weight_samples)
    
    # N 포인트 앞의 경사도 유추
    slope_look_ahead_km = 2

    # 결승선 근처에서는 결승선으로 클램핑
    future_slope_dist_m = min(curr_dist + slope_look_ahead_km * 1000, race.total_distance)
    future_slope_idx = min(np.searchsorted(route_dist, future_slope_dist_m), n - 1)

    # 만약 결승선이 아니라면 모든 구간에서 가중평균, 결승선은 그대로
    if future_slope_idx > i:
        slope_ahead = route_slope[i:future_slope_idx + 1].mean()
    else:
        slope_ahead = route_slope[future_slope_idx]

    return avg_gen_ratio, slope_ahead

def compute_required_pace(step, const):

    # 변수 선언
    curr_dist       = step["curr_dist"]
    DY              = step["DY"]
    HR              = step["HR"]
    next_cs         = step["next_cs"]
    remaining_dist  = step["remaining_dist"]

    # 설정값 선언
    race  = const["race"]
    drive = const["drive"]

    # 남은 주행 최적 페이스 도출(전체/다음CS)
    remaining_race_dist = (race.total_distance - curr_dist) / 1000
    hours_to_finish = drivable_hours_until(DY, HR, target_h = 113)
    required_race_pace = remaining_race_dist / hours_to_finish if hours_to_finish > 0.01 else drive.v_max

    if curr_dist < 2720500:
        hours_to_next_cs = drivable_hours_until(DY, HR, race.CS_close_hour[next_cs])
        required_next_cs_pace = remaining_dist / hours_to_next_cs if hours_to_next_cs > 0.01 else drive.v_max
    else:
        required_next_cs_pace = required_race_pace

    return required_race_pace, required_next_cs_pace

def compute_motor_derating(step, const):

    # 변수 선언
    prev_v          = step["prev_v"]
    prev_V_terminal = step["prev_V_terminal"]

    # 설정값 선언
    drive = const["drive"]

    # 전압 디레이팅 반영
    omega_wheel = prev_v / drive.wheel_radius
    backEMP_DC = drive.speed_constant * omega_wheel * m.sqrt(6) # SVPWM

    if prev_V_terminal < backEMP_DC:
        omega_max = prev_V_terminal / (drive.speed_constant * m.sqrt(6))
        v_max_derated = omega_max * drive.wheel_radius * 3.6        
    else:
        v_max_derated = drive.motor_nom_speed * drive.wheel_radius * 3.6

    return v_max_derated

def calender_handler(Accum_s):

    # 총 소요 시간 추정
    total_s = 8 * 3600 + Accum_s

    # 날짜, 시간 추정
    DY = 23 + int(total_s // 86400)
    HR = int((total_s % 86400) // 3600)

    # 야간 데이터 처리
    if HR < 8 or 17 <= HR:
        if HR < 8:
            next_day = (DY - 23)
        else:
            next_day = DY - 23 + 1
        return {"Action": "Reset_Go", "Accum_s": next_day * 86400}

    # 27일 이후 데이터 처리
    if(27 < DY):
        return {"Action": "Stop", "reason": "27일 제한기간 초과"}
    
    return {"Action": "Go", "Accum_s": Accum_s, "DY": DY, "HR": HR, "total_s": total_s}

def control_stop_handler(step, total_s, drive_time_s, Accum_s, soc, visited_cs, last_cs_dist, last_cs_time, nearest_diff, env_data, const):

    # 설정값 선언
    race = const["race"]

    # Control Stop 정차 확인
    cs_hit = cs_arrive(step["curr_dist"], race.Control_Stop_2025, visited_cs)
    
    if not cs_hit:
        return {"Action": "Go"}

    # Control Stop 정차 시뮬레이션
    visited_cs.add(cs_hit)

    # 컨트롤 스탑 마감 체크: 마감시각 넘겨서 도착하면 실격
    if total_s > race.CS_close_hour[cs_hit] * 3600:
        return {"Action": "Fail", "reason": f"{race.Control_Stop_2025[cs_hit]} 마감시각 초과"}

    # 구간(직전 CS ~ 지금 CS) 평균속도 실격 체크 (정차 시간 제외, 순수 주행 기준)
    leg_dist_goto = (step["curr_dist"] - last_cs_dist) / 1000
    leg_time_hr = (drive_time_s - last_cs_time) / 3600
    if leg_time_hr > 0 and (leg_dist_goto / leg_time_hr) < race.min_leg_avg_speed:
        return {"Action": "Fail", "reason": f"{race.Control_Stop_2025[cs_hit]} 구간 평균속도({race.min_leg_avg_speed:.0f}km/h) 미달"}

    Accum_s, soc = cs_stop_simulation(soc, Accum_s, nearest_diff, env_data, const)
    total_s = 8 * 3600 + Accum_s
    DY = 23 + int(total_s // 86400)
    HR = int((total_s % 86400) / 3600)

    last_cs_dist = step["curr_dist"]
    last_cs_time = drive_time_s

    return {
        "Action": "Stop", 
        "visited_cs": visited_cs,
        "Accum_s": Accum_s, "soc": soc,
        "DY": DY, "HR": HR, "total_s": total_s,
        "last_cs_dist": last_cs_dist, "last_cs_time": last_cs_time}

def compute_vehicle_energy(step, soc, env_row, dt, const):

    # 차량 헤딩 방향 [deg]
    vehicle_heading = cal_route_vector(step)

    # 배터리 전력 소비량 [W]
    step["P_batt"], step["a"] = cal_drive_res(
        step, dt,
        env_row["wind_speed_10m"],
        env_row["wind_direction_10m"],
        vehicle_heading, const)

    # PV 발전량
    step["P_gen"] = gen_solar(env_row["shortwave_radiation"], const)

    # SOC Update
    soc, V_terminal = update_soc(soc, step, dt, const)
    prev_V_terminal = V_terminal
    step["P_net"] = step["P_gen"] - step["P_batt"]

    # 풍향, 풍속, 차량 헤딩 방향 업데이트
    prev_wind_speed = env_row["wind_speed_10m"]
    prev_wind_dir   = env_row["wind_direction_10m"]
    prev_heading    = vehicle_heading

    return soc, prev_V_terminal, prev_wind_speed, prev_wind_dir, prev_heading

def light_arrive(curr_dist, light_dists, visited_lights):
    for i, light_dist in enumerate(light_dists):
        if i not in visited_lights and abs(curr_dist - light_dist) < 20:
            return i
    return None

def compute_speed_limit(step, const):
    
    # 변수 선언
    curr_dist_km        = step["curr_dist"] / 1000

    # 상수 선언
    speed_limit_dists   = const["speed_limit_dists"]
    speed_limit_vals    = const["speed_limit_vals"]

    # 현재의 위치가 어느 속도 제한 구역에 있는지 확인
    idx = np.searchsorted(speed_limit_dists, curr_dist_km, side="right") - 1
    idx = max(idx, 0)
    return speed_limit_vals[idx]

def run_simulation(params, route, env_data, dist_vals, nearest_map, rad_max, light_dists, light_types,
                   speed_limit_dists, speed_limit_vals, cfg, progress_cb=None):

    # 차량 설정값 - 호출자가 넘긴 cfg(세션/호출별 독립 인스턴스)에서 꺼내 씀.
    # 모듈 전역 physics/solar/... 싱글턴을 여기서 직접 참조하지 않는 이유:
    # Streamlit처럼 여러 사용자가 한 서버 프로세스를 공유하는 환경에서 전역
    # 싱글턴을 직접 mutate하면(예: 차량 제원 설정 다이얼로그) 그 순간 다른
    # 모든 사용자의 시뮬레이션에도 영향을 주는 버그가 됨. cfg는 사용자마다
    # (app.py의 st.session_state.cfg) 독립적으로 만들어짐 - Configs.Vehicle_Params
    # .build_default_cfg() 참고.
    physics, solar, cell, pack, power, drive, race, simpara = (
        cfg.physics, cfg.solar, cfg.cell, cfg.pack, cfg.power, cfg.drive, cfg.race, cfg.simpara
    )

    # 인자 생성
    i                   = 1
    results             = []
    visited_cs          = set()
    visited_lights      = set()
    soc                 = simpara.soc
    Accum_s             = simpara.Accum_s
    DY                  = simpara.DY
    HR                  = simpara.HR
    prev_radiation      = simpara.prev_radiation
    prev_radiation_std  = 0.0          # 일사량 표준편차 (LV3 불확실성 보정용)
    prev_v              = simpara.prev_v
    prev_a              = simpara.prev_a
    prev_wind_speed     = simpara.prev_wind_speed
    prev_wind_dir       = simpara.prev_wind_dir
    prev_heading        = simpara.prev_heading
    prev_V_terminal     = np.interp(simpara.soc, cell.ocv_soc, cell.ocv_V) * pack.HV_S
    drive_time_s        = 0.0            # 순수 주행시간 누적 (야간 점프 미포함, 구간 평균속도 계산용)
    last_cs_dist        = 0.0            # 구간 평균속도 계산용 (직전 CS 위치)
    last_cs_time        = 0.0            # 구간 평균속도 계산용 (직전 CS 통과 시점의 drive_time_s)
    termination_reason  = "완주"          # 루프가 break 없이 끝까지 돌면 완주로 간주, break 지점마다 덮어씀

    # route 컬럼을 numpy 배열로 미리 추출 (매 스텝 route.iloc[] 생성 오버헤드 제거)
    route_dist          = route["dist"]
    route_lat           = route["lat"]
    route_lon           = route["lon"]
    route_slope         = route["slope"]
    route_theta         = route["theta"]
    route_is_downhill   = route["is_downhill"]
    route_is_uphill     = route["is_uphill"]

    n = len(route_dist)

    # 상수 딕셔너리 생성
    const = dict(
        env_data            = env_data,
        dist_vals           = dist_vals,
        rad_max             = rad_max,
        route_dist          = route_dist,
        route_slope         = route_slope,
        route_is_downhill   = route_is_downhill,
        route_is_uphill     = route_is_uphill,
        n                   = n,
        speed_limit_dists   = speed_limit_dists,
        speed_limit_vals    = speed_limit_vals,
        physics             = physics,
        solar               = solar,
        cell                = cell,
        pack                = pack,
        power               = power,
        drive               = drive,
        race                = race,
        )

    while i < n:
        step = dict(
            curr_dist       = route_dist[i],
            prev_dist       = route_dist[i - 1],
            theta           = route_theta[i],
            curr_slope      = route_slope[i],
            curr_lat        = route_lat[i],
            curr_lon        = route_lon[i],
            prev_lat        = route_lat[i - 1],
            prev_lon        = route_lon[i - 1],
            wind_speed      = prev_wind_speed,
            wind_direction  = prev_wind_dir,
            vehicle_heading = prev_heading,
            soc             = soc,
            a               = prev_a,
            i               = i,
            DY              = DY,
            HR              = HR,
            prev_v          = prev_v,
            prev_V_terminal = prev_V_terminal,
            Accum_s         = Accum_s,
            gen_ratio       = prev_radiation / rad_max,
            gen_ratio_std   = prev_radiation_std / rad_max,
        )

        # 각 Step 별 간격
        step["delta_dist"] = step["curr_dist"] - step["prev_dist"]
        
        # 다음 Control Stop
        step["next_cs"] = min([cs for cs in race.Control_Stop_2025 if cs > step["curr_dist"]], default=3038326)
        
        # 다음 Control Stop까지 남은 거리
        step["remaining_dist"] = (step["next_cs"] - step["curr_dist"]) / 1000

        # 현재 위치 기준 앞, 뒤 Control Stop 간 거리 
        step["leg_dist_km"] = (step["next_cs"] - last_cs_dist) / 1000

        # 미래 데이터 예측(경사도, 일사량)
        step["avg_gen_ratio"], step["slope_ahead"] = compute_lookahead(step, const)

        # 남은 주행 최적 페이스 도출(전체/다음CS)
        step["required_race_pace"], step["required_next_cs_pace"] = compute_required_pace(step, const)

        # 모터 속도 Derating 반영
        step["v_max_derated"] = compute_motor_derating(step, const)

        # 법정 제한속도 반영
        step["speed_limit"] = compute_speed_limit(step, const)

        # 속도 업데이트
        step["v"] = mpc_speed(step, params, const)
        prev_v = step["v"]

        # 구간 Delta Time [s]
        dt = step["delta_dist"] / step["v"]

        # 시간 업데이트 및 야간 데이터 처리
        Accum_s += dt
        drive_time_s += dt

        calender_result = calender_handler(Accum_s)
        if calender_result["Action"] == "Stop":
            termination_reason = calender_result.get("reason", "기간 초과")
            break
        
        Accum_s = calender_result["Accum_s"]
        if calender_result["Action"] == "Reset_Go":
            continue

        DY, HR, total_s = calender_result["DY"], calender_result["HR"], calender_result["total_s"]

        # route 데이터를 10k resolution 데이터로 치환
        nearest_diff = nearest_map[step["curr_dist"]]

        cs_stop_result = control_stop_handler(step, total_s, drive_time_s, Accum_s, soc, visited_cs, last_cs_dist, last_cs_time, nearest_diff, env_data, const)
        if cs_stop_result["Action"] == "Fail":
            termination_reason = cs_stop_result.get("reason", "컨트롤스탑 실격")
            break

        if cs_stop_result["Action"] == "Stop":
            visited_cs      = cs_stop_result["visited_cs"]
            Accum_s         = cs_stop_result["Accum_s"]
            soc             = cs_stop_result["soc"]
            DY              = cs_stop_result["DY"]
            HR              = cs_stop_result["HR"]
            total_s         = cs_stop_result["total_s"]
            last_cs_dist    = cs_stop_result["last_cs_dist"]
            last_cs_time    = cs_stop_result["last_cs_time"]
            prev_v          = 0

        light_hit = light_arrive(step["curr_dist"], light_dists, visited_lights)
        if light_hit is not None:
            visited_lights.add(light_hit)
            if light_types[light_hit] == "traffic_light":
                Accum_s += simpara.avg_traffic_light_delay
            else:       # pedestrian_light
                Accum_s += simpara.avg_pedestrian_light_delay

        # DY, HR로 행 생성
        env_row = env_data.get((nearest_diff, DY, HR))
        if env_row is None:
            # 스킵 전 i += 1
            i += 1
            continue

        # 스킵 전 i += 1
        i += 1

        # SOC 떨어지면 그대로 종료
        if soc < simpara.soc_hard_stop:
            termination_reason = "배터리 SOC 하한 도달"
            break

        # 일사량 업데이트
        prev_radiation = env_row["shortwave_radiation"]
        prev_radiation_std = env_row["shortwave_radiation_std"]
        
        # 차량 에너지 계산
        soc, prev_V_terminal, prev_wind_speed, prev_wind_dir, prev_heading = compute_vehicle_energy(step, soc, env_row, dt, const)
        prev_a = step["a"]

        # 진척율 표시
        if progress_cb and i % 100 == 0:
            progress_cb(step["curr_dist"] / race.total_distance)

        # 결과 값 리스트에 Append
        results.append({
            "dist":     step["curr_dist"],
            "DY":       DY,
            "HR":       HR,
            "v":        step["v"],
            "soc":      soc,
            "P_batt":   step["P_batt"],
            "P_gen":    step["P_gen"],
            "P_net":    step["P_net"],
            "slope":    step["curr_slope"],
        })

    return pd.DataFrame(results), termination_reason