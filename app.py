"""
로컬 웹사이트 생성
"""

import os
import sys
import time
import base64
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import optuna
from plotly.subplots import make_subplots

from Functions.Vehicle_Function import read_path, run_simulation
from mpc.mpc_controller import mpc_default_params
from Configs.Vehicle_Params import *

try:
    study = optuna.load_study(
        study_name="WSC_MPC_Opt",
        storage="sqlite:///outputs/optuna_study.db"
    )
    best_params = {**mpc_default_params, **study.best_params}
except:
    best_params = mpc_default_params

# 브라우저 탭 이름
st.set_page_config(page_title="WSC Drive Simulator", layout="wide")

# 시뮬레이션 실행 중 다른 버튼 클릭으로 중단되는 것 방지용 플래그
if "sim_running" not in st.session_state:
    st.session_state.sim_running = False

# 차량 제원 팝업 (제목 옆 버튼에서 호출하므로 먼저 정의)
@st.dialog("차량 제원 설정")
def vehicle_settings_dialog():
    tab_physics, tab_solar, tab_cell, tab_pack, tab_power, tab_drive, tab_race, tab_ocv = st.tabs(
        ["물리 제원", "태양광 패널", "배터리 셀", "배터리 팩", "전력 시스템", "구동계", "레이스 설정", "OCV 테이블"]
    )

    with tab_physics:
        mass    = st.number_input("총 질량 [kg]",       value=physics.mass)
        Cd      = st.number_input("Cd",                 value=physics.Cd)
        Af      = st.number_input("Af [m^2]",           value=physics.A_f)
        Crr     = st.number_input("Crr",                value=physics.Crr)
        Dr_eff  = st.number_input("구동계 효율",         value=physics.Drive_eff)
        Air_Den = st.number_input("공기 밀도 [kg/m^3]", value=physics.Air_Density)
        Ag      = st.number_input("중력 가속도 [m/s^2]",value=physics.a_g)

    with tab_solar:
        A_solar   = st.number_input("패널 면적 [m^2]",  value=solar.A_Solar)
        Solar_eff = st.number_input("패널 효율",         value=solar.Solar_eff)

    with tab_cell:
        V_max = st.number_input("최대 전압 [V]",         value=cell.V_batt_max)
        V_nom = st.number_input("공칭 전압 [V]",         value=cell.V_batt_nom)
        V_min = st.number_input("Cut-off 전압 [V]",      value=cell.V_batt_min)
        Capa  = st.number_input("방전 용량 [mAh]",       value=float(cell.Capa_batt))
        R     = st.number_input("내부 저항 [Ω]",         value=cell.R_cell)

    with tab_pack:
        HV_S = st.number_input("HV 직렬 수",  value=float(pack.HV_S))
        HV_P = st.number_input("HV 병렬 수",  value=float(pack.HV_P))
        LV_S = st.number_input("LV 직렬 수",  value=float(pack.LV_S))
        LV_P = st.number_input("LV 병렬 수",  value=float(pack.LV_P))

    with tab_power:
        P_LV_race  = st.number_input("주행 LV 소비전력 [W]",    value=power.P_LV_race)
        P_LV_chg   = st.number_input("정차 LV 소비전력 [W]",    value=power.P_LV_chg)
        Regen_eff  = st.number_input("회생제동 효율",            value=power.Regen_eff)
        cs_chg_eff = st.number_input("CS 충전 보정계수",         value=power.cs_chg_eff)

    with tab_drive:
        Kv         = st.number_input("속도 상수 Kv [Vs/rad]",   value=drive.speed_constant)
        Kt         = st.number_input("토크 상수 Kt",             value=drive.torque_constant)
        nom_dcV    = st.number_input("정격 DC 전압 [V]",         value=float(drive.motor_nom_dcV))
        nom_spd    = st.number_input("정격 속도 [rad/s]",        value=float(drive.motor_nom_speed))
        max_spd    = st.number_input("최대 속도 [rad/s]",        value=float(drive.motor_max_speed))
        nom_pwr    = st.number_input("정격 출력 [W]",            value=float(drive.motor_nom_power))
        nom_trq    = st.number_input("정격 토크 [Nm]",           value=drive.nom_torque)
        max_trq    = st.number_input("최대 토크 [Nm]",           value=float(drive.max_torque))
        phase_res  = st.number_input("상 저항 [Ω]",              value=drive.phase_res)
        motor_eff  = st.number_input("모터 효율",                value=drive.motor_eff)
        inv_eff    = st.number_input("인버터 효율",              value=drive.inverter_eff)
        wheel_r    = st.number_input("휠 반경 [m]",              value=drive.wheel_radius)

    with tab_race:
        soc_min    = st.number_input("출발 최소 SOC",            value=race.soc_start_min)
        cs_max     = st.number_input("CS 최대 정차 시간 [s]",    value=float(race.cs_stop_max))
        cs_min     = st.number_input("CS 최소 정차 시간 [s]",    value=float(race.cs_stop_min))

    with tab_ocv:
        ocv_df = pd.DataFrame({
            "SOC": cell.ocv_soc.tolist(),
            "V":   cell.ocv_V.tolist()
        })
        edited = st.data_editor(ocv_df, num_rows="fixed")

    if st.button("적용"):
        physics.mass        = mass
        physics.Cd          = Cd
        physics.A_f         = Af
        physics.Crr         = Crr
        physics.Drive_eff   = Dr_eff
        physics.Air_Density = Air_Den
        physics.a_g         = Ag

        solar.A_Solar       = A_solar
        solar.Solar_eff     = Solar_eff

        cell.V_batt_max     = V_max
        cell.V_batt_nom     = V_nom
        cell.V_batt_min     = V_min
        cell.Capa_batt      = Capa
        cell.R_cell         = R
        cell.ocv_soc        = edited["SOC"].to_numpy()
        cell.ocv_V          = edited["V"].to_numpy()

        pack.HV_S           = int(HV_S)
        pack.HV_P           = int(HV_P)
        pack.LV_S           = int(LV_S)
        pack.LV_P           = int(LV_P)
        pack.__post_init__()    # 파생값 재계산

        power.P_LV_race     = P_LV_race
        power.P_LV_chg      = P_LV_chg
        power.Regen_eff     = Regen_eff
        power.cs_chg_eff    = cs_chg_eff

        drive.speed_constant    = Kv
        drive.torque_constant   = Kt
        drive.motor_nom_dcV     = int(nom_dcV)
        drive.motor_nom_speed   = int(nom_spd)
        drive.motor_max_speed   = int(max_spd)
        drive.motor_nom_power   = int(nom_pwr)
        drive.nom_torque        = nom_trq
        drive.max_torque        = int(max_trq)
        drive.phase_res         = phase_res
        drive.motor_eff         = motor_eff
        drive.inverter_eff      = inv_eff
        drive.wheel_radius      = wheel_r
        drive.__post_init__()   # v_max 재계산

        race.soc_start_min  = soc_min
        race.cs_stop_max    = int(cs_max)
        race.cs_stop_min    = int(cs_min)

        st.rerun()

# 페이지 제목 + 차량 제원 설정 버튼 (Streamlit 기본 Stop 컨트롤이 뜨는 우측 상단 근처)
title_col, btn_col = st.columns([6, 1])
with title_col:
    st.title("2027 WSC Drive Simulator")
with btn_col:
    st.write("")
    st.write("")
    if st.button("차량 제원 설정", disabled=st.session_state.sim_running):
        vehicle_settings_dialog()

# 캐시
@st.cache_data
def load_data():
    # 데이터 가져오기
    route = read_path("2027 BWSC TRACK.csv")
    env_data = pd.read_csv("outputs/env_data.csv")
    env_data = env_data.set_index(["total_distance_m", "DY", "HR"])

    # 신호등 위치 정보
    lights_df = pd.read_csv("Configs/traffic_lights_2025.csv")
    light_dists = lights_df["distance_km"].to_numpy()
    light_types = lights_df["type"].to_numpy()

    # 법정 최고속도 제한 정보
    speed_limits_df = pd.read_csv("Configs/speed_limits_2025.csv")
    speed_limit_dists = speed_limits_df["distance_km"].to_numpy()
    speed_limit_vals  = speed_limits_df["speed_limit_kmh"].to_numpy()

    # 거리 10km 격자 전처리
    # .to_numpy(): pandas Index 그대로 두면 compute_lookahead()의 매 스텝
    # dist_vals - future_dist_m 연산이 pandas 내부 타입체크/dtype추론을
    # 거쳐 numpy 배열 연산보다 훨씬 느려짐 (scripts/main.py에서 프로파일링으로
    # 확인, 전체 실행시간의 70%+ 차지 - progress/17 참고)
    dist_vals = env_data.index.get_level_values("total_distance_m").unique().sort_values().to_numpy()
    nearest_map = {
        d: dist_vals[np.abs(dist_vals - d).argmin()]
        for d in route["total_distance_m"]
    }
    env_dict = env_data.to_dict("index")
    rad_max = env_data["shortwave_radiation"].max()

    route_np = {
        "dist":         route["total_distance_m"].to_numpy(),
        "lat":          route["lat"].to_numpy(),
        "lon":          route["lon"].to_numpy(),
        "slope":        route["slope"].to_numpy(),
        "theta":        route["theta"].to_numpy(),
        "is_downhill":  route["is_downhill"].to_numpy(),
        "is_uphill":    route["is_uphill"].to_numpy(),
    }

    return route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limit_dists, speed_limit_vals

route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limits_dists, speed_limits_vals = load_data()

# 사이드바 - MPC 파라미터 (읽기 전용, Optuna 최적값 그대로 사용)
with st.sidebar:
    st.header("MPC 파라미터 (Optuna 최적값)")
    st.dataframe(
        pd.DataFrame(best_params.items(), columns=["파라미터", "값"]),
        hide_index=True,
        use_container_width=True
    )

# 경로 지도 - 커스텀 컴포넌트 (배경/전체경로는 최초 1회만, 이후 마커+주행경로만 갱신 -> 부드러운 이동)
_bg_lat = route_np["lat"][::5]
_bg_lon = route_np["lon"][::5]

_AUS_BOUNDS = dict(minx=113.18476562500001, miny=-39.1455078125, maxx=153.61689453125, maxy=-10.707324218750003)
_aus_img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "australia_silhouette.png")
_aus_img_uri = None
if os.path.exists(_aus_img_path):
    with open(_aus_img_path, "rb") as f:
        _aus_img_uri = "data:image/png;base64," + base64.b64encode(f.read()).decode()

_route_animator = components.declare_component(
    "route_animator",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "route_animator")
)

def route_animator(duration_sec=None, final_lon=None, final_lat=None, key=None):
    # 컴포넌트는 한 실행 안에서 반복 호출하면 iframe이 매번 재생성되어 깜빡이므로,
    # 딱 두 번만 호출: (1) 시작 시 예상 소요시간 동안 스스로 애니메이션 (2) 완료 시 실제 도달 지점으로 즉시 스냅
    kwargs = dict(
        bg_lon=_bg_lon.tolist(),
        bg_lat=_bg_lat.tolist(),
        bg_image=_aus_img_uri,
        bounds=_AUS_BOUNDS,
        key=key,
        default=None,
    )
    if final_lon is not None:
        kwargs["final_lon"] = final_lon
        kwargs["final_lat"] = final_lat
    else:
        kwargs["route_lon"] = _bg_lon.tolist()
        kwargs["route_lat"] = _bg_lat.tolist()
        kwargs["duration_sec"] = duration_sec or 20
    return _route_animator(**kwargs)

# 실행 버튼
if st.button("시뮬레이션 실행", type="primary", disabled=st.session_state.sim_running):
    st.session_state.sim_running = True
    st.rerun()

if st.session_state.sim_running:
    params = {**best_params}

    st.subheader("경로 진행 상황")
    anim_placeholder = st.empty()
    with anim_placeholder.container():
        route_animator(duration_sec=6)  # 실제 진행률과 무관하게 계속 반복 재생되는 장식용 애니메이션
    time.sleep(1)  # 지도 iframe이 다 뜬 뒤에 퍼센테이지가 시작되도록 살짝 대기

    pct_text = st.empty()
    eta_text = st.empty()
    _progress_start = time.time()

    def update_progress(pct):
        pct_text.markdown(
            f"<div style='font-size:2em; font-weight:bold;'>{pct*100:.1f}%</div>",
            unsafe_allow_html=True
        )
        elapsed = time.time() - _progress_start
        if pct > 0.02:
            remaining = max(0, elapsed / pct - elapsed)
            eta_text.caption(f"Estimated Time Left: {remaining:.0f}s")
        else:
            eta_text.caption("Estimated Time Left: calculating...")

    df = run_simulation(params, route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limits_dists, speed_limits_vals, progress_cb=update_progress)
    eta_text.empty()
    pct_text.empty()
    st.session_state.sim_running = False

    # 계산 완료 -> 실제 도달 지점까지 애니메이션 없이 즉시 반영 (완주 실패 시 그 지점에서 멈춤)
    route_dist_arr = route_np["dist"]
    _final_idx = int(np.searchsorted(route_dist_arr, df["dist"].max()))
    _final_idx = min(_final_idx, len(route_dist_arr) - 1)
    _final_lon = route_np["lon"][:_final_idx + 1:5].tolist() + [float(route_np["lon"][_final_idx])]
    _final_lat = route_np["lat"][:_final_idx + 1:5].tolist() + [float(route_np["lat"][_final_idx])]
    with anim_placeholder.container():
        route_animator(final_lon=_final_lon, final_lat=_final_lat)

    # 요약 지표 - 1
    col1, col2, col3 = st.columns(3)
    col1.metric("평균속도",  f"{df['v'].mean()*3.6:.1f} km/h")
    col2.metric("최고 속도", f"{df['v'].max()*3.6:.2f} km/h")
    col3.metric("총 주행 거리", f"{df['dist'].max()/1000:.0f} km")

    # 요약 지표 - 2
    col4, col5, col6 = st.columns(3)
    col4.metric("평균 소비 전력", f"{df[df['P_batt']>0]['P_batt'].mean():.2f} W")
    col5.metric("최저 SOC", f"{df['soc'].min()*100:.1f} %")
    if df['dist'].max() >= 3038000:
        col6.success("완주 성공")
    elif df['dist'].max() < 3038000:
        col6.error("완주 실패")

    # 요약 지표 - 3
    col7, col8 = st.columns(2)
    col7.metric("최대 경사도", f"{df['slope'].abs().max()*100:.1f} %")
    col8.metric("평균 발전량", f"{df['P_gen'].mean():.2f} W")

    # 그래프
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        subplot_titles=("SOC", "전력 [W]", "속도 [km/h]"),
                        vertical_spacing=0.08)

    fig.add_trace(go.Scatter(x=df["dist"]/1000, y=df["soc"],
                             name="SOC", line=dict(color="steelblue")), row=1, col=1)

    fig.add_trace(go.Scatter(x=df["dist"]/1000, y=df["P_batt"],
                             name="소비", line=dict(color="tomato")), row=2, col=1)
    fig.add_trace(go.Scatter(x=df["dist"]/1000, y=df["P_gen"],
                             name="발전", line=dict(color="orange")), row=2, col=1)

    fig.add_trace(go.Scatter(x=df["dist"]/1000, y=df["v"]*3.6,
                             name="순간속도", line=dict(color="lightblue"), opacity=0.4), row=3, col=1)
    fig.add_trace(go.Scatter(x=df["dist"]/1000, y=df["v"].expanding().mean()*3.6,
                             name="누적평균", line=dict(color="orange")), row=3, col=1)

    # 날짜 경계선
    for dy, grp in df.groupby("DY"):
        x = grp["dist"].max()/1000
        for r in [1, 2, 3]:
            fig.add_vline(x=x, line_dash="dash", line_color="gray",
                          line_width=1, row=r, col=1)

    for cs_dist in race.Control_Stop_2025.keys():
        idx = (df["dist"] - cs_dist).abs().idxmin()
        soc_val = df.loc[idx, "soc"]

        fig.add_annotation(
            x=cs_dist / 1000,
            y=soc_val,
            ax=0, ay=-30,
            arrowhead=2,
            arrowcolor="red",
            arrowsize=1,
            showarrow=True,
            text="",
            row=1, col=1,
        )

    fig.update_xaxes(title_text="거리 [km]", row=3, col=1)
    fig.update_layout(height=800, showlegend=True)
    st.plotly_chart(fig, use_container_width=True)

    st.download_button(
    label="CSV 저장",
    data=df.to_csv(index=False),
    file_name="sim_result.csv",
    mime="text/csv"
    )
