"""
로컬 웹사이트 생성
"""

import os
import sys
import time
import base64
import dataclasses
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import optuna
from plotly.subplots import make_subplots
from supabase import create_client

from Functions.Vehicle_Function import read_path, run_simulation
from mpc.mpc_controller import mpc_default_params
from Configs.Vehicle_Params import *

# Supabase 클라이언트: st.session_state에 세션별로 저장(브라우저 세션마다 독립).
# @st.cache_resource로 캐싱하면 서버 프로세스 전체에서 하나의 클라이언트를
# 공유하게 되어, 로그인 시 클라이언트 내부에 저장되는 인증 세션이 다른
# 사용자의 요청에도 그대로 섞여 들어가는(계정 뒤섞임) 위험이 있어 사용 안 함.
if "supabase" not in st.session_state:
    st.session_state.supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
supabase = st.session_state.supabase

if "user" not in st.session_state:
    st.session_state.user = None

# 차량 제원(physics/solar/cell/pack/power/drive/race) 묶음: 세션별로 독립된
# 인스턴스로 만들어서 st.session_state에 보관. 예전엔 Configs.Vehicle_Params의
# 전역 싱글턴(physics 등)을 "차량 제원 설정" 다이얼로그가 직접 수정했는데,
# Streamlit Cloud는 여러 사용자가 같은 서버 프로세스를 공유하는 구조라 그
# 수정이 그 순간 접속 중인 모든 사용자에게 그대로 반영되는 버그였음
# (한 사용자가 값을 바꾸면 다른 사용자의 시뮬레이션 결과도 바뀜). 이제
# run_simulation()이 cfg를 인자로 받아 사용하므로, 세션마다 독립된 cfg를
# 쓰면 서로 영향을 안 줌.
if "cfg" not in st.session_state:
    st.session_state.cfg = build_default_cfg()

def cfg_to_jsonable(cfg):
    """cfg(physics/solar/... 묶음, numpy 배열 포함)를 Supabase(jsonb)에 저장 가능한 dict로 변환.
    dataclasses.asdict()는 선언된 필드만 뽑아내서 __post_init__이 계산한 파생값
    (HV_Energy, v_max 등)은 자동으로 빠짐 - 복원 시 __post_init__()을 다시 불러
    재계산하면 되므로 저장할 필요 없음."""
    def convert(o):
        if isinstance(o, dict):
            return {k: convert(v) for k, v in o.items()}
        if isinstance(o, np.ndarray):
            return o.tolist()
        return o
    return {
        name: convert(dataclasses.asdict(getattr(cfg, name)))
        for name in ("physics", "solar", "cell", "pack", "power", "drive", "race")
    }

def cfg_from_jsonable(data):
    """cfg_to_jsonable()의 역변환. build_default_cfg()를 베이스로 저장된 값만
    덮어써서, 나중에 필드가 추가돼도(예: 새 차량 제원 항목) 저장 당시엔 없던
    필드는 기본값으로 안전하게 채워짐."""
    cfg = build_default_cfg()
    for name in ("physics", "solar", "power", "drive", "race"):
        obj = getattr(cfg, name)
        for k, v in data.get(name, {}).items():
            if hasattr(obj, k):
                setattr(obj, k, v)
    for k, v in data.get("cell", {}).items():
        if hasattr(cfg.cell, k):
            setattr(cfg.cell, k, np.array(v) if k in ("ocv_soc", "ocv_V") else v)
    for k in ("HV_S", "HV_P", "LV_S", "LV_P"):
        if k in data.get("pack", {}):
            setattr(cfg.pack, k, data["pack"][k])
    cfg.pack.__post_init__()   # 파생값 재계산 (HV_Energy 등)
    cfg.drive.__post_init__()  # 파생값 재계산 (v_max)
    return cfg

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

# 릴리즈 노트: 새 버전이 나올 때마다 맨 위(리스트 맨 앞)에 새 항목을
# 추가하고 APP_VERSION을 그 버전으로 올린다. 파일로 따로 안 두고 코드에
# 데이터로 두는 이유는 사용자 요청대로 "제목만 각각 버튼(펼치기)이면
# 충분"한 가벼운 용도이기 때문 - 내부 개발 이력은 progress/, debug_logs/
# 쪽이 이미 훨씬 상세하게 담당하고 있고, 여기는 사용자에게 보여줄 요약본.
RELEASE_NOTES = [
    {
        "version": "1.0.6",
        "date": "2026-08-02",
        "title": "릴리즈 노트 · 첫 로그인 튜토리얼 추가",
        "details": "- 현재 버전과 업데이트 이력을 앱에서 바로 확인할 수 있는 릴리즈 노트 추가\n"
                    "- 처음 로그인한 사용자에게 사용법 안내 팝업 표시(한 번 확인하면 다시 안 뜸)",
    },
    {
        "version": "1.0.5",
        "date": "2026-08-02",
        "title": "차량 제원 설정 화면 UI 개선",
        "details": "- '적용' / '적용 후 계정에 저장'으로 나뉘어 있던 버튼을 '적용' 버튼 + "
                    "'계정에도 저장' 체크박스로 통합\n"
                    "- '마지막 저장값 불러오기' 버튼을 설정 화면 맨 위로 이동",
    },
    {
        "version": "1.0.4",
        "date": "2026-08-02",
        "title": "차량 제원 설정 저장/불러오기 기능 추가",
        "details": "- 차량 제원 설정을 계정에 저장하고, 다음 로그인 시 마지막 설정을 그대로 불러오는 기능 추가\n"
                    "- 지난 시뮬레이션 기록에서 '이 설정 불러오기'로 그때 사용했던 차량 제원을 바로 복원 가능",
    },
    {
        "version": "1.0.3",
        "date": "2026-08-02",
        "title": "차량 제원 설정이 계정별로 독립 적용되도록 수정",
        "details": "- (버그 수정) 한 사용자가 차량 제원을 변경하면 그 순간 접속 중인 다른 모든 "
                    "사용자의 시뮬레이션에도 영향을 주던 문제를 수정\n"
                    "- 이제 차량 제원 변경은 본인 계정/세션에만 적용됨",
    },
    {
        "version": "1.0.2",
        "date": "2026-08-02",
        "title": "완주 실패 원인 분석 패널 추가",
        "details": "- 시뮬레이션이 완주하지 못했을 때 원인(배터리 SOC 부족, 체크포인트 마감시각 초과, "
                    "구간 평균속도 미달 등)을 결과 화면에서 바로 확인 가능",
    },
    {
        "version": "1.0.1",
        "date": "2026-08-02",
        "title": "로그인 및 시뮬레이션 기록 저장 기능 추가",
        "details": "- 로그인/회원가입(닉네임 포함) 기능 추가\n"
                    "- 시뮬레이션 결과를 계정에 저장하고, 지난 기록을 사이드바에서 조회 가능",
    },
    {
        "version": "1.0.0",
        "date": "2026-08-02",
        "title": "첫 배포",
        "details": "- WSC 주행효율 예측 MPC 시뮬레이터 첫 공개 배포\n"
                    "- 경로 지도, 시뮬레이션 실행, 결과 그래프/지표 확인 기능 제공",
    },
]
APP_VERSION = RELEASE_NOTES[0]["version"]

@st.dialog("릴리즈 노트")
def release_notes_dialog():
    for note in RELEASE_NOTES:
        with st.expander(f"v{note['version']} · {note['date']} · {note['title']}"):
            st.markdown(note["details"])

# 첫 로그인 사용자를 위한 사용법 안내 팝업. 한 번 확인하면 Supabase
# user_metadata에 tutorial_seen=True로 남겨서(닉네임과 같은 방식) 다음부터는
# 다시 안 뜨게 함 - 세션(session_state)이 아니라 계정에 남기는 이유는
# 새로고침/재로그인해도 계속 유지돼야 하기 때문.
@st.dialog("사용법 안내")
def tutorial_dialog():
    st.markdown(
        "환영합니다! 간단히 사용법을 안내해드릴게요.\n\n"
        "1. 상단 [차량 제원 설정] 버튼에서 차량 물리 제원을 조정할 수 있어요. "
        "(로그인 후 계정에 저장/불러오기도 가능)\n"
        "2. [시뮬레이션 실행] 버튼을 누르면 완주 시뮬레이션이 진행돼요.\n"
        "3. 시뮬레이션이 끝나면 결과 그래프와 함께, 완주하지 못했을 경우 원인 분석도 확인할 수 있어요.\n"
        "4. [결과 서버에 저장]을 누르면 이 기록이 계정에 남고, 사이드바 "
        "[내 시뮬레이션 기록]에서 다시 확인하거나 그때 설정을 불러올 수 있어요.\n\n"
        "궁금한 점은 상단 [릴리즈 노트] 버튼에서 그동안의 업데이트 내역도 확인해보세요."
    )
    if st.button("확인했습니다", type="primary", use_container_width=True):
        try:
            res = supabase.auth.update_user({"data": {"tutorial_seen": True}})
            st.session_state.user = res.user
        except Exception:
            pass
        st.rerun()

# 차량 제원 팝업 (제목 옆 버튼에서 호출하므로 먼저 정의)
# 아래에서 읽고 쓰는 physics/solar/cell/pack/power/drive/race는 전부
# st.session_state.cfg(이 세션 전용 인스턴스)에서 옴 - Configs.Vehicle_Params의
# 전역 싱글턴을 여기서 직접 참조/수정하지 않음(수정하면 다른 사용자에게도
# 영향을 주는 버그였음, 위 st.session_state.cfg 초기화 주석 참고).
@st.dialog("차량 제원 설정")
def vehicle_settings_dialog():
    # 계정에 저장된 마지막 설정 불러오기 - 편집 시작 전에 한 번 하는 동작이라
    # 적용/저장 버튼들과 묶지 않고 상단에 별도로 분리
    if st.button("☁ 마지막 저장값 불러오기", disabled=st.session_state.user is None, use_container_width=True):
        try:
            res = (
                supabase.table("user_settings")
                .select("vehicle_cfg")
                .eq("user_id", st.session_state.user.id)
                .execute()
            )
            if res.data:
                st.session_state.cfg = cfg_from_jsonable(res.data[0]["vehicle_cfg"])
                st.success("저장된 설정을 불러왔어요.")
            else:
                st.info("저장된 설정이 없어요. 값을 수정하고 아래 '계정에 저장'을 체크한 뒤 적용해주세요.")
        except Exception as e:
            st.error(f"불러오기 실패: {e}")
        st.rerun()

    cfg = st.session_state.cfg
    physics, solar, cell, pack, power, drive, race = (
        cfg.physics, cfg.solar, cfg.cell, cfg.pack, cfg.power, cfg.drive, cfg.race
    )

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

    save_to_account = st.checkbox(
        "계정에도 저장", value=False, disabled=st.session_state.user is None,
        help="체크하면 적용과 동시에 이 설정을 계정에 저장해서, 다음에 로그인했을 때 위 '마지막 저장값 불러오기'로 다시 불러올 수 있어요."
        + ("" if st.session_state.user is not None else " (로그인 필요)")
    )
    apply_clicked = st.button("적용", use_container_width=True)

    if apply_clicked:
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

        if save_to_account:
            try:
                supabase.table("user_settings").upsert({
                    "user_id":     st.session_state.user.id,
                    "vehicle_cfg": cfg_to_jsonable(cfg),
                }).execute()
                st.success("적용하고 계정에도 저장했어요.")
            except Exception as e:
                st.error(f"저장 실패: {e}")

        st.rerun()

# 첫 로그인 사용자 튜토리얼 팝업: 계정에 tutorial_seen 플래그가 없으면 표시.
# 로그인 버튼의 st.rerun() 직후 스크립트가 처음부터 다시 실행될 때 여기서
# 걸리므로, 로그인 처리 코드 안이 아니라 메인 흐름 쪽에 둠.
if st.session_state.user is not None and not st.session_state.user.user_metadata.get("tutorial_seen"):
    tutorial_dialog()

# 페이지 제목 + 버전/릴리즈노트 + 차량 제원 설정 버튼 (Streamlit 기본 Stop 컨트롤이 뜨는 우측 상단 근처)
# 참고: 이 위치가 Streamlit 앱 콘텐츠 영역에서 사용 가능한 가장 위쪽 자리.
# 화면 우측 상단의 Share/GitHub/Manage app 등은 Streamlit Cloud가 앱
# iframe 바깥에 그리는 플랫폼 UI라서, 앱 코드(Python)로는 그 툴바 안에
# 버튼을 끼워넣거나 위치를 옮길 수 없음.
title_col, version_col, btn_col = st.columns([5, 1.3, 1])
with title_col:
    st.title("2027 WSC Drive Simulator")
with version_col:
    st.write("")
    st.write("")
    v_col, note_col = st.columns([1, 1.7])
    with v_col:
        st.write("")
        st.caption(f"v{APP_VERSION}")
    with note_col:
        if st.button("Release note", use_container_width=True):
            release_notes_dialog()
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

# 사이드바 - 계정 (로그인/회원가입, 로그인 시 시뮬레이션 기록 저장/조회)
with st.sidebar:
    st.header("계정")
    if st.session_state.user is None:
        tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
        with tab_login:
            login_email = st.text_input("이메일", key="login_email")
            login_pw = st.text_input("비밀번호", type="password", key="login_pw")
            if st.button("로그인", key="login_btn"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": login_email, "password": login_pw})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.error(f"로그인 실패: {e}")
        with tab_signup:
            signup_nickname = st.text_input("닉네임", key="signup_nickname")
            signup_email = st.text_input("이메일", key="signup_email")
            signup_pw = st.text_input("비밀번호", type="password", key="signup_pw")
            if st.button("회원가입", key="signup_btn"):
                if not signup_nickname.strip():
                    st.error("닉네임을 입력해주세요.")
                else:
                    try:
                        supabase.auth.sign_up({
                            "email": signup_email,
                            "password": signup_pw,
                            "options": {"data": {"nickname": signup_nickname.strip()}},
                        })
                        st.success("가입 완료. 이메일 인증 후 로그인해주세요.")
                    except Exception as e:
                        st.error(f"가입 실패: {e}")
    else:
        _display_name = st.session_state.user.user_metadata.get("nickname") or st.session_state.user.email
        st.write(f"**{_display_name}**님 반갑습니다!")
        if st.button("로그아웃", key="logout_btn"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

        with st.expander("닉네임 수정"):
            new_nickname = st.text_input(
                "새 닉네임",
                value=st.session_state.user.user_metadata.get("nickname", ""),
                key="edit_nickname"
            )
            if st.button("변경", key="update_nickname_btn"):
                if not new_nickname.strip():
                    st.error("닉네임을 입력해주세요.")
                else:
                    try:
                        res = supabase.auth.update_user({"data": {"nickname": new_nickname.strip()}})
                        st.session_state.user = res.user
                        st.success("닉네임이 변경됐습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"변경 실패: {e}")

        with st.expander("내 시뮬레이션 기록"):
            try:
                records = (
                    supabase.table("simulation_runs")
                    .select("id, created_at, completion_ratio, avg_speed_kmh, final_soc, final_dist_m, vehicle_cfg")
                    .eq("user_id", st.session_state.user.id)
                    .order("created_at", desc=True)
                    .limit(20)
                    .execute()
                )
                if records.data:
                    for row in records.data:
                        created = (
                            pd.to_datetime(row["created_at"])
                            .tz_convert("Asia/Seoul")
                            .strftime("%y.%m.%d %H:%M")
                        )
                        # 사이드바 폭이 좁아 컬럼으로 나누면 버튼 텍스트가
                        # 세로로 줄바꿈됨(한글 4글자 기준) - 캡션/버튼을
                        # 세로로 쌓아서 전체 폭을 다 쓰도록 함
                        st.caption(
                            f"{created} · 완주율 {row['completion_ratio']*100:.1f}% · "
                            f"평균 {row['avg_speed_kmh']:.1f}km/h · 최저SOC {row['final_soc']*100:.1f}%"
                        )
                        if st.button("이 설정 불러오기", key=f"load_run_{row['id']}", use_container_width=True):
                            if row.get("vehicle_cfg"):
                                st.session_state.cfg = cfg_from_jsonable(row["vehicle_cfg"])
                                st.success("이 기록의 차량 제원 설정을 불러왔어요.")
                            else:
                                st.info("이 기록엔 저장된 차량 제원 설정이 없어요(예전 기록).")
                            st.rerun()
                        st.divider()
                else:
                    st.caption("아직 기록이 없습니다.")
            except Exception as e:
                st.caption(f"기록 조회 실패: {e}")

    st.divider()

    # MPC 파라미터 (읽기 전용, Optuna 최적값 그대로 사용)
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

# 결과 저장 상태 (버튼 클릭으로 인한 rerun에도 결과 화면이 유지되도록 session_state에 보관)
if "last_df" not in st.session_state:
    st.session_state.last_df = None
    st.session_state.last_params = None
    st.session_state.last_reason = None
    st.session_state.last_vehicle_cfg = None
    st.session_state.last_final_pos = None
    st.session_state.last_saved = False

# 실행 버튼 (로그인해야 실행 가능)
if st.session_state.user is None:
    st.info("시뮬레이션을 실행하려면 로그인이 필요합니다.")
if st.button("시뮬레이션 실행", type="primary",
             disabled=st.session_state.sim_running or st.session_state.user is None):
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

    df, reason = run_simulation(params, route_np, env_dict, dist_vals, nearest_map, rad_max, light_dists, light_types, speed_limits_dists, speed_limits_vals, st.session_state.cfg, progress_cb=update_progress)
    eta_text.empty()
    pct_text.empty()
    st.session_state.sim_running = False

    # 계산 완료 -> 실제 도달 지점까지 애니메이션 없이 즉시 반영 (완주 실패 시 그 지점에서 멈춤)
    route_dist_arr = route_np["dist"]
    _final_idx = int(np.searchsorted(route_dist_arr, df["dist"].max()))
    _final_idx = min(_final_idx, len(route_dist_arr) - 1)
    _final_lon = route_np["lon"][:_final_idx + 1:5].tolist() + [float(route_np["lon"][_final_idx])]
    _final_lat = route_np["lat"][:_final_idx + 1:5].tolist() + [float(route_np["lat"][_final_idx])]

    # 결과를 session_state에 보관 후 rerun -> 아래 "결과 표시" 블록이 그 결과를 그리고,
    # 이후 CSV/서버 저장 버튼 클릭으로 다시 rerun이 일어나도 결과 화면이 사라지지 않음
    st.session_state.last_df = df
    st.session_state.last_params = params
    st.session_state.last_reason = reason
    st.session_state.last_vehicle_cfg = cfg_to_jsonable(st.session_state.cfg)
    st.session_state.last_final_pos = (_final_lon, _final_lat)
    st.session_state.last_saved = False
    st.rerun()

if st.session_state.last_df is not None:
    df = st.session_state.last_df
    params = st.session_state.last_params
    reason = st.session_state.last_reason
    _final_lon, _final_lat = st.session_state.last_final_pos

    st.subheader("경로 진행 상황")
    anim_placeholder = st.empty()
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

    # 결과 분석 (규칙 기반 - 종료 사유별 분기)
    st.subheader("결과 분석")
    if reason == "완주":
        soc_margin = df["soc"].min() - simpara.soc_hard_stop
        if soc_margin < 0.05:
            st.warning(
                f"완주는 했지만 최저 SOC({df['soc'].min()*100:.1f}%)가 하한"
                f"({simpara.soc_hard_stop*100:.0f}%)에 근접했습니다. 여유가 적은 편이라, "
                f"날씨가 조금만 나빴어도 실패했을 수 있습니다."
            )
        else:
            st.success(f"여유 있게 완주했습니다 (최저 SOC {df['soc'].min()*100:.1f}%).")
    elif "SOC" in reason:
        st.error(
            f"완주 실패: {reason}. 배터리 소비가 발전량 대비 과했을 가능성이 큽니다 — "
            f"energy_v/soc_cutoff를 더 보수적으로 조정하거나 전반적으로 속도를 낮춰보세요."
        )
    elif "마감시각" in reason:
        st.error(
            f"완주 실패: {reason}. 전체 진행 페이스가 요구 마감 대비 느렸습니다 — "
            f"margin_total/margin_next_cs 관련 파라미터를 확인해보세요."
        )
    elif "구간 평균속도" in reason:
        st.error(
            f"완주 실패: {reason}. 직전 CS 구간에서 저속 주행 구간이 길었을 수 있습니다."
        )
    elif "제한기간" in reason:
        st.error(f"완주 실패: {reason}. 27일 안에 전체 구간을 주행하지 못했습니다.")
    else:
        st.error(f"완주 실패: {reason}")

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

    for cs_dist in st.session_state.cfg.race.Control_Stop_2025.keys():
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

    col_dl, col_save = st.columns(2)
    with col_dl:
        st.download_button(
            label="CSV 저장",
            data=df.to_csv(index=False),
            file_name="sim_result.csv",
            mime="text/csv"
        )
    with col_save:
        if st.session_state.user is None:
            st.caption("로그인하면 결과를 서버에 저장할 수 있어요.")
        elif st.session_state.last_saved:
            st.success("서버에 저장됨")
        else:
            if st.button("결과 서버에 저장"):
                try:
                    supabase.table("simulation_runs").insert({
                        "user_id":          st.session_state.user.id,
                        "params":           params,
                        "vehicle_cfg":      st.session_state.last_vehicle_cfg,
                        "completion_ratio": float(df["dist"].max() / st.session_state.cfg.race.total_distance),
                        "avg_speed_kmh":    float(df["v"].mean() * 3.6),
                        "final_soc":        float(df["soc"].min()),
                        "final_dist_m":     float(df["dist"].max()),
                    }).execute()
                    st.session_state.last_saved = True
                    st.rerun()
                except Exception as e:
                    st.error(f"저장 실패: {e}")
