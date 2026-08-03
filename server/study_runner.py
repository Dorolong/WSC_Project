"""
웹에서 트리거된 Optuna 탐색을 실제로 돌리는 스크립트.
server/main.py(FastAPI)가 이 파일을 별도 프로세스로 띄웁니다
(subprocess) - Optuna의 study.optimize()가 동기/블로킹 호출이라,
FastAPI 프로세스 안에서 그냥 돌리면 다른 사람의 요청까지 막히기
때문입니다. GIL 때문에 스레드로는 진짜 병렬이 안 되고(순수 Python
CPU-bound 루프), 여러 명이 각자 진짜 동시에 돌아가려면 OS 프로세스를
분리해야 합니다 (progress/33 백로그에도 있는 이유와 같음).

사용법: python server/study_runner.py <study_name> <n_trials>

진행 상황은 Optuna 자체 storage(sqlite)에 이미 기록되니 별도 진행률
파일을 안 만들어도 되고, server/main.py가 그 storage를 그대로 읽어서
"N/전체" 진행률을 알아냅니다. 이 스크립트는 완료 후 best_params 결과
요약만 별도 JSON으로 남겨서, 최종 결과 조회를 study storage 파싱 없이
가볍게 할 수 있게 합니다.
"""
import os
import sys
import json
import traceback
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import optuna
import sqlite3
from scripts.main import build_objective, run_best_params_simulation

STUDIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "studies")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "study_results")


def main():
    if len(sys.argv) != 3:
        print("사용법: python study_runner.py <study_name> <n_trials>", file=sys.stderr)
        sys.exit(1)

    study_name = sys.argv[1]
    n_trials = int(sys.argv[2])

    os.makedirs(STUDIES_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    db_path = os.path.join(STUDIES_DIR, f"{study_name}.db")
    result_path = os.path.join(RESULTS_DIR, f"{study_name}.json")

    # WAL 모드: 이 프로세스가 study.optimize()로 계속 쓰는 동안,
    # server/main.py(FastAPI)가 같은 파일을 동시에 읽어서 진행률을
    # 확인할 수 있게 해줍니다 (읽기가 쓰기를 막지 않음).
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.close()

    try:
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        objective, context = build_objective()

        study = optuna.create_study(
            study_name=study_name,
            storage=f"sqlite:///{db_path}",
            load_if_exists=False,  # 이 study_name은 이번 실행 전용(웹에서 매번 새로 발급)이라 재사용 안 함
            direction="maximize",
            sampler=optuna.samplers.TPESampler(multivariate=True, group=True),
        )

        study.optimize(objective, n_trials=n_trials)

        df, reason = run_best_params_simulation(
            study.best_params, context,
            output_csv=os.path.join(RESULTS_DIR, f"{study_name}_result.csv"),
        )

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": "done",
                "study_name": study_name,
                "n_trials": n_trials,
                "best_value": study.best_value,
                "best_params": study.best_params,
                "termination_reason": reason,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, f, ensure_ascii=False, indent=2)

    except Exception as e:
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
