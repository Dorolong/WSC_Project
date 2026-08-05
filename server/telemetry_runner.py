"""Background worker for uploaded CAN telemetry logs."""

from __future__ import annotations

import json
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


def _insert_frames(access_token: str, rows: list[dict]):
    if not rows:
        return
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/telemetry_frames",
        headers=_headers(access_token, "return=minimal"),
        json=rows,
        timeout=30,
    )
    resp.raise_for_status()


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
                    "seg_one": frame.seg_one,
                    "seg_two": frame.seg_two,
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
