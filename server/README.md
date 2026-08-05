# WSC 통합 웹 서버 — 배포 가이드

팀원들이 로그인해서 단일 시뮬레이션과 Optuna 탐색을 오라클 서버에서 돌려볼 수 있는
HTML/CSS/JS + FastAPI 서버예요. 기존 Streamlit 앱은 최종 중단 확인 전까지 legacy로
보관합니다.

## 이게 왜 필요한가

Streamlit Cloud 배포는 무료 티어 리소스 한계 때문에 무거운 계산을 안정적으로
돌리기 어렵습니다. 이 서버는 시뮬레이션과 Optuna 탐색을 각각 별도 자식 프로세스로
실행하고, 프론트엔드는 진행률과 결과를 same-origin API로 조회합니다.

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

## 한 번 실행해서 확인 (로컬에서만)

```bash
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000
```
같은 서버 안에서 `curl -I http://127.0.0.1:8000` 이 200을 주는지 확인하세요.

> ⚠️ **`--host 0.0.0.0` 으로 띄우지 마세요.** 이 앱은 Caddy 리버스 프록시
> 뒤에서만 노출됩니다. 8000 포트를 외부에 직접 열면 Supabase access token이
> 평문 HTTP로 오가는 경로가 생깁니다. 포트 8000은 방화벽에서 **닫아둡니다**.
> 자세한 배경은 [`progress/46`](../progress/46_도메인_TLS_보안_계획.txt).

여기까지 확인되면 `Ctrl+C`로 끄고, 아래 HTTPS 설정 → systemd 순서로 진행하세요.

## HTTPS (도메인 + Caddy)

도메인은 **`wsc-drive.duckdns.org`** (DuckDNS 무료). A 레코드가 이 서버의
public IP를 가리켜야 합니다. `nslookup wsc-drive.duckdns.org` 로 확인하세요.

### 1) 방화벽 — 오라클은 두 겹입니다

**한쪽만 열고 "왜 접속이 안 되지" 하는 게 가장 흔한 실패입니다.**

- **오라클 콘솔**: VCN → Security Lists → Ingress Rules
  - `80/tcp` 개방 (Let's Encrypt 인증서 발급에 필요)
  - `443/tcp` 개방
  - `8000/tcp` **삭제** (Caddy 뒤로 숨기므로)
- **서버 안** (Oracle Ubuntu 이미지는 iptables가 22 외를 막아둡니다):
  ```bash
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save     # 이걸 빼면 재부팅 시 원복됩니다
  ```

### 2) Caddy 설치 및 적용

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp server/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy
```

인증서 발급/갱신은 Caddy가 자동으로 합니다. **certbot이나 갱신 cron을 따로
만들지 마세요.**

### 3) 확인

- `https://wsc-drive.duckdns.org` 접속 → 자물쇠 표시
- `http://` 로 접속하면 `https` 로 자동 리다이렉트되는지
- **`http://<서버IP>:8000` 이 외부에서 접속 안 되는지** (되면 방화벽 확인)
- 브라우저 콘솔에 **CSP 위반이 없는지** — 차트가 뜨고 로그인이 되는지로 확인.
  CSP는 화면에 에러를 안 띄우고 콘솔에만 찍혀서 조용히 깨집니다.

발급이 반복 실패하면 Let's Encrypt 한도에 걸립니다. 설정을 실험하는 중이라면
`server/Caddyfile` 맨 아래 staging 블록의 주석을 풀고 시험하세요.

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
- `WSC_MAX_SIM_CONCURRENT` — 동시에 몇 명까지 단일 시뮬레이션 실행을 허용할지 (기본 2)
- `WSC_LOG_LEVEL` — 서버 로그 레벨 (기본 `INFO`)

## 로그 확인

서버 로그는 `outputs/logs/server.log`에 저장되고, 20MB 단위로 최대 10개까지
회전합니다. systemd로 실행 중이면 journald에도 같은 로그가 남습니다.

```bash
journalctl -u wsc-launcher -f
tail -f outputs/logs/server.log
```

Optuna 탐색 자식 프로세스의 stdout/stderr는 실행마다
`outputs/logs/run_{run_id}.log`에 저장됩니다. 단일 시뮬레이션 자식 프로세스는
`outputs/logs/sim_{run_id}.log`에 저장됩니다. 서버 시작 시 오래된 실행 로그와
시뮬레이션 CSV/figure 산출물을 정리합니다.

## 아직 안 된 것 / 한계 (솔직하게)

- 실행 중이던 탐색/시뮬레이션은 서버가 재시작되면(재부팅, systemd 재시작 등)
  사라져요. 진행 상황이 메모리에만 있어서예요. 완료된 Optuna 결과와 시뮬레이션
  CSV/figure는 파일로 남습니다.
- 서버 배포 후에는 실제 계정으로 로그인 → 시뮬레이션 실행 → 차트/CSV 확인 →
  Optuna 탐색 시작까지 한 번 눈으로 확인하세요.
