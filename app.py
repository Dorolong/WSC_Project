"""
로컬 웹사이트 생성
"""

import os
import sys
import time
import base64
import requests
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
from shared.cfg_serde import cfg_from_jsonable, cfg_to_jsonable

# 오라클 서버 주소. Caddy 리버스 프록시 뒤에 있어서 https + 도메인으로 붙는다.
# (예전에는 http://<IP>:8000 이었는데, 평문이라 Authorization 헤더의
#  Supabase access token이 그대로 노출됐다 - progress/46 참고)
# DuckDNS 도메인이라 오라클 IP가 바뀌어도 이 주소는 그대로다.
WSC_OPTUNA_SERVER_URL = "https://wsc-drive.duckdns.org"

# Supabase 클라이언트: st.session_state에 세션별로 저장(브라우저 세션마다 독립).
# @st.cache_resource로 캐싱하면 서버 프로세스 전체에서 하나의 클라이언트를
# 공유하게 되어, 로그인 시 클라이언트 내부에 저장되는 인증 세션이 다른
# 사용자의 요청에도 그대로 섞여 들어가는(계정 뒤섞임) 위험이 있어 사용 안 함.
if "supabase" not in st.session_state:
    st.session_state.supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
supabase = st.session_state.supabase

if "user" not in st.session_state:
    st.session_state.user = None

# 자동 로그인: 로그인 성공 시 Supabase의 refresh token을 브라우저
# localStorage에 저장해뒀다가(아래 session_storage() 함수), 페이지를 새로
# 열 때마다 그 토큰으로 세션을 복구 시도. Streamlit은 파이썬이 서버에서
# 도는 구조라 브라우저 저장공간을 직접 못 봐서, route_animator와 같은
# 방식의 작은 JS 컴포넌트(components/session_storage/)를 통해서만 가능함.
_session_storage_component = components.declare_component(
    "session_storage",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "session_storage")
)

def session_storage(save_token=None, action=None, key="session_storage_main"):
    return _session_storage_component(save_token=save_token, action=action, key=key, default=None)

if st.session_state.user is None and not st.session_state.get("auto_login_tried"):
    _stored_refresh_token = session_storage(key="session_storage_reader")
    if _stored_refresh_token:
        st.session_state.auto_login_tried = True  # 실패해도 같은 세션에서 반복 재시도 안 함
        try:
            res = supabase.auth.refresh_session(_stored_refresh_token)
            st.session_state.user = res.user
            st.rerun()
        except Exception:
            pass  # 토큰 만료/무효 - 그냥 로그인 화면 유지

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
        "version": "1.2.0",
        "date": "2026-08-05",
        "title": "Optuna 탐색 중단 버튼 추가",
        "details": "- 진행 중인 Optuna 탐색을 Stop 버튼으로 중단하고 완료된 trial 결과를 저장하도록 추가\n"
                    "- 중단 시 현재 trial을 마무리한 뒤 최적값과 결과 JSON을 남기도록 정리",
    },
    {
        "version": "1.1.2",
        "date": "2026-08-05",
        "title": "통합 웹 API 레이트 리밋 추가",
        "details": "- 공개 서버 보호를 위해 API 요청과 실행 생성 요청에 레이트 리밋 적용\n"
                    "- 정상 폴링은 막히지 않도록 여유를 두고, 운영 중 문제 발생 시 환경변수로 즉시 끌 수 있게 정리",
    },
    {
        "version": "1.1.1",
        "date": "2026-08-05",
        "title": "통합 웹 회원가입 모달 추가",
        "details": "- 통합 웹 로그인 화면에서 바로 회원가입할 수 있는 모달 추가\n"
                    "- 가입 시 이름을 계정 닉네임으로 저장해서 대기열과 기록에 표시되도록 정리",
    },
    {
        "version": "1.1.0",
        "date": "2026-08-05",
        "title": "HTTPS 전환 — 이제 주소가 wsc-drive.duckdns.org 입니다",
        "details": "- 통합 웹이 https://wsc-drive.duckdns.org 로 옮겨졌습니다. 자물쇠 표시를 확인하세요\n"
                    "- 예전 주소(IP + 8000 포트)는 접속이 막혔습니다. 즐겨찾기를 새 주소로 바꿔주세요\n"
                    "- 로그인 정보가 암호화되지 않은 채 오가던 문제를 해결했습니다\n"
                    "- 페이지를 오래 열어두면 진행률 표시가 멈추던 문제 수정\n"
                    "- '내 기록'에서 Optuna 탐색 결과가 안 뜨던 문제 수정",
    },
    {
        "version": "1.0.9",
        "date": "2026-08-05",
        "title": "비로그인 화면 정리",
        "details": "- 로그인 전에는 본문 로그인 화면만 표시되도록 정리\n"
                    "- Optuna 웹 런처 HTML 전환 Phase 1과 화면 흐름을 맞춤",
    },
    {
        "version": "1.0.8",
        "date": "2026-08-03",
        "title": "차량 제원 설정에 '시뮬레이션 설정' 탭 추가",
        "details": "- 신호등/보행자 신호 평균 대기시간, 최소 SOC 보장값 등을 설정 화면에서 직접 조정 가능\n"
                    "- (버그 수정) 이 값들이 세션별로 분리가 안 돼있어서 한 사용자가 바꾸면 다른 모든 "
                    "사용자에게도 반영되던 문제를 같이 고침 (예전 차량 제원 버그와 같은 종류)",
    },
    {
        "version": "1.0.7",
        "date": "2026-08-03",
        "title": "Optuna 탐색 서버 연동",
        "details": "- 사이드바에 Optuna 탐색 서버(오라클) 바로가기 버튼 추가 - 같은 계정으로 로그인해서 "
                    "MPC 파라미터 탐색(여러 trial)을 서버에서 돌릴 수 있음\n"
                    "- '내 Optuna 탐색 결과'에서 그동안 돌린 탐색들의 진행 상황·최적값을 확인하고, "
                    "'이 파라미터로 시뮬레이션하기'로 바로 적용 가능",
    },
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

# 원본 코드 보기: GitHub raw 주소에서 그때그때 파일을 그대로 받아와서 보여줌
# (별도 DB/사본 없이 매번 GitHub 현재 상태를 직접 조회하는 방식이라, push하면
# 바로 반영됨 - "실시간"을 별도 동기화 장치 없이 만족). st.cache_data(ttl=30)은
# 다이얼로그 안에서 파일 버튼 몇 번 눌러볼 때마다 매번 GitHub에 새로 요청하지
# 않게 하는 용도일 뿐, 30초 지나면 다음 클릭에서 자동으로 다시 최신을 받아옴.
GITHUB_REPO = "Dorolong/WSC_Project"
GITHUB_BRANCH = "main"
CODE_VIEWER_FILES = [
    ("app.py", "Streamlit 메인 앱"),
    ("Configs/Vehicle_Params.py", "차량 제원·시뮬레이션 파라미터"),
    ("Functions/Vehicle_Function.py", "차량 물리 계산·시뮬레이션 엔진"),
    ("mpc/mpc_controller.py", "MPC 속도 플래너"),
    ("Environment/Open_Meteo_API.py", "기상 데이터 수집"),
    ("scripts/main.py", "Optuna 파라미터 최적화"),
    ("server/main.py", "Optuna 웹 런처 - 백엔드"),
    ("server/study_runner.py", "Optuna 웹 런처 - 탐색 실행"),
]

@st.cache_data(ttl=30, show_spinner=False)
def fetch_github_file(path):
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text

if "code_viewer_selected" not in st.session_state:
    st.session_state.code_viewer_selected = None

@st.dialog("원본 코드", width="large")
def code_viewer_dialog():
    st.caption(f"GitHub `{GITHUB_BRANCH}` 브랜치의 지금 코드를 그대로 보여줘요 (읽기 전용).")
    for path, desc in CODE_VIEWER_FILES:
        if st.button(f"📄 {path}", key=f"codeview_{path}", use_container_width=True, help=desc):
            st.session_state.code_viewer_selected = path

    if st.session_state.code_viewer_selected:
        st.divider()
        selected = st.session_state.code_viewer_selected
        st.markdown(f"**`{selected}`**")
        try:
            content = fetch_github_file(selected)
            st.code(content, language="python", line_numbers=True, height=420)
        except Exception as e:
            st.error(f"불러오기 실패: {e}")

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


def render_login_gate():
    st.info("시뮬레이션을 실행하려면 로그인해주세요.")
    gate_login, gate_signup = st.tabs(["로그인", "회원가입"])

    with gate_login:
        login_email = st.text_input("이메일", key="gate_login_email")
        login_pw = st.text_input("비밀번호", type="password", key="gate_login_pw")
        if st.button("로그인", key="gate_login_btn", type="primary", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": login_email, "password": login_pw})
                st.session_state.user = res.user
                session_storage(save_token=res.session.refresh_token, key="session_storage_writer")
                st.rerun()
            except Exception as e:
                st.error(f"로그인 실패: {e}")

    with gate_signup:
        signup_nickname = st.text_input("닉네임", key="gate_signup_nickname")
        signup_email = st.text_input("이메일", key="gate_signup_email")
        signup_pw = st.text_input("비밀번호", type="password", key="gate_signup_pw")
        if st.button("회원가입", key="gate_signup_btn", use_container_width=True):
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
    physics, solar, cell, pack, power, drive, race, simpara = (
        cfg.physics, cfg.solar, cfg.cell, cfg.pack, cfg.power, cfg.drive, cfg.race, cfg.simpara
    )

    tab_physics, tab_solar, tab_cell, tab_pack, tab_power, tab_drive, tab_race, tab_sim, tab_ocv = st.tabs(
        ["물리 제원", "태양광 패널", "배터리 셀", "배터리 팩", "전력 시스템", "구동계", "레이스 설정", "시뮬레이션 설정", "OCV 테이블"]
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

    with tab_sim:
        st.caption("신호등·보행자 신호에 걸렸을 때 지연 시간, 그리고 시뮬레이션 안전 마진값들이에요.")
        traffic_delay    = st.number_input("신호등 평균 대기시간 [s]",   value=float(simpara.avg_traffic_light_delay))
        pedestrian_delay = st.number_input("보행자 신호 평균 대기시간 [s]", value=float(simpara.avg_pedestrian_light_delay))
        soc_hard_stop    = st.number_input("최소 SOC 보장값",           value=simpara.soc_hard_stop,
                                            help="배터리 SOC가 이 값 밑으로 떨어지면 안전상 주행을 멈춰요.")
        max_v_delta      = st.number_input("매 스텝 최대 속도 변화량 [m/s]", value=float(simpara.max_v_delta))
        decel_brake      = st.number_input("Control Stop 진입 감속도 [g]", value=simpara.decel_brake)

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

        simpara.avg_traffic_light_delay    = int(traffic_delay)
        simpara.avg_pedestrian_light_delay = int(pedestrian_delay)
        simpara.soc_hard_stop              = soc_hard_stop
        simpara.max_v_delta                = int(max_v_delta)
        simpara.decel_brake                = decel_brake

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

# 페이지 제목 + 버전/릴리즈노트 (Streamlit 기본 Stop 컨트롤이 뜨는 우측 상단 근처)
# 참고: 이 위치가 Streamlit 앱 콘텐츠 영역에서 사용 가능한 가장 위쪽 자리.
# 화면 우측 상단의 Share/GitHub/Manage app 등은 Streamlit Cloud가 앱
# iframe 바깥에 그리는 플랫폼 UI라서, 앱 코드(Python)로는 그 툴바 안에
# 버튼을 끼워넣거나 위치를 옮길 수 없음.
title_col, version_col = st.columns([6, 1.4])
with title_col:
    st.title("2027 WSC Drive Simulator")
with version_col:
    st.write("")
    st.write("")
    # 캡션+버튼을 컬럼으로 나눠 붙이려던 방식은 컬럼 폭이 좁아지면 버튼
    # 텍스트가 줄바꿈되는 문제가 있어서, 버전과 "Release note"를 아예
    # 버튼 하나의 라벨로 합쳐 한 줄로 안정적으로 표시되게 함.
    if st.button(f"v{APP_VERSION} (Release note)"):
        release_notes_dialog()

if st.session_state.user is None:
    render_login_gate()
    st.stop()

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
                    session_storage(save_token=res.session.refresh_token, key="session_storage_writer")
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
            session_storage(action="clear", key="session_storage_writer")
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

        st.link_button("🏎️ Optuna 탐색 서버로 이동", WSC_OPTUNA_SERVER_URL, use_container_width=True)
        st.caption("같은 계정으로 로그인해서 MPC 파라미터 탐색(여러 trial)을 서버에서 돌려볼 수 있어요.")
        if st.button("💻 코드 보기", use_container_width=True):
            code_viewer_dialog()

        with st.expander("내 Optuna 탐색 결과"):
            try:
                optuna_records = (
                    supabase.table("optuna_runs")
                    .select("study_name, updated_at, n_trials_completed, n_trials_target, best_value, status, best_params")
                    .eq("user_id", st.session_state.user.id)
                    .order("updated_at", desc=True)
                    .limit(20)
                    .execute()
                )
                if optuna_records.data:
                    for row in optuna_records.data:
                        updated = (
                            pd.to_datetime(row["updated_at"])
                            .tz_convert("Asia/Seoul")
                            .strftime("%y.%m.%d %H:%M")
                        )
                        status_label = {
                            "running": "진행 중",
                            "stopping": "중단 중",
                            "stopped": "중단됨",
                            "done": "완료",
                            "error": "오류",
                            "interrupted": "중단됨(서버 재시작)",
                            "lost": "상태 유실",
                        }.get(row["status"], row["status"])
                        best_val_str = f"{row['best_value']:.2f}" if row.get("best_value") is not None else "-"
                        st.caption(
                            f"{updated} · {status_label} · Trial {row['n_trials_completed']}/{row['n_trials_target']} · "
                            f"Best {best_val_str}"
                        )
                        if row.get("best_params"):
                            if st.button("이 파라미터로 시뮬레이션하기", key=f"load_optuna_{row['study_name']}", use_container_width=True):
                                st.session_state.active_best_params = {**mpc_default_params, **row["best_params"]}
                                st.success("이 탐색 결과의 파라미터를 적용했어요. 아래 'MPC 파라미터'에서 확인하세요.")
                                st.rerun()
                        st.divider()
                else:
                    st.caption("아직 Optuna 탐색 결과가 없습니다.")
            except Exception as e:
                st.caption(f"탐색 결과 조회 실패: {e}")

    st.divider()

    # MPC 파라미터 (읽기 전용) - 기본값은 레포에 커밋된 로컬 탐색 결과,
    # 사이드바에서 "이 파라미터로 시뮬레이션하기"를 누르면 그 사용자의
    # Optuna 탐색 결과로 세션 동안 바뀜(active_best_params).
    active_params = st.session_state.get("active_best_params", best_params)
    header_suffix = " (내 Optuna 탐색 결과 적용됨)" if "active_best_params" in st.session_state else " (기본값)"
    st.header(f"MPC 파라미터{header_suffix}")
    st.dataframe(
        pd.DataFrame(active_params.items(), columns=["파라미터", "값"]),
        hide_index=True,
        use_container_width=True
    )
    if "active_best_params" in st.session_state:
        if st.button("기본값으로 되돌리기"):
            del st.session_state.active_best_params
            st.rerun()

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

# 실행 버튼 + 차량 제원 설정 버튼 (로그인해야 실행 가능)
# 컬럼으로 나란히 배치하면 컬럼 간 최소 여백 때문에 버튼끼리 못 붙어서,
# 세로로 쌓는 방식으로 변경 (시뮬레이션 실행이 원래 있던 자리 그대로,
# 차량 제원 설정을 바로 아래에 붙임)
if st.session_state.user is None:
    st.info("시뮬레이션을 실행하려면 로그인이 필요합니다.")
if st.button("시뮬레이션 실행", type="primary",
             disabled=st.session_state.sim_running or st.session_state.user is None):
    st.session_state.sim_running = True
    st.rerun()
if st.button("차량 제원 설정", disabled=st.session_state.sim_running):
    vehicle_settings_dialog()

if st.session_state.sim_running:
    params = {**st.session_state.get("active_best_params", best_params)}

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
        soc_margin = df["soc"].min() - st.session_state.cfg.simpara.soc_hard_stop
        if soc_margin < 0.05:
            st.warning(
                f"완주는 했지만 최저 SOC({df['soc'].min()*100:.1f}%)가 하한"
                f"({st.session_state.cfg.simpara.soc_hard_stop*100:.0f}%)에 근접했습니다. 여유가 적은 편이라, "
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
