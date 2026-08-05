# -*- coding: utf-8 -*-
"""장난감 DP - "한 번 달려서 점수"와 "모든 상태에 답"의 차이를 눈으로 본다.

물리를 극단적으로 단순화했다(P = a·v³ + b). 요점은 물리가 아니라
**계산의 방향**이다.
"""
import numpy as np

# ── 설정 ──────────────────────────────────────────────
N_SEG   = 6                      # 거리 구간
DS      = 50.0                   # 구간 길이 [km]
SOCS    = np.linspace(0, 1, 11)  # SOC 격자 0, 0.1, ... 1.0
SPEEDS  = np.array([60, 70, 80, 90, 100], float)   # 후보 속도 [km/h]
SLOPE   = np.array([0, 0, +1, +1, -1, 0])          # 구간별 지형 (+1 오르막)

A, B, SOLAR = 1.8e-7, 0.004, 0.030   # 소비/발전 계수 (임의)

def step(soc, v, seg):
    """한 구간을 v로 달렸을 때 (소요시간, 다음 SOC)."""
    hours = DS / v
    use   = (A * v**3 + B) * hours * (1 + 0.6 * SLOPE[seg])   # 오르막이면 더 씀
    gain  = SOLAR * hours
    return hours, soc - use + gain

# ── DP: 끝에서 거꾸로 ─────────────────────────────────
INF = 1e9
V      = np.zeros((N_SEG + 1, len(SOCS)))   # 가치함수 = 남은 최소 소요시간
POLICY = np.zeros((N_SEG, len(SOCS)))       # 최적 속도

V[N_SEG, :] = 0.0                            # 도착 지점: 남은 시간 0
V[N_SEG, SOCS < 0.05] = INF                  # 단, SOC 고갈 상태로 도착은 실격

for seg in range(N_SEG - 1, -1, -1):         # ← 뒤에서 앞으로
    for i, soc in enumerate(SOCS):
        best, best_v = INF, np.nan
        for v in SPEEDS:
            hours, soc_next = step(soc, v, seg)
            if soc_next < 0.05:              # SOC 하한 위반 → 이 선택 금지
                continue
            future = np.interp(soc_next, SOCS, V[seg + 1])   # 다음 칸의 가치
            total  = hours + future                          # 지금 + 미래
            if total < best:
                best, best_v = total, v
        V[seg, i], POLICY[seg, i] = best, best_v

# ── 출력 ──────────────────────────────────────────────
print("최적 속도표  (행=출발 SOC, 열=구간).  지형: " +
      " ".join({0: "평지", 1: "오르막", -1: "내리막"}[s] for s in SLOPE))
print()
head = "  SOC │" + "".join(f"{f'구간{j+1}':>9}" for j in range(N_SEG))
print(head); print("─" * len(head))
for i, soc in enumerate(SOCS):
    if soc < 0.1:
        continue
    cells = []
    for j in range(N_SEG):
        p = POLICY[j, i]
        cells.append("      -" if np.isnan(p) else f"{int(p):>6} ")
    print(f"  {soc:4.1f} │" + "".join(f"{c:>9}" for c in cells))

print("""
읽는 법
  · 같은 구간(열)이라도 SOC(행)에 따라 권장 속도가 다르다
  · 오르막 구간(3·4)에서 SOC가 낮으면 더 느리게 간다
  · '-' 는 그 상태에서 어떤 속도로도 완주 불가 (실격 영역)

핵심: 이 표는 주행을 한 번도 하지 않고 만들어졌다.
      끝에서 거꾸로, 모든 칸을 채웠을 뿐이다.""")

n_cells = N_SEG * len(SOCS)
print(f"\n계산량: {N_SEG}구간 x {len(SOCS)}SOC칸 x {len(SPEEDS)}속도후보 "
      f"= {n_cells * len(SPEEDS):,}번의 '한 스텝' 계산")
print(f"반면 시뮬레이션 한 번은 {N_SEG}스텝만 계산하고 경로 하나만 본다.")
