package com.prohelion.service.impl;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import com.prohelion.canbus.model.LogPacket;
import com.prohelion.canbus.model.LogSource;
import com.prohelion.canbus.model.VehicleSnapshot;
import com.prohelion.canbus.serial.WscTelemetryDecoder;

/**
 * 실제 RFD900x/LoRa 하드웨어 없이 대시보드를 검증/시연하기 위한 시뮬레이터.
 * can-signal-summary.md §5의 17개 무선 PRIMARY 패킷을 200ms 주기로 생성해
 * LogPacket.parse()(CRC-8 검증 포함) → WscTelemetryDecoder.apply()까지 실제
 * 수신 경로와 동일한 코드로 흘려보낸다 — COBS/시리얼 계층만 건너뛴다.
 *
 * application.properties의 wsc.telemetry.simulate=true 일 때만 동작하며,
 * 실제 하드웨어가 uart.rx로 연결되면 이 값을 false로 끄면 된다.
 */
@Service
public class WscSimulatorService {

    private static final Logger LOG = LoggerFactory.getLogger(WscSimulatorService.class);

    @Value("${wsc.telemetry.simulate:false}")
    private boolean enabled;

    @Autowired
    private VehicleSnapshot vehicleSnapshot;

    private ScheduledExecutorService executor;
    private double odometerM = 0;
    private double dcBusAh = 0;
    private long tickCount = 0;

    @PostConstruct
    public void start() {
        if (!enabled) {
            LOG.info("WSC telemetry simulator disabled (wsc.telemetry.simulate=false)");
            return;
        }
        LOG.info("WSC telemetry simulator ENABLED — generating synthetic PRIMARY packets every 200ms");
        executor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "wsc-sim");
            t.setDaemon(true);
            return t;
        });
        executor.scheduleAtFixedRate(this::tick, 0, 200, TimeUnit.MILLISECONDS);
    }

    private void tick() {
        try {
            tickCount++;
            double t = System.currentTimeMillis() / 1000.0;

            double stackV = 118.0 + 3.0 * Math.sin(t / 20.0);
            double packCurrentA = 8.0 + 6.0 * Math.sin(t / 5.0);
            double maxCellMv = 4150 + 10 * Math.sin(t / 7.0);
            double minCellMv = 4080 + 10 * Math.sin(t / 7.3);
            double cellTemp = 28.0 + 2.0 * Math.sin(t / 30.0);
            double socPct = 72.0 - (t % 3600) / 200.0; // 서서히 방전

            // #1 BMS BOT VOLT_STACK
            emit(LogSource.SRC_BMS_BOT, 0x00, packU16x4(
                    (int) Math.round(stackV * 100), (int) Math.round(stackV * 100),
                    (int) Math.round(maxCellMv), (int) Math.round(minCellMv)));
            // #2 BMS BOT CURR_TEMP
            emit(LogSource.SRC_BMS_BOT, 0x01, packI16I16U16U16(
                    (short) Math.round(packCurrentA * 100), (short) Math.round(cellTemp * 10), 0, 0));
            // #3 BMS BOT FAULT
            emit(LogSource.SRC_BMS_BOT, 0x02, packU32x2(0, 0));
            // #16 BMS BOT SOC
            emit(LogSource.SRC_BMS_BOT, 0x03, packU16x4((int) Math.round(socPct * 10), 0, 0, 0));

            // #4 BMS TOP VOLT_STACK (동일 경향, 약간의 오프셋)
            emit(LogSource.SRC_BMS_TOP, 0x00, packU16x4(
                    (int) Math.round(stackV * 100) - 20, (int) Math.round(stackV * 100) - 20,
                    (int) Math.round(maxCellMv) - 5, (int) Math.round(minCellMv) + 5));
            // #5 BMS TOP CURR_TEMP (전류 슬롯 없음)
            emit(LogSource.SRC_BMS_TOP, 0x01, packI16U16U16U16(
                    (short) Math.round((cellTemp + 0.5) * 10), 0, 0, 0));
            // #6 BMS TOP FAULT
            emit(LogSource.SRC_BMS_TOP, 0x02, packU32x2(0, 0));
            // #17 BMS TOP SOC
            emit(LogSource.SRC_BMS_TOP, 0x03, packU16x4((int) Math.round(socPct * 10) - 2, 0, 0, 0));

            // #7/#8/#9 MPPT x3
            for (int i = 0; i < 3; i++) {
                double phase = i * 2.1;
                double inV = 60 + 15 * Math.max(0, Math.sin(t / 40.0 + phase));
                double inI = 2.0 + 1.5 * Math.max(0, Math.sin(t / 6.0 + phase));
                double outV = stackV;
                double outI = (inV * inI) / Math.max(outV, 1.0);
                int src = LogSource.SRC_MPPT1 + i;
                emit(src, 0x00, packU16x4(
                        (int) Math.round(inV * 100), (int) Math.round(inI * 100),
                        (int) Math.round(outV * 100), (int) Math.round(outI * 100)));
            }

            // #10 MOTOR BUS_VEL
            double busI = 10.0 * Math.sin(t / 8.0);
            int rpm = (int) Math.max(0, 2200 + 800 * Math.sin(t / 25.0));
            double vehSpeedMs = Math.max(0, 18.0 + 6.0 * Math.sin(t / 25.0));
            emit(LogSource.SRC_MOTOR, 0x00, packU16I16I16U16(
                    (int) Math.round(stackV * 100), (short) Math.round(busI * 10),
                    (short) rpm, (int) Math.round(vehSpeedMs * 100)));

            // #11 MOTOR TEMP
            double heatsinkT = 35 + 5 * Math.sin(t / 15.0);
            double motorT = 40 + 6 * Math.sin(t / 15.0 + 1.0);
            emit(LogSource.SRC_MOTOR, 0x01, packI16I16I16I16(
                    (short) Math.round(heatsinkT * 10), (short) Math.round(motorT * 10), (short) 0, (short) 0));

            // #12 MOTOR BEMF
            emit(LogSource.SRC_MOTOR, 0x02, packI16I16I16I16((short) 0, (short) Math.round(vehSpeedMs * 5), (short) 0, (short) 0));

            // #13 MOTOR ODO (누적)
            odometerM += vehSpeedMs * 0.2; // 200ms tick
            dcBusAh += Math.abs(busI) * (0.2 / 3600.0);
            emit(LogSource.SRC_MOTOR, 0x03, packFloat2((float) odometerM, (float) dcBusAh));

            // #14 BMS_LV SOC
            emit(LogSource.SRC_BMS_LV, 0x00, packFloat2(4.2f, 92.0f + (float) Math.sin(t / 60.0)));
            // #15 BMS_LV PACK_VI
            emit(LogSource.SRC_BMS_LV, 0x01, packU32I32(13200 + (long) (100 * Math.sin(t / 10.0)), (int) (150 * Math.sin(t / 4.0))));

            // DETAIL(1s) 신호는 5틱(200ms x 5 = 1s)마다 한 번씩만 내보낸다 — 실제 펌웨어와 동일한 주기
            if (tickCount % 5 == 0) {
                tickDetail(t, stackV, maxCellMv, minCellMv, cellTemp);
            }

        } catch (Exception ex) {
            LOG.warn("Simulator tick error: {}", ex.getMessage());
        }
    }

    private void tickDetail(double t, double stackV, double maxCellMv, double minCellMv, double cellTemp) {
        // BMS BOT/TOP 셀 전압 16개 + 상세온도
        for (int side = 0; side < 2; side++) {
            boolean top = side == 1;
            int source = top ? LogSource.SRC_BMS_TOP : LogSource.SRC_BMS_BOT;
            for (int frame = 0; frame < 4; frame++) {
                int base = frame * 4;
                int[] v = new int[4];
                for (int i = 0; i < 4; i++) {
                    int cellIdx = base + i;
                    double spread = (maxCellMv - minCellMv) * (cellIdx / 16.0);
                    v[i] = (int) Math.round(minCellMv + spread + 3 * Math.sin(t / 9.0 + cellIdx));
                }
                emit(source, 0x10 + frame, packU16x4(v[0], v[1], v[2], v[3]));
            }
            emit(source, 0x14, packI16I16I16I16( // TEMP_A: TS1, FET, Int, CFETOFF
                    (short) Math.round(cellTemp * 10), (short) Math.round((cellTemp + 3) * 10),
                    (short) Math.round((cellTemp + 1) * 10), (short) Math.round((cellTemp + 2) * 10)));
            emit(source, 0x15, packI16I16I16I16( // TEMP_B: HDQ, Max, Min, Avg
                    (short) Math.round((cellTemp + 0.5) * 10), (short) Math.round((cellTemp + 4) * 10),
                    (short) Math.round((cellTemp - 2) * 10), (short) Math.round(cellTemp * 10)));
        }

        // MPPT x3 DETAIL
        for (int i = 0; i < 3; i++) {
            double mosfetT = 32 + 4 * Math.sin(t / 20.0 + i);
            double ctrlT = 30 + 3 * Math.sin(t / 22.0 + i);
            int src = LogSource.SRC_MPPT1 + i;
            emit(src, 0x10, packI16I16I16I16((short) Math.round(mosfetT * 10), (short) Math.round(ctrlT * 10), (short) 0, (short) 0));
            emit(src, 0x11, packU16x4(15000, 1000, 0, 0)); // MaxOutV=150.00V, MaxInI=10.00A
            emit(src, 0x12, packI16I16I16I16((short) 4800, (short) Math.round(ctrlT * 10), (short) 0, (short) 0)); // PowerConnV=48.00V
        }

        // Motor DETAIL
        emit(LogSource.SRC_MOTOR, 0x10, packI16I16I16I16((short) Math.round((35 + 3 * Math.sin(t / 18.0)) * 10), (short) 0, (short) 0, (short) 0));
        emit(LogSource.SRC_MOTOR, 0x11, packU16x4(0, 0, 1, 0)); // Limit/Error flags=0, ActiveMotor=1
        emit(LogSource.SRC_MOTOR, 0x12, packI16I16I16I16((short) Math.round(3 * Math.sin(t / 6.0) * 10), (short) Math.round(3 * Math.cos(t / 6.0) * 10), (short) 0, (short) 0));

        // BMS_LV DETAIL — CMU0 셀 8개 + 밸런스/충전기/프리차지/최소최대/상태/팬
        emit(LogSource.SRC_BMS_LV, 0x11, packI16I16I16I16((short) 3300, (short) 3305, (short) 3298, (short) 3302));
        emit(LogSource.SRC_BMS_LV, 0x12, packI16I16I16I16((short) 3301, (short) 3299, (short) 3303, (short) 3297));
        emit(LogSource.SRC_BMS_LV, 0x13, packFloat2(0.4f, 8.0f));
        emit(LogSource.SRC_BMS_LV, 0x14, packI16I16I16U16((short) 5, (short) 20, (short) -5, 20));
        emit(LogSource.SRC_BMS_LV, 0x15, new byte[]{1, 4, (byte) 0xE8, 0x03, 0, 0, 0, 0}); // contactor=1,state=4(run),12V=0x03E8=1000mV
        emit(LogSource.SRC_BMS_LV, 0x16, packU16x4(3297, 3305, 0, 0x0100)); // minV,maxV,minCmu/minCell,maxCmu/maxCell
        emit(LogSource.SRC_BMS_LV, 0x17, packU16x4((int) ((cellTemp - 1) * 10), (int) ((cellTemp + 1) * 10), 0, 0));
        emit(LogSource.SRC_BMS_LV, 0x18, packU16x4(4200, 4100, 0x0001, 100)); // threshRise,threshFall,status/cmuCount,fwBuild
        emit(LogSource.SRC_BMS_LV, 0x19, packU16x4(4200, 4200, 500, 300)); // fan0,fan1,fanContactorI,cmuI(mA)
    }

    private void emit(int source, int key, byte[] value8) {
        byte[] pkt = new byte[16];
        ByteBuffer buf = ByteBuffer.wrap(pkt).order(ByteOrder.LITTLE_ENDIAN);
        buf.putInt((int) System.currentTimeMillis());
        buf.put((byte) 0); // level = LOG_INFO
        buf.put((byte) source);
        buf.put((byte) key);
        buf.put(value8, 0, 8);
        pkt[15] = LogPacket.crc8(pkt, 15);

        LogPacket parsed = LogPacket.parse(pkt);
        if (parsed == null) {
            LOG.warn("Simulator produced an invalid packet (should never happen) src={} key={}", source, key);
            vehicleSnapshot.recordChecksumFailure();
            return;
        }
        vehicleSnapshot.recordFrameOk();
        WscTelemetryDecoder.apply(vehicleSnapshot, parsed);
    }

    // ---- value[8] 패킹 헬퍼 (little-endian) ----

    private static byte[] packU16x4(int a, int b, int c, int d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort((short) a).putShort((short) b).putShort((short) c).putShort((short) d);
        return buf.array();
    }

    private static byte[] packI16I16U16U16(short a, short b, int c, int d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort(a).putShort(b).putShort((short) c).putShort((short) d);
        return buf.array();
    }

    private static byte[] packI16I16I16U16(short a, short b, short c, int d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort(a).putShort(b).putShort(c).putShort((short) d);
        return buf.array();
    }

    private static byte[] packI16U16U16U16(short a, int b, int c, int d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort(a).putShort((short) b).putShort((short) c).putShort((short) d);
        return buf.array();
    }

    private static byte[] packU16I16I16U16(int a, short b, short c, int d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort((short) a).putShort(b).putShort(c).putShort((short) d);
        return buf.array();
    }

    private static byte[] packI16I16I16I16(short a, short b, short c, short d) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putShort(a).putShort(b).putShort(c).putShort(d);
        return buf.array();
    }

    private static byte[] packU32x2(long a, long b) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putInt((int) a).putInt((int) b);
        return buf.array();
    }

    private static byte[] packU32I32(long a, int b) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putInt((int) a).putInt(b);
        return buf.array();
    }

    private static byte[] packFloat2(float a, float b) {
        ByteBuffer buf = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        buf.putFloat(a).putFloat(b);
        return buf.array();
    }

    @PreDestroy
    public void stop() {
        if (executor != null) {
            executor.shutdownNow();
        }
    }
}
