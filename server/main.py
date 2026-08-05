"""
WSC Optuna 웹 런처 — FastAPI 백엔드.

팀원이 웹페이지에서 "실행" 누르면:
1. Supabase 로그인 토큰 확인 (이미 있는 Supabase 프로젝트 재사용)
2. 서버 용량(MAX_CONCURRENT) 안에 여유가 있으면 바로 study_runner.py를
   별도 프로세스로 실행, 꽉 차있으면 대기열에 넣음
3. 프론트엔드는 몇 초마다 /api/status, /api/runs/{run_id}를 조회해서
   동접자 %, 내 trial 진행률을 갱신

실행 방법 (오라클 서버에서):
    pip install -r server/requirements.txt
    uvicorn server.main:app --host 0.0.0.0 --port 8000
(재부팅돼도 자동 재시작되게 하려면 systemd 서비스로 등록 - README 참고)
"""
import os
import sys
import json
import uuid
import subprocess
import threading
import time
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, Header, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.logging_conf import setup_logging
from server.rate_limit import ApiRateLimitMiddleware, enforce_run_creation_rate
from shared.cfg_serde import cfg_to_jsonable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIES_DIR = os.path.join(PROJECT_ROOT, "outputs", "studies")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "study_results")
LOGS_DIR = os.path.join(PROJECT_ROOT, "outputs", "logs")
SIM_RUNS_DIR = os.path.join(PROJECT_ROOT, "outputs", "sim_runs")
TELEMETRY_DIR = os.path.join(PROJECT_ROOT, "outputs", "telemetry")
TELEMETRY_UPLOAD_DIR = os.path.join(PROJECT_ROOT, "outputs", "telemetry_uploads")
RUNS_STATE_PATH = os.environ.get(
    "WSC_RUNS_STATE_PATH",
    os.path.join(PROJECT_ROOT, "outputs", "runs_state.json"),
)
STUDY_RUNNER = os.path.join(PROJECT_ROOT, "server", "study_runner.py")
SIM_RUNNER = os.path.join(PROJECT_ROOT, "server", "sim_runner.py")
TELEMETRY_RUNNER = os.path.join(PROJECT_ROOT, "server", "telemetry_runner.py")

# ---- 설정 (환경변수로 조절 가능, 없으면 기본값) ----
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wijwbujsihhzzjzawfzp.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_IKdkodgmKWm05tQh15bqVg_uNRqdpEO")
MAX_CONCURRENT = int(os.environ.get("WSC_MAX_CONCURRENT", "1"))  # 지금 서버 사양 기준 보수적으로 1
MAX_TRIALS_PER_RUN = int(os.environ.get("WSC_MAX_TRIALS", "100"))  # 한 번 실행에 허용하는 최대 trial 수 (남용 방지)
MAX_SIM_CONCURRENT = int(os.environ.get("WSC_MAX_SIM_CONCURRENT", "2"))
MAX_TELEMETRY_CONCURRENT = int(os.environ.get("WSC_MAX_TELEMETRY_CONCURRENT", "1"))
MAX_TELEMETRY_UPLOAD_BYTES = int(os.environ.get("WSC_TELEMETRY_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
CANCEL_GRACE_SECONDS = int(os.environ.get("WSC_CANCEL_GRACE_SECONDS", "300"))

os.makedirs(STUDIES_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SIM_RUNS_DIR, exist_ok=True)
os.makedirs(TELEMETRY_DIR, exist_ok=True)
os.makedirs(TELEMETRY_UPLOAD_DIR, exist_ok=True)

logger = setup_logging(LOGS_DIR)
logger.info("WSC Optuna launcher starting")

app = FastAPI(title="WSC Optuna Launcher")
app.add_middleware(ApiRateLimitMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # 접속자 IP. Caddy 리버스 프록시 뒤에 있으므로 그냥 두면 전부
    # 127.0.0.1로 찍힌다. systemd의 --proxy-headers --forwarded-allow-ips
    # 127.0.0.1 덕분에 uvicorn이 X-Forwarded-For를 반영해주고, 신뢰
    # 대상을 로컬 프록시로 한정했으므로 헤더 위조로 오염되지 않는다.
    # (Authorization 헤더 값은 절대 로그에 남기지 말 것 - 토큰이다)
    client = request.client.host if request.client else "-"
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception("%s %s %s error %.1fms", client, request.method, request.url.path, elapsed_ms)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s %s %s %.1fms", client, request.method, request.url.path, response.status_code, elapsed_ms)
    if request.url.path == "/" or request.url.path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response

# ---- 실행 상태 관리 (메모리에 보관 - 서버 재시작하면 초기화됨, 진행 중이던 것도 새로 세야 함) ----
_lock = threading.Lock()
RUNS = {}       # run_id -> {user_email, study_name, n_trials, process, status, queued_at, started_at}
QUEUE = []      # 대기 중인 run_id 리스트 (순서대로 처리)
SIM_RUNS = {}
SIM_QUEUE = []
TELEMETRY_RUNS = {}
TELEMETRY_QUEUE = []

TERMINAL_STATUSES = {"done", "error", "lost", "interrupted", "stopped"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _study_result_path(study_name: str):
    return os.path.join(RESULTS_DIR, f"{study_name}.json")


def _study_cancel_path(study_name: str):
    return os.path.join(RESULTS_DIR, f"{study_name}.cancel")


def _sim_result_path(run_id: str):
    return os.path.join(SIM_RUNS_DIR, f"{run_id}.json")


def _telemetry_result_path(run_id: str):
    return os.path.join(TELEMETRY_DIR, f"{run_id}.json")


def _telemetry_progress_path(run_id: str):
    return os.path.join(TELEMETRY_DIR, f"{run_id}_progress.json")


def _sanitize_for_state(run: dict, kind: str):
    allowed = {
        "run_id",
        "user_id",
        "user_email",
        "nickname",
        "study_name",
        "n_trials",
        "params",
        "cfg",
        "status",
        "queued_at",
        "started_at",
        "finished_at",
        "cancel_requested_at",
        "log_path",
        "pid",
        "interrupted_reason",
        "file_name",
        "file_size",
        "stored_path",
        "frame_count",
    }
    clean = {"kind": kind}
    for key in allowed:
        if key in run:
            clean[key] = run.get(key)
    proc = run.get("process")
    if proc is not None:
        clean["pid"] = proc.pid
    return clean


def _state_snapshot_unlocked():
    return {
        "version": 1,
        "saved_at": _now_iso(),
        "runs": [_sanitize_for_state(run, "optuna") for run in RUNS.values()],
        "queue": [run_id for run_id in QUEUE if run_id in RUNS],
        "sim_runs": [_sanitize_for_state(run, "simulation") for run in SIM_RUNS.values()],
        "sim_queue": [run_id for run_id in SIM_QUEUE if run_id in SIM_RUNS],
        "telemetry_runs": [_sanitize_for_state(run, "telemetry") for run in TELEMETRY_RUNS.values()],
        "telemetry_queue": [run_id for run_id in TELEMETRY_QUEUE if run_id in TELEMETRY_RUNS],
    }


def _save_runs_state_unlocked():
    os.makedirs(os.path.dirname(RUNS_STATE_PATH), exist_ok=True)
    tmp_path = f"{RUNS_STATE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_state_snapshot_unlocked(), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, RUNS_STATE_PATH)


def _load_result_status(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("status")
    except (OSError, json.JSONDecodeError):
        return None


def _cleanup_study_files(study_name: str):
    prefixes = (f"{study_name}.db", f"{study_name}_r")
    try:
        for name in os.listdir(STUDIES_DIR):
            if not (name.startswith(prefixes[0]) or name.startswith(prefixes[1])):
                continue
            path = os.path.join(STUDIES_DIR, name)
            try:
                os.remove(path)
                logger.info("removed study file after cancellation %s", name)
            except OSError:
                logger.warning("could not remove study file after cancellation %s", path)
    except OSError:
        logger.warning("study file cleanup failed for %s", study_name, exc_info=True)


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _push_stopped_checkpoint(run: dict):
    access_token = run.get("access_token")
    if not access_token:
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/optuna_runs?on_conflict=study_name",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={
                "study_name": run["study_name"],
                "user_id": run["user_id"],
                "n_trials_completed": 0,
                "n_trials_target": run["n_trials"],
                "best_value": None,
                "best_params": None,
                "status": "stopped",
                "termination_reason": "cancelled before start",
                "updated_at": _now_iso(),
            },
            timeout=15,
        )
    except Exception:
        logger.warning("queued cancellation checkpoint failed run_id=%s", run.get("run_id"), exc_info=True)


def _terminate_run_process(proc, pid):
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        return

    if not _pid_alive(pid):
        return
    try:
        os.kill(int(pid), 15)
        time.sleep(2)
        if _pid_alive(pid):
            os.kill(int(pid), 9)
    except (OSError, TypeError, ValueError):
        logger.warning("could not terminate restored pid=%s", pid, exc_info=True)


def _restore_optuna_run(raw: dict):
    run = dict(raw)
    run.pop("kind", None)
    run["process"] = None
    status = run.get("status")
    study_name = run.get("study_name")
    result_status = _load_result_status(_study_result_path(study_name)) if study_name else None
    if result_status:
        run["status"] = result_status
    elif status == "queued":
        # Optuna needs the user's access token to report trial rows to Supabase.
        # Tokens are intentionally never persisted, so queued Optuna work cannot
        # be restarted after a server reboot.
        run["status"] = "interrupted"
        run["interrupted_reason"] = "server restarted before queued Optuna run could start"
        run["finished_at"] = _now_iso()
    elif status in {"running", "stopping"} and not _pid_alive(run.get("pid")):
        run["status"] = "lost"
        run["interrupted_reason"] = "server restarted and Optuna worker process is no longer alive"
        run["finished_at"] = _now_iso()
    elif status not in {"running", "stopping", "finished_process", "done", "error", "lost", "interrupted", "stopped"}:
        run["status"] = "lost"
    return run


def _restore_sim_run(raw: dict):
    run = dict(raw)
    run.pop("kind", None)
    run["process"] = None
    status = run.get("status")
    result_status = _load_result_status(_sim_result_path(run.get("run_id"))) if run.get("run_id") else None
    if result_status:
        run["status"] = result_status
    elif status == "running" and not _pid_alive(run.get("pid")):
        run["status"] = "lost"
        run["interrupted_reason"] = "server restarted and simulation worker process is no longer alive"
        run["finished_at"] = _now_iso()
    elif status not in {"queued", "running", "finished_process", "done", "error", "lost", "interrupted"}:
        run["status"] = "lost"
    return run


def _restore_telemetry_run(raw: dict):
    run = dict(raw)
    run.pop("kind", None)
    run["process"] = None
    status = run.get("status")
    result_status = _load_result_status(_telemetry_result_path(run.get("run_id"))) if run.get("run_id") else None
    if result_status:
        run["status"] = result_status
    elif status == "queued":
        run["status"] = "interrupted"
        run["interrupted_reason"] = "server restarted before queued telemetry upload could start"
        run["finished_at"] = _now_iso()
        try:
            if run.get("stored_path") and os.path.exists(run["stored_path"]):
                os.remove(run["stored_path"])
        except OSError:
            logger.warning("could not remove interrupted telemetry upload %s", run.get("stored_path"))
    elif status == "running" and not _pid_alive(run.get("pid")):
        run["status"] = "lost"
        run["interrupted_reason"] = "server restarted and telemetry worker process is no longer alive"
        run["finished_at"] = _now_iso()
    elif status not in {"queued", "running", "finished_process", "done", "error", "lost", "interrupted"}:
        run["status"] = "lost"
    return run


def _restore_runs_state():
    try:
        with open(RUNS_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError):
        logger.warning("run state restore failed; starting with empty in-memory queues", exc_info=True)
        return

    with _lock:
        RUNS.clear()
        QUEUE.clear()
        SIM_RUNS.clear()
        SIM_QUEUE.clear()
        TELEMETRY_RUNS.clear()
        TELEMETRY_QUEUE.clear()

        for raw in data.get("runs", []):
            run = _restore_optuna_run(raw)
            if run.get("run_id"):
                RUNS[run["run_id"]] = run

        for raw in data.get("sim_runs", []):
            run = _restore_sim_run(raw)
            if run.get("run_id"):
                SIM_RUNS[run["run_id"]] = run

        for raw in data.get("telemetry_runs", []):
            run = _restore_telemetry_run(raw)
            if run.get("run_id"):
                TELEMETRY_RUNS[run["run_id"]] = run

        for run_id in data.get("sim_queue", []):
            run = SIM_RUNS.get(run_id)
            if run and run.get("status") == "queued":
                SIM_QUEUE.append(run_id)

        for run_id in data.get("telemetry_queue", []):
            run = TELEMETRY_RUNS.get(run_id)
            if run and run.get("status") == "queued":
                TELEMETRY_QUEUE.append(run_id)

        _save_runs_state_unlocked()

    logger.info(
        "restored run state optuna=%s sim=%s sim_queue=%s telemetry=%s telemetry_queue=%s",
        len(RUNS),
        len(SIM_RUNS),
        len(SIM_QUEUE),
        len(TELEMETRY_RUNS),
        len(TELEMETRY_QUEUE),
    )


def _cleanup_run_logs(keep: int = 50):
    try:
        paths = [
            os.path.join(LOGS_DIR, name)
            for name in os.listdir(LOGS_DIR)
            if name.startswith("run_") and name.endswith(".log")
        ]
        paths.sort(key=os.path.getmtime, reverse=True)
        for path in paths[keep:]:
            try:
                os.remove(path)
                logger.info("removed old run log %s", os.path.basename(path))
            except OSError:
                logger.warning("could not remove old run log %s", path)
    except OSError:
        logger.exception("run log cleanup failed")


_cleanup_run_logs()


def _cleanup_sim_outputs(keep_per_user: int = 5, ttl_seconds: int = 24 * 60 * 60):
    now = time.time()
    grouped = {}
    try:
        for name in os.listdir(SIM_RUNS_DIR):
            if not name.endswith(".json") or name.endswith("_progress.json") or name.endswith("_figure.json"):
                continue
            run_id = name[:-5]
            result_path = os.path.join(SIM_RUNS_DIR, name)
            try:
                with open(result_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            user_id = data.get("user_id", "_unknown")
            grouped.setdefault(user_id, []).append((run_id, result_path, os.path.getmtime(result_path)))
    except OSError:
        logger.exception("sim output cleanup failed")
        return

    remove_ids = set()
    for rows in grouped.values():
        rows.sort(key=lambda x: x[2], reverse=True)
        for run_id, _, mtime in rows:
            if now - mtime > ttl_seconds:
                remove_ids.add(run_id)
        for run_id, _, _ in rows[keep_per_user:]:
            remove_ids.add(run_id)

    for run_id in remove_ids:
        for suffix in (".json", ".csv", "_progress.json", "_figure.json", "_payload.json"):
            path = os.path.join(SIM_RUNS_DIR, f"{run_id}{suffix}")
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                logger.warning("could not remove old sim output %s", path)


_cleanup_sim_outputs()


def verify_user(authorization: str | None):
    """Authorization: Bearer <supabase access token> 헤더를 Supabase에 확인 요청."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요해요.")
    token = authorization.removeprefix("Bearer ").strip()
    resp = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="로그인이 만료됐어요. 다시 로그인해주세요.")
    return resp.json()  # {id, email, user_metadata: {...}, ...}


def _active_count():
    return sum(1 for r in RUNS.values() if r["status"] in {"running", "stopping"})


def _active_sim_count():
    return sum(1 for r in SIM_RUNS.values() if r["status"] == "running")


def _active_telemetry_count():
    return sum(1 for r in TELEMETRY_RUNS.values() if r["status"] == "running")


def _try_start_next():
    """대기열 맨 앞을 꺼내서 자리가 있으면 시작. 반드시 _lock 잡고 호출."""
    while QUEUE and _active_count() < MAX_CONCURRENT:
        run_id = QUEUE.pop(0)
        run = RUNS[run_id]
        log_path = os.path.join(LOGS_DIR, f"run_{run_id}.log")
        logger.info("starting run_id=%s study=%s n_trials=%s", run_id, run["study_name"], run["n_trials"])
        with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
            log_file.write(
                f"{_now_iso()} "
                f"starting study={run['study_name']} n_trials={run['n_trials']}\n"
            )
            proc = subprocess.Popen(
                [sys.executable, STUDY_RUNNER, run["study_name"], str(run["n_trials"]),
                 run["user_id"], run["access_token"]],
                cwd=PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        run["process"] = proc
        run["pid"] = proc.pid
        run["log_path"] = log_path
        run["status"] = "running"
        run["started_at"] = _now_iso()
        logger.info("run_id=%s process started pid=%s log=%s", run_id, proc.pid, os.path.basename(log_path))
        _save_runs_state_unlocked()


def _try_start_next_sim():
    while SIM_QUEUE and _active_sim_count() < MAX_SIM_CONCURRENT:
        run_id = SIM_QUEUE.pop(0)
        run = SIM_RUNS[run_id]
        payload_path = os.path.join(SIM_RUNS_DIR, f"{run_id}_payload.json")
        log_path = os.path.join(LOGS_DIR, f"sim_{run_id}.log")
        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump({"params": run["params"], "cfg": run["cfg"], "user_id": run["user_id"]}, f, ensure_ascii=False)
        logger.info("starting sim run_id=%s user_id=%s", run_id, run["user_id"])
        with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
            log_file.write(f"{_now_iso()} starting sim run_id={run_id}\n")
            proc = subprocess.Popen(
                [sys.executable, SIM_RUNNER, run_id, payload_path],
                cwd=PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        run["process"] = proc
        run["pid"] = proc.pid
        run["log_path"] = log_path
        run["status"] = "running"
        run["started_at"] = _now_iso()
        logger.info("sim run_id=%s process started pid=%s log=%s", run_id, proc.pid, os.path.basename(log_path))
        _save_runs_state_unlocked()


def _try_start_next_telemetry():
    while TELEMETRY_QUEUE and _active_telemetry_count() < MAX_TELEMETRY_CONCURRENT:
        run_id = TELEMETRY_QUEUE.pop(0)
        run = TELEMETRY_RUNS[run_id]
        payload_path = os.path.join(TELEMETRY_DIR, f"{run_id}_payload.json")
        log_path = os.path.join(LOGS_DIR, f"telemetry_{run_id}.log")
        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "file_path": run["stored_path"],
                    "file_name": run["file_name"],
                    "file_size": run["file_size"],
                    "user_id": run["user_id"],
                    "access_token": run["access_token"],
                },
                f,
                ensure_ascii=False,
            )
        logger.info("starting telemetry run_id=%s user_id=%s file=%s", run_id, run["user_id"], run["file_name"])
        with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
            log_file.write(f"{_now_iso()} starting telemetry run_id={run_id}\n")
            proc = subprocess.Popen(
                [sys.executable, TELEMETRY_RUNNER, run_id, payload_path],
                cwd=PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        run["process"] = proc
        run["pid"] = proc.pid
        run["log_path"] = log_path
        run["status"] = "running"
        run["started_at"] = _now_iso()
        logger.info("telemetry run_id=%s process started pid=%s log=%s", run_id, proc.pid, os.path.basename(log_path))
        _save_runs_state_unlocked()


def _watcher_loop():
    """백그라운드에서 끝난 프로세스를 정리하고, 자리 나면 대기열에서 다음 걸 시작."""
    while True:
        time.sleep(2)
        with _lock:
            changed = False
            for run in RUNS.values():
                if run["status"] == "running" and run["process"].poll() is not None:
                    returncode = run["process"].returncode
                    if returncode == 0:
                        logger.info("run finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("run finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"  # 아래 /api/runs 조회 시 결과 파일 보고 done/error로 확정
            _try_start_next()
            for run in SIM_RUNS.values():
                if run["status"] == "running" and run["process"].poll() is not None:
                    returncode = run["process"].returncode
                    if returncode == 0:
                        logger.info("sim finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("sim finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"
            _try_start_next_sim()
            for run in TELEMETRY_RUNS.values():
                if run["status"] == "running" and run["process"].poll() is not None:
                    returncode = run["process"].returncode
                    if returncode == 0:
                        logger.info("telemetry finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("telemetry finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"
            _try_start_next_telemetry()


def _watcher_loop_persistent():
    """Watch child processes, including restored jobs without Popen handles."""
    while True:
        time.sleep(2)
        with _lock:
            changed = False
            for run in RUNS.values():
                if run["status"] not in {"running", "stopping"}:
                    continue
                proc = run.get("process")
                if proc is not None and proc.poll() is not None:
                    returncode = proc.returncode
                    if returncode == 0:
                        logger.info("run finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("run finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"
                    run["finished_at"] = _now_iso()
                    changed = True
                elif proc is None and not _pid_alive(run.get("pid")):
                    run["status"] = "finished_process" if os.path.exists(_study_result_path(run.get("study_name"))) else "lost"
                    run["finished_at"] = _now_iso()
                    changed = True
                elif run["status"] == "stopping":
                    requested_at = _parse_iso(run.get("cancel_requested_at"))
                    elapsed = (
                        datetime.now(timezone.utc) - requested_at
                    ).total_seconds() if requested_at else 0
                    if elapsed > CANCEL_GRACE_SECONDS:
                        logger.warning("cancel grace timed out run_id=%s pid=%s", run.get("run_id"), run.get("pid"))
                        _terminate_run_process(proc, run.get("pid"))
                        run["status"] = "stopped"
                        run["finished_at"] = _now_iso()
                        run["interrupted_reason"] = "graceful stop timed out"
                        _cleanup_study_files(run.get("study_name"))
                        cancel_path = _study_cancel_path(run.get("study_name"))
                        try:
                            if os.path.exists(cancel_path):
                                os.remove(cancel_path)
                        except OSError:
                            logger.warning("could not remove cancel flag %s", cancel_path)
                        changed = True

            _try_start_next()

            for run in SIM_RUNS.values():
                if run["status"] != "running":
                    continue
                proc = run.get("process")
                if proc is not None and proc.poll() is not None:
                    returncode = proc.returncode
                    if returncode == 0:
                        logger.info("sim finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("sim finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"
                    run["finished_at"] = _now_iso()
                    changed = True
                elif proc is None and not _pid_alive(run.get("pid")):
                    run["status"] = "finished_process" if os.path.exists(_sim_result_path(run.get("run_id"))) else "lost"
                    run["finished_at"] = _now_iso()
                    changed = True

            _try_start_next_sim()

            for run in TELEMETRY_RUNS.values():
                if run["status"] != "running":
                    continue
                proc = run.get("process")
                if proc is not None and proc.poll() is not None:
                    returncode = proc.returncode
                    if returncode == 0:
                        logger.info("telemetry finished run_id=%s returncode=0", run.get("run_id", "?"))
                    else:
                        logger.error("telemetry finished run_id=%s returncode=%s", run.get("run_id", "?"), returncode)
                    run["status"] = "finished_process"
                    run["finished_at"] = _now_iso()
                    changed = True
                elif proc is None and not _pid_alive(run.get("pid")):
                    run["status"] = "finished_process" if os.path.exists(_telemetry_result_path(run.get("run_id"))) else "lost"
                    run["finished_at"] = _now_iso()
                    changed = True

            _try_start_next_telemetry()
            if changed:
                _save_runs_state_unlocked()


_restore_runs_state()
threading.Thread(target=_watcher_loop_persistent, daemon=True).start()


def _read_progress_data(study_name: str):
    """study_runner.py가 매 trial마다 남기는 진행률 파일을 읽습니다.
    (study 파일을 직접 열어서 세는 것보다 가볍고, 디스크 부족으로 study가
    로테이션돼도 이 파일 경로는 그대로라 끊김 없이 진행률을 보여줄 수 있음)"""
    try:
        progress_path = os.path.join(RESULTS_DIR, f"{study_name}_progress.json")
        if not os.path.exists(progress_path):
            return {"completed": 0, "started_at": None}
        with open(progress_path, encoding="utf-8") as f:
            data = json.load(f)
            return {"completed": data.get("completed", 0), "started_at": data.get("started_at")}
    except Exception:
        return {"completed": None, "started_at": None}


# 실제로 관측된 "trial 하나당 걸리는 시간" - 셰이프를 바꾸거나(Ampere<->Micro)
# 서버가 바빠지면 자연스럽게 다시 계산돼요. 아직 아무 데이터도 없을 때 쓰는
# 초기값이라 정확하지 않을 수 있어요 - 첫 실행이 끝나면 바로 실측값으로 바뀝니다.
_pace_lock = threading.Lock()
_last_known_pace_seconds = 90.0


def _update_pace(seconds_per_trial):
    global _last_known_pace_seconds
    if seconds_per_trial and seconds_per_trial > 0:
        with _pace_lock:
            _last_known_pace_seconds = seconds_per_trial


def _get_pace():
    with _pace_lock:
        return _last_known_pace_seconds


@app.get("/api/status")
def get_status():
    with _lock:
        active = _active_count()
        queued = len(QUEUE)
        running_list = [
            {"nickname": r["nickname"], "study_name": r["study_name"], "n_trials": r["n_trials"], "status": r["status"]}
            for r in RUNS.values() if r["status"] in {"running", "stopping"}
        ]
        queue_list = [
            {"nickname": RUNS[run_id]["nickname"], "n_trials": RUNS[run_id]["n_trials"]}
            for run_id in QUEUE
        ]
    for item in running_list:
        progress = _read_progress_data(item.pop("study_name"))
        item["trial_current"] = progress["completed"]
    occupancy = round(active / MAX_CONCURRENT * 100) if MAX_CONCURRENT else 0
    if occupancy < 50:
        level = "원활"
    elif occupancy < 75:
        level = "복잡"
    else:
        level = "혼잡"
    return {
        "active": active,
        "max_concurrent": MAX_CONCURRENT,
        "queued": queued,
        "occupancy_pct": occupancy,
        "level": level,
        "running": running_list,
        "queue": queue_list,
    }


@app.get("/api/my-active-run")
def get_my_active_run(authorization: str | None = Header(default=None)):
    """로그인한 사용자가 가장 최근에 시작한 실행의 run_id를 돌려줍니다.
    페이지를 새로고침하거나 나갔다 다시 들어와도(브라우저 메모리엔 run_id가
    안 남아있으니) 이걸로 "내가 뭘 돌리고 있었는지" 다시 찾아서 진행 상황
    카드를 이어서 보여줄 수 있어요. 상태(대기/실행/완료/오류)는 안 가리고
    가장 최근 것 하나만 돌려주고, 실제 상태 판단은 기존 /api/runs/{id}가 함."""
    user = verify_user(authorization)
    user_id = user.get("id")
    with _lock:
        mine = [
            (run_id, run)
            for run_id, run in RUNS.items()
            if run["user_id"] == user_id and run.get("status") not in TERMINAL_STATUSES
        ]
    if not mine:
        return {"run_id": None}
    mine.sort(key=lambda x: x[1]["queued_at"], reverse=True)
    return {"run_id": mine[0][0]}


@app.post("/api/runs")
def create_run(payload: dict, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    enforce_run_creation_rate(user.get("id"), "/api/runs")
    access_token = authorization.removeprefix("Bearer ").strip()
    n_trials = int(payload.get("n_trials", 20))
    if n_trials < 1 or n_trials > MAX_TRIALS_PER_RUN:
        raise HTTPException(status_code=400, detail=f"trial 수는 1~{MAX_TRIALS_PER_RUN} 사이여야 해요.")

    run_id = uuid.uuid4().hex[:12]
    nickname = (user.get("user_metadata") or {}).get("nickname") or user.get("email", "user")
    safe_nick = "".join(c for c in nickname if c.isalnum())[:20] or "user"
    study_name = f"WSC_{safe_nick}_{run_id}"

    with _lock:
        RUNS[run_id] = {
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "nickname": nickname,
            "access_token": access_token,
            "study_name": study_name,
            "n_trials": n_trials,
            "process": None,
            "status": "queued",
            "queued_at": _now_iso(),
            "started_at": None,
            "run_id": run_id,
            "log_path": None,
        }
        QUEUE.append(run_id)
        logger.info("queued run_id=%s user_id=%s nickname=%s n_trials=%s", run_id, user.get("id"), nickname, n_trials)
        _save_runs_state_unlocked()
        _try_start_next()

    return {"run_id": run_id, "study_name": study_name}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    user_id = user.get("id")
    with _lock:
        run = RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="해당 실행을 찾을 수 없어요.")
        if run["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="본인의 실행만 중단할 수 있어요.")

        status = run.get("status")
        if status in TERMINAL_STATUSES:
            return {"run_id": run_id, "status": status}
        if status == "queued":
            if run_id in QUEUE:
                QUEUE.remove(run_id)
            run["status"] = "stopped"
            run["finished_at"] = _now_iso()
            run["interrupted_reason"] = "cancelled before start"
            logger.info("cancelled queued run_id=%s user_id=%s", run_id, user_id)
            _push_stopped_checkpoint(run)
            _save_runs_state_unlocked()
            _try_start_next()
            return {"run_id": run_id, "status": "stopped"}
        if status == "running":
            cancel_path = _study_cancel_path(run["study_name"])
            with open(cancel_path, "w", encoding="utf-8") as f:
                json.dump({"run_id": run_id, "requested_at": _now_iso()}, f)
            run["status"] = "stopping"
            run["cancel_requested_at"] = _now_iso()
            logger.info("requested graceful cancel run_id=%s user_id=%s", run_id, user_id)
            _save_runs_state_unlocked()
            return {"run_id": run_id, "status": "stopping"}
        if status == "stopping":
            return {"run_id": run_id, "status": "stopping"}

    raise HTTPException(status_code=400, detail="현재 상태에서는 중단할 수 없어요.")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    with _lock:
        run = RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="해당 실행을 찾을 수 없어요.")
        if run["user_id"] != user.get("id"):
            raise HTTPException(status_code=403, detail="본인의 실행만 조회할 수 있어요.")
        status = run["status"]
        study_name = run["study_name"]
        n_trials = run["n_trials"]
        position_in_queue = QUEUE.index(run_id) + 1 if run_id in QUEUE else None
        # 대기 예상시간 계산용: 지금 앞서 실행 중인 것들의 남은 trial + 내 앞의 대기열 trial 총합
        ahead_trials = 0
        if position_in_queue is not None:
            for other in RUNS.values():
                if other["status"] in {"running", "stopping"}:
                    other_progress = _read_progress_data(other["study_name"])
                    other_done = other_progress["completed"] or 0
                    ahead_trials += max(other["n_trials"] - other_done, 0)
            for other_id in QUEUE[:position_in_queue - 1]:
                ahead_trials += RUNS[other_id]["n_trials"]

    if status in ("finished_process", "done", "error", "stopped"):
        result_path = _study_result_path(study_name)
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            with _lock:
                run["status"] = result["status"]  # done | stopped | error
                run["finished_at"] = run.get("finished_at") or _now_iso()
                _save_runs_state_unlocked()
            return {"run_id": run_id, "status": result["status"], "n_trials": n_trials, "result": result}
        if status == "stopped":
            return {
                "run_id": run_id,
                "status": "stopped",
                "n_trials": n_trials,
                "detail": run.get("interrupted_reason") or "Search was stopped before results were written.",
                "result": {
                    "status": "stopped",
                    "study_name": study_name,
                    "n_trials": n_trials,
                    "best_value": None,
                    "best_params": None,
                    "termination_reason": run.get("interrupted_reason"),
                },
            }
        # 프로세스는 끝났는데 결과 파일이 아직 안 써졌으면 잠깐 더 기다리라고 안내
        return {"run_id": run_id, "status": "finalizing", "n_trials": n_trials}

    if status in ("lost", "interrupted"):
        return {
            "run_id": run_id,
            "status": status,
            "n_trials": n_trials,
            "detail": run.get("interrupted_reason") or "Run is no longer active.",
        }

    if status == "queued":
        pace = _get_pace()
        return {
            "run_id": run_id,
            "status": "queued",
            "position": position_in_queue,
            "n_trials": n_trials,
            "estimated_wait_seconds": round(ahead_trials * pace),
        }

    # running / stopping
    progress = _read_progress_data(study_name)
    trial_current = progress["completed"]
    estimated_remaining_seconds = None
    if trial_current:
        pace = _get_pace()
        if progress["started_at"]:
            try:
                started = datetime.fromisoformat(progress["started_at"])
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if trial_current > 0:
                    pace = elapsed / trial_current  # 이 실행 자체의 실측 속도가 더 정확함
                    _update_pace(pace)  # 다음 대기자들의 예상시간 계산에도 이 실측값을 반영
            except (ValueError, TypeError):
                pass
        estimated_remaining_seconds = round(max(n_trials - trial_current, 0) * pace)

    return {
        "run_id": run_id,
        "status": status,
        "n_trials": n_trials,
        "trial_current": trial_current,
        "progress_pct": round(trial_current / n_trials * 100) if trial_current is not None else None,
        "estimated_remaining_seconds": estimated_remaining_seconds,
    }


def _read_sim_progress(run_id: str):
    progress_path = os.path.join(SIM_RUNS_DIR, f"{run_id}_progress.json")
    try:
        with open(progress_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"pct": 0.0, "started_at": None}


def _read_telemetry_progress(run_id: str):
    try:
        with open(_telemetry_progress_path(run_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"status": "queued", "frame_count": 0, "started_at": None}


def _safe_upload_name(name: str):
    base = os.path.basename(name or "canlog.csv")
    safe = "".join(c if c.isalnum() or c in {".", "-", "_"} else "_" for c in base)
    return safe[:120] or "canlog.csv"


def _supabase_headers(access_token: str, content_type: str | None = "application/json"):
    headers = {"Authorization": f"Bearer {access_token}", "apikey": SUPABASE_ANON_KEY}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _supabase_get(path: str, access_token: str, params: dict | None = None):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers=_supabase_headers(access_token, None),
        params=params or {},
        timeout=20,
    )
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=resp.status_code, detail="Supabase telemetry access denied.")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Supabase telemetry query failed.")
    return resp.json()

@app.post("/api/sim/runs")
def create_sim_run(payload: dict, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    enforce_run_creation_rate(user.get("id"), "/api/sim/runs")
    run_id = uuid.uuid4().hex[:12]
    params = payload.get("params") or {}
    cfg = payload.get("cfg") or {}
    nickname = (user.get("user_metadata") or {}).get("nickname") or user.get("email", "user")

    with _lock:
        SIM_RUNS[run_id] = {
            "run_id": run_id,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "nickname": nickname,
            "params": params,
            "cfg": cfg,
            "process": None,
            "status": "queued",
            "queued_at": _now_iso(),
            "started_at": None,
            "log_path": None,
        }
        SIM_QUEUE.append(run_id)
        logger.info("queued sim run_id=%s user_id=%s nickname=%s", run_id, user.get("id"), nickname)
        _save_runs_state_unlocked()
        _try_start_next_sim()
    return {"run_id": run_id}


@app.get("/api/sim/my-active-run")
def get_my_active_sim_run(authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    user_id = user.get("id")
    with _lock:
        mine = [
            (run_id, run)
            for run_id, run in SIM_RUNS.items()
            if run["user_id"] == user_id and run.get("status") not in TERMINAL_STATUSES
        ]
    if not mine:
        return {"run_id": None}
    mine.sort(key=lambda x: x[1]["queued_at"], reverse=True)
    return {"run_id": mine[0][0]}


@app.get("/api/sim/runs/{run_id}")
def get_sim_run(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    with _lock:
        run = SIM_RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Simulation run not found.")
        if run["user_id"] != user.get("id"):
            raise HTTPException(status_code=403, detail="You can only read your own simulation.")
        status = run["status"]
        position = SIM_QUEUE.index(run_id) + 1 if run_id in SIM_QUEUE else None

    if status in ("finished_process", "done", "error"):
        result_path = _sim_result_path(run_id)
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            final_status = result.get("status", "error")
            with _lock:
                run["status"] = final_status
                run["finished_at"] = run.get("finished_at") or _now_iso()
                _save_runs_state_unlocked()
            return {"run_id": run_id, "status": final_status, "result": result}
        return {"run_id": run_id, "status": "finalizing"}

    if status in ("lost", "interrupted"):
        return {
            "run_id": run_id,
            "status": status,
            "detail": run.get("interrupted_reason") or "Simulation is no longer active.",
            "progress_pct": 0,
        }

    if status == "queued":
        return {"run_id": run_id, "status": "queued", "position": position, "progress_pct": 0}

    progress = _read_sim_progress(run_id)
    return {
        "run_id": run_id,
        "status": "running",
        "progress_pct": round(float(progress.get("pct") or 0) * 100, 1),
    }


@app.get("/api/sim/runs/{run_id}/figure")
def get_sim_figure(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    with _lock:
        run = SIM_RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Simulation run not found.")
        if run["user_id"] != user.get("id"):
            raise HTTPException(status_code=403, detail="You can only read your own simulation.")
    path = os.path.join(SIM_RUNS_DIR, f"{run_id}_figure.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Figure is not ready.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/sim/runs/{run_id}/csv")
def get_sim_csv(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    with _lock:
        run = SIM_RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Simulation run not found.")
        if run["user_id"] != user.get("id"):
            raise HTTPException(status_code=403, detail="You can only read your own simulation.")
    path = os.path.join(SIM_RUNS_DIR, f"{run_id}.csv")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="CSV is not ready.")
    return FileResponse(path, media_type="text/csv", filename="sim_result.csv")


@app.get("/api/sim/route")
def get_sim_route():
    route = None
    try:
        import base64
        import pandas as pd

        route_path = os.path.join(PROJECT_ROOT, "2027 BWSC TRACK.csv")
        route_df = pd.read_csv(route_path)
        image_path = os.path.join(PROJECT_ROOT, "assets", "australia_silhouette.png")
        image_data = None
        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                image_data = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        route = {
            "lon": route_df["lon"].iloc[::5].tolist(),
            "lat": route_df["lat"].iloc[::5].tolist(),
            "bounds": {
                "minx": 113.18476562500001,
                "miny": -39.1455078125,
                "maxx": 153.61689453125,
                "maxy": -10.707324218750003,
            },
            "bg_image": image_data,
        }
    except Exception:
        logger.exception("route metadata load failed")
        raise HTTPException(status_code=500, detail="Route metadata failed to load.")
    return route


@app.get("/api/sim/default-config")
def get_default_sim_config():
    try:
        from Configs.Vehicle_Params import build_default_cfg
        from mpc.mpc_controller import mpc_default_params

        return {"cfg": cfg_to_jsonable(build_default_cfg()), "params": mpc_default_params}
    except Exception:
        logger.exception("default config load failed")
        raise HTTPException(status_code=500, detail="Default config failed to load.")


@app.get("/api/telemetry/signals")
def get_telemetry_signals():
    try:
        from telemetry.signals import load_signal_defs

        rows = load_signal_defs()
        return {"signals": rows, "primary": [row for row in rows if row.get("priority") == "PRIMARY"]}
    except Exception:
        logger.exception("telemetry signal load failed")
        raise HTTPException(status_code=500, detail="Telemetry signal definitions failed to load.")


@app.post("/api/telemetry/logs")
async def upload_telemetry_log(file: UploadFile = File(...), authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    enforce_run_creation_rate(user.get("id"), "/api/telemetry/logs")
    access_token = authorization.removeprefix("Bearer ").strip()
    run_id = uuid.uuid4().hex[:12]
    file_name = _safe_upload_name(file.filename or "canlog.csv")
    stored_path = os.path.join(TELEMETRY_UPLOAD_DIR, f"{run_id}_{file_name}")
    total = 0
    try:
        with open(stored_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TELEMETRY_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Telemetry log exceeds the upload size limit.")
                out.write(chunk)
    except HTTPException:
        try:
            os.remove(stored_path)
        except OSError:
            pass
        raise
    finally:
        await file.close()

    nickname = (user.get("user_metadata") or {}).get("nickname") or user.get("email", "user")
    with _lock:
        TELEMETRY_RUNS[run_id] = {
            "run_id": run_id,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "nickname": nickname,
            "access_token": access_token,
            "file_name": file_name,
            "file_size": total,
            "stored_path": stored_path,
            "process": None,
            "status": "queued",
            "queued_at": _now_iso(),
            "started_at": None,
            "log_path": None,
            "frame_count": 0,
        }
        TELEMETRY_QUEUE.append(run_id)
        logger.info("queued telemetry run_id=%s user_id=%s file=%s size=%s", run_id, user.get("id"), file_name, total)
        _save_runs_state_unlocked()
        _try_start_next_telemetry()
    return {"run_id": run_id, "file_name": file_name, "file_size": total}


@app.get("/api/telemetry/logs")
def list_telemetry_logs(authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    access_token = authorization.removeprefix("Bearer ").strip()
    rows = _supabase_get(
        "telemetry_logs",
        access_token,
        {
            "select": "id,file_name,status,frame_count,min_timestamp,max_timestamp,created_at,finished_at",
            "user_id": f"eq.{user.get('id')}",
            "order": "created_at.desc",
            "limit": "20",
        },
    )
    with _lock:
        active = [
            {
                "id": run_id,
                "file_name": run.get("file_name"),
                "status": run.get("status"),
                "frame_count": _read_telemetry_progress(run_id).get("frame_count", run.get("frame_count", 0)),
                "created_at": run.get("queued_at"),
            }
            for run_id, run in TELEMETRY_RUNS.items()
            if run.get("user_id") == user.get("id") and run.get("status") not in TERMINAL_STATUSES
        ]
    active_ids = {row.get("id") for row in active}
    return {"logs": active + [row for row in rows if row.get("id") not in active_ids]}


@app.get("/api/telemetry/logs/{run_id}")
def get_telemetry_log(run_id: str, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    with _lock:
        run = TELEMETRY_RUNS.get(run_id)
        if not run:
            run = None
        elif run["user_id"] != user.get("id"):
            raise HTTPException(status_code=403, detail="You can only read your own telemetry log.")
        if run:
            status = run.get("status")
            position = TELEMETRY_QUEUE.index(run_id) + 1 if run_id in TELEMETRY_QUEUE else None
        else:
            status = None
            position = None

    if run and status in ("finished_process", "done", "error"):
        result_path = _telemetry_result_path(run_id)
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            final_status = result.get("status", "error")
            with _lock:
                run["status"] = final_status
                run["finished_at"] = run.get("finished_at") or _now_iso()
                run["frame_count"] = result.get("frame_count", run.get("frame_count", 0))
                _save_runs_state_unlocked()
            return {"run_id": run_id, "status": final_status, "result": result}
        return {"run_id": run_id, "status": "finalizing"}

    if run and status == "queued":
        return {"run_id": run_id, "status": "queued", "position": position, "progress_pct": 0, "frame_count": 0}

    if run and status == "running":
        progress = _read_telemetry_progress(run_id)
        return {
            "run_id": run_id,
            "status": progress.get("status", "running"),
            "frame_count": progress.get("frame_count", 0),
            "progress_pct": None,
        }

    if run and status in ("lost", "interrupted"):
        return {
            "run_id": run_id,
            "status": status,
            "detail": run.get("interrupted_reason") or "Telemetry upload is no longer active.",
            "frame_count": run.get("frame_count", 0),
        }

    access_token = authorization.removeprefix("Bearer ").strip()
    rows = _supabase_get(
        "telemetry_logs",
        access_token,
        {"select": "*", "id": f"eq.{run_id}", "user_id": f"eq.{user.get('id')}", "limit": "1"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Telemetry log not found.")
    return {"run_id": run_id, "status": rows[0].get("status"), "result": rows[0]}


@app.get("/api/telemetry/logs/{run_id}/series")
def get_telemetry_series(run_id: str, can_id: str | None = None, limit: int = 1000, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    access_token = authorization.removeprefix("Bearer ").strip()
    log_rows = _supabase_get(
        "telemetry_logs",
        access_token,
        {"select": "id", "id": f"eq.{run_id}", "user_id": f"eq.{user.get('id')}", "limit": "1"},
    )
    if not log_rows:
        raise HTTPException(status_code=404, detail="Telemetry log not found.")
    params = {
        "select": "frame_index,timestamp_text,can_id,raw_data_hex,seg_one,seg_two",
        "log_id": f"eq.{run_id}",
        "order": "frame_index.asc",
        "limit": str(max(1, min(int(limit), 5000))),
    }
    if can_id:
        params["can_id"] = f"eq.{can_id}"
    rows = _supabase_get("telemetry_frames", access_token, params)
    return {"frames": rows}


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
