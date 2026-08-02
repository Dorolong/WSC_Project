import requests
r = requests.get("https://api.open-meteo.com/v1/forecast", params={
    "latitude": 37.5665, "longitude": 126.9780,
    "current": "wind_direction_10m,wind_speed_10m",
    "timezone": "Asia/Seoul"
})
print(r.json())