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
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIES_DIR = os.path.join(PROJECT_ROOT, "outputs", "studies")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "study_results")
STUDY_RUNNER = os.path.join(PROJECT_ROOT, "server", "study_runner.py")

# ---- 설정 (환경변수로 조절 가능, 없으면 기본값) ----
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wijwbujsihhzzjzawfzp.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_IKdkodgmKWm05tQh15bqVg_uNRqdpEO")
MAX_CONCURRENT = int(os.environ.get("WSC_MAX_CONCURRENT", "1"))  # 지금 서버 사양 기준 보수적으로 1
MAX_TRIALS_PER_RUN = int(os.environ.get("WSC_MAX_TRIALS", "100"))  # 한 번 실행에 허용하는 최대 trial 수 (남용 방지)

os.makedirs(STUDIES_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

app = FastAPI(title="WSC Optuna Launcher")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 팀 내부용 도구라 단순하게. 필요하면 특정 도메인으로 좁힐 것.
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 실행 상태 관리 (메모리에 보관 - 서버 재시작하면 초기화됨, 진행 중이던 것도 새로 세야 함) ----
_lock = threading.Lock()
RUNS = {}       # run_id -> {user_email, study_name, n_trials, process, status, queued_at, started_at}
QUEUE = []      # 대기 중인 run_id 리스트 (순서대로 처리)


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


def _try_start_next():
    """대기열 맨 앞을 꺼내서 자리가 있으면 시작. 반드시 _lock 잡고 호출."""
    while QUEUE and _active_count() < MAX_CONCURRENT:
        run_id = QUEUE.pop(0)
        run = RUNS[run_id]
        proc = subprocess.Popen(
            [sys.executable, STUDY_RUNNER, run["study_name"], str(run["n_trials"])],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        run["process"] = proc
        run["status"] = "running"
        run["started_at"] = datetime.now(timezone.utc).isoformat()


def _watcher_loop():
    """백그라운드에서 끝난 프로세스를 정리하고, 자리 나면 대기열에서 다음 걸 시작."""
    while True:
        time.sleep(2)
        with _lock:
            for run in RUNS.values():
                if run["status"] == "running" and run["process"].poll() is not None:
                    run["status"] = "finished_process"  # 아래 /api/runs 조회 시 결과 파일 보고 done/error로 확정
            _try_start_next()


threading.Thread(target=_watcher_loop, daemon=True).start()


def _read_trial_progress(study_name: str):
    """Optuna study의 sqlite storage를 직접 읽어서 완료된 trial 수를 셉니다."""
    try:
        import optuna
        db_path = os.path.join(STUDIES_DIR, f"{study_name}.db")
        if not os.path.exists(db_path):
            return 0
        study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{db_path}")
        completed = sum(1 for t in study.get_trials(deepcopy=False) if t.state.is_finished())
        return completed
    except Exception:
        return None


@app.get("/api/status")
def get_status():
    with _lock:
        active = _active_count()
        queued = len(QUEUE)
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
    }


@app.post("/api/runs")
def create_run(payload: dict, authorization: str | None = Header(default=None)):
    user = verify_user(authorization)
    n_trials = int(payload.get("n_trials", 20))
    if n_trials < 1 or n_trials > MAX_TRIALS_PER_RUN:
        raise HTTPException(status_code=400, detail=f"trial 수는 1~{MAX_TRIALS_PER_RUN} 사이여야 해요.")

    run_id = uuid.uuid4().hex[:12]
    nickname = (user.get("user_metadata") or {}).get("nickname") or user.get("email", "user")
    safe_nick = "".join(c for c in nickname if c.isalnum())[:20] or "user"
    study_name = f"WSC_{safe_nick}_{run_id}"

    with _lock:
        RUNS[run_id] = {
            "user_email": user.get("email"),
            "study_name": study_name,
            "n_trials": n_trials,
            "process": None,
            "status": "queued",
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
        }
        QUEUE.append(run_id)
        _try_start_next()

    return {"run_id": run_id, "study_name": study_name}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, authorization: str | None = Header(default=None)):
    verify_user(authorization)
    with _lock:
        run = RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="해당 실행을 찾을 수 없어요.")
        status = run["status"]
        study_name = run["study_name"]
        n_trials = run["n_trials"]
        position_in_queue = QUEUE.index(run_id) + 1 if run_id in QUEUE else None

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
        return {"run_id": run_id, "status": "queued", "position": position_in_queue, "n_trials": n_trials}

    # running
    trial_current = _read_trial_progress(study_name)
    return {
        "run_id": run_id,
        "status": "running",
        "n_trials": n_trials,
        "trial_current": trial_current,
        "progress_pct": round(trial_current / n_trials * 100) if trial_current is not None else None,
    }


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
