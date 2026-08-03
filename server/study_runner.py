"""
웹에서 트리거된 Optuna 탐색을 실제로 돌리는 스크립트.
server/main.py(FastAPI)가 이 파일을 별도 프로세스로 띄웁니다
(subprocess) - Optuna의 study.optimize()가 동기/블로킹 호출이라,
FastAPI 프로세스 안에서 그냥 돌리면 다른 사람의 요청까지 막히기
때문입니다. GIL 때문에 스레드로는 진짜 병렬이 안 되고(순수 Python
CPU-bound 루프), 여러 명이 각자 진짜 동시에 돌아가려면 OS 프로세스를
분리해야 합니다 (progress/33 백로그에도 있는 이유와 같음).

사용법: python server/study_runner.py <study_name> <n_trials> <user_id> <access_token>

동작 방식:
- 매 trial마다 로컬 진행률 파일(outputs/study_results/{study_name}_progress.json)을
  갱신 - server/main.py가 이걸 읽어서 "N/전체" 실시간 표시를 함. study가
  로테이션(아래)되어도 이 파일 경로는 원래 study_name 그대로라 끊김 없음.
- CHECKPOINT_EVERY(기본 20) trial마다 지금까지의 최적값을 Supabase
  optuna_runs 테이블에 저장(그 사용자 계정에 upsert) - 서버가 죽어도
  최소 이 지점까지는 안전하게 남아요.
- 매 체크포인트마다 로컬 디스크 여유 공간을 확인해서, MIN_FREE_BYTES
  아래로 떨어지면 지금까지 쓴 로컬 study sqlite 파일을 지우고,
  best_params로 새 trial을 미리 넣어둔(enqueue_trial) 새 study로
  이어서 진행합니다 - 로컬 저장공간이 부족해도 지금까지 찾은 최적값
  기반으로 탐색이 계속 이어지고, 진짜 결과물(최적 파라미터)은 항상
  Supabase 계정에 남아있어요.
"""
import os
import sys
import json
import shutil
import traceback
from datetime import datetime, timezone

import requests
import optuna
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.main import build_objective, run_best_params_simulation

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIES_DIR = os.path.join(PROJECT_ROOT, "outputs", "studies")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "outputs", "study_results")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wijwbujsihhzzjzawfzp.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_IKdkodgmKWm05tQh15bqVg_uNRqdpEO")

CHECKPOINT_EVERY = int(os.environ.get("WSC_CHECKPOINT_EVERY", "20"))
MIN_FREE_BYTES = int(os.environ.get("WSC_MIN_FREE_BYTES", str(500 * 1024 * 1024)))  # 500MB


def _new_sqlite_with_wal(db_path):
    """Optuna가 만들기 전에 미리 WAL 모드로 켜둠 - server/main.py가 진행 중에도
    같은 파일을 동시에 읽어서 진행률을 보여줄 수 있게 해줍니다."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.close()


def push_checkpoint(study_name, user_id, access_token, n_completed, n_target,
                     best_value, best_params, status="running", termination_reason=None):
    """지금까지의 최적값을 그 사용자 계정(Supabase optuna_runs)에 upsert."""
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
                "study_name": study_name,
                "user_id": user_id,
                "n_trials_completed": n_completed,
                "n_trials_target": n_target,
                "best_value": best_value,
                "best_params": best_params,
                "status": status,
                "termination_reason": termination_reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=15,
        )
    except Exception as e:
        # 체크포인트 저장 실패는 탐색 자체를 막지 않음 - 다음 체크포인트에서 재시도됨
        print(f"[경고] Supabase 체크포인트 저장 실패: {e}", file=sys.stderr)


def make_progress_writer(progress_path, rotation_offset, run_started_at):
    """매 trial 끝날 때마다 로컬 진행률 파일 갱신 (server/main.py의 실시간 표시·잔여시간 계산용).
    rotation_offset: 지금 활성 study가 시작되기 전까지 이미 끝낸 trial 수.
    run_started_at: 전체 실행이 시작된 시각(ISO) - 로테이션이 있어도 안 바뀜,
    그래야 "지금까지 걸린 시간 / 지금까지 끝낸 trial 수"로 정확한 평균 속도가 나옴."""
    def callback(study, trial):
        try:
            done = sum(1 for t in study.trials if t.state.is_finished())
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump({"completed": rotation_offset + done, "started_at": run_started_at}, f)
        except OSError:
            pass
    return callback


def main():
    if len(sys.argv) != 5:
        print("사용법: python study_runner.py <study_name> <n_trials> <user_id> <access_token>", file=sys.stderr)
        sys.exit(1)

    study_name = sys.argv[1]
    n_trials_target = int(sys.argv[2])
    user_id = sys.argv[3]
    access_token = sys.argv[4]

    os.makedirs(STUDIES_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    result_path = os.path.join(RESULTS_DIR, f"{study_name}.json")
    progress_path = os.path.join(RESULTS_DIR, f"{study_name}_progress.json")

    try:
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        objective, context = build_objective()

        run_started_at = datetime.now(timezone.utc).isoformat()

        active_name = study_name
        active_db_path = os.path.join(STUDIES_DIR, f"{active_name}.db")
        _new_sqlite_with_wal(active_db_path)
        study = optuna.create_study(
            study_name=active_name,
            storage=f"sqlite:///{active_db_path}",
            load_if_exists=False,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(multivariate=True, group=True),
        )

        completed = 0             # 전체(로테이션 포함) 누적 완료 trial 수
        rotation_offset = 0       # 지금 활성 study가 시작되기 전까지의 누적 완료 수
        best_value_overall = None
        best_params_overall = None
        rotation_count = 0

        while completed < n_trials_target:
            chunk = min(CHECKPOINT_EVERY, n_trials_target - completed)
            study.optimize(objective, n_trials=chunk, callbacks=[make_progress_writer(progress_path, rotation_offset, run_started_at)])
            completed += chunk

            if study.trials and study.best_value is not None:
                if best_value_overall is None or study.best_value > best_value_overall:
                    best_value_overall = study.best_value
                    best_params_overall = study.best_params

            push_checkpoint(study_name, user_id, access_token, completed, n_trials_target,
                             best_value_overall, best_params_overall, status="running")

            if completed >= n_trials_target:
                break

            # 로컬 저장 공간이 부족해지면: 지금까지 study 파일을 지우고,
            # 지금까지 찾은 best_params를 미리 넣어둔(enqueue_trial) 새
            # study로 교체해서 이어갑니다. 결과(최적값)는 이미 위에서
            # Supabase 계정에 저장했으니 안전합니다.
            free_bytes = shutil.disk_usage(STUDIES_DIR).free
            if free_bytes < MIN_FREE_BYTES:
                rotation_count += 1
                print(f"[안내] 디스크 여유공간 부족({free_bytes / 1e6:.0f}MB) - "
                      f"study 파일 정리 후 이어서 진행 (rotation {rotation_count})", file=sys.stderr)
                try:
                    os.remove(active_db_path)
                    for ext in ("-wal", "-shm"):
                        extra = active_db_path + ext
                        if os.path.exists(extra):
                            os.remove(extra)
                except OSError:
                    pass

                rotation_offset = completed
                active_name = f"{study_name}_r{rotation_count}"
                active_db_path = os.path.join(STUDIES_DIR, f"{active_name}.db")
                _new_sqlite_with_wal(active_db_path)
                study = optuna.create_study(
                    study_name=active_name,
                    storage=f"sqlite:///{active_db_path}",
                    load_if_exists=False,
                    direction="maximize",
                    sampler=optuna.samplers.TPESampler(multivariate=True, group=True),
                )
                if best_params_overall:
                    study.enqueue_trial(best_params_overall)

        df, reason = run_best_params_simulation(
            best_params_overall, context,
            output_csv=os.path.join(RESULTS_DIR, f"{study_name}_result.csv"),
        )

        push_checkpoint(study_name, user_id, access_token, completed, n_trials_target,
                         best_value_overall, best_params_overall, status="done",
                         termination_reason=reason)

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "done",
                "study_name": study_name,
                "n_trials": n_trials_target,
                "best_value": best_value_overall,
                "best_params": best_params_overall,
                "termination_reason": reason,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, f, ensure_ascii=False, indent=2)

        # 마지막 활성 study 파일(로컬 진행률 조회용)도 정리 - 결과는 이미
        # Supabase + 위 result_path에 안전하게 남아있으니 계속 안 남겨둬도 됨
        try:
            os.remove(active_db_path)
            for ext in ("-wal", "-shm"):
                extra = active_db_path + ext
                if os.path.exists(extra):
                    os.remove(extra)
        except OSError:
            pass

    except Exception as e:
        push_checkpoint(study_name, user_id, access_token, 0, n_trials_target,
                         None, None, status="error", termination_reason=str(e))
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "error",
                "study_name": study_name,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, f, ensure_ascii=False, indent=2)
        raise


if __name__ == "__main__":
    main()
