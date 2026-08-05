"""Verify the project CAN data byte-order rule against canlog.csv.

Usage:
    python scripts/verify_can_decode.py                 # specs/canlog.csv 사용
    python scripts/verify_can_decode.py path/to/other.csv

Expected Phase 1 result:
    reversed/LE should be at least 87.7% accurate, and non-reversed parsing
    should stay below 15%.
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
from pathlib import Path

# 저장소 루트를 import 경로에 추가한다. 이게 없으면 저장소 루트에서
# `python scripts/verify_can_decode.py ...` 로 돌릴 때 telemetry 패키지를
# 못 찾는다(scripts/main.py 도 같은 방식을 쓴다).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telemetry.decode import close_float, decode_canlog_data_hex


def _read_rows(path: Path):
    rows = []
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 7 or not row[4].strip().lower().startswith("0x"):
                continue
            try:
                data_hex = row[4].strip()
                logged_seg_two = float(row[5])
                logged_seg_one = float(row[6])
            except ValueError:
                continue
            rows.append((data_hex, logged_seg_one, logged_seg_two))
    return rows


def _segments(data: bytes, fmt: str):
    return struct.unpack(fmt, data[0:4])[0], struct.unpack(fmt, data[4:8])[0]


def _score(rows, *, reverse: bool, fmt: str):
    matched = 0
    samples = []
    for data_hex, expected_one, expected_two in rows:
        text = data_hex[2:] if data_hex.lower().startswith("0x") else data_hex
        raw = bytes.fromhex(text)
        data = raw[::-1] if reverse else raw
        seg_one, seg_two = _segments(data, fmt)
        ok = close_float(seg_one, expected_one) and close_float(seg_two, expected_two)
        if ok:
            matched += 1
        if len(samples) < 5:
            samples.append(
                {
                    "data": data_hex,
                    "seg_one": seg_one,
                    "expected_one": expected_one,
                    "seg_two": seg_two,
                    "expected_two": expected_two,
                    "ok": ok,
                }
            )
    return matched, samples


def main() -> int:
    parser = argparse.ArgumentParser()
    # 인자를 안 주면 저장소에 커밋된 샘플 로그를 쓴다.
    parser.add_argument("path", type=Path, nargs="?",
                        default=Path(__file__).resolve().parents[1] / "specs" / "canlog.csv")
    parser.add_argument("--min-accuracy", type=float, default=87.7)
    parser.add_argument("--max-no-reverse", type=float, default=15.0)
    args = parser.parse_args()

    rows = _read_rows(args.path)
    if not rows:
        raise SystemExit("no comparable rows found")

    candidates = {
        "reversed/LE": _score(rows, reverse=True, fmt="<f"),
        "reversed/BE": _score(rows, reverse=True, fmt=">f"),
        "printed/LE": _score(rows, reverse=False, fmt="<f"),
        "printed/BE": _score(rows, reverse=False, fmt=">f"),
    }
    print(f"rows={len(rows):,}")
    for name, (matched, _) in candidates.items():
        pct = matched / len(rows) * 100
        print(f"{name:12} {matched:7,}/{len(rows):,} {pct:6.2f}%")

    correct, samples = candidates["reversed/LE"]
    no_reverse, _ = candidates["printed/LE"]
    correct_pct = correct / len(rows) * 100
    no_reverse_pct = no_reverse / len(rows) * 100

    print("samples:")
    for sample in samples:
        print(sample)

    # Also assert that the public helper follows the same reversal rule.
    first_data = decode_canlog_data_hex(rows[0][0])
    if first_data != bytes.fromhex(rows[0][0].removeprefix("0x"))[::-1]:
        raise SystemExit("decode_canlog_data_hex did not preserve the reversal rule")

    if correct_pct < args.min_accuracy:
        raise SystemExit(f"reversed/LE accuracy too low: {correct_pct:.2f}%")
    if no_reverse_pct >= args.max_no_reverse:
        raise SystemExit(f"printed/LE unexpectedly high: {no_reverse_pct:.2f}%")
    if math.isnan(correct_pct):
        raise SystemExit("invalid score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
