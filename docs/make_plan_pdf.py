"""WSC_DriveEff_Project 총괄 기획안 PDF 생성 스크립트.

내용을 수정한 뒤 다시 실행하면 docs/WSC_DriveEff_총괄기획안.pdf가 갱신됩니다.

    pip install reportlab      # 앱 배포에는 불필요해서 requirements.txt에는 안 넣음
    python docs/make_plan_pdf.py

한글 폰트는 Windows 기본 맑은 고딕을 사용합니다. 다른 OS에서 돌릴 때는
아래 registerFont 경로만 바꾸면 됩니다.
"""
import os
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, PageBreak, KeepTogether)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WSC_DriveEff_총괄기획안.pdf")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBd", r"C:\Windows\Fonts\malgunbd.ttf"))
pdfmetrics.registerFontFamily("Malgun", normal="Malgun", bold="MalgunBd")

NAVY = colors.HexColor("#1B3A5C")
ACCENT = colors.HexColor("#C25E00")
GREY = colors.HexColor("#5A6472")
LIGHT = colors.HexColor("#EEF2F6")
LINE = colors.HexColor("#C8D2DC")

ss = getSampleStyleSheet()
S = {}
S["title"] = ParagraphStyle("title", fontName="MalgunBd", fontSize=26, leading=34,
                            textColor=NAVY, alignment=TA_CENTER, spaceAfter=6)
S["subtitle"] = ParagraphStyle("subtitle", fontName="Malgun", fontSize=12.5, leading=19,
                               textColor=GREY, alignment=TA_CENTER)
S["h1"] = ParagraphStyle("h1", fontName="MalgunBd", fontSize=16, leading=22, textColor=colors.white,
                         backColor=NAVY, borderPadding=(7, 8, 7, 8), spaceBefore=20, spaceAfter=10, keepWithNext=1)
S["h2"] = ParagraphStyle("h2", fontName="MalgunBd", fontSize=12.5, leading=17, textColor=NAVY,
                         spaceBefore=13, spaceAfter=5, keepWithNext=1)
S["h3"] = ParagraphStyle("h3", fontName="MalgunBd", fontSize=10.8, leading=15, textColor=ACCENT,
                         spaceBefore=9, spaceAfter=3, keepWithNext=1)
S["body"] = ParagraphStyle("body", fontName="Malgun", fontSize=9.6, leading=15.4,
                           alignment=TA_JUSTIFY, spaceAfter=5)
S["bullet"] = ParagraphStyle("bullet", parent=S["body"], leftIndent=11, bulletIndent=2, spaceAfter=3)
S["sub"] = ParagraphStyle("sub", parent=S["body"], leftIndent=22, bulletIndent=13,
                          fontSize=9.1, leading=14, spaceAfter=2)
S["cell"] = ParagraphStyle("cell", fontName="Malgun", fontSize=8.5, leading=12.2)
S["cellb"] = ParagraphStyle("cellb", fontName="MalgunBd", fontSize=8.5, leading=12.2)
S["cellh"] = ParagraphStyle("cellh", fontName="MalgunBd", fontSize=8.6, leading=12.2,
                            textColor=colors.white)
S["code"] = ParagraphStyle("code", fontName="Courier", fontSize=8.2, leading=12,
                           backColor=LIGHT, borderPadding=(6, 7, 6, 7), spaceAfter=6)
S["note"] = ParagraphStyle("note", parent=S["body"], fontSize=9.0, leading=14,
                           textColor=GREY, leftIndent=9, borderPadding=(5, 7, 5, 7),
                           backColor=colors.HexColor("#FBF4EC"))
S["caption"] = ParagraphStyle("caption", fontName="Malgun", fontSize=8.3, leading=12,
                              textColor=GREY, spaceBefore=2, spaceAfter=9)

F = []
def h1(t): F.append(Paragraph(t, S["h1"]))
def h2(t): F.append(Paragraph(t, S["h2"]))
def h3(t): F.append(Paragraph(t, S["h3"]))
def p(t): F.append(Paragraph(t, S["body"]))
def b(t): F.append(Paragraph(t, S["bullet"], bulletText="•"))
def sb(t): F.append(Paragraph(t, S["sub"], bulletText="–"))
def note(t): F.append(Paragraph(t, S["note"]))
def code(t): F.append(Paragraph(t.replace(" ", "&nbsp;").replace("\n", "<br/>"), S["code"]))
def cap(t): F.append(Paragraph(t, S["caption"]))
def sp(h=5): F.append(Spacer(1, h))

def table(header, rows, widths, align_left_cols=(0,)):
    data = [[Paragraph(c, S["cellh"]) for c in header]]
    for r in rows:
        data.append([Paragraph(str(c), S["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("GRID", (0, 0), (-1, -1), 0.4, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 4),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LEFTPADDING", (0, 0), (-1, -1), 5),
          ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT])]
    t.setStyle(TableStyle(st))
    F.append(t)
    F.append(Spacer(1, 7))

# ============================== 표지 ==============================
F.append(Spacer(1, 52 * mm))
F.append(Paragraph("WSC 주행효율 예측 MPC 시뮬레이터", S["title"]))
F.append(Paragraph("총괄 기획안", S["title"]))
sp(8)
F.append(Paragraph("Bridgestone World Solar Challenge 2027 출전 대비<br/>"
                   "태양광 자동차 구간별 최적 주행속도 예측 시스템", S["subtitle"]))
F.append(Spacer(1, 22 * mm))
cover = Table([
    [Paragraph("프로젝트명", S["cellb"]), Paragraph("WSC_DriveEff_Project", S["cell"])],
    [Paragraph("저장소", S["cellb"]), Paragraph("github.com/Dorolong/WSC_Project (Public)", S["cell"])],
    [Paragraph("배포 앱 버전", S["cellb"]), Paragraph("v1.0.8 (Streamlit Cloud)", S["cell"])],
    [Paragraph("문서 기준일", S["cellb"]), Paragraph("2026-08-05", S["cell"])],
    [Paragraph("대상 경로", S["cellb"]), Paragraph("Darwin → Adelaide, 3,038.3 km", S["cell"])],
    [Paragraph("문서 성격", S["cellb"]), Paragraph("설계·구현·운영 전반 총괄 기획안", S["cell"])],
], colWidths=[38 * mm, 92 * mm], hAlign="CENTER")
cover.setStyle(TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
    ("BACKGROUND", (0, 0), (0, -1), LIGHT),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
]))
F.append(cover)
F.append(PageBreak())

# ============================== 0. 요약 ==============================
h1("0. 문서 요약 (Executive Summary)")
p("본 프로젝트는 태양광 자동차가 3,038km의 호주 종단 경로를 <b>27일 제한시간과 9개 컨트롤스탑(CS) "
  "마감시각, 구간 평균속도 60km/h 하한, 법정 속도제한</b>이라는 실제 대회 규칙 아래에서 완주할 수 있도록, "
  "매 지점의 SOC·일사량·경사·풍향·에너지 예산을 종합해 <b>구간별 권장 주행속도</b>를 산출하는 "
  "예측·제어 시뮬레이터다. 액추에이터를 직접 제어하지 않고 드라이버에게 권장속도를 제시하는 "
  "어드바이저리(advisory) 시스템이다.")
p("현재 규칙 기반(Rule-based) MPC와 Optuna 파라미터 최적화, 웹 시뮬레이터, 팀 공용 탐색 서버까지 "
  "동작하는 상태이며, 다음 단계는 코스팅·제동 등 물리 building block을 완성한 뒤 "
  "규칙 항들을 명시적 비용함수 기반 MPC로 재구성하는 것이다.")

h2("핵심 성과 요약")
table(["구분", "내용"], [
    ["제어 로직", "SOC·경사·일사량·에너지예산·풍향 5개 보정항 + 시간예산 블렌딩(LV1~LV8), 전 항목 연속(ramp) 방식"],
    ["최적화", "Optuna TPE로 12개 파라미터 탐색. 고정 5개 날씨 시나리오 평균(common random numbers)으로 로버스트 평가"],
    ["웹 서비스", "Streamlit Cloud 시뮬레이터 + Supabase 인증/기록 + 오라클 서버 Optuna 런처(팀 공용)"],
    ["성능 개선", "프로파일링 기반 병목 제거로 탐색 1회 214초 → 51초 (4.2배)"],
    ["검증", "리팩터링 전후 A/B 비교로 도달거리 차이 0.1% 확인, 멀티유저 격리 버그 2건 발견·수정"],
], [30 * mm, 132 * mm])

h2("문서 구성")
table(["장", "내용"], [
    ["1장", "프로젝트 개요 — 배경, 목표, 산출물, 대회 규칙 제약"],
    ["2장", "문제 정의 — 최적화 문제로서의 정식화"],
    ["3장", "시스템 아키텍처 — 2앱 구조, 계층, 설계 원칙"],
    ["4장", "물리 모델 — 주행저항·발전·배터리·모터"],
    ["5장", "MPC 제어 로직 — LV1~LV8 상세와 현재 한계"],
    ["6장", "파라미터 최적화 — 목적함수, 탐색공간, 로버스트 설계"],
    ["7장", "웹 서비스 — Streamlit 앱, Supabase, Optuna 런처"],
    ["8장", "데이터 파이프라인 — 경로·기상·규정 데이터"],
    ["9장", "검증 전략 및 이력"],
    ["10장", "개발 현황 및 로드맵"],
    ["11장", "리스크 및 알려진 이슈"],
    ["12장", "개발 운영 규칙 — 문서 체계, Git 워크플로"],
], [16 * mm, 146 * mm])

# ============================== 1. 개요 ==============================
h1("1. 프로젝트 개요")

h2("1.1 배경")
p("World Solar Challenge(WSC)는 호주 Darwin에서 Adelaide까지 3,038km를 태양광 에너지만으로 종단하는 "
  "대회다. 차량에 탑재할 수 있는 배터리 용량과 태양광 패널 면적이 규정으로 제한되므로, "
  "<b>순간 최고속도보다 에너지 수지를 어떻게 배분하느냐가 완주와 순위를 결정</b>한다.")
p("빠르게 달리면 공기저항이 속도의 제곱(소비전력은 세제곱)으로 증가해 배터리가 조기에 고갈되고, "
  "느리게 달리면 27일 제한시간과 각 컨트롤스탑의 마감시각을 넘겨 실격된다. "
  "즉 이 문제는 <b>에너지 제약과 시간 제약 사이의 최적 균형점을 경로 전 구간에 걸쳐 찾는 문제</b>다.")

h2("1.2 목표")
b("<b>1차 목표</b> — SOC·일사량·경사·풍향·에너지 예산을 입력으로 구간별 권장 최적 속도를 산출하는 "
  "MPC 기반 의사결정 시스템 구축 (액추에이터 직접 제어가 아닌 드라이버 어드바이저리 출력)")
b("<b>2차 목표</b> — 규칙 기반 제어기를 명시적 비용함수와 제약조건을 푸는 실제 MPC로 전환")
b("<b>3차 목표</b> — 발전량·소비전력 AI 예측 모델로 MPC 입력을 고도화하고, 강화학습 기반 전략과 비교")
b("<b>최종 목표</b> — 실차 계측 데이터로 시뮬레이션 파라미터를 교체해 실전 운영 도구로 전환")

h2("1.3 산출물")
table(["산출물", "형태", "상태"], [
    ["시뮬레이션 엔진", "Python 모듈 (run_simulation)", "완료"],
    ["MPC 속도 플래너", "Python 모듈 (mpc_speed)", "완료 (규칙 기반)"],
    ["파라미터 최적화", "Optuna 스크립트 + 웹 런처", "완료 (실기동 검증 전)"],
    ["웹 시뮬레이터", "Streamlit 앱 (공개 배포)", "완료, v1.0.8"],
    ["팀 공용 탐색 서버", "FastAPI + systemd (오라클)", "구현 완료, 검증 전"],
    ["기술 문서", "README / progress / debug_logs", "지속 갱신"],
], [42 * mm, 62 * mm, 42 * mm])

h2("1.4 대회 규칙 제약 (시뮬레이션에 반영된 항목)")
table(["제약", "값 / 규칙", "시뮬레이션 반영 방식"], [
    ["총 제한기간", "27일 (2027-08-23 출발 기준)", "일자 초과 시 즉시 실격 처리"],
    ["일일 주행시간", "08:00 ~ 17:00", "야간 진입 시 다음날 08:00으로 시간 점프"],
    ["컨트롤스탑", "9개소, 각 오픈/마감 시각 지정", "마감 초과 시 실격, 정차시간 SOC 연동 30~60분"],
    ["구간 평균속도", "직전 CS~현재 CS 60 km/h 이상", "미달 시 실격 처리"],
    ["법정 속도제한", "구간별 계단형 (Route Notes 기준)", "제어 출력 최종 클립"],
    ["신호등/보행자", "실제 위치 데이터 보유", "평균 대기시간 가산 (단위 버그로 현재 미발동)"],
], [30 * mm, 58 * mm, 74 * mm])
cap("컨트롤스탑 위치·시각은 2025년 실제 대회 데이터를 사용하며, 2027년 확정 시 Configs/Vehicle_Params.py의 "
    "RaceConfig만 교체하면 된다.")

# ============================== 2. 문제 정의 ==============================
h1("2. 문제 정의")

h2("2.1 최적화 문제로서의 정식화")
p("경로를 약 20m 간격의 이산 지점 <i>i</i> = 1…N으로 나누고, 각 지점의 주행속도 <i>v<sub>i</sub></i>를 "
  "결정변수로 두면 문제는 다음과 같이 쓸 수 있다.")
code("목적:   maximize   f(v) =  완주 시 평균속도  (미완주 시 도달률 기반 페널티)\n"
     "\n"
     "제약:   SOC(i) >= soc_hard_stop            (배터리 고갈 방지)\n"
     "        T(CS_k) <= CS_close_hour[k]        (각 컨트롤스탑 마감시각)\n"
     "        avg_speed(leg_k) >= 60 km/h        (구간 평균속도 하한)\n"
     "        v_i <= speed_limit(i)              (법정 속도제한)\n"
     "        v_i <= v_max_derated(SOC)          (전압 강하에 따른 모터 상한)\n"
     "        T_total <= 27 days                 (총 제한기간)")

h2("2.2 문제의 난점")
b("<b>강한 상태 의존성</b> — 지금의 속도 결정이 SOC를 바꾸고, 그 SOC가 이후 전 구간의 가용 선택지를 "
  "바꾼다. 각 스텝을 독립적으로 풀 수 없다.")
b("<b>미래 불확실성</b> — 일사량과 풍속은 예보값이며 실제와 다르다. 특정 날씨에만 잘 맞는 해는 "
  "실전에서 위험하다.")
b("<b>비선형·비대칭 페널티</b> — 공기저항은 v², 소비전력은 v³, 배터리 손실은 I²R로 증가한다. "
  "반면 시간 제약 위반은 즉시 실격이라 연속적인 트레이드오프가 아니다.")
b("<b>이산 이벤트 혼재</b> — 컨트롤스탑 정차, 야간 정지, 신호등 대기 같은 이산 이벤트가 "
  "연속적인 주행 물리와 섞여 있다.")

h2("2.3 채택한 접근")
p("전 구간을 한 번에 푸는 대규모 최적화 대신 <b>2단계 구조</b>를 채택했다.")
table(["단계", "역할", "수행 주체"], [
    ["온라인 (매 스텝)", "현재 상태를 관측하고 규칙 기반으로 즉시 권장속도 산출. "
                        "receding horizon 방식으로 매 스텝 재계산",
     "mpc_speed()"],
    ["오프라인 (사전)", "규칙의 가중치·임계값 14개를 전 구간 시뮬레이션 결과로 평가해 "
                       "베이지안 최적화(TPE)로 튜닝", "Optuna"],
], [30 * mm, 92 * mm, 40 * mm])
note("<b>설계 의도</b> — 매 스텝 수치 최적화를 푸는 대신 '잘 튜닝된 규칙'으로 근사한다. "
     "계산량이 실시간 수준으로 작고 동작을 사람이 해석할 수 있다는 장점이 있으나, "
     "제약을 최적화 내부에서 다루지 못하고 사후 클리핑에 의존하는 한계가 있다 (5.4절 참고).")

# ============================== 3. 아키텍처 ==============================
h1("3. 시스템 아키텍처")

h2("3.1 전체 구성")
p("시스템은 <b>공용 계산 엔진</b> 하나를 <b>두 개의 앱</b>이 공유하는 구조다. 두 앱은 같은 Supabase "
  "프로젝트를 백엔드로 사용해 계정과 결과가 이어진다.")
code("[Streamlit Cloud]                       [오라클 클라우드]\n"
     "  app.py                                  server/main.py (FastAPI)\n"
     "  단일 시뮬레이션 1회 실행                 Optuna 탐색 N trial 실행\n"
     "  결과 시각화 / 차량 제원 설정             대기열 / 진행률 / 체크포인트\n"
     "        |                                        |\n"
     "        +--------------+-------------------------+\n"
     "                       |\n"
     "        [공용 계산 엔진]  Configs / Functions / mpc / scripts\n"
     "                       |\n"
     "                  [Supabase]\n"
     "     Auth · simulation_runs · user_settings · optuna_runs")

h2("3.2 모듈 계층")
table(["계층", "파일", "역할"], [
    ["설정", "Configs/Vehicle_Params.py",
     "차량 제원 dataclass 8종 + build_default_cfg() (세션별 독립 인스턴스 생성)"],
    ["물리 엔진", "Functions/Vehicle_Function.py",
     "주행저항·SOC·발전량 계산, run_simulation() 메인 루프, 헬퍼 6종"],
    ["제어기", "mpc/mpc_controller.py", "mpc_speed() — LV1~LV8 규칙 기반 속도 결정"],
    ["최적화", "scripts/main.py",
     "build_objective() — 탐색 공간 정의(단일 소스), run_cli()"],
    ["웹 앱", "app.py", "Streamlit UI, 로그인, 결과 저장/조회, 차량 제원 편집"],
    ["탐색 서버", "server/", "FastAPI 런처 + 별도 프로세스 탐색 실행"],
    ["데이터 수집", "Environment/Open_Meteo_API.py", "과거 기상 데이터 수집"],
], [22 * mm, 50 * mm, 90 * mm])

h2("3.3 핵심 설계 원칙")
h3("원칙 1 — 설정은 전역이 아니라 인자로 전달한다")
p("모든 차량 제원과 시뮬레이션 파라미터는 모듈 전역 싱글턴이 아니라 <font face='Courier'>cfg</font> → "
  "<font face='Courier'>const</font> dict로 함수에 전달된다. Streamlit Cloud는 여러 사용자가 "
  "<b>서버 프로세스 하나를 공유</b>하므로, 전역 객체를 수정하면 한 사용자의 설정 변경이 그 순간 "
  "접속 중인 모든 사용자의 시뮬레이션 결과를 바꾼다.")
note("이 버그는 실제로 두 번 발생했다. 1차는 차량 제원 전체(physics/solar/cell/pack/power/drive/race)가 "
     "전역이던 문제로 build_default_cfg() 도입으로 해결했고(progress/28), 2차는 mpc_controller.py가 "
     "simpara만 전역 참조로 남아 사용자의 설정 변경이 조용히 무시되던 문제로 const 전달로 "
     "해결했다(progress/36). <b>run_simulation()/mpc_speed()를 직접 호출하는 코드를 새로 작성할 때는 "
     "최신 시그니처를 반드시 확인해야 한다.</b>")

h3("원칙 2 — 탐색 공간은 한 곳에서만 정의한다")
p("Optuna 탐색 공간은 <font face='Courier'>scripts/main.py</font>의 "
  "<font face='Courier'>build_objective()</font>에만 존재하고, 웹 런처는 이를 import해서 재사용한다. "
  "CLI로 돌리든 웹으로 돌리든 파라미터 범위가 갈라지지 않는다.")

h3("원칙 3 — 원시 데이터 조회와 제어 판단을 분리한다")
p("속도제한·신호등 같은 원시 데이터 조회는 Vehicle_Function.py에서 수행해 "
  "<font face='Courier'>step</font> dict에 실어 보내고, mpc_controller.py는 그 값을 "
  "제어에 반영하기만 한다. 제어기가 데이터 소스를 직접 알지 않게 해 교체 가능성을 확보한다.")

# ============================== 4. 물리 모델 ==============================
h1("4. 물리 모델")

h2("4.1 차량 제원")
table(["항목", "값", "항목", "값"], [
    ["차량 질량", "250 kg", "구름저항계수 Crr", "0.001"],
    ["항력계수 Cd", "0.081 (80km/h 기준)", "전면 투영면적", "1.0 m²"],
    ["구동계 효율", "0.99", "공기밀도", "1.225 kg/m³"],
    ["태양광 패널", "6.0 m², 효율 27%", "회생제동 효율", "0.60"],
    ["배터리 셀", "Molicel P60B 6000mAh", "셀 내부저항", "0.0128 Ω"],
    ["HV 팩", "40S3P, 약 2,592 Wh", "LV 팩", "5S2P, 약 216 Wh"],
    ["모터 정격", "1,800 W / 150 V DC", "정격 토크", "16.2 Nm"],
    ["모터 효율", "0.97 (인버터 0.95)", "휠 반경", "0.275 m"],
    ["이론 최대속도", "약 155 km/h", "주행 중 LV 소비", "50 W"],
], [30 * mm, 50 * mm, 32 * mm, 50 * mm])

h2("4.2 주행 저항")
p("매 스텝 차량에 작용하는 저항력을 합산해 필요 구동력과 소비전력을 계산한다.")
code("F_aero  = 0.5 · ρ · Cd · A_f · v_rel²      (v_rel: 대기 상대속도, 풍향 반영)\n"
     "F_roll  = Crr · m · g · cos(θ)\n"
     "F_slope = m · g · sin(θ)\n"
     "F_acc   = m · a                            (a = (v - v_prev)/dt, 실측 기반 동적 계산)\n"
     "\n"
     "P_drive = (F_aero + F_roll + F_slope + F_acc) · v / (η_drive · η_motor · η_inv)")
b("풍향은 차량 헤딩과의 상대각을 계산해 정면풍 성분만 유효 속도에 반영한다.")
b("가속도 <i>a</i>는 고정 상수가 아니라 직전 스텝 대비 실측값으로 계산한다. "
  "<font face='Courier'>dt = 0</font>인 경로 중복점에서 0으로 나누는 문제가 있어 "
  "<font face='Courier'>dt &gt; 0</font> 가드를 두었다.")
b("경사각 θ는 원본 20m 해상도 slope를 그대로 쓰지 않는다. 고도 데이터 노이즈가 과대증폭되기 때문에 "
  "500m 이동평균으로 스무딩한 뒤 오르막/내리막을 판정한다.")

h2("4.3 발전 모델")
code("P_gen = 일사량[W/m²] · A_solar · η_solar")
p("컨트롤스탑 정차 중에는 패널 각도를 태양에 맞출 수 있으므로 보정계수 "
  "<font face='Courier'>cs_chg_eff = 0.8</font>을 적용한 별도 경로로 충전을 계산한다.")

h2("4.4 배터리 모델")
p("SOC-OCV 룩업 테이블(12점 선형보간)로 개방전압을 구하고, 내부저항에 의한 전압 강하와 "
  "I²R 손실을 반영한다.")
code("V_ocv    = interp(SOC, ocv_soc, ocv_V) · HV_S\n"
     "R_eq     = R_cell · HV_S / HV_P\n"
     "I        = (V_ocv - sqrt(V_ocv² - 4·R_eq·P_batt)) / (2·R_eq)\n"
     "SOC(t+1) = SOC(t) - I·dt / HV_Capa")
note("<font face='Courier'>sqrt</font> 안의 값이 음수가 되면(요구 전력이 배터리 최대 출력을 초과) "
     "NaN이 발생해 이후 계산 전체가 오염된다. 실제로 dt=0 버그가 이 경로를 통해 "
     "시뮬레이션 크래시로 이어진 사례가 있었다.")

h2("4.5 모터 디레이팅")
p("SOC가 낮아지면 단자전압이 떨어져 모터가 낼 수 있는 최대 회전수가 제한된다. "
  "매 스텝 현재 단자전압으로부터 물리적 최대속도를 계산해 제어 출력의 상한으로 사용한다.")
code("ω_max = V_terminal / (K_v · sqrt(6))        (SVPWM 기준)\n"
     "v_max_derated = ω_max · r_wheel · 3.6")

# ============================== 5. MPC ==============================
h1("5. MPC 제어 로직")

h2("5.1 시뮬레이션 1스텝 처리 순서")
code("경로/기상 조회 → lookahead(향후 발전량·경사) → 필요 페이스(전체완주·다음CS)\n"
     "  → 모터 디레이팅 → 법정 속도제한 조회\n"
     "  → mpc_speed(step, params, const)      ← 권장속도 결정\n"
     "  → dt 계산 → 야간 경계 검사 → 컨트롤스탑 정차 처리\n"
     "  → 종료조건 검사(SOC / CS마감 / 구간평균속도 / 27일)\n"
     "  → 주행저항·발전량으로 SOC 갱신")
p("루프 시작부에서 먼저 달력을 확인해 현재 시각이 주행 가능 시간(08:00~17:00)이 아니면 "
  "속도·에너지 계산을 전부 건너뛰고 다음날 08:00으로 점프한다. 또한 이번 스텝의 소요시간이 "
  "당일 17:00까지 남은 시간을 넘으면 그 스텝을 계산하지 않고 시간만 17:00으로 보낸 뒤 "
  "다음 루프에서 야간 리셋한다. 불필요한 계산을 줄이기 위한 선처리다.")

h2("5.2 속도 결정 단계 (LV1~LV8)")
table(["단계", "기준", "조절 방식"], [
    ["LV1", "SOC (soc_ramp_low ~ soc_ramp_high)",
     "v_min ~ v_soc_high 선형보간으로 기저속도 결정"],
    ["LV2", "경사 look-ahead (현재~2km 구간평균) + 직전 가속도",
     "slope_k 비례 감속. 오르막 진입 시 momentum_gain·a 만큼 페널티 완화"],
    ["LV3", "일사량 비율", "radi_para 비례 가감속. radi_risk·표준편차로 불확실성 할인"],
    ["LV4", "에너지 예산 (다중지점 가중평균 발전량 기반)",
     "잔여 구간 필요 SOC 대비 예상 SOC 부족분에 energy_v 비례 감속"],
    ["LV5", "정면풍 성분", "winddir_para 비례, 대칭 클리핑"],
    ["LV8", "시간 예산 (전체완주 페이스 + 다음CS 페이스)",
     "SOC 여유에 비례해 목표 페이스로 3항 가중평균 블렌딩"],
], [16 * mm, 62 * mm, 84 * mm])
p("LV6은 설계 당시 결번이고, 구 LV7(미래 일사량 추세)은 LV4에 병합됐다. 파라미터 이름은 "
  "LV 번호 접두어를 떼고 역할 기반 이름(v_soc_high, slope_k 등)을 쓴다 — 로직 순서가 바뀔 때마다 "
  "번호를 다시 매겨야 하는 문제 때문에 폐기했다.")

h2("5.3 클리핑 순서와 댐퍼")
p("보정이 모두 누적된 뒤 다음 순서로 상하한을 적용한다. <b>순서가 중요하다.</b>")
code("1. v = max(v, v_min)                    누적 보정으로 v가 0 이하가 되는 것 방지\n"
     "2. SOC <= soc_cutoff 이면 v = v_min      하드 안전장치 (계단형)\n"
     "3. LV8 시간예산 블렌딩\n"
     "4. v = min(v, v_max_derated, drive.v_max)  물리적 상한\n"
     "5. v = min(v, speed_limit)              법정 속도제한  ← 반드시 v_min 클램프보다 뒤\n"
     "6. 댐퍼:  v = v_prev + Δmax · tanh(α · (v - v_prev) / Δmax)")
note("5번이 1번보다 앞에 오면, v_min 강제 로직(예: 60km/h)이 그보다 낮은 법정 속도제한"
     "(예: CS 진입 25km/h)을 덮어써서 규정 위반 주행이 된다. 실제로 이 순서 문제를 "
     "검증 과정에서 확인하고 고정했다.")
p("댐퍼는 EMA+tanh 형태로, 빠른 오실레이션은 감쇠시키되 느린 추세는 그대로 따라가고 "
  "한 번의 큰 이상치는 차량의 물리적 가감속 한계에서 포화되도록 설계했다. "
  "이전에는 단순 rate limiting을 썼으나 경계에서 속도가 고착되는 문제가 있었다.")

h2("5.4 현재 모델의 한계 (실제 MPC 정의 대비)")
table(["구분", "항목"], [
    ["없는 것", "명시적 예측 모델 기반 수치 최적화(매 스텝 비용함수를 실제로 풂), "
               "명시적 objective function, 제약조건을 최적화 내부에서 다루는 것 "
               "(현재는 soc_cutoff / v_max / speed_limit 전부 사후 클리핑)"],
    ["있는 것", "receding horizon(매 스텝 상태 재측정 후 재계산), 상태 피드백, "
               "부분적 예측(avg_gen_ratio, slope_ahead)"],
], [22 * mm, 140 * mm])
p("전환 순서는 합의돼 있다. 코스팅·제동·내리막 캡 같은 물리 building block을 규칙 기반으로 먼저 "
  "완성해 물리적 타당성을 검증한 뒤, 같은 항들을 비용함수와 solver로 재구성한다. "
  "오르막 처리는 배터리 I²R 손실(제곱 손실) 기반 비용항으로, LV4의 균등 배분 가정은 "
  "지형 기반 1회성 예산 배분으로 재설계할 예정이다.")

# ============================== 6. 최적화 ==============================
h1("6. 파라미터 최적화")

h2("6.1 목적함수")
code("for each of K=5 fixed weather scenarios:\n"
     "    df, reason = run_simulation(params, ...)\n"
     "    if 완주:      score = 평균속도 [km/h]\n"
     "    else:        score = 도달률 - 2          (범위 [-2, -1])\n"
     "\n"
     "objective = mean(scores)")
p("완주 여부가 1차 기준이고 그 안에서 평균속도를 겨루는 구조다. 미완주 해에 "
  "<font face='Courier'>-2</font> 오프셋을 주어 어떤 완주 해보다도 항상 낮게 만들되, "
  "도달률을 더해 '얼마나 아깝게 실패했는지'의 기울기를 남겨 탐색이 방향을 잡을 수 있게 했다.")

h2("6.2 탐색 공간 (12개 파라미터)")
table(["파라미터", "범위", "의미"], [
    ["v_min", "20 ~ 60 (int)", "속도 하한 [km/h]"],
    ["v_soc_high", "60 ~ 100 (int)", "SOC 충분 시 목표속도 [km/h]"],
    ["soc_ramp_high", "0.5 ~ 1.0", "LV1 램프 상단 SOC 임계값"],
    ["soc_ramp_low", "0.0 ~ 0.5", "LV1 램프 하단 SOC 임계값"],
    ["slope_k", "0 ~ 150 (int)", "경사 보정 계수"],
    ["radi_para", "0 ~ 40 (int)", "일사량 보정 계수"],
    ["radi_risk", "0.0 ~ 1.0", "일사량 불확실성 할인 계수"],
    ["energy_v", "0 ~ 20", "에너지 예산 보정 계수"],
    ["winddir_para", "0 ~ 20 (int)", "풍향 보정 계수"],
    ["margin_total", "0.1 ~ 0.6", "전체 완주 페이스 블렌딩 여유"],
    ["margin_next_cs", "0.1 ~ 0.6", "다음 CS 페이스 블렌딩 여유"],
    ["soc_cutoff", "0.00 ~ 0.20", "하드 세이프티 SOC 하한"],
], [34 * mm, 34 * mm, 94 * mm])
p("<font face='Courier'>momentum_gain</font>과 <font face='Courier'>alpha</font>는 현재 고정값이며, "
  "본 탐색 재실행 시 탐색 공간 포함 여부를 결정한다. 파라미터 이름은 "
  "<b>세 지점(기본값 dict, mpc_speed 본문, suggest 호출부)이 모두 일치</b>해야 하며, "
  "하나라도 다르면 조용히 기본값으로 fallback되므로 주의가 필요하다.")

h2("6.3 로버스트 설계 — 날씨 처리")
h3("고정 시나리오 (Common Random Numbers)")
p("매 trial마다 새 날씨를 뽑으면 '운 좋은 날씨를 만난 trial'이 이겨버려 파라미터의 실력을 "
  "비교할 수 없다. 고정 시드 5개로 미리 만든 동일한 날씨 세트에서 모든 trial을 평가한다.")
h3("CS 구간 단위 상관 섭동")
p("예보값에 표준편차를 곱해 흔들 때, 지점마다 독립적인 난수를 쓰면 바로 옆 지점의 일사량이 "
  "뜬금없이 튀는 비현실적 노이즈가 된다. 실제 날씨는 전선 단위로 뭉쳐 움직이므로, "
  "<b>같은 CS 구간(leg) 안에서는 같은 z값을 공유</b>하도록 바꿨다. 한 leg 안에서는 "
  "'이번엔 대체로 맑은/흐린 구간'처럼 일관되게 흔들리고, leg가 바뀌면 새로 뽑힌다.")

h2("6.4 샘플러 선택")
p("TPE(Tree-structured Parzen Estimator)에 <font face='Courier'>multivariate=True, group=True</font> "
  "옵션을 적용했다. 목적함수가 K개 평균으로 평활화되었더라도, 완주/미완주 경계에서 "
  "목적함수가 불연속적으로 튀는 특성 때문에 CMA-ES보다 TPE가 안정적이라고 판단했다.")

h2("6.5 병렬화 전략")
p("Optuna의 <font face='Courier'>n_jobs</font>는 GIL 때문에 CPU-bound 순수 Python 루프에서 "
  "실효성이 없다. 진짜 병렬을 얻으려면 <b>OS 프로세스를 분리</b>해 같은 storage에 붙여야 하며, "
  "이때 SQLite는 WAL 모드로 열어야 동시 접근이 가능하다. 웹 런처가 이 방식으로 구현되어 있다.")

# ============================== 7. 웹 서비스 ==============================
h1("7. 웹 서비스 아키텍처")

h2("7.1 Streamlit 앱 (app.py)")
table(["기능", "설명"], [
    ["경로 애니메이션", "호주 실루엣 배경 위에 주행 진행을 실시간 표시. 배경/전체경로는 최초 1회만 "
                      "그리고 이후 마커·주행경로만 갱신하는 커스텀 JS 컴포넌트"],
    ["시뮬레이션 실행", "로그인한 사용자만 실행 가능. 진행률 콜백으로 실시간 상태 표시"],
    ["결과 분석", "종료 사유(SOC/CS마감/구간속도/27일/완주)별로 분기한 규칙 기반 진단 메시지"],
    ["차량 제원 설정", "9개 탭(물리·태양광·셀·팩·전력·구동계·레이스·시뮬레이션·OCV)에서 직접 편집. "
                     "세션별로 격리되며 계정에 저장/불러오기 가능"],
    ["기록 관리", "결과를 계정에 저장하고 사이드바에서 조회. 각 기록에서 그때 사용한 차량 제원 복원"],
    ["Optuna 결과 연동", "서버에서 돌린 탐색 결과를 조회하고 '이 파라미터로 시뮬레이션하기'로 즉시 적용"],
    ["부가 기능", "자동 로그인(refresh token), 릴리즈 노트, 첫 로그인 튜토리얼, GitHub 원본 코드 뷰어"],
], [30 * mm, 132 * mm])

h2("7.2 Supabase 스키마")
table(["테이블", "용도", "주요 컬럼"], [
    ["auth.users", "인증 (Supabase 기본)", "user_metadata에 nickname, tutorial_seen 저장"],
    ["simulation_runs", "시뮬레이션 실행 기록", "params, completion_ratio, avg_speed_kmh, "
                                            "final_soc, final_dist_m, vehicle_cfg"],
    ["user_settings", "사용자별 마지막 차량 제원", "user_id(PK), vehicle_cfg(jsonb)"],
    ["optuna_runs", "Optuna 탐색 진행/결과", "study_name(고유), n_trials_completed/target, "
                                        "best_value, best_params, status"],
], [30 * mm, 42 * mm, 90 * mm])
p("모든 테이블에 RLS(Row Level Security)를 적용해 <font face='Courier'>auth.uid() = user_id</font> "
  "조건으로 본인 행만 접근 가능하다. 클라이언트에 노출되는 anon key는 RLS를 전제로 공개해도 되는 "
  "값이며, service_role key는 절대 클라이언트에서 사용하지 않는다.")
note("<b>보완 필요</b> — optuna_runs 테이블의 생성 SQL 원문이 저장소에 남아있지 않아, 현재는 "
     "코드에서 컬럼을 역추적해야 한다. Supabase 재구축 상황에 대비해 SETUP.md에 정리가 필요하다.")

h2("7.3 Optuna 웹 런처 (server/)")
p("Streamlit Cloud 무료 티어로는 수십 분이 걸리는 탐색을 돌릴 수 없고, 돌린다 해도 "
  "서버 프로세스를 공유하는 다른 사용자에게 영향을 준다. 따라서 탐색만 오라클 클라우드의 "
  "별도 서버로 분리했다.")
code("로그인 (Supabase 토큰을 서버가 Supabase에 검증 요청)\n"
     "  → 대기열 등록 (동시 실행 WSC_MAX_CONCURRENT=1, 최대 trial 100)\n"
     "  → subprocess로 study_runner.py 실행\n"
     "  → 매 trial마다 progress.json 갱신 → 진행률·예상 잔여시간 표시\n"
     "  → 20 trial마다 optuna_runs에 체크포인트 upsert\n"
     "  → 완료 시 best_params로 최종 시뮬레이션 1회 + 결과 파일 저장")
h3("설계 판단")
b("<b>왜 subprocess인가</b> — <font face='Courier'>study.optimize()</font>가 블로킹 호출이라 "
  "FastAPI 프로세스 안에서 돌리면 다른 사용자의 요청까지 막힌다. 스레드로는 GIL 때문에 "
  "실제 병렬이 되지 않는다.")
b("<b>왜 자체 사용자 DB를 안 만들었나</b> — 이미 있는 Supabase Auth를 재사용해 계정 체계를 "
  "하나로 유지했다. 서버는 받은 토큰을 Supabase에 물어봐 검증만 한다.")
b("<b>디스크 로테이션</b> — 무료 인스턴스의 작은 디스크가 차면, 지금까지의 best_params를 "
  "<font face='Courier'>enqueue_trial</font>로 이어받은 새 study로 교체해 탐색을 계속한다. "
  "결과는 이미 Supabase 체크포인트에 있어 안전하다.")
b("<b>진행률 파일 분리</b> — study sqlite를 직접 세지 않고 별도 progress.json을 읽는다. "
  "로테이션이 일어나도 경로가 바뀌지 않아 진행률 표시가 끊기지 않는다.")

# ============================== 8. 데이터 ==============================
h1("8. 데이터 파이프라인")

h2("8.1 데이터 소스")
table(["데이터", "출처", "규모 / 형태"], [
    ["경로", "2027 BWSC TRACK.csv", "Darwin~Adelaide 3,038km, 약 20m 간격 GPS + 고도"],
    ["기상", "Open-Meteo 과거 데이터 API", "305좌표 × 8일 × 12시간 = 29,280행"],
    ["속도제한", "공식 Route Notes PDF에서 추출", "구간별 계단형 제한속도"],
    ["신호등", "공식 Route Notes PDF에서 추출", "위치 + 종류(차량/보행자)"],
    ["컨트롤스탑", "2025 대회 실제 데이터", "9개소 위치·오픈/마감 시각"],
], [26 * mm, 56 * mm, 80 * mm])

h2("8.2 전처리")
b("<b>경사 스무딩</b> — 20m 해상도 원본 slope는 고도 노이즈가 과대증폭되므로 500m 이동평균 후 "
  "<font face='Courier'>Crr·cos(θ) + sin(θ)</font> 부호로 오르막/내리막을 판정한다.")
b("<b>기상 격자 매핑</b> — 경로의 각 지점을 가장 가까운 기상 관측 지점에 사전 매핑해 "
  "런타임 조회를 O(1)로 만든다.")
b("<b>메모리 절감</b> — 실제 사용하는 5개 컬럼만 남기고 dict로 변환한다. K=5개 날씨 사본을 "
  "동시에 들고 있어야 해서 1GB 메모리 서버에서는 이 최적화가 필수다.")
b("<b>numpy 변환</b> — 거리 배열을 pandas Index가 아닌 numpy 배열로 유지한다 (9.2절 참고).")

h2("8.3 지형 세그먼트")
p("연속된 내리막 구간의 경계를 <font face='Courier'>np.diff</font>/<font face='Courier'>np.where</font>로 "
  "찾아 [시작거리, 끝거리, 대표경사각] 배열로 변환하는 1회성 전처리가 구현되어 있다. "
  "이 배열은 코스팅 진입 속도 상한 계산에 쓰일 예정이나, <b>이를 소비하는 "
  "compute_downhill_cap()이 아직 구현되지 않아 현재는 계산만 하고 사용되지 않는다.</b>")

# ============================== 9. 검증 ==============================
h1("9. 검증 전략 및 이력")

h2("9.1 검증 원칙")
b("동작을 바꾸지 않아야 하는 리팩터링은 <b>변경 전후 A/B 비교</b>로 결과 동일성을 확인한다.")
b("성능 문제는 추측하지 않고 <b>cProfile로 실측</b>한 뒤 병목을 특정한다.")
b("멀티유저 관련 수정은 <b>격리 테스트</b>(두 설정이 서로 영향을 주지 않으면서 각자 결과에는 "
  "반영되는지)로 검증한다.")
b("코드를 작성한 세션이 실행 환경이 없어 검증하지 못한 경우, 다음 세션이 <b>대신 검증</b>하고 "
  "결과를 문서에 남긴다.")

h2("9.2 주요 검증 사례")
h3("사례 1 — 함수 분리 리팩터링 A/B 검증")
p("200줄이 넘던 run_simulation()을 6개 헬퍼 함수로 분리(약 160줄로 축소)한 뒤, 동일 입력에 대한 "
  "도달거리 차이가 0.1%임을 확인해 동작 보존을 검증했다.")

h3("사례 2 — 성능 병목 특정 (4.2배 개선)")
p("탐색 시간이 갑자기 8분대로 늘어난 원인을 두 가지 가설(크래시 조기종료, 조기 실격)로 추정했으나 "
  "모두 반증됐다. cProfile로 직접 측정한 결과 <font face='Courier'>dist_vals</font>가 numpy 배열이 "
  "아닌 pandas Index여서 lookahead 샘플링 루프가 매번 pandas의 무거운 내부 경로를 타고 있었고, "
  "이것이 전체 실행시간의 74%를 차지했다. <font face='Courier'>.to_numpy()</font> 한 줄로 "
  "214초 → 51초로 개선했고 결과는 동일함을 확인했다.")
note("<b>교훈</b> — 성능 문제는 가설을 세우는 것보다 프로파일러를 먼저 돌리는 것이 빠르다.")

h3("사례 3 — 멀티유저 격리 버그 2건")
p("Streamlit Cloud가 서버 프로세스를 공유한다는 특성 때문에 전역 상태가 사용자 간에 새는 버그가 "
  "두 번 발생했다. 두 경우 모두 '전역을 잠시 바꿨다가 되돌리는' 방식을 검토했으나, "
  "Streamlit이 세션마다 별도 스레드로 실행되고 시뮬레이션이 수십 초~수 분 도는 동안 "
  "바이트코드 수준 인터리빙이 일어날 수 있어 <b>근본적으로 안전하지 않다고 판단</b>하고 "
  "인자 전달 구조로 재설계했다.")

h3("사례 4 — 야간 경계 선처리 검증")
p("루프 순서 변경 후 전 구간 시뮬레이션이 무한루프 없이 정상 종료함을 확인했다. 도달거리는 "
  "2,833,560m → 2,833,500m(-60m, 0.002%)로, partial segment 분할을 아직 하지 않아 17시 직전 "
  "잔여 거리를 보수적으로 버린다는 설계 설명과 일치했다. 경계 조건(등호 포함 비교, "
  "잔여시간 0인 경우)도 검토해 이중 처리와 무한루프가 없음을 확인했다.")

h2("9.3 발견된 주요 버그 이력")
table(["버그", "영향", "상태"], [
    ["야간 데이터 처리 (HR==17에 날짜 미전환)", "도달거리 993km(35%) 차이", "수정"],
    ["dt=0 divide-by-zero → NaN 전파", "시뮬레이션 크래시", "수정 (가드 추가)"],
    ["차량 제원 전역상태 누수", "한 사용자 설정이 전체에 반영", "수정 (cfg 격리)"],
    ["mpc_controller simpara 전역 참조", "사용자 설정이 조용히 무시됨", "수정 (const 전달)"],
    ["dist_vals pandas Index", "실행시간 4.2배", "수정"],
    ["법정 속도제한 클립 순서", "속도제한 무시 가능", "수정 (순서 고정)"],
    ["light_arrive() 단위 불일치 (m vs km)", "신호등 지연 미발동", "미수정 (보류 결정)"],
], [56 * mm, 56 * mm, 50 * mm])

# ============================== 10. 로드맵 ==============================
h1("10. 개발 현황 및 로드맵")

h2("10.1 단계별 현황")
table(["#", "단계", "상태"], [
    ["1", "경로·환경 데이터 수집 / 차량 물리 모델", "완료"],
    ["2", "Rule-based MPC (LV1~LV5 ramp + LV8 페이스 블렌딩)", "완료"],
    ["3", "Streamlit 시뮬레이터 UI", "완료"],
    ["4", "웹 배포 (Streamlit Cloud + Supabase + Optuna 런처)", "완료 (런처 실기동 검증 전)"],
    ["5", "MPC 물리 building block (코스팅/제동/내리막 캡)", "진행 중"],
    ["6", "비용함수 기반 MPC로 전환", "설계 논의 완료"],
    ["7", "AI 예측 모델 (발전량 / 소비전력)", "미착수"],
    ["8", "강화학습 실험", "미착수"],
    ["9", "실측 데이터 교체", "미착수"],
], [10 * mm, 100 * mm, 52 * mm])

h2("10.2 단기 로드맵")
h3("1순위 — Optuna 웹 런처 실제 동작 검증")
p("서버 코드가 인터넷이 없는 환경에서 작성되어 <b>한 번도 실제로 기동해본 적이 없다.</b> "
  "다음을 순서대로 확인해야 한다.")
sb("오라클 서버에서 uvicorn 기동 및 접속 확인 (포트 8000 Security List 개방 필요)")
sb("로그인 → 탐색 시작 → 진행률 표시 → 앱에서 결과 조회 → 파라미터 적용까지 관통 확인")
sb("배포본에서 자동 로그인·코드 뷰어 동작 확인")
sb("문제 없으면 systemd 등록으로 재부팅 자동 기동 구성")

h3("2순위 — MPC 물리 building block 완성")
p("설계는 완료되어 있고 코드만 없는 상태다.")
sb("<b>compute_downhill_cap(step, const)</b> — 내리막 세그먼트 진입 전 목표속도 상한 계산. "
   "a_coast = (F_aero+F_roll+F_slope)/m, v_entry_max = sqrt(v_exit_cap² - 2·a_coast·L)")
sb("<b>CS 접근 코스팅/제동</b> — coast_distance = v²/(2·a_coast)를 트리거로 가속 해제. "
   "내리막 등 a_coast ≤ 0 구간은 decel_brake(0.7g)로 기계 제동. "
   "코스팅 중에는 배터리를 거치지 않고 LV 소비전력만 반영")
sb("완성되면 app.py에도 동일한 세그먼트 전처리 추가 필요 (현재 scripts/main.py에만 존재)")
sb("이후 light_arrive() 단위 버그 수정 → 본격 Optuna 재탐색")

h3("3순위 — 문서/인프라 정리")
sb("optuna_runs 테이블 SQL을 SETUP.md에 정리 (현재 저장소에 원문 없음)")
sb("SETUP.md에 server/ 배포 절차 링크 추가")
sb("서버 보안 검토 (CORS 와일드카드, anon key 하드코딩의 노출 범위)")

h2("10.3 장기 방향")
b("<b>비용함수 MPC 전환</b> — 오르막은 배터리 I²R 손실 기반 비용항으로, 에너지 예산은 "
  "균등 배분 대신 지형 기반 1회성 배분으로 재설계")
b("<b>AI 예측 모델</b> — 발전량·소비전력 예측 모델로 MPC 입력을 고도화")
b("<b>강화학습 비교</b> — 동일 환경에서 RL 정책과 MPC 전략의 성능 비교")
b("<b>실측 데이터 교체</b> — 실차 계측값으로 물리 파라미터를 대체해 실전 운영 도구로 전환")

# ============================== 11. 리스크 ==============================
h1("11. 리스크 및 알려진 이슈")

h2("11.1 기술 리스크")
table(["리스크", "영향", "대응"], [
    ["Optuna 런처 미검증", "실제 배포 시 동작 실패 가능성", "1순위 작업으로 지정, 배포 후 즉시 관통 검증"],
    ["서버 재시작 시 진행 상태 소실", "진행 중이던 탐색 유실", "완료 결과는 파일+Supabase에 남으므로 "
                                                    "치명적이지 않음. 필요 시 상태 영속화"],
    ["오라클 무료 인스턴스 사양", "동시 실행 1개로 제한", "대기열로 처리. 사양 상향 시 설정값만 변경"],
    ["신호등 지연 미발동", "실제보다 낙관적인 시간 추정", "단위 변환 수정 (보류 중)"],
    ["partial segment 미분할", "17시 직전 잔여 거리 손실", "20m 해상도라 영향 미미(0.002%), "
                                                  "필요 시 ds_eff 분할로 정밀화"],
], [40 * mm, 46 * mm, 76 * mm])

h2("11.2 모델 신뢰성 리스크")
b("<b>실측 데이터 부재</b> — 현재 모든 물리 파라미터가 카탈로그 값과 이론식 기반이다. "
  "특히 회생제동 효율(0.6)과 Cd(0.081)는 실측 검증이 필요하다. "
  "회생제동 효율 측정 절차는 코드 주석에 기록되어 있다.")
b("<b>기상 예보 오차</b> — 과거 데이터 기반 시뮬레이션이라 실전 예보 오차는 반영되지 않는다. "
  "K=5 시나리오 평균이 부분적으로 이를 보완한다.")
b("<b>momentum 결합 효과 미검증</b> — LV2의 momentum 항이 실제 SOC를 개선하는지는 "
  "A/B 검증 전이다. 물리적 타당성 검토(회생제동 손실 감안 시 '가속 후 회생'은 오히려 손해)는 완료했다.")

h2("11.3 운영 리스크")
b("<b>다중 세션 병행 작업</b> — 여러 컴퓨터와 여러 AI 에이전트(Claude Code / Codex)가 동시에 "
  "작업하면서 백로그 파일이 두 개로 갈라지거나, 코드만 올라오고 문서가 누락되는 일이 있었다. "
  "→ 12장의 문서 규칙으로 대응")
b("<b>커밋 누락</b> — 구현·테스트를 마치고 push를 잊어 배포에 반영되지 않은 사례가 있었다. "
  "→ '완료 보고 전 커밋·푸시 완료' 규칙 명문화")

# ============================== 12. 운영 규칙 ==============================
h1("12. 개발 운영 규칙")

h2("12.1 기준 문서 체계")
p("여러 컴퓨터와 여러 AI 세션을 오가며 작업하므로 <b>대화 기억은 기준이 될 수 없다.</b> "
  "GitHub 저장소의 문서와 커밋된 코드만이 기준이다.")
table(["문서", "역할"], [
    ["README.md", "전체 요약 — 구조·구동원리·현재 상태·다음 할 일. 항상 여기서 시작"],
    ["progress/NN_주제.txt", "완료된 작업별 상세 기록 (배경/구현/버그/검증/상태)"],
    ["progress/ 최대 번호", "최신 백로그 — 지금 당장 다음에 할 일. 항상 하나만 존재"],
    ["debug_logs/(날짜)_주제.txt", "버그 추적 과정 (문제→원인→해결→상태)"],
    ["SETUP.md", "환경 재현 절차"],
    ["server/README.md", "탐색 서버 배포 가이드"],
    ["CLAUDE.md / AGENTS.md", "AI 에이전트 작업 규칙 (두 파일은 동일 원칙 유지)"],
], [42 * mm, 120 * mm])

h2("12.2 Git 워크플로")
b("컴퓨터 간 인계는 GitHub 저장소로만 한다 (ZIP 압축 방식 폐기).")
b("작업 시작 전 브랜치·작업 트리 상태와 원격 최신 상태를 확인한다.")
b("커밋되지 않은 사용자 변경사항을 임의로 덮어쓰거나 삭제하지 않는다.")
b("<b>기능 구현이 끝나면 커밋·푸시까지 마친 뒤에 완료 보고한다.</b> 사용자 액션을 기다리는 "
  "중간 단계가 있으면 다른 이슈가 끼어들어 push를 잊기 쉬우므로 특히 주의한다.")
b("다른 세션의 미커밋 변경이 남아 있으면, 변경 내용을 직접 조사해 무엇이 바뀌었는지 설명하는 "
  "메시지로 커밋해 항상 최신 상태를 유지한다.")
b("배포는 push 시 Streamlit Cloud가 자동 반영한다. 오라클 서버는 git pull + systemctl restart가 필요하다.")

h2("12.3 코드 작성 주체 구분")
table(["영역", "작성 주체", "비고"], [
    ["Functions/Vehicle_Function.py", "사용자", "의사결정·물리 로직. AI는 공식/시그니처/후크 지점 "
                                             "스펙만 텍스트로 제공"],
    ["mpc/mpc_controller.py", "사용자", "동일. 명시적 요청 시에만 예외적으로 AI가 작성"],
    ["scripts/main.py, app.py, server/", "AI", "인프라·배관 작업 (파라미터 연결, 데이터 로딩, "
                                              "UI, 서버/배포 설정)"],
    ["CSV 데이터, 분석/플로팅 스크립트", "AI", ""],
], [50 * mm, 22 * mm, 90 * mm])
p("이 구분의 목적은 <b>핵심 물리·제어 로직에 대한 이해를 사용자가 직접 유지</b>하는 것이다. "
  "연구 과제이자 포트폴리오인 프로젝트 성격상, 의사결정 로직을 남이 대신 작성하면 의미가 없다.")

h2("12.4 릴리즈 관리")
p("사용자가 체감할 기능을 배포할 때마다 app.py의 RELEASE_NOTES 리스트 맨 앞에 항목을 추가하고 "
  "버전을 올린다(현재 v1.0.8). 앱 안에서 버전과 업데이트 이력을 바로 확인할 수 있다.")

sp(10)
F.append(Paragraph("― 문서 끝 ―", ParagraphStyle("end", parent=S["body"], alignment=TA_CENTER,
                                                textColor=GREY)))

# ============================== 렌더링 ==============================
def deco(canv, doc):
    canv.saveState()
    if doc.page > 1:
        canv.setStrokeColor(LINE); canv.setLineWidth(0.5)
        canv.line(20 * mm, 283 * mm, 190 * mm, 283 * mm)
        canv.setFont("Malgun", 7.6); canv.setFillColor(GREY)
        canv.drawString(20 * mm, 286 * mm, "WSC 주행효율 예측 MPC 시뮬레이터 — 총괄 기획안")
        canv.drawRightString(190 * mm, 286 * mm, "2026-08-05")
        canv.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
        canv.setFont("Malgun", 8.4); canv.setFillColor(NAVY)
        canv.drawCentredString(105 * mm, 10.5 * mm, str(doc.page))
    canv.restoreState()

doc = BaseDocTemplate(OUT, pagesize=A4,
                      leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=24 * mm, bottomMargin=22 * mm,
                      title="WSC 주행효율 예측 MPC 시뮬레이터 총괄 기획안",
                      author="WSC_DriveEff_Project")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="n")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=deco)])
doc.build(F)
print("생성 완료:", OUT, os.path.getsize(OUT), "bytes")
