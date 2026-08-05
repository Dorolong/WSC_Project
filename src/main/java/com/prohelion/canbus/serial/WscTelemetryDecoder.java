package com.prohelion.canbus.serial;

import com.prohelion.canbus.model.LogPacket;
import com.prohelion.canbus.model.LogSource;
import com.prohelion.canbus.model.VehicleSnapshot;

/**
 * LOG 패킷(source+key+value[8]) → {@link VehicleSnapshot} 반영.
 *
 * 슬롯 정의 출처:
 *  - PRIMARY(200ms) 17개 패킷: can-signal-summary.md §5 (명시적 슬롯 표, SSOT)
 *  - DETAIL(1s) 패킷: WSC_Transmitter_Code_V1/Core/Inc/types.h의 BMS_KEY/MPPT_KEY/
 *    MOTOR_KEY/BMS_LV_KEY enum 주석 및 BmsData_t/MpptData_t/MotorData_t/BmsLvData_t
 *    구조체 필드 주석 (각 필드 순서가 곧 value[8] 내 바이트 오프셋 순서).
 * SD_ONLY(무선 미전송) 키와, 바이트 배치가 명시적으로 확인되지 않는
 * KEY_BMS_LV_CMU_BASE(0x10, "Status/Temp")는 범위 밖으로 남겨둔다.
 */
public final class WscTelemetryDecoder {

    // ---- source별 key 네임스페이스 (Core/Inc/types.h) ----

    // BMS_KEY (SRC_BMS_BOT / SRC_BMS_TOP)
    private static final int KEY_BMS_VOLT_STACK = 0x00;
    private static final int KEY_BMS_CURR_TEMP = 0x01;
    private static final int KEY_BMS_FAULT = 0x02;
    private static final int KEY_BMS_SOC = 0x03;
    private static final int KEY_BMS_CELL_00_03 = 0x10;
    private static final int KEY_BMS_CELL_04_07 = 0x11;
    private static final int KEY_BMS_CELL_08_11 = 0x12;
    private static final int KEY_BMS_CELL_12_15 = 0x13;
    private static final int KEY_BMS_TEMP_A = 0x14;
    private static final int KEY_BMS_TEMP_B = 0x15;

    // MPPT_KEY (SRC_MPPT1~3)
    private static final int KEY_MPPT_IV_IN_OUT = 0x00;
    private static final int KEY_MPPT_TEMP_FLAGS = 0x10;
    private static final int KEY_MPPT_MAXLIM = 0x11;
    private static final int KEY_MPPT_AUX_2 = 0x12;

    // MOTOR_KEY (SRC_MOTOR)
    private static final int KEY_MOTOR_BUS_VEL = 0x00;
    private static final int KEY_MOTOR_TEMP = 0x01;
    private static final int KEY_MOTOR_BEMF = 0x02;
    private static final int KEY_MOTOR_ODO = 0x03;
    private static final int KEY_MOTOR_DSP_TEMP = 0x10;
    private static final int KEY_MOTOR_STATUS = 0x11;
    private static final int KEY_MOTOR_PHASE_I = 0x12;

    // BMS_LV_KEY (SRC_BMS_LV, LV_MAX_CMU=1 가정 → 고정 키가 0x13부터 파생됨)
    private static final int KEY_BMS_LV_SOC = 0x00;
    private static final int KEY_BMS_LV_PACK_VI = 0x01;
    private static final int KEY_BMS_LV_CMU0_CELL_00_03 = 0x11; // CMU_BASE(0x10) + 1
    private static final int KEY_BMS_LV_CMU0_CELL_04_07 = 0x12; // CMU_BASE(0x10) + 2
    private static final int KEY_BMS_LV_BALANCE_SOC = 0x13;     // 0x10 + 3*LV_MAX_CMU(1)
    private static final int KEY_BMS_LV_CHARGER = 0x14;
    private static final int KEY_BMS_LV_PRECHARGE = 0x15;
    private static final int KEY_BMS_LV_MINMAX_V = 0x16;
    private static final int KEY_BMS_LV_MINMAX_T = 0x17;
    private static final int KEY_BMS_LV_STATUS = 0x18;
    private static final int KEY_BMS_LV_FAN = 0x19;

    private WscTelemetryDecoder() { }

    /** @return true면 알려진 (source,key) 조합이라 스냅샷에 반영함, false면 무시함(SD_ONLY 등) */
    public static boolean apply(VehicleSnapshot snapshot, LogPacket pkt) {
        int source = pkt.getSource() & 0xFF;
        int key = pkt.getKey() & 0xFF;

        switch (source) {
            case LogSource.SRC_BMS_BOT:
                return applyBms(snapshot, pkt, key, false);
            case LogSource.SRC_BMS_TOP:
                return applyBms(snapshot, pkt, key, true);
            case LogSource.SRC_MPPT1:
                return applyMppt(snapshot, pkt, key, 0);
            case LogSource.SRC_MPPT2:
                return applyMppt(snapshot, pkt, key, 1);
            case LogSource.SRC_MPPT3:
                return applyMppt(snapshot, pkt, key, 2);
            case LogSource.SRC_MOTOR:
                return applyMotor(snapshot, pkt, key);
            case LogSource.SRC_BMS_LV:
                return applyBmsLv(snapshot, pkt, key);
            default:
                return false; // SRC_SYS / 에러 소스 / 예약 슬롯 — 대시보드 범위 밖
        }
    }

    private static boolean applyBms(VehicleSnapshot snapshot, LogPacket pkt, int key, boolean top) {
        switch (key) {
            case KEY_BMS_VOLT_STACK: {
                // #1/#4: Stack_V(cV), Pack_V(cV), MaxCell(mV), MinCell(mV) — 전부 u16
                double stackV = pkt.u16(0) / 100.0;   // cV -> V
                double packV = pkt.u16(2) / 100.0;
                int maxCellMv = pkt.u16(4);
                int minCellMv = pkt.u16(6);
                snapshot.updateBmsVoltStack(top, stackV, packV, maxCellMv, minCellMv);
                return true;
            }
            case KEY_BMS_CURR_TEMP: {
                if (top) {
                    // #5 TOP: CellTemp(i16), BattStat(u16), Alarm(u16), pad — PackCurrent 슬롯 없음(항상 0)
                    double cellTempC = pkt.i16(0) / 10.0;
                    int battStat = pkt.u16(2);
                    int alarm = pkt.u16(4);
                    snapshot.updateBmsCurrTemp(true, 0.0, cellTempC, battStat, alarm);
                } else {
                    // #2 BOT: PackCurrent(i16, 10mA), CellTemp(i16), BattStat(u16), Alarm(u16)
                    double packCurrentA = pkt.i16(0) / 100.0; // 10mA 단위 -> A
                    double cellTempC = pkt.i16(2) / 10.0;
                    int battStat = pkt.u16(4);
                    int alarm = pkt.u16(6);
                    snapshot.updateBmsCurrTemp(false, packCurrentA, cellTempC, battStat, alarm);
                }
                return true;
            }
            case KEY_BMS_FAULT: {
                // #3/#6: Global_Fault(u32) + pad(u32)
                snapshot.updateBmsFault(top, pkt.u32(0));
                return true;
            }
            case KEY_BMS_SOC: {
                // #16/#17: SOC_Permille(u16) + pad x3
                snapshot.updateBmsSoc(top, pkt.u16(0) / 10.0); // permille -> percent
                return true;
            }
            case KEY_BMS_CELL_00_03:
                snapshot.updateBmsCells(top, 0, pkt.u16(0), pkt.u16(2), pkt.u16(4), pkt.u16(6));
                return true;
            case KEY_BMS_CELL_04_07:
                snapshot.updateBmsCells(top, 4, pkt.u16(0), pkt.u16(2), pkt.u16(4), pkt.u16(6));
                return true;
            case KEY_BMS_CELL_08_11:
                snapshot.updateBmsCells(top, 8, pkt.u16(0), pkt.u16(2), pkt.u16(4), pkt.u16(6));
                return true;
            case KEY_BMS_CELL_12_15:
                snapshot.updateBmsCells(top, 12, pkt.u16(0), pkt.u16(2), pkt.u16(4), pkt.u16(6));
                return true;
            case KEY_BMS_TEMP_A:
                // CellTemp(TS1), FETTemp, IntTemp, CFETOFFTemp — i16×4, 0.1℃
                snapshot.updateBmsTempA(top, pkt.i16(0) / 10.0, pkt.i16(2) / 10.0, pkt.i16(4) / 10.0, pkt.i16(6) / 10.0);
                return true;
            case KEY_BMS_TEMP_B:
                // HDQTemp, MaxCellTemp, MinCellTemp, AvgCellTemp — i16×4, 0.1℃
                snapshot.updateBmsTempB(top, pkt.i16(0) / 10.0, pkt.i16(2) / 10.0, pkt.i16(4) / 10.0, pkt.i16(6) / 10.0);
                return true;
            default:
                return false; // 쿨롱카운터(스케일 미정)/SD_ONLY — 범위 밖
        }
    }

    private static boolean applyMppt(VehicleSnapshot snapshot, LogPacket pkt, int key, int index) {
        switch (key) {
            case KEY_MPPT_IV_IN_OUT: {
                // #7/#8/#9: InV, InI, OutV, OutI — 전부 u16, x100 스케일
                double inV = pkt.u16(0) / 100.0;
                double inI = pkt.u16(2) / 100.0;
                double outV = pkt.u16(4) / 100.0;
                double outI = pkt.u16(6) / 100.0;
                snapshot.updateMppt(index, inV, inI, outV, outI);
                return true;
            }
            case KEY_MPPT_TEMP_FLAGS: {
                // MosfetT,CtrlT(i16×2, x10) + ErrorF,Mode(u8×2)
                double mosfetTempC = pkt.i16(0) / 10.0;
                double ctrlTempC = pkt.i16(2) / 10.0;
                int errorFlags = pkt.getValue()[4] & 0xFF;
                int mode = pkt.getValue()[5] & 0xFF;
                snapshot.updateMpptTempFlags(index, mosfetTempC, ctrlTempC, errorFlags, mode);
                return true;
            }
            case KEY_MPPT_MAXLIM: {
                // MaxOutput_Voltage, MaxInput_Current — u16×2, x100
                snapshot.updateMpptMaxLim(index, pkt.u16(0) / 100.0, pkt.u16(2) / 100.0);
                return true;
            }
            case KEY_MPPT_AUX_2: {
                // PowerConnV(u16, x100), PowerConnTemp(i16, x10)
                snapshot.updateMpptAux2(index, pkt.u16(0) / 100.0, pkt.i16(2) / 10.0);
                return true;
            }
            default:
                return false; // SD_ONLY(12V/3V aux) — 범위 밖
        }
    }

    private static boolean applyMotor(VehicleSnapshot snapshot, LogPacket pkt, int key) {
        switch (key) {
            case KEY_MOTOR_BUS_VEL: {
                // #10: BusV(u16,x100), BusI(i16,x10), MotorRPM(i16), VehSpeed(u16,x100)
                double busV = pkt.u16(0) / 100.0;
                double busI = pkt.i16(2) / 10.0;
                int rpm = pkt.i16(4);
                double vehSpeedMs = pkt.u16(6) / 100.0;
                snapshot.updateMotorBusVel(busV, busI, rpm, vehSpeedMs);
                return true;
            }
            case KEY_MOTOR_TEMP: {
                // #11: HeatsinkT(i16,x10), MotorT(i16,x10), pad, pad
                double heatsinkTempC = pkt.i16(0) / 10.0;
                double motorTempC = pkt.i16(2) / 10.0;
                snapshot.updateMotorTemp(heatsinkTempC, motorTempC);
                return true;
            }
            case KEY_MOTOR_BEMF: {
                // #12: BEMFd(i16,x100), BEMFq(i16,x100), pad, pad
                double bemfD = pkt.i16(0) / 100.0;
                double bemfQ = pkt.i16(2) / 100.0;
                snapshot.updateMotorBemf(bemfD, bemfQ);
                return true;
            }
            case KEY_MOTOR_ODO: {
                // #13: Odometer(float, m), DC_Bus_AmpHours(float, Ah)
                double odometerM = pkt.f32(0);
                double dcBusAh = pkt.f32(4);
                snapshot.updateMotorOdo(odometerM, dcBusAh);
                return true;
            }
            case KEY_MOTOR_DSP_TEMP:
                snapshot.updateMotorDspTemp(pkt.i16(0) / 10.0);
                return true;
            case KEY_MOTOR_STATUS: {
                int limitFlags = pkt.u16(0);
                int errorFlags = pkt.u16(2);
                int activeMotor = pkt.u16(4);
                int txErrCnt = pkt.getValue()[6] & 0xFF;
                int rxErrCnt = pkt.getValue()[7] & 0xFF;
                snapshot.updateMotorStatus(limitFlags, errorFlags, activeMotor, txErrCnt, rxErrCnt);
                return true;
            }
            case KEY_MOTOR_PHASE_I:
                snapshot.updateMotorPhaseI(pkt.i16(0) / 10.0, pkt.i16(2) / 10.0);
                return true;
            default:
                return false; // SD_ONLY(벡터/레일/슬립) — 범위 밖
        }
    }

    private static boolean applyBmsLv(VehicleSnapshot snapshot, LogPacket pkt, int key) {
        switch (key) {
            case KEY_BMS_LV_SOC:
                // #14: SoC_Ah(float), SoC_Pct(float)
                snapshot.updateBmsLvSoc(pkt.f32(0), pkt.f32(4));
                return true;
            case KEY_BMS_LV_PACK_VI:
                // #15: Pack_V(u32, mV), Pack_I(i32, mA)
                snapshot.updateBmsLvPackVi(pkt.u32(0), pkt.i32(4));
                return true;
            case KEY_BMS_LV_CMU0_CELL_00_03:
                snapshot.updateBmsLvCells(0, pkt.i16(0), pkt.i16(2), pkt.i16(4), pkt.i16(6));
                return true;
            case KEY_BMS_LV_CMU0_CELL_04_07:
                snapshot.updateBmsLvCells(4, pkt.i16(0), pkt.i16(2), pkt.i16(4), pkt.i16(6));
                return true;
            case KEY_BMS_LV_BALANCE_SOC:
                snapshot.updateBmsLvBalance(pkt.f32(0), pkt.f32(4));
                return true;
            case KEY_BMS_LV_CHARGER:
                snapshot.updateBmsLvCharger(pkt.i16(0), pkt.i16(2) / 10.0, pkt.i16(4), pkt.u16(6));
                return true;
            case KEY_BMS_LV_PRECHARGE: {
                byte[] v = pkt.getValue();
                int contactor = v[0] & 0xFF;
                int state = v[1] & 0xFF;
                int supply12v = pkt.u16(2);
                int timerElapsed = v[4] & 0xFF;
                int timerCnt = v[5] & 0xFF;
                snapshot.updateBmsLvPrecharge(contactor, state, supply12v, timerElapsed, timerCnt);
                return true;
            }
            case KEY_BMS_LV_MINMAX_V: {
                byte[] v = pkt.getValue();
                snapshot.updateBmsLvMinMaxV(pkt.u16(0), pkt.u16(2), v[4] & 0xFF, v[5] & 0xFF, v[6] & 0xFF, v[7] & 0xFF);
                return true;
            }
            case KEY_BMS_LV_MINMAX_T: {
                byte[] v = pkt.getValue();
                snapshot.updateBmsLvMinMaxT(pkt.u16(0) / 10.0, pkt.u16(2) / 10.0, v[4] & 0xFF, v[5] & 0xFF);
                return true;
            }
            case KEY_BMS_LV_STATUS: {
                byte[] v = pkt.getValue();
                snapshot.updateBmsLvStatus(pkt.u16(0), pkt.u16(2), v[4] & 0xFF, v[5] & 0xFF, pkt.u16(6));
                return true;
            }
            case KEY_BMS_LV_FAN:
                snapshot.updateBmsLvFan(pkt.u16(0), pkt.u16(2), pkt.u16(4), pkt.u16(6));
                return true;
            default:
                return false; // CMU_BASE(0x10, 바이트배치 미확인) / SD_ONLY / heartbeat — 범위 밖
        }
    }
}
