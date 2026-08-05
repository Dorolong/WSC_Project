"""Signal definition loader for telemetry CAN IDs."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from telemetry.decode import normalize_can_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGNAL_CSV = PROJECT_ROOT / "specs" / "can_signals.csv"


@lru_cache(maxsize=1)
def load_signal_defs(path: str | Path = DEFAULT_SIGNAL_CSV) -> list[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["can_id"] = normalize_can_id(row.get("can_id"))
        row["priority"] = (row.get("priority") or "").upper()
        row["status"] = row.get("status") or "확인 필요"
    return rows


def signal_map(path: str | Path = DEFAULT_SIGNAL_CSV) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in load_signal_defs(path):
        grouped.setdefault(row["can_id"], []).append(row)
    return grouped


def primary_signals(path: str | Path = DEFAULT_SIGNAL_CSV) -> list[dict]:
    return [row for row in load_signal_defs(path) if row.get("priority") == "PRIMARY"]
