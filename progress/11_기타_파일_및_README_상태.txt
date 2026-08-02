================================================================
기타 파일 현재 상태 (README.md, requirements.txt, outputs/, assets/)
================================================================

[ README.md - 2026-07-20 기준 최신 상태로 유지 관리 중 ]
이 파일이 처음 작성된 시점(07-13)엔 README가 07-12 상태로 낡아있었으나,
이후 여러 세션을 거치며 README.md 자체가 계속 최신화되고 있음(가장
최근: 2026-07-20, run_simulation() 함수분리 6/6 완료 + momentum 반영
반영). 이제 README.md의 "현재 상태" 섹션 상단 날짜가 최신 갱신 시점을
그대로 보여주므로, 이 progress 파일보다 **README.md 자체를 최신 상태
기준으로 우선 참고할 것.**

[ requirements.txt ]
pip freeze 기준 전체 의존성 버전 고정 (60개 패키지). geopandas/geodatasets/
pyproj/shapely/pyogrio는 호주 실루엣 PNG 생성 1회용으로만 쓰고 앱 실행엔
불필요해서 포함 안 함 (venv엔 설치되어 있으나 requirements.txt엔 미기재).

[ outputs/ 폴더 현황 ]
- env_data.csv: 원본 환경 데이터 (변경 없음)
- optuna_study.db: 현재 진행 중인 라운드 (LV1 순차샘플링 + 스무스 LV8,
  컨트롤스탑 규칙 비활성화 상태로 탐색 중)
- Optuna_result.csv, sim_result.csv/pdf: 이전 라운드 산출물 (최신 상태
  아닐 수 있음, 다음 완주 확정 라운드 이후 재생성 권장)
- trial_1_260712 ~ trial_4_260713: 아카이빙된 이전 라운드 db + read.txt
  (progress_260713/04_Optuna_워크플로우.txt에 요약 있음)

[ assets/ 폴더 (신규) ]
- australia_silhouette.png: Natural Earth 공개 데이터 기반 호주 실루엣,
  lon 113.185~153.617 / lat -39.146~-10.707 범위에 정확히 맞춰 렌더링됨
  (종횡비 보정 완료). app.py의 지도 컴포넌트 배경으로 사용.

[ components/ 폴더 (신규) ]
- route_animator/index.html: 커스텀 Streamlit 컴포넌트 (progress_260713/
  10_app_py_및_컴포넌트.txt 참고)

[ 2027 BWSC TRACK.csv ]
변경 없음. Darwin~Adelaide 3,038km GPS 경로 원본.

[ 상태 ]
README.md 갱신이 유일하게 남은 문서화 작업. 나머지는 현재 상태 그대로
정확함.
================================================================
