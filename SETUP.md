# 환경 설정 (새 컴퓨터로 옮길 때)

이 프로젝트는 `.venv`(가상환경) 폴더 자체를 옮기지 않는다. `.venv`는 그 컴퓨터의 Python 경로·아키텍처에 종속되어 있어서 복사하면 깨진다. 대신 `requirements.txt`(패키지 명세)만 옮기고, 새 컴퓨터에서 아래 명령으로 동일한 환경을 다시 만든다.

## 요구사항
- **Python 3.12** (`st.dialog` 등 최신 Streamlit 기능 때문에 3.9+ 필요. 3.12 권장)
  - 확인: `py -0p` 로 3.12가 있는지 체크
  - 없으면 설치: `winget install --id Python.Python.3.12 -e`

## 설치 순서

프로젝트 루트(`WSC_DriveEff_Project/`)에서:

```powershell
# 1. 가상환경 생성 (.venv 폴더가 프로젝트 안에 생김)
py -3.12 -m venv .venv

# 2. 가상환경의 pip로 패키지 설치
.\.venv\Scripts\pip.exe install -r requirements.txt
```

이 두 줄이면 끝. `.venv/`는 git에 커밋하지 않는다(`.gitignore`에 추가 권장).

## 실행

```powershell
# 웹 시뮬레이터
.\.venv\Scripts\python.exe -m streamlit run app.py

# CLI (Optuna 최적화 등)
.\.venv\Scripts\python.exe scripts\main.py
```

VS Code에서 작업할 경우, 하단 상태바에서 Python 인터프리터를 `.venv\Scripts\python.exe`로 선택하면 터미널에서 `python`, `streamlit` 명령을 활성화 없이 바로 써도 된다 (`Ctrl+Shift+P` → `Python: Select Interpreter`).

## venv/pip install만으로 안 되는 것 (같이 옮겨야 하는 파일)

`requirements.txt`는 파이썬 패키지만 재현한다. 아래 파일/폴더는 **git으로
같이 커밋되어 있거나, 직접 복사해서 옮겨야** 앱이 지금과 동일하게 동작한다.
전부 코드로 자동 생성되는 게 아니라 데이터/자산 파일이라 빠지면 조용히
깨지거나(파일 없음 에러) 기능이 빈 채로 뜬다(예: 지도 배경 없음, best_params
없이 기본값만 사용).

| 경로 | 없으면 생기는 일 |
|------|------|
| `2027 BWSC TRACK.csv` | 실행 자체가 FileNotFoundError로 즉시 실패 |
| `outputs/env_data.csv` | 마찬가지로 즉시 실패 (환경 데이터 없이는 시뮬레이션 불가) |
| `assets/australia_silhouette.png` | 앱은 뜨지만 지도 배경 실루엣만 빠짐 (`app.py`가 `os.path.exists`로 체크해서 없으면 그냥 생략, 에러는 안 남) |
| `components/route_animator/index.html` | 경로 애니메이션 컴포넌트 자체가 로드 안 됨 |
| `outputs/optuna_study.db` | 없으면 `app.py`가 `mpc_default_params`(임시값)로 폴백. 지금까지 찾은 최적 파라미터로 돌리려면 이 파일이 있어야 함 |

이 5개는 git에 커밋되어 있다면 clone/pull만으로 같이 옮겨지지만,
`.gitignore`에 `outputs/`나 `*.db`, `*.png`가 걸려있는지 꼭 확인할 것.

## (선택) 호주 실루엣 이미지 재생성

`assets/australia_silhouette.png`는 Natural Earth 공개 데이터로 1회성
생성한 정적 파일이라 앱 실행엔 `requirements.txt`의 패키지만 있으면
되고, 이 이미지를 다시 만들 때만 아래를 임시로 추가 설치하면 된다
(재생성 안 할 거면 이 섹션은 무시해도 됨):

```powershell
.\.venv\Scripts\pip.exe install geopandas geodatasets
```
Natural Earth CDN(naciscdn.org)에서 land polygon 데이터를 받아
호주 대륙 폴리곤만 필터링, matplotlib으로 렌더링하는 방식. 좌표 범위는
`app.py`의 `_AUS_BOUNDS`와 정확히 일치해야 지도에 어긋나지 않게 붙는다.

## 문서화 컨벤션 (progress/, debug_logs/)

이 프로젝트는 git을 안 쓰고(버전 관리는 `outputs/trial_N_YYMMDD/` 수동
아카이빙으로 대체) 대신 진행상황을 `progress/`와 `debug_logs/` 두
폴더에 텍스트로 남긴다. 새 세션(다른 컴퓨터 포함)에서 이어갈 때 아래
규칙을 지킬 것:

- **`progress/`는 번호를 이어 붙이는 파일 목록**이다. 새로 정리할
  주제가 생기면 가장 큰 번호 다음 번호로 새 파일(`progress/NN_주제.txt`)
  을 추가한다.
- **"향후 개선 과제 백로그" 파일은 항상 `progress/` 안에서 가장 끝
  번호를 유지한다.** 백로그 안의 항목이 완료되면, 그 항목을 백로그
  에서 지우고 `progress/NN_주제.txt`로 번호를 이어 붙여 별도 파일로
  옮긴 뒤, 백로그 파일 자체의 번호를 한 칸 뒤로 민다(예: 백로그가
  13번이던 상태에서 완료 항목 3개를 14~16번으로 옮기면, 백로그는
  17번이 됨). 백로그 안에는 "완료 이력" 절을 두어 옮겨진 파일들의
  위치를 남긴다.
- **`debug_logs/`는 `(YYYY-MM-DD)_주제.txt` 형식으로, 하루에 여러
  주제를 다뤘으면 그만큼 여러 파일로 쪼갠다** (하나의 파일에 여러
  주제를 욱여넣지 않음). 각 파일은 배경 -> 논의/설계 과정(질문-답변
  형태의 구체적 근거 포함) -> 발견된 버그(원인 -> 수정) -> 상태 순으로,
  progress/ 스냅샷보다 훨씬 서술적·구체적으로 적는다 - 나중에 "왜
  이렇게 했는지"를 복원할 수 있어야 하는 게 목적.
- README.md의 "현재 상태 (YYYY-MM-DD)" 섹션 날짜와 `progress/`의
  최신 백로그 파일이 다른 컴퓨터/세션에서 이어서 시작할 때 가장 먼저
  볼 진입점이다.

## 참고: 이전 환경 이슈
- 예전엔 시스템 전역 Python 3.7.8에 패키지가 직접 설치되어 있었는데, Streamlit이 Python 3.7 지원을 끊어서 최신 버전(`st.dialog` 필요)을 설치할 수 없었음. Python 3.12 + venv로 전환하며 해결.
- `requirements.txt`는 `pip freeze` 결과로, 실제 설치된 전체 의존성 트리가 버전 고정되어 있다. 새 패키지를 추가로 설치했다면 `.\.venv\Scripts\pip.exe freeze > requirements.txt`로 갱신할 것.
