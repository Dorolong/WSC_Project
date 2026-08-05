package com.prohelion.canbus.model;

import org.springframework.stereotype.Component;

/**
 * 무선(RFD900x/LoRa)으로 수신한 WSC 텔레메트리 LOG 패킷의 최신 상태를 담는 싱글턴.
 * {@link com.prohelion.canbus.serial.WscTelemetryDecoder}가 패킷을 파싱해 여기에 반영하고,
 * 대시보드/BMS 요약 컨트롤러가 이 상태의 스냅샷(DTO)을 읽어 JSON으로 내려준다.
 *
 * 값 갱신은 전부 이 인스턴스에 대한 synchronized 블록 안에서만 일어난다 — 패킷 처리량이
 * 초당 수십 건 수준이라 단일 락으로 충분하고, 필드 단위 원자성보다 "한 패킷이 갱신하는
 * 여러 필드가 항상 함께 보인다"는 일관성이 더 중요하기 때문에 이 방식을 택했다.
 */
@Component
public class VehicleSnapshot {

    /** BMS(HV) 한 개 유닛(BOT 또는 TOP)의 최신 값. PRIMARY(200ms) + DETAIL(1s) 병합. */
    public static class BmsUnit {
        // PRIMARY
        public double stackVoltageV;
        public double packVoltageV;
        public int maxCellMv;
        public int minCellMv;
        public double packCurrentA;
        public double cellTempC;
        public int battStat;
        public int alarm;
        public long faultFlags;
        public double socPercent;
        public long lastUpdate;

        // DETAIL — 셀별 전압(16개)
        public int[] cellMv = new int[16];
        public long cellMvUpdate;

        // DETAIL — 상세 온도 A/B
        public double cellTempTs1C;
        public double fetTempC;
        public double intTempC;
        public double cfetoffTempC;
        public double hdqTempC;
        public double maxCellTempC;
        public double minCellTempC;
        public double avgCellTempC;
        public long detailTempUpdate;
    }

    /** MPPT 한 대의 최신 값. PRIMARY + DETAIL 병합. */
    public static class MpptUnit {
        // PRIMARY
        public double inVoltageV;
        public double inCurrentA;
        public double outVoltageV;
        public double outCurrentA;
        public long lastUpdate;

        // DETAIL
        public double mosfetTempC;
        public double ctrlTempC;
        public int errorFlags;
        public int mode;
        public double maxOutVoltageV;
        public double maxInCurrentA;
        public double powerConnVoltageV;
        public double powerConnTempC;
        public long detailUpdate;

        public double outputPowerW() { return outVoltageV * outCurrentA; }
    }

    /** 모터/VCU(잠정) 최신 값. PRIMARY + DETAIL 병합. */
    public static class MotorUnit {
        // PRIMARY
        public double busVoltageV;
        public double busCurrentA;
        public int rpm;
        public double vehicleSpeedMs;
        public double heatsinkTempC;
        public double motorTempC;
        public double bemfDV;
        public double bemfQV;
        public double odometerM;
        public double dcBusAmpHours;
        public long lastUpdate;

        // DETAIL
        public double dspTempC;
        public int limitFlags;
        public int errorFlags;
        public int activeMotor;
        public int txErrCnt;
        public int rxErrCnt;
        public double phaseBCurrentA;
        public double phaseCCurrentA;
        public long detailUpdate;

        public double vehicleSpeedKmh() { return vehicleSpeedMs * 3.6; }
    }

    /** 저전압 보조배터리 BMS(잠정) 최신 값. PRIMARY + DETAIL 병합. */
    public static class BmsLvUnit {
        // PRIMARY
        public double socAh;
        public double socPercent;
        public long packVoltageMv;
        public long packCurrentMa;
        public long lastUpdate;

        // DETAIL — CMU0 셀 전압 (LV_MAX_CMU=1 가정)
        public int[] cellMv = new int[8];
        public long cellUpdate;

        // DETAIL — 밸런싱
        public double balanceAh;
        public double balancePercent;

        // DETAIL — 충전기 제어
        public int chargeVErrMv;
        public double chargeTempMarginC;
        public int dischargeVErrMv;
        public int totalCapacityAh;

        // DETAIL — 프리차지 상태
        public int contactorStatus;
        public int prechargeState;
        public int supply12vMv;
        public int prechargeTimerElapsed;
        public int prechargeTimerCnt;

        // DETAIL — 셀 최소/최대 전압
        public int minCellMv;
        public int maxCellMv;
        public int minCellCmu, minCellIdx, maxCellCmu, maxCellIdx;

        // DETAIL — 셀 최소/최대 온도
        public double minCellTempC, maxCellTempC;
        public int minTempCmu, maxTempCmu;

        // DETAIL — 팩 상태
        public int balanceThreshRisingMv, balanceThreshFallingMv;
        public int statusFlags;
        public int cmuCount;
        public int fwBuild;

        // DETAIL — 팬/컨택터 전류
        public int fanSpeed0Rpm, fanSpeed1Rpm;
        public int fanContactorCurrentMa;
        public int cmuCurrentMa;

        public long detailUpdate;
    }

    private final BmsUnit bmsBot = new BmsUnit();
    private final BmsUnit bmsTop = new BmsUnit();
    private final MpptUnit[] mppt = { new MpptUnit(), new MpptUnit(), new MpptUnit() };
    private final MotorUnit motor = new MotorUnit();
    private final BmsLvUnit bmsLv = new BmsLvUnit();

    private long totalFrames = 0;
    private long checksumFailures = 0;
    private long framingErrors = 0;
    private long lastFrameTime = 0;

    // 현재 운전 중인 드라이버 (1~3) — 텔레메트리로 오는 값이 아니라 팀이 대시보드에서 수동으로 지정하는
    // 운영 정보. 여기 저장해두면 폴링하는 모든 화면에 동일하게 반영된다.
    private int currentDriver = 1;

    public synchronized void recordFrameOk() {
        totalFrames++;
        lastFrameTime = System.currentTimeMillis();
    }

    public synchronized void setCurrentDriver(int driver) {
        if (driver >= 1 && driver <= 3) {
            currentDriver = driver;
        }
    }

    public synchronized void recordChecksumFailure() {
        checksumFailures++;
    }

    public synchronized void recordFramingError() {
        framingErrors++;
    }

    // ---- BMS(HV) PRIMARY 갱신 ----

    public synchronized void updateBmsVoltStack(boolean top, double stackV, double packV, int maxCellMv, int minCellMv) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.stackVoltageV = stackV;
        u.packVoltageV = packV;
        u.maxCellMv = maxCellMv;
        u.minCellMv = minCellMv;
        u.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsCurrTemp(boolean top, double packCurrentA, double cellTempC, int battStat, int alarm) {
        BmsUnit u = top ? bmsTop : bmsBot;
        // TOP은 전류감지 핀 미사용이라 항상 0 — BOT 값을 덮어쓰지 않도록 호출부에서 그대로 0 전달
        u.packCurrentA = packCurrentA;
        u.cellTempC = cellTempC;
        u.battStat = battStat;
        u.alarm = alarm;
        u.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsFault(boolean top, long faultFlags) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.faultFlags = faultFlags;
        u.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsSoc(boolean top, double socPercent) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.socPercent = socPercent;
        u.lastUpdate = System.currentTimeMillis();
    }

    // ---- BMS(HV) DETAIL 갱신 ----

    /** cellBase = 이 패킷이 채우는 첫 셀 인덱스 (0,4,8,12). value 4개를 cellMv[cellBase..+3]에 반영. */
    public synchronized void updateBmsCells(boolean top, int cellBase, int v0, int v1, int v2, int v3) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.cellMv[cellBase] = v0;
        u.cellMv[cellBase + 1] = v1;
        u.cellMv[cellBase + 2] = v2;
        u.cellMv[cellBase + 3] = v3;
        u.cellMvUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsTempA(boolean top, double ts1, double fet, double internal, double cfetoff) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.cellTempTs1C = ts1;
        u.fetTempC = fet;
        u.intTempC = internal;
        u.cfetoffTempC = cfetoff;
        u.detailTempUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsTempB(boolean top, double hdq, double maxT, double minT, double avgT) {
        BmsUnit u = top ? bmsTop : bmsBot;
        u.hdqTempC = hdq;
        u.maxCellTempC = maxT;
        u.minCellTempC = minT;
        u.avgCellTempC = avgT;
        u.detailTempUpdate = System.currentTimeMillis();
    }

    // ---- MPPT 갱신 (index 0~2 = MPPT #1~#3) ----

    public synchronized void updateMppt(int index, double inV, double inI, double outV, double outI) {
        if (index < 0 || index >= mppt.length) return;
        MpptUnit u = mppt[index];
        u.inVoltageV = inV;
        u.inCurrentA = inI;
        u.outVoltageV = outV;
        u.outCurrentA = outI;
        u.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMpptTempFlags(int index, double mosfetTempC, double ctrlTempC, int errorFlags, int mode) {
        if (index < 0 || index >= mppt.length) return;
        MpptUnit u = mppt[index];
        u.mosfetTempC = mosfetTempC;
        u.ctrlTempC = ctrlTempC;
        u.errorFlags = errorFlags;
        u.mode = mode;
        u.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMpptMaxLim(int index, double maxOutV, double maxInI) {
        if (index < 0 || index >= mppt.length) return;
        MpptUnit u = mppt[index];
        u.maxOutVoltageV = maxOutV;
        u.maxInCurrentA = maxInI;
        u.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMpptAux2(int index, double powerConnV, double powerConnTempC) {
        if (index < 0 || index >= mppt.length) return;
        MpptUnit u = mppt[index];
        u.powerConnVoltageV = powerConnV;
        u.powerConnTempC = powerConnTempC;
        u.detailUpdate = System.currentTimeMillis();
    }

    // ---- Motor PRIMARY 갱신 ----

    public synchronized void updateMotorBusVel(double busV, double busI, int rpm, double vehSpeedMs) {
        motor.busVoltageV = busV;
        motor.busCurrentA = busI;
        motor.rpm = rpm;
        motor.vehicleSpeedMs = vehSpeedMs;
        motor.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMotorTemp(double heatsinkTempC, double motorTempC) {
        motor.heatsinkTempC = heatsinkTempC;
        motor.motorTempC = motorTempC;
        motor.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMotorBemf(double bemfD, double bemfQ) {
        motor.bemfDV = bemfD;
        motor.bemfQV = bemfQ;
        motor.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMotorOdo(double odometerM, double dcBusAh) {
        motor.odometerM = odometerM;
        motor.dcBusAmpHours = dcBusAh;
        motor.lastUpdate = System.currentTimeMillis();
    }

    // ---- Motor DETAIL 갱신 ----

    public synchronized void updateMotorDspTemp(double dspTempC) {
        motor.dspTempC = dspTempC;
        motor.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMotorStatus(int limitFlags, int errorFlags, int activeMotor, int txErrCnt, int rxErrCnt) {
        motor.limitFlags = limitFlags;
        motor.errorFlags = errorFlags;
        motor.activeMotor = activeMotor;
        motor.txErrCnt = txErrCnt;
        motor.rxErrCnt = rxErrCnt;
        motor.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateMotorPhaseI(double phaseBA, double phaseCA) {
        motor.phaseBCurrentA = phaseBA;
        motor.phaseCCurrentA = phaseCA;
        motor.detailUpdate = System.currentTimeMillis();
    }

    // ---- BMS(LV) PRIMARY 갱신 ----

    public synchronized void updateBmsLvSoc(double socAh, double socPercent) {
        bmsLv.socAh = socAh;
        bmsLv.socPercent = socPercent;
        bmsLv.lastUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvPackVi(long packVoltageMv, long packCurrentMa) {
        bmsLv.packVoltageMv = packVoltageMv;
        bmsLv.packCurrentMa = packCurrentMa;
        bmsLv.lastUpdate = System.currentTimeMillis();
    }

    // ---- BMS(LV) DETAIL 갱신 ----

    public synchronized void updateBmsLvCells(int cellBase, int v0, int v1, int v2, int v3) {
        bmsLv.cellMv[cellBase] = v0;
        bmsLv.cellMv[cellBase + 1] = v1;
        bmsLv.cellMv[cellBase + 2] = v2;
        bmsLv.cellMv[cellBase + 3] = v3;
        bmsLv.cellUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvBalance(double ah, double pct) {
        bmsLv.balanceAh = ah;
        bmsLv.balancePercent = pct;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvCharger(int chargeVErrMv, double tempMarginC, int dischargeVErrMv, int totalCapAh) {
        bmsLv.chargeVErrMv = chargeVErrMv;
        bmsLv.chargeTempMarginC = tempMarginC;
        bmsLv.dischargeVErrMv = dischargeVErrMv;
        bmsLv.totalCapacityAh = totalCapAh;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvPrecharge(int contactorStatus, int prechargeState, int supply12vMv, int timerElapsed, int timerCnt) {
        bmsLv.contactorStatus = contactorStatus;
        bmsLv.prechargeState = prechargeState;
        bmsLv.supply12vMv = supply12vMv;
        bmsLv.prechargeTimerElapsed = timerElapsed;
        bmsLv.prechargeTimerCnt = timerCnt;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvMinMaxV(int minV, int maxV, int minCmu, int minCell, int maxCmu, int maxCell) {
        bmsLv.minCellMv = minV;
        bmsLv.maxCellMv = maxV;
        bmsLv.minCellCmu = minCmu;
        bmsLv.minCellIdx = minCell;
        bmsLv.maxCellCmu = maxCmu;
        bmsLv.maxCellIdx = maxCell;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvMinMaxT(double minT, double maxT, int minCmu, int maxCmu) {
        bmsLv.minCellTempC = minT;
        bmsLv.maxCellTempC = maxT;
        bmsLv.minTempCmu = minCmu;
        bmsLv.maxTempCmu = maxCmu;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvStatus(int threshRisingMv, int threshFallingMv, int statusFlags, int cmuCount, int fwBuild) {
        bmsLv.balanceThreshRisingMv = threshRisingMv;
        bmsLv.balanceThreshFallingMv = threshFallingMv;
        bmsLv.statusFlags = statusFlags;
        bmsLv.cmuCount = cmuCount;
        bmsLv.fwBuild = fwBuild;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    public synchronized void updateBmsLvFan(int fanSpeed0, int fanSpeed1, int fanContactorMa, int cmuMa) {
        bmsLv.fanSpeed0Rpm = fanSpeed0;
        bmsLv.fanSpeed1Rpm = fanSpeed1;
        bmsLv.fanContactorCurrentMa = fanContactorMa;
        bmsLv.cmuCurrentMa = cmuMa;
        bmsLv.detailUpdate = System.currentTimeMillis();
    }

    /** 현재 상태를 JSON 직렬화용 불변 DTO로 복사한다. */
    public synchronized Dto toDto() {
        Dto dto = new Dto();
        dto.bmsBot = copy(bmsBot);
        dto.bmsTop = copy(bmsTop);
        dto.mppt = new MpptDto[mppt.length];
        for (int i = 0; i < mppt.length; i++) {
            dto.mppt[i] = copy(mppt[i]);
        }
        dto.motor = copy(motor);
        dto.bmsLv = copy(bmsLv);
        dto.totalFrames = totalFrames;
        dto.checksumFailures = checksumFailures;
        dto.framingErrors = framingErrors;
        dto.lastFrameTime = lastFrameTime;
        dto.currentDriver = currentDriver;
        dto.serverTime = System.currentTimeMillis();
        return dto;
    }

    private static BmsUnit copy(BmsUnit src) {
        BmsUnit c = new BmsUnit();
        c.stackVoltageV = src.stackVoltageV;
        c.packVoltageV = src.packVoltageV;
        c.maxCellMv = src.maxCellMv;
        c.minCellMv = src.minCellMv;
        c.packCurrentA = src.packCurrentA;
        c.cellTempC = src.cellTempC;
        c.battStat = src.battStat;
        c.alarm = src.alarm;
        c.faultFlags = src.faultFlags;
        c.socPercent = src.socPercent;
        c.lastUpdate = src.lastUpdate;
        c.cellMv = src.cellMv.clone();
        c.cellMvUpdate = src.cellMvUpdate;
        c.cellTempTs1C = src.cellTempTs1C;
        c.fetTempC = src.fetTempC;
        c.intTempC = src.intTempC;
        c.cfetoffTempC = src.cfetoffTempC;
        c.hdqTempC = src.hdqTempC;
        c.maxCellTempC = src.maxCellTempC;
        c.minCellTempC = src.minCellTempC;
        c.avgCellTempC = src.avgCellTempC;
        c.detailTempUpdate = src.detailTempUpdate;
        return c;
    }

    private static MpptDto copy(MpptUnit src) {
        MpptDto c = new MpptDto();
        c.inVoltageV = src.inVoltageV;
        c.inCurrentA = src.inCurrentA;
        c.outVoltageV = src.outVoltageV;
        c.outCurrentA = src.outCurrentA;
        c.outputPowerW = src.outputPowerW();
        c.lastUpdate = src.lastUpdate;
        c.mosfetTempC = src.mosfetTempC;
        c.ctrlTempC = src.ctrlTempC;
        c.errorFlags = src.errorFlags;
        c.mode = src.mode;
        c.maxOutVoltageV = src.maxOutVoltageV;
        c.maxInCurrentA = src.maxInCurrentA;
        c.powerConnVoltageV = src.powerConnVoltageV;
        c.powerConnTempC = src.powerConnTempC;
        c.detailUpdate = src.detailUpdate;
        return c;
    }

    private static MotorUnit copy(MotorUnit src) {
        MotorUnit c = new MotorUnit();
        c.busVoltageV = src.busVoltageV;
        c.busCurrentA = src.busCurrentA;
        c.rpm = src.rpm;
        c.vehicleSpeedMs = src.vehicleSpeedMs;
        c.heatsinkTempC = src.heatsinkTempC;
        c.motorTempC = src.motorTempC;
        c.bemfDV = src.bemfDV;
        c.bemfQV = src.bemfQV;
        c.odometerM = src.odometerM;
        c.dcBusAmpHours = src.dcBusAmpHours;
        c.lastUpdate = src.lastUpdate;
        c.dspTempC = src.dspTempC;
        c.limitFlags = src.limitFlags;
        c.errorFlags = src.errorFlags;
        c.activeMotor = src.activeMotor;
        c.txErrCnt = src.txErrCnt;
        c.rxErrCnt = src.rxErrCnt;
        c.phaseBCurrentA = src.phaseBCurrentA;
        c.phaseCCurrentA = src.phaseCCurrentA;
        c.detailUpdate = src.detailUpdate;
        return c;
    }

    private static BmsLvUnit copy(BmsLvUnit src) {
        BmsLvUnit c = new BmsLvUnit();
        c.socAh = src.socAh;
        c.socPercent = src.socPercent;
        c.packVoltageMv = src.packVoltageMv;
        c.packCurrentMa = src.packCurrentMa;
        c.lastUpdate = src.lastUpdate;
        c.cellMv = src.cellMv.clone();
        c.cellUpdate = src.cellUpdate;
        c.balanceAh = src.balanceAh;
        c.balancePercent = src.balancePercent;
        c.chargeVErrMv = src.chargeVErrMv;
        c.chargeTempMarginC = src.chargeTempMarginC;
        c.dischargeVErrMv = src.dischargeVErrMv;
        c.totalCapacityAh = src.totalCapacityAh;
        c.contactorStatus = src.contactorStatus;
        c.prechargeState = src.prechargeState;
        c.supply12vMv = src.supply12vMv;
        c.prechargeTimerElapsed = src.prechargeTimerElapsed;
        c.prechargeTimerCnt = src.prechargeTimerCnt;
        c.minCellMv = src.minCellMv;
        c.maxCellMv = src.maxCellMv;
        c.minCellCmu = src.minCellCmu;
        c.minCellIdx = src.minCellIdx;
        c.maxCellCmu = src.maxCellCmu;
        c.maxCellIdx = src.maxCellIdx;
        c.minCellTempC = src.minCellTempC;
        c.maxCellTempC = src.maxCellTempC;
        c.minTempCmu = src.minTempCmu;
        c.maxTempCmu = src.maxTempCmu;
        c.balanceThreshRisingMv = src.balanceThreshRisingMv;
        c.balanceThreshFallingMv = src.balanceThreshFallingMv;
        c.statusFlags = src.statusFlags;
        c.cmuCount = src.cmuCount;
        c.fwBuild = src.fwBuild;
        c.fanSpeed0Rpm = src.fanSpeed0Rpm;
        c.fanSpeed1Rpm = src.fanSpeed1Rpm;
        c.fanContactorCurrentMa = src.fanContactorCurrentMa;
        c.cmuCurrentMa = src.cmuCurrentMa;
        c.detailUpdate = src.detailUpdate;
        return c;
    }

    /** MPPT DTO — outputPowerW를 함께 실어보내기 위해 MpptUnit과 별도 타입으로 둔다. */
    public static class MpptDto {
        public double inVoltageV;
        public double inCurrentA;
        public double outVoltageV;
        public double outCurrentA;
        public double outputPowerW;
        public long lastUpdate;
        public double mosfetTempC;
        public double ctrlTempC;
        public int errorFlags;
        public int mode;
        public double maxOutVoltageV;
        public double maxInCurrentA;
        public double powerConnVoltageV;
        public double powerConnTempC;
        public long detailUpdate;
    }

    /** REST 응답으로 그대로 직렬화되는 불변 스냅샷. */
    public static class Dto {
        public BmsUnit bmsBot;
        public BmsUnit bmsTop;
        public MpptDto[] mppt;
        public MotorUnit motor;
        public BmsLvUnit bmsLv;
        public long totalFrames;
        public long checksumFailures;
        public long framingErrors;
        public long lastFrameTime;
        public long serverTime;
        public int currentDriver;
    }
}
