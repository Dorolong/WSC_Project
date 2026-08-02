# WSC_DriveEff_Project

태양광 자동차(World Solar Challenge 출전 + 연구과제 + 포트폴리오) 주행효율 예측을 위한
MPC(+ 추후 강화학습) 프로젝트.

## 목표
- MPC가 SOC·일사량·경사·풍향·에너지 예산을 바탕으로 **구간별 권장 최적 속도**를 드라이버에게 제시
  (액추에이터를 직접 제어하지 않음 — 어드바이저리 출력)
- 추후 AI 예측 모델(발전량·소비전력)로 MPC 입력 고도화
- 실측 데이터가 없는 현재는 Open-Meteo 과거 기상 데이터 + 차량 물리 모델로 시뮬레이션

## 진행 단계

| # | 단계 | 상태 |
|---|------|------|
| 1 | 경로·환경 데이터 수집 / 차량 물리 모델 | **완료** |
| 2 | Rule-based MPC (LV1~LV5 ramp + LV8 페이스 블렌딩) | **완료** |
| 3 | Streamlit 시뮬레이터 UI | **완료** |
| 4 | AI 예측 모델 (발전량 / 소비전력) — `ai_models/` | 미착수 |
| 5 | MPC → AI 예측값 연동 및 통합 검증 | 미착수 |
| 6 | 강화학습 실험 — `rl/` | 미착수 |
| 7 | 실측 데이터 교체 | 미착수 |

## 현재 상태 (2026-08-02)
- **릴리즈 노트(버전 표시) + 첫 로그인 튜토리얼 팝업**: 앱 제목 옆에
  현재 버전(`v1.0.6`)과 "릴리즈 노트" 버튼 추가 - 클릭 시 버전별
  업데이트 내역을 펼쳐서 확인 가능(`app.py`의 `RELEASE_NOTES` 리스트,
  새 기능 배포 시마다 맨 앞에 항목 추가하고 버전을 올릴 것). 처음
  로그인한 사용자에게 사용법 안내 팝업을 자동 표시하고, 확인하면
  계정(`user_metadata.tutorial_seen`)에 남겨서 다시 안 뜨게 함
  (`progress/32`).
- **차량 제원 설정 계정 저장/불러오기**: 위 세션 격리 버그수정의
  후속 - "새로고침하면 설정이 사라진다"는 피드백에 대응해, `user_settings`
  테이블(사용자당 1행, JSON)에 저장/불러오기 버튼 추가. "내 시뮬레이션
  기록" 각 행에서도 그때 썼던 차량 제원을 불러올 수 있음
  (`simulation_runs.vehicle_cfg`) (`progress/30`).
- **[버그 수정] 차량 제원 설정이 전역 상태로 새서 모든 사용자에게
  반영되던 멀티유저 버그**: "차량 제원 설정" 다이얼로그가
  `Configs.Vehicle_Params`의 전역 싱글턴(physics/solar/cell/pack/
  power/drive/race)을 직접 mutate하고 있어서, Streamlit Cloud처럼
  여러 사용자가 서버 프로세스 하나를 공유하는 환경에서 한 사용자의
  설정 변경이 다른 모든 사용자에게 그대로 반영되는 버그였음. `cfg`
  (`build_default_cfg()`로 세션마다 독립 생성, `st.session_state.cfg`)
  를 `run_simulation()`/`mpc_speed()`에 인자로 넘기는 구조로 변경해
  완전 격리 - `run_simulation()`/`mpc_speed()` 시그니처가 바뀌었으니
  직접 호출하는 코드 작성 시 주의 (`progress/28`).
- **GitHub 레포 생성 + Streamlit Cloud 배포**: 프로젝트를
  [github.com/Dorolong/WSC_Project](https://github.com/Dorolong/WSC_Project)
  (Public)에 올리고 Streamlit Community Cloud에 배포. GitHub Pages
  프론트 + Supabase 백엔드 아키텍처는 무거운 Python 연산이 핵심인 이
  프로젝트엔 안 맞아 기각, Streamlit 단일 배포로 결정 (`progress/24`).
- **Supabase 로그인 + 시뮬레이션 기록 저장/조회**: 회원가입(닉네임
  포함)/로그인/닉네임 수정, 로그인해야 시뮬레이션 실행 가능, 결과를
  "결과 서버에 저장" 버튼으로 명시적 저장, 사이드바에서 최근 기록
  조회. Supabase 클라이언트는 세션별로 격리(멀티유저 인증 세션 섞임
  방지) (`progress/25`).
- **시뮬레이션 종료 사유 추적 + 규칙 기반 결과 분석**: AI API 연동은
  실제 과금(공개 앱이라 방문자가 누를 때마다 앱 소유자 비용 발생)
  문제로 기각하고, 이미 코드에 있던 실격/중단 사유(SOC 하한, CS
  마감초과, 구간평균속도 미달, 27일초과)를 `run_simulation()`이
  `(df, termination_reason)`으로 반환하도록 수정 후 케이스별 분기
  메시지 표시 (`progress/26`).
- **실제 2025 BWSC 속도제한/신호등 데이터 반영**: 공식 루트 규정집
  (Route Notes) PDF에서 추출한 `Configs/speed_limits_2025.csv`(계단형
  속도제한)/`traffic_lights_2025.csv`(신호등 위치)를 `mpc_speed()`에
  연결(법정 속도제한 클립은 v_min 하한보다 반드시 뒤에 위치해야
  함). **알려진 버그**: 신호등 지연은 단위 불일치(미터 vs km)로
  실제로는 미발동, `progress/20`/`31` 참고.
- **Optuna 로버스트 탐색 날씨 섭동을 CS 구간 단위로 상관화**: 포인트별
  독립 노이즈 대신 CS 구간(leg)마다 공유되는 z값으로 흔들어, 공간적으로
  뭉쳐 움직이는 실제 날씨 패턴에 더 가깝게 개선 (`progress/21`).
- **오르막/내리막 지형 세그먼트 전처리** (`read_path()`): 20m 원본
  slope는 고도 데이터 노이즈가 과대증폭돼 500m 이동평균으로 스무딩
  후 판정(`Crr*cos(theta)+sin(theta)` 부호 기반). CS 접근 코스팅/
  제동, 오르막 momentum 로직이 사용할 기반 데이터 - **활용 로직
  자체는 아직 미구현** (`progress/22`, 다음 세션 최우선 작업).
- MPC를 규칙 기반에서 비용함수 기반으로 전환하는 방향 논의 완료
  (물리 building block 먼저 완성 후 전환하기로 합의, `progress/22`).
- 컨트롤스탑 규칙(2025 실전 오픈/마감 시각 + 구간평균속도 60km/h)
  실격로직 완성 및 검증 완료
- 날씨 불확실성 반영: common random numbers(K=5 고정 시드)로 로버스트
  Optuna 탐색 방식 확립
- **MPC 파라미터 이름 전면 개편**: LV 번호 접두어(LV1_V1 등) 폐기,
  역할 기반 이름(v_soc_high, slope_k 등)으로 전환 - 로직 순서가
  바뀔 때마다 번호를 다시 매겨야 하는 문제 해소
- **LV1/LV2/LV5를 계단형에서 연속(ramp) 방식으로 통일**, LV3의
  SOC 게이트 제거, **LV4(에너지 예산)+LV7(미래 추세)을 하나로 병합**
  (다중 지점 거리역수 가중평균 기반). 하드 세이프티(soc_cutoff,
  soc_hard_stop)만 계단형 유지
- **LV2에 경사 look-ahead 추가**(구간평균 방식으로 "얼마나 오래
  이어지는 경사인지"까지 반영), **가속도(momentum) 반영 추가**
  (아래 참고)
- **스텝 변화량 제한을 EMA+tanh 댐퍼로 전환**(빠른 오실레이션은
  감쇠, 느린 추세는 그대로 따라가되 단일 이상치는 물리적 상한에서
  포화)
- **mpc_speed(step, params) 구조로 리팩터링**: 개별 인자 14개 ->
  dict 2개로 통합, 반복되던 인자 순서 불일치 버그 해소
- **야간 데이터 처리 버그 수정**(중대): 특정 시각(HR==17)에 날짜
  전환이 안 되던 버그, A/B 테스트로 993km(35%) 도달거리 차이 확인
  후 수정
- **run_simulation() 함수 분리 완료 (6/6)**: 200줄 넘던 함수를
  compute_lookahead/compute_required_pace/compute_motor_derating/
  calender_handler/control_stop_handler/compute_vehicle_energy
  6개 헬퍼로 분리(약 160줄로 축소)
- **가속도(a) 동적 계산 + LV2 momentum 결합**: 기존 고정 상수였던
  가속도를 cal_drive_res()에서 매 스텝 실측 기반으로 계산, LV2가
  오르막 진입 시 직전 가속도(momentum)를 반영해 페널티를 완화하도록
  결합(회생제동 손실을 고려한 물리적 타당성 검토 완료, 실제 SOC
  개선 효과는 A/B 검증 전)
- **성능 버그 수정(4.2배 개선)**: `scripts/main.py`의 `dist_vals`가
  numpy 배열이 아니라 pandas Index라, `compute_lookahead()`의
  N-포인트 샘플링 루프가 매 조회마다 pandas의 무거운 내부 경로를
  타고 있었음(cProfile로 확인, 전체 실행시간의 74% 차지). `.to_numpy()`
  한 줄로 214초 -> 51초로 개선, 결과는 동일함을 검증
- 다음 Optuna 탐색은 아직 미실행 (리팩터링 전후 A/B 검증 완료,
  트라이얼 병렬화 설정은 탐색 직전으로 계속 보류, 현재
  `scripts/main.py`가 임시 스모크테스트 설정(`n_trials=2`, 테스트용
  study_name/storage)으로 남아있어 본 탐색 전 원복 필요)
- 자세한 진행 내역은 `progress/`(주제별 정리, 특히 `progress/33`이
  다음 할 일 목록), `debug_logs/`(디버깅 과정) 참고

## 폴더 구조
```
Configs/            차량 제원·시뮬레이션 파라미터 (dataclass)
  Vehicle_Params.py   VehiclePhysics, SolarPanel, BatteryCell,
                      BatteryPack, PowerSystem, Drivesystem,
                      RaceConfig(CS 오픈시간/구간속도 포함), SimulationParameter
Functions/          차량 물리 계산·시뮬레이션 엔진
  Vehicle_Function.py  주행저항·SOC·발전량 계산, run_simulation()
mpc/                MPC 속도 플래너 (Rule-based, LV1~LV8)
  mpc_controller.py
Environment/        기상 데이터 수집 (Open-Meteo API)
  Open_Meteo_API.py
scripts/            CLI 실행 스크립트
  main.py             Optuna 파라미터 최적화
components/         Streamlit 커스텀 컴포넌트
  route_animator/     경로 진행 애니메이션 (순수 HTML/JS, 빌드 불필요)
assets/             정적 자산
  australia_silhouette.png  지도 배경용 호주 실루엣 (Natural Earth 데이터)
outputs/            시뮬레이션 결과물 + Optuna DB 아카이브
  env_data.csv        305좌표 × 8일 × 12시간 = 29,280행
  optuna_study.db      Optuna study DB (재탐색 전이라 현재 없음, 최초
                        실행 시 자동 생성됨)
  trial_N_YYMMDD/      이전 라운드 DB 아카이브 (조건 기록 read.txt 포함)
progress/           오늘까지 진행상황 주제별 정리
debug_logs/         버그 추적·디버깅 과정 기록 ((YYYY-MM-DD)_주제.txt)
app.py              Streamlit 웹 시뮬레이터
2027 BWSC TRACK.csv 전체 경로 GPS 데이터 (Darwin~Adelaide, 3,038km)
SETUP.md            다른 컴퓨터로 옮길 때 환경 재현 방법
```

## 실행 방법
자세한 환경 구성(venv, Python 버전, 옮길 때 같이 필요한 파일)은
`SETUP.md` 참고. 요약:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt

# 웹 시뮬레이터 (권장)
.\.venv\Scripts\python.exe -m streamlit run app.py

# CLI 실행 (Optuna 최적화)
.\.venv\Scripts\python.exe scripts\main.py
```

## MPC 속도 결정 로직
| 단계 | 기준 | 조절 방식 |
|------|------|----------|
| LV1 | SOC (soc_ramp_low~soc_ramp_high 구간) | v_min ~ v_soc_high 선형보간(ramp) |
| LV2 | 경사도 look-ahead (현재~2km 앞 구간평균) + 직전 가속도(momentum) | slope_k 비례 감가속(ramp), 오르막 진입 시 momentum_gain*a로 페널티 완화 |
| LV3 | 일사량 비율 (게이트 없이 항상 적용) | radi_para 비례, radi_risk*gen_ratio_std로 불확실성 할인(ramp) |
| LV4 | 에너지 예산 (다중 지점 가중평균 발전량 기반, 구 LV7 병합) | energy_v 비례 감속(ramp) |
| LV5 | 정면풍 성분 | winddir_para 비례, 대칭 클리핑(ramp) |
| LV8 | 시간 예산 (전체완주 페이스 + 다음CS 페이스 2-신호 블렌딩) | SOC 여유(soc_cutoff 초과)에 비례해 목표 페이스로 블렌딩 |

SOC가 `soc_cutoff` 이하로 떨어지면 위 결과와 무관하게 `v_min`으로 강제
고정(하드 안전장치, `soc_hard_stop`과 함께 유일하게 계단형으로 남은
로직). 스텝 간 속도 변화량도 EMA+tanh 댐퍼(`alpha`, `simpara.max_v_delta`)로
제한 - 빠른 오실레이션은 감쇠, 느린 추세는 그대로 따라가되 한 번의
큰 이상치는 물리적 상한(차량 최대 가감속 능력)에서 포화.

LV6은 존재하지 않고(설계 당시 결번), 구 LV7(미래 일사량 추세)은
LV4에 병합됐다. 파라미터 이름은 전부 LV 번호 접두어를 뗀 역할 기반
이름(위 표의 `v_soc_high`, `slope_k` 등)을 쓴다 - 로직 순서가 바뀔
때마다 번호를 다시 매겨야 하는 문제 때문에 폐기했다 (자세한 과정은
`debug_logs/(2026-07-17)_LV3_게이트_제거_LV4_LV7_병합_및_mpc_speed_리팩터링.txt`,
LV8 자체의 재설계 배경은 `debug_logs/(2026-07-13)_LV8_시간예산_설계.txt`).

## 차량 제원 요약
| 항목 | 값 |
|------|-----|
| 차량 질량 | 250 kg |
| Cd | 0.081 |
| 태양광 패널 | 6.0 m², 27% |
| 배터리 (HV) | Molicel P60B, 40S3P, ~2,592 Wh |
| 모터 정격 | 1,800 W, 150 V DC |
| 최대속도 | ~155 km/h (이론) |

## 할 일

### 단기 (진행 중, 다음에 이어서 할 것 - 자세한 건 `progress/33` 참고)
- [ ] 내리막 세그먼트 경계 배열 추출 (main.py/app.py, 작성 중
      미완성 상태로 세션 종료)
- [ ] `compute_downhill_cap(step, const)` 구현 (설계 완료, 코드 없음)
- [ ] CS 접근 코스팅/제동 구현 (`coast_distance`, `simpara.decel_active`
      - 설계 완료, 코드 없음)
- [ ] `simpara.decel_active` 상수 추가 (`Configs/Vehicle_Params.py`)
- [ ] `light_arrive()` 단위 불일치 버그 수정 (미터 vs km, 신호등
      지연 미발동 - 수정 보류 중으로 결정)
- [ ] 속도 정수(int) 출력 반영 (`results.append()` 시점에만 반올림,
      내부 계산은 float 유지 - 결정은 됐고 코드 반영만 남음)
- [ ] Optuna 트라이얼 병렬화 설정 (SQLite WAL 모드 + 별도 프로세스
      여러 개로 분산 - 탐색 재실행 직전에 처리하기로 보류 중)
- [ ] 위 정리 끝나면 새 Optuna 탐색 실행 (`scripts/main.py`를 임시
      스모크테스트 설정에서 `n_trials=50`, `study_name="WSC_MPC_Opt"`,
      `storage="sqlite:///outputs/optuna_study.db"`로 원복 필요)

### 완료
- [x] 릴리즈 노트(버전 표시) + 첫 로그인 튜토리얼 팝업 (`progress/32`)
- [x] 차량 제원 설정 계정 저장/불러오기 (`progress/30`)
- [x] 차량 제원 설정 전역상태 격리 버그수정 - `cfg` 세션별 격리 (`progress/28`)
- [x] GitHub 레포 생성 + Streamlit Cloud 배포 (`progress/24`)
- [x] Supabase 로그인 + 시뮬레이션 기록 저장/조회 + 닉네임 (`progress/25`)
- [x] 시뮬레이션 종료 사유 추적 + 규칙 기반 결과 분석 패널 (`progress/26`)
- [x] `run_simulation()` 함수 분리 (6/6 완료: `compute_lookahead()`/
      `compute_required_pace()`/`compute_motor_derating()`/
      `calender_handler()`/`control_stop_handler()`/
      `compute_vehicle_energy()`)
- [x] 가속도(a) 동적 계산 + LV2 momentum 결합
- [x] `run_simulation()` 함수분리 리팩터링 전후 A/B 비교 검증
      (`progress/19`, 도달거리 차이 0.1%)
- [x] 실제 2025 BWSC 속도제한/신호등 데이터 반영 (`progress/20`)
- [x] Optuna 로버스트 탐색 날씨 섭동 CS구간 상관화 (`progress/21`)
- [x] 오르막/내리막 지형 세그먼트 전처리 - `read_path()` (`progress/22`)
- [x] 컨트롤스탑 CS_open_hour/CS_close_hour 실제 2025 대회 값 반영,
      마감시각/구간평균속도(60km/h) 실격로직 활성화 및 검증
- [x] env_data.csv `_std` 컬럼 활용 (K=5 common random numbers 로버스트 탐색)
- [x] app.py — Darwin~Adelaide 경로 지도 시각화 (커스텀 컴포넌트,
      전체 경로 회색 + 주행 구간 주황 + 진행 애니메이션)
- [x] app.py — 배경 이미지 추가 (호주 실루엣, 지도 좌표에 맞춰 삽입)

### 장기
- [ ] AI 예측 모델 (발전량 / 소비전력) — `ai_models/`
- [ ] MPC → AI 예측값 연동
- [ ] 강화학습 실험 — `rl/`
- [ ] 실측 데이터 교체

## 환경 데이터
- **출처**: Open-Meteo Archive API (ERA5-Land, ~11km 해상도)
- **기간**: 2020~2025년 6개년 평균, 8/22~8/29 (BWSC 일정)
- **샘플**: 10km 간격 305개 좌표 × DY 22~29 × HR 7~18
- **보간 방식**: nearest (풍향 순환값 문제, NASA 공간 해상도 고려)

## 진행상황 / 디버깅 기록
- `progress/`: 전체 진행상황을 주제별로 정리 (이벤트 중심 + 파일별 현재
  상태 스냅샷). 프로젝트를 오랜만에 다시 보거나 새로 파악할 때 먼저 볼 것.
- `debug_logs/`: 버그 추적·성능 개선 등 코드로 남기기 애매한 디버깅
  과정을 날짜별 텍스트 파일로 정리.
  - 파일명 규칙: `(YYYY-MM-DD)_주제.txt` (예: `(2026-07-12)_optuna_속도_개선.txt`)
  - 내용: 문제 → 원인 → 해결 방향 → 변경 대상 파일 → 적용 상태 순으로 기록
