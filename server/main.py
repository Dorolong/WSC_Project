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
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.logging_conf import setup_logging
from shared.cfg_serde import cfg_to_jsonable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIES_DIR = os.path.join(PROJECT_ROOT, "outputs", "studies")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "study_results")
LOGS_DIR = os.path.join(PROJECT_ROOT, "outputs", "logs")
SIM_RUNS_DIR = os.path.join(PROJECT_ROOT, "outputs", "sim_runs")
STUDY_RUNNER = os.path.join(PROJECT_ROOT, "server", "study_runner.py")
SIM_RUNNER = os.path.join(PROJECT_ROOT, "server", "sim_runner.py")

# ---- 설정 (환경변수로 조절 가능, 없으면 기본값) ----
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wijwbujsihhzzjzawfzp.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_IKdkodgmKWm05tQh15bqVg_uNRqdpEO")
MAX_CONCURRENT = int(os.environ.get("WSC_MAX_CONCURRENT", "1"))  # 지금 서버 사양 기준 보수적으로 1
MAX_TRIALS_PER_RUN = int(os.environ.get("WSC_MAX_TRIALS", "100"))  # 한 번 실행에 허용하는 최대 trial 수 (남용 방지)
MAX_SIM_CONCURRENT = int(os.environ.get("WSC_MAX_SIM_CONCURRENT", "2"))

os.makedirs(STUDIES_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SIM_RUNS_DIR, exist_ok=True)

logger = setup_logging(LOGS_DIR)
logger.info("WSC Optuna launcher starting")

app = FastAPI(title="WSC Optuna Launcher")


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
    return response

# ---- 실행 상태 관리 (메모리에 보관 - 서버 재시작하면 초기화됨, 진행 중이던 것도 새로 세야 함) ----
_lock = threading.Lock()
RUNS = {}       # run_id -> {user_email, study_name, n_trials, process, status, queued_at, started_at}
QUEUE = []      # 대기 중인 run_id 리스트 (순서대로 처리)
SIM_RUNS = {}
SIM_QUEUE = []


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
    return sum(1 for r in RUNS.values() if r["status"] == "running")


def _active_sim_count():
    return sum(1 for r in SIM_RUNS.values() if r["status"] == "running")


def _try_start_next():
    """대기열 맨 앞을 꺼내서 자리가 있으면 시작. 반드시 _lock 잡고 호출."""
    while QUEUE and _active_count() < MAX_CONCURRENT:
        run_id = QUEUE.pop(0)
        run = RUNS[run_id]
        log_path = os.path.join(LOGS_DIR, f"run_{run_id}.log")
        logger.info("starting run_id=%s study=%s n_trials=%s", run_id, run["study_name"], run["n_trials"])
        with open(log_path, "a", encoding="utf-8", buffering=1) as log_file:
            log_file.write(
                f"{datetime.now(timezone.utc).isoformat()} "
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
        run["log_path"] = log_path
        run["status"] = "running"
        run["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("run_id=%s process started pid=%s log=%s", run_id, proc.pid, os.path.basename(log_path))


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
            log_file.write(f"{datetime.now(timezone.utc).isoformat()} starting sim run_id={run_id}\n")
            proc = subprocess.Popen(
                [sys.executable, SIM_RUNNER, run_id, payload_path],
                cwd=PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        run["process"] = proc
        run["log_path"] = log_path
        run["status"] = "running"
        run["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("sim run_id=%s process started pid=%s log=%s", run_id, proc.pid, os.path.basename(log_path))


def _watcher_loop():
    """백그라운드에서 끝난 프로세스를 정리하고, 자리 나면 대기열에서 다음 걸 시작."""
    while True:
        time.sleep(2)
        with _lock:
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


threading.Thread(target=_watcher_loop, daemon=True).start()


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
            {"nickname": r["nickname"], "study_name": r["study_name"], "n_trials": r["n_trials"]}
            for r in RUNS.values() if r["status"] == "running"
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
        mine = [(run_id, run) for run_id, run in RUNS.items() if run["user_id"] == user_id]
    if not mine:
        return {"run_id": None}
    mine.sort(key=lambda x: x[1]["queued_at"], reverse=True)
    return {"run_id": mine[0][0]}


@app.post("/api/runs")
def create_run(payload: dict, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
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
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "run_id": run_id,
            "log_path": None,
        }
        QUEUE.append(run_id)
        logger.info("queued run_id=%s user_id=%s nickname=%s n_trials=%s", run_id, user.get("id"), nickname, n_trials)
        _try_start_next()

    return {"run_id": run_id, "study_name": study_name}


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
                if other["status"] == "running":
                    other_progress = _read_progress_data(other["study_name"])
                    other_done = other_progress["completed"] or 0
                    ahead_trials += max(other["n_trials"] - other_done, 0)
            for other_id in QUEUE[:position_in_queue - 1]:
                ahead_trials += RUNS[other_id]["n_trials"]

    if status in ("finished_process", "done", "error"):
        result_path = os.path.join(RESULTS_DIR, f"{study_name}.json")
        if os.path.exists(result_path):
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            with _lock:
                run["status"] = result["status"]  # done | error
            return {"run_id": run_id, "status": result["status"], "n_trials": n_trials, "result": result}
        # 프로세스는 끝났는데 결과 파일이 아직 안 써졌으면 잠깐 더 기다리라고 안내
        return {"run_id": run_id, "status": "finalizing", "n_trials": n_trials}

    if status == "queued":
        pace = _get_pace()
        return {
            "run_id": run_id,
            "status": "queued",
            "position": position_in_queue,
            "n_trials": n_trials,
            "estimated_wait_seconds": round(ahead_trials * pace),
        }

    # running
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
        "status": "running",
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


def _sim_result_path(run_id: str):
    return os.path.join(SIM_RUNS_DIR, f"{run_id}.json")


@app.post("/api/sim/runs")
def create_sim_run(payload: dict, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
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
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "log_path": None,
        }
        SIM_QUEUE.append(run_id)
        logger.info("queued sim run_id=%s user_id=%s nickname=%s", run_id, user.get("id"), nickname)
        _try_start_next_sim()
    return {"run_id": run_id}


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
            return {"run_id": run_id, "status": final_status, "result": result}
        return {"run_id": run_id, "status": "finalizing"}

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


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
