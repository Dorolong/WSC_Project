# -*- coding: utf-8 -*-
"""표를 만들 때 '어떤 날씨를 가정했는가'가 실제 주행 결과를 가른다."""
import numpy as np

N_SEG, DS = 8, 50.0
SOCS   = np.linspace(0, 1, 41)
SPEEDS = np.array([60, 70, 80, 90, 100], float)
SLOPE  = np.array([0, +1, +1, 0, -1, +1, 0, 0])
A, B, SOLAR = 3.2e-7, 0.004, 0.050
SOC_MIN, INF = 0.05, 1e9

WEATHER = {"흐림": 0.50, "보통": 1.00, "맑음": 1.50}

def step(soc, v, seg, wm):
    h = DS / v
    use = (A * v**3 + B) * h * (1 + 0.6 * SLOPE[seg])
    return h, soc - use + SOLAR * wm * h

def build(wmuls, penalty=40.0):
    """기대 비용으로 표를 만든다. SOC 위반은 하드 금지가 아니라 **페널티**로
    둬서, '평균 가정'과 '최악 가정'이 실제로 다른 표를 내놓게 한다."""
    V = np.zeros((N_SEG + 1, len(SOCS)))
    P = np.full((N_SEG, len(SOCS)), np.nan)
    V[N_SEG] = np.where(SOCS < SOC_MIN, penalty, 0.0)
    for seg in range(N_SEG - 1, -1, -1):
        for i, soc in enumerate(SOCS):
            best, bv = INF, np.nan
            for v in SPEEDS:
                tot = 0.0
                for wm in wmuls:
                    h, sn = step(soc, v, seg, wm)
                    cost = h + (penalty if sn < SOC_MIN else 0.0)
                    tot += cost + np.interp(max(sn, 0), SOCS, V[seg + 1])
                tot /= len(wmuls)
                if tot < best:
                    best, bv = tot, v
            V[seg, i], P[seg, i] = best, bv
    return P

def run(P, wm, soc0=1.0):
    soc, t = soc0, 0.0
    for seg in range(N_SEG):
        v = np.interp(soc, SOCS, P[seg])
        h, soc = step(soc, v, seg, wm)
        t += h
        if soc < SOC_MIN:
            return False, t, soc
    return True, t, soc

tables = {
    "① 맑음 가정 (낙관)": build([WEATHER["맑음"]]),
    "② 세 날씨 평균":     build(list(WEATHER.values())),
    "③ 흐림 가정 (보수)": build([WEATHER["흐림"]]),
}

print("SOC 1.0 으로 출발해 실제 날씨를 바꿔가며 주행\n")
print(f"{'표를 만든 가정':<20}" + "".join(f"{w:>18}" for w in WEATHER))
print("─" * 76)
for name, P in tables.items():
    row = ""
    for w, wm in WEATHER.items():
        ok, t, soc = run(P, wm)
        row += f"{(f'{t:5.2f}h  SOC{soc:4.2f}' if ok else '  ✗ 완주 실패'):>18}"
    print(f"{name:<20}{row}")

print("\n\n같은 상황에서 표가 실제로 다른 속도를 지시하는가 (구간2 오르막)")
print(f"{'출발 SOC':<12}" + "".join(f"{n[:9]:>14}" for n in tables))
print("─" * 54)
for soc in (0.3, 0.5, 0.7, 0.9):
    i = int(np.argmin(abs(SOCS - soc)))
    print(f"{soc:<12.1f}" + "".join(f"{int(P[1, i]):>14}" for P in tables.values()))

print("""
핵심: 표는 '날씨와 무관'해질 수 없다. **어떤 날씨를 가정하고 만드느냐**가
      로버스트성을 정한다. 지금 Optuna 의 '고정 5개 날씨 평균'이 ②다.""")
