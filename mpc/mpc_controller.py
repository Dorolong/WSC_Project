"""
속도 조절 함수
"""

import math as m
import numpy as np

from Configs.Vehicle_Params import *

# MPC 모델 파라미터들
mpc_default_params = {
    "v_soc_high":           92,     # SOC 기반 속도 조절
    "soc_ramp_high":        0.7424, # SOC 임계값 match with v1
    "soc_ramp_low":         0.2762, # SOC 임계값 match with v2
    "slope_k":              75,     # 경사도 보정계수
    "momentum_gain":        1.0,    # 경사를 만나기 전 얼마나 가속을 붙일거냐
    "radi_para":            19,     # 일사량 계수(max/min: 10)
    "radi_risk":            0.0,    # 일사량 불확실성 계수
    "energy_v":             16.8,   # 에너지 예산 기반 속도 계수
    "winddir_para":         9,      # 풍향 계수
    "margin_total":         0.5,    # 전체 거리 대비 SOC factor 결정값
    "margin_next_cs":       0.5,    # 다음 CS 대비 SOC factor 결정값
    "soc_cutoff":           0.108,  # SOC 하한값
    "v_min":                60,     # 속도 하한값 [km/h]
    "alpha":                0.3,    # 속도 변화 댐핑계수
}

# 속도 제한 데이터


def mpc_speed(step, params, const):

    # 설정값 선언 (호출자의 cfg에서 옴 - 세션별로 독립적, simpara는
    # 다이얼로그가 안 건드리는 값이라 계속 전역 참조해도 안전함)
    solar = const["solar"]
    pack  = const["pack"]
    race  = const["race"]
    drive = const["drive"]

    # 차량 헤딩 기준 풍향/속 결정
    headwind = step["wind_speed"] * m.cos(m.radians(step["wind_direction"] - step["vehicle_heading"]))

    # 1. SOC 기반 속도 조절
    frac = np.clip((step["soc"] - params.get("soc_ramp_low", 0.2762)) / (params.get("soc_ramp_high", 0.7424) - params.get("soc_ramp_low", 0.2762)), 0, 1)
    v = params.get("v_min", 45) + frac * (params.get("v_soc_high", 92)  - params.get("v_min", 45))

    # 2. 경사각 기반 속도 조절
    slope_severity = np.clip((step["slope_ahead"] - 0.02) / 0.02, 0, 1)
    momentum = np.clip(step["a"] * params.get("momentum_gain", 1.0), 0, 1) * slope_severity
    v -= params.get("slope_k", 75) * step["slope_ahead"] * (1 - momentum)

    # 3. 일사량 기반 속도 조절
    # 일사량 최대 대비 50% 기준 속도 조절 (Max / min: +10 / -10)
    # soc가 특정 값 이하일 때 속도 증가 방지
    # 표준 편차를 이용해 날씨의 불확실성 반영
    gen_ratio_conservation = step["gen_ratio"] - params.get("radi_risk", 0.0) * step["gen_ratio_std"]
    v += (gen_ratio_conservation - 0.5) * params.get("radi_para", 20)

    # 4. 에너지 예산 기반 속도 조절
    if step["remaining_dist"] > 0:
        # 현재 속도 기반 남은 시간 추정
        remaining_HR = step["remaining_dist"] / v

        # 앞으로 받을 발전량 -> SOC로 환산
        expected_gen_soc = step["avg_gen_ratio"] * (solar.A_Solar * solar.Solar_eff * 1000) * remaining_HR / pack.HV_Energy

        # 실질 사용 가능 SOC
        available_soc = (step["soc"] - race.soc_start_min) + expected_gen_soc
        expected_soc_per_km = available_soc / step["remaining_dist"]

        # 정상상태 소비율 기준치: 이번 stint 기준
        energy_crit = (race.soc_start_min - params.get("soc_cutoff", 0.15)) / step["leg_dist_km"]
        deficit = np.clip((energy_crit - expected_soc_per_km) / energy_crit, 0, 1)
        v -= deficit * params.get("energy_v", 10)

    # 5. 풍향 고려 속도 조절
    v -= np.clip(params.get("winddir_para", 10) * headwind,
                 -params.get("winddir_para", 10), params.get("winddir_para", 10))

    # 누적 보정으로 v가 0 이하로 내려갈 수 있어, 나눗셈 전에 하한 적용
    v = max(v, params.get("v_min", 45))

    # SOC 하한선 최소 속도 고정 로직
    if step["soc"] <= params.get("soc_cutoff", 0.15):
        v = params.get("v_min", 45)

    # 6. 만약 다음 CS에 적절하게 도착을 못 한다면? (SOC 보존 구간에서는 개입 안 함)
    else:
        # 전체 거리에 대해
        urgency_total = np.clip((step["required_race_pace"] - v) / v, 0, 1)
        soc_factor_total = np.clip(((step["soc"] - params.get("soc_cutoff", 0.15)) / params.get("margin_total", 0.5)), 0, 1)
        global_factor = urgency_total * soc_factor_total

        # 다음 CS에 대해
        urgency_next_cs = np.clip((step["required_next_cs_pace"] - v) / v, 0, 1)
        soc_factor_next_cs = np.clip(((step["soc"] - params.get("soc_cutoff", 0.15)) / params.get("margin_next_cs", 0.5)), 0, 1)
        next_cs_factor = urgency_next_cs * soc_factor_next_cs

        total = 1 + global_factor + next_cs_factor
        v = (v + global_factor * step["required_race_pace"] + next_cs_factor * step["required_next_cs_pace"]) / total

    # 배터리 전압 기반 속도 제한 로직
    v = min(v, step["v_max_derated"])

    # 최고, 최저속도 하한선 추가
    v = max(v, params.get("v_min", 45))
    v = min(v, drive.v_max)

    # 법정 최고속도 준수
    v = min(v, step["speed_limit"])

    # 스텝 변화량 조절
    v = v / 3.6
    delta = v - step["prev_v"]
    v = step["prev_v"] + simpara.max_v_delta * m.tanh(params.get("alpha", 0.3) * delta / simpara.max_v_delta)
    
    return v