"""Signal definition loader for telemetry CAN IDs."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from telemetry.decode import normalize_can_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGNAL_CSV = PROJECT_ROOT / "specs" / "can_signals.csv"

# 전송 주기는 별도 파일로 둔다. can_signals.csv 는 엑셀에서 통째로 재생성되므로
# (scripts/can_signals_from_xlsx.py 가 덮어쓴다) 거기에 주기를 넣으면 다음
# 재생성 때 사라진다. 또 주기는 엑셀에 있는 하드웨어 사실이 아니라 우리가
# 정한 설정 정책이라, 출처를 나눠두는 편이 맞다.
DEFAULT_RATE_CSV = PROJECT_ROOT / "specs" / "can_signal_rates.csv"

DEFAULT_PERIOD_MS = 1000


@lru_cache(maxsize=1)
def load_rate_policy(path: str | Path = DEFAULT_RATE_CSV) -> dict[str, int]:
    """can_id -> 전송 주기(ms). 파일이 없으면 빈 dict."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, int] = {}
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[normalize_can_id(row.get("can_id"))] = int(row["tx_period_ms"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


@lru_cache(maxsize=1)
def load_signal_defs(path: str | Path = DEFAULT_SIGNAL_CSV) -> list[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rates = load_rate_policy()
    for row in rows:
        row["can_id"] = normalize_can_id(row.get("can_id"))
        row["priority"] = (row.get("priority") or "").upper()
        row["status"] = row.get("status") or "확인 필요"
        row["tx_period_ms"] = rates.get(row["can_id"], DEFAULT_PERIOD_MS)
    return rows


def expected_frame_rate(path: str | Path = DEFAULT_SIGNAL_CSV,
                        include_sd_only: bool = True) -> float:
    """초당 예상 프레임 수. 저장 용량 산정과 배치 주기 결정에 쓴다.

    include_sd_only=False 는 서버 수신 기준(SD_ONLY 는 무선 미전송이라 제외),
    True 는 SD카드 기록 기준.
    """
    total = 0.0
    for row in load_signal_defs(path):
        if not include_sd_only and row["priority"].startswith("SD_ONLY"):
            continue
        period = row.get("tx_period_ms") or DEFAULT_PERIOD_MS
        total += 1000.0 / period
    return total


def signal_map(path: str | Path = DEFAULT_SIGNAL_CSV) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in load_signal_defs(path):
        grouped.setdefault(row["can_id"], []).append(row)
    return grouped


def primary_signals(path: str | Path = DEFAULT_SIGNAL_CSV) -> list[dict]:
    return [row for row in load_signal_defs(path) if row.get("priority") == "PRIMARY"]
