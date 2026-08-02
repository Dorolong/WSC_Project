"""
차량 제원 설정값
"""

from dataclasses import dataclass, field    # 구조체 선언용
import numpy as np                          # numpy

# Vehicle Physics
@dataclass
class VehiclePhysics:
    mass:           float = 250.0       # [kg], 차량 질량
    Cd:             float = 0.081       # [-], Cd at 80kph
    A_f:            float = 1.0         # [m**2], 전면 투영 면적
    Crr:            float = 0.001       # [-], 구름저항 계수
    Drive_eff:      float = 0.99        # [-], 구동계 효율
    Air_Density:    float = 1.225       # [kg/m**3], 공기 밀도
    a_g:            float = 9.81        # [m/s**2], 중력 가속도

# Solar Panel
@dataclass
class SolarPanel:
    A_Solar:        float = 6.0         # [m**2], 태양광 패널 면적
    Solar_eff:      float = 0.27        # [-], 태양광 패널 효율

# Battery Cell, Molicel P60B
@dataclass
class BatteryCell:
    V_batt_max:     float = 4.2         # [V], 셀 최대 전압
    V_batt_nom:     float = 3.6         # [V], 셀 공칭 전압
    V_batt_min:     float = 3.0         # [V], 셀 Cut-Off 전압
    Capa_batt:      float = 6000        # [mAh], 셀 방전 용량
    R_cell:         float = 0.0128      # [Ω], 셀 내부저항
    
    # OCV SOC [-]
    ocv_soc: np.ndarray = field(default_factory=lambda: np.array([
    0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00   
    ]))

    # V matched with SOC [V]
    ocv_V: np.ndarray = field(default_factory=lambda: np.array([
    3.00, 3.10, 3.25, 3.42, 3.52, 3.58, 3.63, 3.72, 3.80, 3.90, 4.07, 4.20   
    ]))

# Battery Pack
@dataclass
class BatteryPack:
    HV_S:           int = 40            # [-], HV Pack 직렬 수
    HV_P:           int = 3             # [-], HV Pack 병렬 수
    LV_S:           int = 5             # [-], LV Pack 직렬 수
    LV_P:           int = 2             # [-], LV Pack 병렬 수
    Cell: BatteryCell = field(default_factory=BatteryCell)

    def __post_init__(self):
        # HV
        self.HV_Vmax = self.HV_S * self.Cell.V_batt_max # [V]
        self.HV_Vnom = self.HV_S * self.Cell.V_batt_nom # [V]
        self.HV_Vmin = self.HV_S * self.Cell.V_batt_min # [V]
        self.HV_Capa = self.HV_P * self.Cell.Capa_batt  # [mAh]
        
        # HV Total Resistance (Cell)
        self.HV_Req = (self.Cell.R_cell * self.HV_S) / self.HV_P

        # HV Energy [Wh]
        self.HV_Energy = self.HV_S * self.HV_P * self.Cell.V_batt_nom * self.Cell.Capa_batt / 1000

        # LV
        self.LV_Vmax = self.LV_S * self.Cell.V_batt_max # [V]
        self.LV_Vnom = self.LV_S * self.Cell.V_batt_nom # [V]
        self.LV_Vmin = self.LV_S * self.Cell.V_batt_min # [V]
        self.LV_Capa = self.LV_P * self.Cell.Capa_batt  # [mAh]
        
        # LV Total Resistance (Cell)
        self.LV_Req = (self.Cell.R_cell * self.LV_S) / self.LV_P

        # LV Energy [Wh]
        self.LV_Energy = self.LV_S * self.LV_P * self.Cell.V_batt_nom * self.Cell.Capa_batt / 1000

# Power System
@dataclass
class PowerSystem:
    P_LV_race:      float = 50.0        # [W], 주행 중 LV 소비전력
    P_LV_chg:       float = 25.0        # [W], Control Stop에서 LV 소비전력
    Regen_eff:      float = 0.6         # [-], 회생제동 효율
    cs_chg_eff:     float = 0.8         # [-], Control Stop 충전 보정계수

"""
회생제동 테스트 방법
1) 평지에서 일정속도 v1으로 주행 후 회생제동만으로 v2까지 감속
2) 배터리 출력 단자에서 그동안의 전압/전류 실측 후 적분
E_regen = ∫V*I dt
3) 바퀴에서의 제동 에너지 물리식으로 계산
E_vehicle = m*(v1^2-v2^2)/2 - Eff_other(Aero, roll ...)
4) Regen_eff = E_regen / E_vehicle
"""

# Motor Parameter
@dataclass
class Drivesystem:

    speed_constant:     float = 0.45    # [Vs/rad], Kv
    torque_constant:    float = 0.44    # [-], Kt
    motor_nom_dcV:      int = 150       # [V], 모터 정격 DC 전압
    motor_nom_speed:    int = 111       # [rad/s], 모터 정격 속도
    motor_max_speed:    int = 157       # [rad/s], 모터 최대 속도
    motor_nom_power:    int = 1800      # [W], 모터 최대 출력(정격)
    nom_torque:         float = 16.2    # [Nm], 모터 정격 토크
    max_torque:         int = 80        # [Nm], 모터 최대 토크
    cont_max_torque:    int = 42        # [Nm], 모터 연속 최대 토크
    phase_res:          float = 0.0575  # [Ω], 상 저항
    total_loss:         float = 55.7    # [W], 모터 총 손실(정격)
    motor_eff:          float = 0.97    # [-], 모터 효율(정격)
    inverter_eff:       float = 0.95    # [-], 인버터 효율(정격)
    wheel_radius:       float = 0.275   # [m], 휠 반경
    
    def __post_init__(self):
        # 이론 상 최대속도 [km/h]
        self.v_max = self.motor_max_speed * self.wheel_radius * 3.6

# Race Configuration
@dataclass
class RaceConfig:

    # 최소 출발 SOC
    soc_start_min:  float = 0.2         # [-], 각 일자 출발 최소 SOC

    # Control Stop 정차 시간
    cs_stop_max:    int = 3600          # [s], Control Stop 최대 정차 시간
    cs_stop_min:    int = 1800          # [s], Control Stop 최소 정차 시간

    # 2025 Control Stop
    Control_Stop_2025: dict = field(default_factory=lambda: {
    322000:  "CS1",   # Katherine
    631000:  "CS2",   # Dunmarra
    988000:  "CS3",   # Tennant Creek
    1212300: "CS4",   # Barrow Creek
    1496000: "CS5",   # Alice Springs
    1694000: "CS6",   # Erldunda
    2181000: "CS7",   # Coober Pedy
    2434000: "CS8",   # Glendambo
    2720500: "CS9",   # Port Augusta
    })

    # CS별 오픈 시각 [시, 8/23 00시 기준]
    CS_open_hour: dict = field(default_factory=lambda: {
    322000:  35,    # CS1
    631000:  39,    # CS2
    988000:  58,    # CS3
    1212300: 61,    # CS4
    1496000: 80,    # CS5
    1694000: 83,    # CS6
    2181000: 88,    # CS7
    2434000: 106,   # CS8
    2720500: 110,   # CS9
    })

    # CS별 마감 시각 [시, 8/23 00시 기준]
    CS_close_hour: dict = field(default_factory=lambda: {
    322000:  41,    # CS1
    631000:  62,    # CS2
    988000:  83,    # CS3
    1212300: 87,    # CS4
    1496000: 106.5, # CS5
    1694000: 110,   # CS6
    2181000: 133,   # CS7
    2434000: 137,   # CS8
    2720500: 157,   # CS9
    })

    # CS 구간(직전 CS ~ 현재 CS) 최소 평균속도 [km/h], 미달 시 실격
    min_leg_avg_speed: float = 60.0

    # 총 주행거리 [m]
    total_distance: int = 3038326

# Vehicle Simulation Parameter
@dataclass
class SimulationParameter:
    soc:                        float = 1.0         # [-], SOC 초기값
    Accum_s:                    float = 1800.0      # [s], 출발시간 08:00
    DY:                         int = 23            # [-], 출발일: 2027-08-23
    HR:                         int = 8             # [-], 출발시간 08:00
    prev_radiation:             float = 0.0         # [W/m**2], 일사량 초기값
    prev_a:                     float = 0.0         # [m/s**2], 가속도 초기값
    prev_v:                     float = 0.0         # [m/s], 속도 초기값
    prev_wind_speed:            float = 0.0         # [m/s], 풍속 초기값
    prev_wind_dir:              float = 0.0         # [deg], 퐁향 초기값
    prev_heading:               float = 0.0         # [deg], 차량 벡터 초기값
    soc_hard_stop:              float = 0.10        # [-], 최소 SOC 보장값
    max_v_delta:                int = 2             # [m/s], 매 스텝 최대 속도 변화량
    avg_traffic_light_delay:    int = 15            # [s], 신호등 평균 대기시간
    avg_pedestrian_light_delay: int = 10            # [s], 보행자 신호 평균 대기시간
    decel_brake:                float = 0.7         # [g], Control Stop 진입 위한 감속도

physics = VehiclePhysics()
solar   = SolarPanel()
cell    = BatteryCell()
pack    = BatteryPack()
pack.Cell = cell        # pack 자체 Cell 복사본 대신 전역 cell을 참조 (app.py 다이얼로그 편집이 반영되도록)
pack.__post_init__()    # cell 참조 변경에 맞춰 파생값 재계산
power   = PowerSystem()
drive   = Drivesystem()
race    = RaceConfig()
simpara = SimulationParameter()