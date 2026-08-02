"""
Open Meteo 기반 데이터 호출
"""
import os                           # 경로 설정
import sys                          # 경로 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # route.py 경로 추가

import requests as rq               # API 호출용
import time                         # API 호출 사이 간격 조절용     
import pandas as pd                 # 데이터 처리용
import numpy as np                  # 계산용

from Functions.Vehicle_Function import read_path   # route.py에서 read_path 가져오기

# Sample 좌표 추출

def get_10k_pt(route_df, interval_m=10000):

    max_dist = route_df["total_distance_m"].max()   # 거리 끝 구하기
    targets_pt = np.arange(0, max_dist + interval_m, interval_m) # 10km 간격 포인트 따기

    Sample_pt = []                                  # 리스트 생성
    
    for target_pt in targets_pt:                    # 10km 간격
        idx = (route_df["total_distance_m"] - target_pt).abs().idxmin()
        # 새로운 Sample_pt에 데이터 추가
        Sample_pt.append(route_df.loc[idx, ["total_distance_m", "lat", "lon"]])  # 가장 가까운 좌표 추출

    # 데이터프레임 변환
    return pd.DataFrame(Sample_pt).reset_index(drop=True)

# Open-Meteo API 접근 (Historical Forecast API, ECMWF IFS 사용)

def Fetch_Env_Data(lat, lon, start="", end=""):

    # Open-Meteo url
    url = "https://archive-api.open-meteo.com/v1/archive"

    # API에 전달할 옵션들
    params = {
        # 파라미터: 일사량, 지상 2m 기온, 지상 10m 풍속, 지상 10m 풍향
        "latitude": lat,              # 위도
        "longitude": lon,             # 경도
        "start_date": start,            # 시작 날짜
        "end_date": end,                # 종료 날짜
        # 시간 단위 데이터 (온도, 풍속, 풍향, 일사량, 기압)
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,surface_pressure",
        "models": "era5_land"
    }

    response = rq.get(url, params=params)  # API 호출

    if response.status_code != 200:  # 호출 실패 시
        print(f"오류 발생: {lat}, {lon} / 상태 코드: {response.status_code}")
        return None

    return response.json()     # 데이터 반환

# 데이터 파싱

def parse_response(data):
    parsed_data = pd.DataFrame(data["hourly"])  # json 데이터 내 hourly를 빼내기
    parsed_data["time"] = pd.to_datetime(parsed_data["time"])   # Time 쪼개기
    parsed_data["time"] = parsed_data["time"] + pd.Timedelta(hours=9, minutes=30) # 현지 시간 조정
    parsed_data["DY"] = parsed_data["time"].dt.day    # 날짜 추출
    parsed_data["HR"] = parsed_data["time"].dt.hour   # 시간 추출
    
    return parsed_data   # CSV로 변환

# 일평균 데이터 변환

def total_Env_Data(lat, lon):

    # 2017년 ~ 2025년 데이터 파싱용 리스트
    years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    total_data = []

    # 9개년치 8월 22일 ~ 29일 데이터 추출 위해 for문 사용
    for year in years:
        raw = Fetch_Env_Data(lat, lon, f"{year}-08-21", f"{year}-08-30")
        if raw is None:
            continue
        parsed = parse_response(raw)
        total_data.append(parsed)
        time.sleep(0.3)  # API 호출 간 0.3초 대기

    result = pd.concat(total_data)

    result = result[result["DY"].between(22, 29) & result["HR"].between(7, 18)]
    mean_result = result.groupby(["DY", "HR"]).mean(numeric_only=True)
    std_result = result.groupby(["DY", "HR"]).std(numeric_only=True)    
    std_result.columns = [f"{col}_std" for col in std_result.columns]
    combined = pd.concat([mean_result, std_result], axis=1).reset_index()

    return combined

# API 호출 및 데이터 저장
# 데이터 보간은 GPS 레졸루션에 따라 불필요하다고 판단

if __name__ == "__main__":

    result_list = []

    test_route = read_path("2027 BWSC TRACK.csv")
    
    sample_route = get_10k_pt(test_route, interval_m=10000)

    for i, (_, row) in enumerate(sample_route.iterrows()):
        print(f"{i+1}/{len(sample_route)} 처리 중...")
        avg_data = total_Env_Data(row["lat"], row["lon"])
        avg_data["total_distance_m"] = row["total_distance_m"]
        avg_data["lat"] = row["lat"]
        avg_data["lon"] = row["lon"]
        result_list.append(avg_data)
        
    pd.concat(result_list).to_csv("outputs/env_data.csv", index=False)
    input("Enter 키를 누르면 종료")