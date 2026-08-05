"""canlog.csv로 CAN 데이터 값 변환 규칙을 확정한다.

Java 원본(CanPacket.java)은:
    getDataSegmentOne() = data[0..3] 리틀엔디안 float32
    getDataSegmentTwo() = data[4..7] 리틀엔디안 float32

로그의 data 컬럼은 8바이트를 하나의 hex 문자열로 찍은 것인데,
바이트 순서를 어떻게 잡아야 로그의 float[0]/float[1]과 맞는지를
여러 후보로 전부 시험해서 결정한다.
"""
import csv, struct, io, math

PATH = r"C:\Users\DongHo\AppData\Local\Temp\claude\c--Users-DongHo-Desktop-WSC-DriveEff-Project\9afdb490-0403-4c72-a715-a4ad91c50aef\scratchpad\canlog.csv"

rows = []
with io.open(PATH, encoding="utf-8", errors="replace") as f:
    for r in csv.reader(f):
        if len(r) < 8 or not r[4].strip().startswith("0x"):
            continue
        try:
            data_hex = r[4].strip()[2:]
            f1 = float(r[5]); f0 = float(r[6])
        except ValueError:
            continue
        if len(data_hex) != 16:
            continue
        rows.append((data_hex, f1, f0))

print(f"검증 대상 행: {len(rows):,}")

def close(a, b):
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return abs(a - b) < 1e-30
    return abs(a - b) / denom < 2e-6   # 로그가 6자리 유효숫자로 반올림돼 있음

def cands(h):
    raw = bytes.fromhex(h)               # 문자열 순서 그대로
    rev = raw[::-1]                      # 64비트 값으로 보고 뒤집기
    out = {}
    for name, b in (("문자열순서", raw), ("역순", rev)):
        for endian, fmt in (("LE", "<f"), ("BE", ">f")):
            lo = struct.unpack(fmt, b[0:4])[0]
            hi = struct.unpack(fmt, b[4:8])[0]
            out[f"{name}/{endian}"] = (lo, hi)
    return out

names = list(cands(rows[0][0]).keys())
score = {n: [0, 0] for n in names}       # [f0=lo & f1=hi 로 맞음, f0=hi & f1=lo 로 맞음]

for h, f1, f0 in rows:
    for n, (lo, hi) in cands(h).items():
        if close(lo, f0) and close(hi, f1):
            score[n][0] += 1
        if close(lo, f1) and close(hi, f0):
            score[n][1] += 1

print(f"\n{'해석 방식':<18}{'float[0]=앞4B':>14}{'float[0]=뒤4B':>14}")
print("-" * 46)
for n in names:
    a, b = score[n]
    print(f"{n:<18}{a:>13,}{b:>14,}")

best = max(((n, i, s) for n, sc in score.items() for i, s in enumerate(sc)), key=lambda x: x[2])
print(f"\n결론: {best[0]}, float[0]={'앞 4바이트' if best[1]==0 else '뒤 4바이트'} "
      f"→ {best[2]:,}/{len(rows):,} 행 일치 ({best[2]/len(rows)*100:.2f}%)")
