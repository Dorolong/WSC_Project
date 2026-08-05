# WSC 주행효율 MPC

> 모델 개발만 남긴 구성. 웹·서버·배포 코드는 **의도적으로 뺐다**
> (개발 도구일 뿐 인계 대상이 아님).
>
> **이전 전체 이력과 웹·서버 코드는 `backup_trial260806` 브랜치에 있다.**
> Streamlit 앱, Optuna 웹 런처, Supabase 연동, 배포 설정, `progress/` 60여 개
> 작업 기록, `debug_logs/`, 총괄기획안 PDF, 구조도·흐름도가 전부 거기 있다.
> `git show backup_trial260806:경로/파일` 로 꺼내 볼 수 있다.

---

## 0. 한 문단 요약

Darwin→Adelaide **3,038km**를 태양광 에너지만으로, **27일 제한시간·9개
컨트롤스탑 마감시각·구간평균 60km/h·법정속도제한** 아래 완주하는
**구간별 권장 속도**를 계산한다. 빠르면 공기저항(v²)·소비전력(v³)으로
배터리가 죽고, 느리면 시간 제약에 걸려 실격된다. **에너지와 시간의
최적 균형점을 전 구간에 걸쳐 찾는 문제**다.

**최종 인계물은 프로그램이 아니라 표 파일이다.** 개발자는 호주에 가지
않는다. 현장(팀원 노트북)은 이미 CAN 수신·대시보드를 갖고 있고, 우리는
"어떤 상태에서 얼마로 달릴지"를 담은 표만 보낸다.

---

## 1. 계층 구조 — 아래가 위를 떠받친다

| 층 | 내용 | 상태 |
|---|---|---|
| **L0 인계물** | 권장속도 표 (호주로 나가는 유일한 것) | 미착수 |
| **L1 결정** | DP 최적화 | 미착수 |
| **L2 예측** | 주행저항·SOC·발전 + **열** + 잔차 | 열 미구현 |
| **L3 데이터** | 시험주행 텔레메트리 (모델 보정용) | 디코더 완료 |
| L4 인프라 | 시뮬레이터·Optuna·웹 | 원본 저장소에 있음 |

---

## 2. 지금 있는 것

### 2.1 물리 엔진 — `Functions/Vehicle_Function.py` (709줄)

**가장 값진 자산. 그대로 유지한다.** DP도 같은 물리를 쓰고 오히려 더 자주 부른다.

```
F_aero  = 0.5·ρ·Cd·A_f·v_rel²      (v_rel: 차량 헤딩 기준 상대풍속)
F_roll  = Crr·m·g·cos(θ)
F_slope = m·g·sin(θ)
F_acc   = m·a                       (a = (v-v_prev)/dt, dt>0 가드 필수)
P_drive = (ΣF)·v / (η_drive·η_motor·η_inv)
P_gen   = 일사량 · A_solar · η_solar
```

배터리: SOC-OCV 12점 룩업 + 내부저항
```
V_ocv = interp(SOC, ocv_soc, ocv_V) · HV_S
R_eq  = R_cell · HV_S / HV_P
I     = (V_ocv - sqrt(V_ocv² - 4·R_eq·P_batt)) / (2·R_eq)
SOC  -= I·dt / HV_Capa
```
**주의**: `sqrt` 안이 음수가 되면 NaN이 전체로 번진다(실제 발생 이력).

모터 디레이팅: `ω_max = V_terminal/(K_v·√6)` → `v_max = ω_max·r_wheel·3.6`

경사: 20m 원본은 고도 노이즈가 과대증폭 → **500m 이동평균 후** 판정.
판정식 `Crr·cos(θ) + sin(θ)`의 부호(내리막 음수).

주요 함수: `read_path()` `cal_drive_res()` `update_soc()` `gen_solar()`
`compute_lookahead()` `compute_required_pace()` `compute_motor_derating()`
`calender_handler()` `control_stop_handler()` `compute_vehicle_energy()`
`run_simulation(params, route, env_data, ..., cfg, progress_cb)`

### 2.2 제어기 — `mpc/mpc_controller.py` (116줄) ← **교체 대상**

`mpc_speed(step, params, const)`가 규칙을 누적한 뒤 상한으로 자른다.

| 단계 | 기준 | 방식 |
|---|---|---|
| LV1 | SOC | `v_min ~ v_soc_high` 선형보간(기저속도) |
| LV2 | 경사 look-ahead + 직전 가속도 | `slope_k` 비례 감속, momentum이 오르막 페널티 완화 |
| LV3 | 일사량 비율 | `radi_para` 비례, `radi_risk·표준편차`로 불확실성 할인 |
| LV4 | 에너지 예산 | 잔여구간 필요SOC 대비 부족분에 `energy_v` 비례 감속 |
| LV5 | 정면풍 | `winddir_para` 비례, 대칭 클리핑 |
| LV8 | 시간 예산 | 전체·다음CS 페이스 2신호를 SOC 여유로 3항 가중평균 |

**클리핑 순서(중요)**: `v_min` 하한 → `soc_cutoff` 하드컷 → LV8 →
물리 상한(`v_max_derated`, `drive.v_max`) → **법정 속도제한** →
EMA+tanh 댐퍼.
법정 속도제한이 `v_min`보다 **뒤**여야 한다. 앞이면 `v_min`(60)이
CS 진입 25km/h를 덮어써 규정 위반이 된다.

LV6은 결번, 구 LV7은 LV4에 병합됨.

### 2.3 설정 — `Configs/Vehicle_Params.py`

dataclass 8종 + `build_default_cfg()`.

| 항목 | 값 | 항목 | 값 |
|---|---|---|---|
| 질량 | 250 kg | Crr | 0.001 |
| Cd | 0.081 | 전면적 | 1.0 m² |
| 구동계 효율 | 0.99 | 공기밀도 | 1.225 |
| 패널 | 6.0 m², 27% | **회생제동 효율** | **0.60 (추정)** |
| 셀 | Molicel P60B 6000mAh | 내부저항 | 0.0128 Ω |
| HV팩 | 40S3P ≈2,592Wh | LV팩 | 5S2P ≈216Wh |
| 모터 | 1800W/150V, Kv 0.45 | 휠반경 | 0.275 m |
| **모터/인버터 효율** | **0.97/0.95 (추정)** | 이론최고속 | ~155 km/h |
| 주행 LV소비 | 50W | CS충전 LV | 25W |
| `soc_hard_stop` | 0.10 | `max_v_delta` | 2 m/s |
| 신호등/보행자 대기 | 15s / 10s | `decel_brake` | 0.7g (**미사용**) |

레이스: 출발 2027-08-23 08:00, 주행 08:00~17:00, 총 3,038,326m,
CS 9개(위치·오픈·마감 시각), 구간평균 60km/h 하한, 출발 최소 SOC 0.2.

> **굵은 값들이 카탈로그·이론값이다.** 실측 교체가 L3의 목적.

### 2.4 설정 전달 규칙 — **반드시 지킬 것**

설정은 전역 싱글턴이 아니라 **`cfg` → `const` dict로 인자 전달**한다.
여러 사용자가 서버 프로세스를 공유할 때 전역을 고치면 모든 사용자의
결과가 바뀐다(**실제로 2회 발생**). `run_simulation()`/`mpc_speed()`
시그니처에 `cfg`/`const`가 있는 이유다.

### 2.5 최적화 — `scripts/main.py`

`build_objective()` → `(objective, context)`. **탐색공간 정의는 여기 한 곳뿐.**

```
완주 시   score = 평균속도[km/h]
미완주 시 score = 도달률 - 2      (범위 [-2,-1])
목적값 = 고정 5개 날씨의 평균
```

**날씨를 고정하는 이유(common random numbers)**: 매번 새 날씨를 뽑으면
"운 좋은 날씨를 만난 trial"이 이겨서 실력 비교가 불가능하다.
섭동은 지점별 독립 난수가 아니라 **CS 구간(leg) 단위로 공유되는 z값**
— 실제 날씨는 전선 단위로 뭉쳐 움직인다.

현재 탐색 파라미터 12개: `v_min` `v_soc_high` `soc_ramp_high`
`soc_ramp_low` `slope_k` `radi_para` `radi_risk` `energy_v`
`winddir_para` `margin_total` `margin_next_cs` `soc_cutoff`

> `run_cli()`가 스모크테스트 설정(`n_trials=2`, `_test` storage)이다.
> 본 탐색 전 `n_trials=50`, `study_name="WSC_MPC_Opt"`,
> `storage="sqlite:///outputs/optuna_study.db"`로 되돌릴 것.

### 2.6 텔레메트리 디코더 — `telemetry/`

네트워크 의존 0. 순수 함수.

**값 해석(실측 검증 완료)**: CAN 8바이트 = **리틀엔디안 float32 두 개**.
```python
raw = bytes.fromhex(hex_str)[::-1]      # ★ 로그 hex는 뒤집혀 인쇄된다
seg_one = struct.unpack("<f", raw[0:4])[0]
seg_two = struct.unpack("<f", raw[4:8])[0]
```
`canlog.csv` 41,397행 대조 결과 **87.74% 일치**. 100%가 아닌 건 정수·
비트필드 프레임을 로그 도구가 억지로 float으로 찍었기 때문. **87% 아래면
엔디안 처리가 틀린 것**(잘못된 해석 3종은 전부 14%대).

검증: `python scripts/verify_can_decode.py` (인자 없으면 `specs/canlog.csv`)

**주의 1**: NaN/Inf가 나오는 프레임이 있다(float 쌍이 아닌 것들). JSON으로
보낼 때 `NaN`은 표준에 없는 리터럴이라 거부된다 → `None`으로 치환하되
**raw 바이트는 보존**해야 나중에 정수로 재해석할 수 있다.

**주의 2**: `parse_udp_packet()`이 CAN ID를 **리틀엔디안**으로 읽는데
**원본 Java는 빅엔디안**이다(`ByteBuffer` 기본값). 원본은 13년간 실제
하드웨어로 검증된 코드다. **이 함수는 아직 아무도 검증하지 않았다**
(87.74%는 CSV 경로라 이 함수를 타지 않음). 실시간 수신을 쓸 일이 생기면
실제 패킷 1개를 양쪽으로 파싱해 `specs/can_signals.csv`의 108개 ID와
대조하면 즉시 판별된다.

### 2.7 CAN 명세 — `specs/`

- `CAN_수신_데이터_정리본.xlsx` — 원본 명세. **읽기 전용으로만 열 것**
  (도형·이미지 포함 → openpyxl로 저장하면 소실). CAN ID 114개:
  BMS(HV) 66 확정 / MPPT 21 확정 / Motor 13 잠정(VCU 미확정) / BMS(LV) 14 잠정
- `can_signals.csv` — 위를 기계가 읽는 형태로 변환한 것. **108행**
  (명세 114개와 **6개 차이**, BMS(HV) 60 vs 66 — 미해결)
- `can_signal_rates.csv` — 전송 주기 정책(**임의 설정값**)
  - 10Hz 12개: BMS PRIMARY 10 (`0x040~047`,`0x6F4`,`0x6FA`) + `0x402`,`0x403`
  - 1Hz 96개
  - 근거: 태양광차는 포뮬러급 과도현상이 없다. 단 `0x403`은 **미분해서
    가속도를 얻고**(가속도 CAN 신호가 없음), 전류는 **I²R 손실이 제곱이라
    평균값으로 계산하면 과소평가**되므로 해상도가 필요하다.
- `canlog.csv` — 검증용 샘플 로그 41,397행

주요 신호: `0x041`×`0x042` 팩 전압×전류(전력) · `0x043`/`0x047` SOC ·
`0x311` MPPT 출력(발전) · `0x402` Bus V/I · `0x403` 차속 ·
`0x40B` 모터/히트싱크 온도 · `0x04C`/`0x04D` 셀 온도 · `0x6FA` LV 팩

---

## 3. 앞으로 만들 것

### 3.1 비용함수 — 거리로 매개변수화

상태 `x = (t, SOC, T_m, T_b)`, 제어 `v`, 독립변수 `s`(거리)

```
dt   = ds/v
dSOC = -(P_batt(v,θ,wind,irr) / E_pack)·dt
dT   = ((P_loss - hA(T - T_amb)) / mc)·dt
```

**[A] 시간 최소화 + 에너지 제약** ← 시작점
```
min Σ ds_i/v_i
s.t. SOC ≥ SOC_min, t(CS_k) ≤ 마감_k, v_min ≤ v ≤ v_cap
```
튜닝 파라미터가 사실상 없다. 라그랑주 완화 시 승수가 **λ**이고 구간별로 분리:
```
v* = argmin_v (1 + λ·P_batt(v)) / v
```

**[B] 소프트 제약** — 하드 제약은 DP 격자에 해가 없는 칸을 만든다.
소프트면 "얼마나 위반했는지"가 보여 디버깅이 쉽다. **개발 초기엔 B, 확정 후 A.**
```
J = Σ [ds/v + ρ_soc·max(0, SOC_min-SOC)² + ρ_t·max(0, t-마감)²]
```

**[C] 부드러움** `+ w_Δ(v_i - v_{i-1})²` — EMA+tanh 댐퍼를 원리적으로 대체
**[D] 열 비용** `+ w_T·max(0, T-T_warn)²` — 하드 상한보다 부드럽다

> **원칙**: 항을 추가할 때마다 가중치가 생기고 그게 다시 튜닝 대상이 된다.
> 파라미터 12개를 없애려는 건데 가중치를 붙이면 제자리다. **A로 시작할 것.**

### 3.2 DP — 왜 거꾸로인가

```
V(s, x) = min_v [ ds/v + V(s+1, f(x,v)) ]
```
우변에 `V(s+1)`이 필요하니 **끝에서부터** 채운다.

**시뮬레이션(앞으로)은 경로 하나만 방문한다.** "이 파라미터가 몇 점"은
알아도 "SOC 40%에서 오르막이면 얼마"는 모른다. **DP는 달리지 않고 모든
상태 칸을 전수 계산**한다. 그래서 결과가 표다.

여러 날씨에 로버스트하게:
```
V(s,x) = min_v (1/K)·Σ_k [ ds/v + V(s+1, f_k(x,v)) ]
```
**표는 '날씨와 무관'해질 수 없다.** 어떤 날씨를 가정하고 만드느냐가
로버스트성을 정한다. 낙관적으로 만들면 흐린 날 무너지고, 보수적으로
만들면 맑은 날 손해 본다. Optuna의 고정 5개 날씨 평균이 그대로 전이된다.
(`prototype/toy_dp_weather.py`가 이 차이를 실제로 보여준다)

**실행 중 적응은 상태를 통해 일어난다** — 날씨가 나쁘면 SOC가 계획보다
낮아지고, 표가 자동으로 다른 칸을 참조해 느린 속도를 낸다.
표가 못 하는 건 **앞으로 올 날씨를 미리 아는 것**뿐이다.

### 3.3 표 구조 — 하나로 만들면 터진다

uint8(0~255 km/h) 기준 크기:

| 축 구성 | 크기 |
|---|---|
| 거리600 × SOC100 | 0.1 MB |
| + 시각200 | 12 MB |
| + 모터온도30 | 360 MB |
| + 배터리온도30 | **10.8 GB** ✗ |

**해법 — 의미 단위로 셋으로 쪼갠다**

| 표 | 축 | 크기 | 의미 |
|---|---|---|---|
| **A. λ** | 거리600 × SOC100 × 시각편차100 | 6 MB | 에너지가 얼마나 귀한가(전략) |
| **B. 속도** | λ50 × 경사40 × 정면풍20 | 0.04 MB | 그 가격에 이 지형이면 얼마(전술) |
| **C. 열 상한** | 모터온도60 × 배터리온도60 | 0.004 MB | 열 때문에 못 넘는 선(제약) |

합계 **6 MB** (1800배 축소). 가능한 이유: **온도는 속도를 "결정"하지 않고
"제한"한다** → 곱하지 않고 마지막에 자른다.

현장 조회:
```
λ    = A[거리, SOC, 시각편차]
v    = B[λ, 경사, 정면풍]
권장 = min(v, C[모터온도, 배터리온도])
```

**시간 축 주의**: "남은시간 / 다음CS마감까지 / 일정편차"는 전부
`(거리, 시각)`에서 파생된다. **축을 늘리지 말 것.**

**파일 형식**: B·C는 **CSV**(눈으로 확인 가능, Java가 몇 줄로 읽음),
A는 **바이너리**(헤더 + uint8 배열). Parquet은 Java 라이브러리가 필요해
제외 — 현장에선 의존성 없는 게 최고다.

### 3.4 열 모델 — 신규

**현재 물리엔진에 온도 항이 아예 없다.**

```
dT/dt = (P_loss - hA·(T - T_amb)) / (mc)
```
`P_loss`는 이미 아는 I²R, 미지수는 **`mc`와 `hA` 두 개뿐**.
→ **회색상자 권장**: 물리 구조를 주고 계수만 데이터로 피팅. 신경망은
이 방정식을 데이터로 재발견해야 해서 데이터가 훨씬 많이 든다.

**즉시 필요한 수정**: `scripts/main.py`의 `ENV_NEEDED_COLS`가 메모리
절약을 위해 **`temperature_2m`을 버리고 있다.** 되살려야 한다
(`env_data.csv`에는 이미 들어있다).

디레이팅 임계는 WaveSculptor22 매뉴얼 + 실측 확인.

**이건 별개 기능이 아니다.** 오르막 → 전류↑ → I²R 손실 제곱 증가 →
온도↑ → 디레이팅. 지금 `slope_k`로 눌러둔 부분에 물리 근거가 생기는 것.

### 3.5 룰베이스 처분표

| 현재 | 처분 | 이유 |
|---|---|---|
| LV1 SOC 기저속도 | 삭제 | SOC가 상태가 되고 λ가 그 역할 |
| LV2 경사+momentum | 삭제 | `F_slope`로 동역학에. 운동에너지는 DP가 알아서 |
| LV3 일사량 | 삭제 | 발전량이 SOC 동역학에 |
| ↳ `radi_risk` | **유지** | 예보 불확실성 할인 → 보수적 예측치로 DP를 도는 손잡이 |
| LV4 에너지 예산 | 삭제→**λ** | 균등배분 순환논리 해소 |
| LV5 정면풍 | 삭제 | `F_aero` 상대속도로 |
| LV8 페이스 블렌딩 | 삭제 | 시간 제약이 최적화 내부로 |
| 속도 클리핑 4종 | 유지 | 제약조건으로 |
| `soc_cutoff` 하드컷 | 유지 | 안전장치 |
| EMA+tanh 댐퍼 | 선택 | [C]항 또는 변화율 제약으로 |

**파라미터 12개 → 2~4개** (`soc_min`, `radi_risk`, 선택 `w_Δ`, 격자 해상도)

> **기존 LV1~LV8을 지우지 말 것.** A/B 비교 기준선으로 남긴다.
> `build_objective()` 하네스로 같은 5개 날씨에서 바로 비교된다.

**하드 세이프티는 두 겹**: `soc_cutoff`·`speed_limit`은 표를 만들 때
반영하고 **현장에서 한 번 더 클립**한다. 표가 틀렸을 때의 마지막 방어선.

---

## 4. 진행 순서

1. **`temperature_2m` 되살리기** (`scripts/main.py`, 한 줄)
2. **코스팅·제동·내리막 캡** — 설계는 원본 저장소 `progress/22`에 있음
   - `a_coast = (F_aero+F_roll+F_slope)/m`
   - `coast_distance = v²/(2·a_coast)`, `v_entry_max = √(v_exit² - 2·a_coast·L)`
   - 내리막(`a_coast ≤ 0`)은 `simpara.decel_brake`(0.7g, 회생제동 배제)
   - 코스팅 중 `P_batt = power.P_LV_race`만(배터리 안 거침)
3. **DP 프로토타입** — **먼저 거리 × SOC 2차원으로.** 시각·온도를 한꺼번에
   넣으면 격자 문제인지 물리 문제인지 비용함수 문제인지 구분이 안 된다
4. **시험주행 로그로 계수 보정** — `Regen_eff`, `Cd`, `Crr`, `mc`, `hA`
5. **DP 상태에 시각·온도 추가**, 표 3분해
6. 표 내보내기 형식 확정 + 팀원 인터페이스 합의
7. (선택) 예보≠실제 분리, 잔차 학습, RL

### RL은 왜 나중인가
지금 시뮬레이션은 **예보 = 실제**다. 여기서 RL을 학습시키면 **미래를 아는
정책**을 배워 실전에 안 옮겨간다. 또 하드 제약(마감시각·SOC)을 잘 못 다룬다.
상태가 1차원인 지금은 **DP가 정확하고 빠르다**. RL은 상태가 커진 뒤에 값한다.
계산량은 문제가 아니다(스텝당 66µs → 100만 스텝이 약 1분).

---

## 5. 겪은 버그 — 반복되는 패턴

| 무엇 | 영향 | 배운 것 |
|---|---|---|
| 야간 시간대 날짜 미전환 | **993 km** | 경계 조건은 A/B로 재봐야 드러난다 |
| 거리 배열이 pandas Index | **4.2배 느림** | 성능은 추측 말고 프로파일러부터 |
| 설정이 전역 → 사용자 섞임 | **2회 발생** | 공유 프로세스에선 전역이 곧 버그 |
| 미터 vs km 비교(신호등) | 조용히 무동작 | 단위 불일치는 에러 없이 몇 주 간다 |
| `dt=0` → NaN 전파 | 크래시 | 나눗셈 전 가드 |
| NaN이 표준 JSON에 없음 | 배치 전량 손실 | 한 건이 500건을 막는다 |
| 문서엔 "정리했다", 실제론 없음 | 재구축 불가 | 문서를 믿되 코드로 교차 확인 |

**가장 값비쌌던 습관**: 검증 없이 넘어간 작업. 실행 환경이 없는 채로
머지된 코드가 여러 번 문제를 만들었다.
→ **검증 스크립트와 샘플 데이터를 함께 두는 것**을 원칙으로.

---

## 6. 폴더 안내

```
  README.md                      ← 이 문서
  2027 BWSC TRACK.csv            경로 3,038km (약 20m 간격, 151,932점)
  outputs/env_data.csv           기상 305좌표 × 8일 × 12시간
  requirements.txt  .python-version
  Configs/    Vehicle_Params.py · speed_limits · traffic_lights
  Functions/  Vehicle_Function.py   ← 물리 엔진, 유지
  mpc/        mpc_controller.py     ← 교체 대상(기준선으로 보존)
  scripts/    main.py · verify_can_decode.py
  telemetry/  decode.py · signals.py
  specs/      CAN 명세 · 신호정의 · 주기정책 · 샘플로그
  prototype/  toy_dp.py · toy_dp_weather.py   ← DP 개념 데모, 바로 실행 가능
```

**실행 확인**
```bash
pip install -r requirements.txt
python scripts/verify_can_decode.py      # 87.74% 나오면 정상
python prototype/toy_dp.py               # DP가 만드는 표를 눈으로
python prototype/toy_dp_weather.py       # 날씨 가정이 결과를 가르는 것
```

**`backup_trial260806` 브랜치에 남겨둔 것**(필요할 때만 참조):
웹 시뮬레이터(`app.py`), Optuna 웹 런처(`server/`), Supabase 연동,
배포 설정, `progress/` 60여 개 작업 기록, `debug_logs/`,
총괄기획안 PDF, 구조도·흐름도 HTML.

```bash
git show backup_trial260806:progress/58_방향_재정립_계층별_로드맵.txt
git checkout backup_trial260806 -- server/     # 통째로 되살리려면
```

---

## 7. 아직 안 정해진 것

1. **표 파일 형식과 팀원 대시보드의 인터페이스** — 어떻게 읽어갈지
2. **열 상태를 모터·배터리 각각 둘지, 하나로 합칠지** (표 크기가 갈림)
3. `can_signals.csv` 108행 vs 명세 114개 — **6개 누락 원인**
4. MPPT #2·#3 14개 신호의 우선순위 미기재 (#1과 같게 채우면 될 것으로 보임)
5. 전송 주기가 **임의 설정값** — WaveSculptor22 매뉴얼·BMS 설정으로 확인 필요
   (단 결론은 안 바뀜: CAN 버스 물리 상한이 500kbps 기준 약 3,900 frame/s)
