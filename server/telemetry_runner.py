"""Background worker for uploaded CAN telemetry logs."""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telemetry.decode import parse_canlog_csv  # noqa: E402


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wijwbujsihhzzjzawfzp.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_IKdkodgmKWm05tQh15bqVg_uNRqdpEO")
TELEMETRY_DIR = PROJECT_ROOT / "outputs" / "telemetry"
BATCH_SIZE = int(os.environ.get("WSC_TELEMETRY_BATCH_SIZE", "500"))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _headers(access_token: str, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _patch_log(access_token: str, log_id: str, payload: dict):
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/telemetry_logs?id=eq.{log_id}",
        headers=_headers(access_token, "return=minimal"),
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()


def _upsert_log(access_token: str, payload: dict):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/telemetry_logs?on_conflict=id",
        headers=_headers(access_token, "resolution=merge-duplicates,return=minimal"),
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()


def _json_safe_float(value):
    """NaN/Infinity 를 None 으로 바꾼다.

    CAN 8바이트를 float32 로 해석하면 NaN/Inf 가 나오는 프레임이 있다.
    그 프레임이 애초에 float 쌍이 아니라 정수·비트필드이기 때문이다
    (예: 0x6FA). 그런데 파이썬 json.dumps 는 이걸 `NaN` 이라는 리터럴로
    직렬화하는데, **표준 JSON(RFC 8259)에는 그런 리터럴이 없어서**
    PostgREST 가 배치 전체를 400 으로 거부한다. 한 건 때문에 500건이
    통째로 날아간다.

    값을 버리는 것처럼 보이지만 손실이 아니다 - raw_data_hex 에 원본
    바이트가 그대로 남아 있어서, 신호 정의에 따라 나중에 정수로
    재해석하면 살아난다.
    """
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
    except TypeError:
        return None
    return value


def _insert_frames(access_token: str, rows: list[dict]):
    if not rows:
        return
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/telemetry_frames",
        headers=_headers(access_token, "return=minimal"),
        json=rows,
        timeout=30,
    )
    if resp.status_code >= 400:
        # raise_for_status() 는 응답 본문을 안 보여줘서 원인 추적이 안 된다.
        # Supabase 는 실패 사유를 본문 JSON 에 담아 보내므로 같이 남긴다.
        detail = (resp.text or "")[:500]
        raise RuntimeError(
            f"telemetry_frames insert failed: HTTP {resp.status_code} "
            f"rows={len(rows)} detail={detail}"
        )


def run(run_id: str, payload_path: Path) -> int:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    result_path = TELEMETRY_DIR / f"{run_id}.json"
    progress_path = TELEMETRY_DIR / f"{run_id}_progress.json"

    with payload_path.open(encoding="utf-8") as f:
        payload = json.load(f)

    file_path = Path(payload["file_path"])
    access_token = payload["access_token"]
    user_id = payload["user_id"]
    file_name = payload["file_name"]

    started_at = _now_iso()
    progress = {
        "status": "running",
        "frame_count": 0,
        "file_size": payload.get("file_size", 0),
        "started_at": started_at,
    }
    _write_json(progress_path, progress)
    _upsert_log(
        access_token,
        {
            "id": run_id,
            "user_id": user_id,
            "file_name": file_name,
            "status": "running",
            "frame_count": 0,
            "created_at": started_at,
            "updated_at": started_at,
        },
    )

    frame_count = 0
    first_ts = None
    last_ts = None
    batch: list[dict] = []
    try:
        for frame in parse_canlog_csv(file_path):
            if first_ts is None:
                first_ts = frame.timestamp
            last_ts = frame.timestamp or last_ts
            batch.append(
                {
                    "log_id": run_id,
                    "user_id": user_id,
                    "frame_index": frame_count,
                    "timestamp_text": frame.timestamp,
                    "can_id": frame.can_id,
                    "raw_data_hex": frame.raw_data_hex,
                    "seg_one": _json_safe_float(frame.seg_one),
                    "seg_two": _json_safe_float(frame.seg_two),
                }
            )
            frame_count += 1
            if len(batch) >= BATCH_SIZE:
                _insert_frames(access_token, batch)
                batch.clear()
                progress.update({"frame_count": frame_count, "updated_at": _now_iso()})
                _write_json(progress_path, progress)
        _insert_frames(access_token, batch)
        finished_at = _now_iso()
        result = {
            "status": "done",
            "run_id": run_id,
            "file_name": file_name,
            "frame_count": frame_count,
            "min_timestamp": first_ts,
            "max_timestamp": last_ts,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        _patch_log(
            access_token,
            run_id,
            {
                "status": "done",
                "frame_count": frame_count,
                "min_timestamp": first_ts,
                "max_timestamp": last_ts,
                "updated_at": finished_at,
                "finished_at": finished_at,
            },
        )
        _write_json(result_path, result)
        _write_json(progress_path, {**progress, "status": "done", "frame_count": frame_count, "updated_at": finished_at})
        return 0
    except Exception as exc:
        finished_at = _now_iso()
        error = str(exc)
        _write_json(
            result_path,
            {
                "status": "error",
                "run_id": run_id,
                "file_name": file_name,
                "frame_count": frame_count,
                "error": error,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
        try:
            _patch_log(
                access_token,
                run_id,
                {"status": "error", "frame_count": frame_count, "error": error, "updated_at": finished_at, "finished_at": finished_at},
            )
        finally:
            _write_json(progress_path, {**progress, "status": "error", "frame_count": frame_count, "error": error, "updated_at": finished_at})
        raise
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: telemetry_runner.py <run_id> <payload_path>", file=sys.stderr)
        return 2
    return run(argv[1], Path(argv[2]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
