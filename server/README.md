# WSC Optuna 웹 런처 — 배포 가이드

팀원들이 로그인해서 각자 독립된 Optuna 탐색을 오라클 서버에서 돌려볼 수 있는 도구예요.
기존 Streamlit 앱(단일 시뮬레이션 실행용)과는 별개로, 이 `server/` 폴더만 오라클 서버에서 돌아가요.

## 이게 왜 필요한가

Streamlit Cloud 배포는 무료 티어 리소스 한계 때문에 **Optuna 탐색 자체는 못 돌리기로**
(`progress/24`) 결정돼 있었어요. 이 런처는 그 탐색을, 노트북을 켜두지 않고도
오라클 서버에서 여러 명이 각자 돌려볼 수 있게 해줘요.

## 프로젝트 전체를 서버로 옮기기

로컬에서 SSH로:
```bash
scp -i "개인키경로" -r . ubuntu@서버IP:~/WSC_Project
```
(`.venv`, `__pycache__`는 `.gitignore`에 이미 있으니 어차피 큰 문제 없지만,
용량 아끼고 싶으면 `robocopy`/`rsync`로 제외하고 옮겨도 돼요 — SETUP.md 참고)

또는 서버에서 직접:
```bash
ssh -i "개인키경로" ubuntu@서버IP
git clone https://github.com/Dorolong/WSC_Project.git
cd WSC_Project
```
(레포가 Public이라 별도 인증 없이 clone 가능해요. 단, `outputs/env_data.csv`처럼
`.gitignore`로 제외된 "앱 실행 필수 파일"은 레포에 없을 수 있어요 — SETUP.md의
"필수 파일" 목록 확인 후 없으면 `scp`로 따로 옮겨주세요.)

## 서버에서 환경 세팅

```bash
sudo apt update && sudo apt install python3-pip python3-venv -y
cd ~/WSC_Project
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```

## 한 번 실행해서 확인

```bash
source .venv/bin/activate
uvicorn server.main:app --host 0.0.0.0 --port 8000
```
브라우저에서 `http://서버IP:8000` 접속해서 로그인 화면이 뜨는지 확인하세요.
(안 뜨면 오라클 콘솔의 **Security List**에서 포트 8000을 열어야 할 수 있어요 —
가입 초반에 SSH 포트(22)만 열려있다고 말씀드렸던 그 부분이에요. VCN → Security Lists
→ Ingress Rules 추가, 소스 0.0.0.0/0, 포트 8000.)

여기까지 확인되면 `Ctrl+C`로 끄고, 아래처럼 자동 재시작되게 등록하세요.

## 재부팅돼도 자동으로 켜지게 (systemd)

```bash
sudo cp server/wsc-launcher.service /etc/systemd/system/
sudo nano /etc/systemd/system/wsc-launcher.service   # WorkingDirectory/ExecStart 경로를 실제 경로로 수정
sudo systemctl daemon-reload
sudo systemctl enable wsc-launcher
sudo systemctl start wsc-launcher
sudo systemctl status wsc-launcher   # active (running) 뜨는지 확인
```

이후 코드를 업데이트하면:
```bash
git pull   # 또는 scp로 변경 파일만 다시 옮기기
sudo systemctl restart wsc-launcher
```

## 설정값 조절

`server/main.py` 상단의 환경변수로 조절 가능해요 (systemd 서비스 파일의
`[Service]` 섹션에 `Environment=WSC_MAX_CONCURRENT=1` 같은 줄 추가):

- `WSC_MAX_CONCURRENT` — 동시에 몇 명까지 탐색 실행 허용할지 (기본 1, 지금 서버
  사양이 작아서 보수적으로 잡아뒀어요. 나중에 서버 사양 올리면 늘려도 돼요)
- `WSC_MAX_TRIALS` — 한 번 실행에 허용하는 최대 trial 수 (기본 100, 남용 방지용)
- `WSC_LOG_LEVEL` — 서버 로그 레벨 (기본 `INFO`)

## 로그 확인

서버 로그는 `outputs/logs/server.log`에 저장되고, 20MB 단위로 최대 10개까지
회전합니다. systemd로 실행 중이면 journald에도 같은 로그가 남습니다.

```bash
journalctl -u wsc-launcher -f
tail -f outputs/logs/server.log
```

Optuna 탐색 자식 프로세스의 stdout/stderr는 실행마다
`outputs/logs/run_{run_id}.log`에 저장됩니다. 서버 시작 시 `run_*.log`는 최근
50개만 남기고 정리합니다.

## 아직 안 된 것 / 한계 (솔직하게)

- 실행 중이던 탐색은 서버가 재시작되면(재부팅, systemd 재시작 등) 사라져요 —
  진행 상황이 메모리에만 있어서예요. 완료된 결과(`outputs/study_results/*.json`)는
  파일로 남아있으니 안전해요.
- 인터넷이 막힌 환경에서 코드를 작성해서, **fastapi/uvicorn을 실제로 띄워서
  테스트하지는 못했어요** (문법 검사와 핵심 로직만 별도로 검증했어요). 서버에
  처음 배포하고 나서 꼭 한 번 실제로 로그인 → 탐색 시작 → 진행률 표시까지
  눈으로 확인해주세요. 막히는 부분 있으면 에러 메시지 그대로 알려주시면 바로
  봐드릴게요.
