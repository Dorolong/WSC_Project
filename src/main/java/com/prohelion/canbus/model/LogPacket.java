package com.prohelion.canbus.model;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * 16바이트 LOG 패킷 구조 (WSC_Transmitter_Code_V1 Core/Inc/types.h 기준):
 * [timestamp 4B][level 1B][source 1B][key 1B][value 8B][checksum 1B]
 *
 * source/key 조합에 따른 value[8] 해석은 {@link com.prohelion.canbus.serial.WscTelemetryDecoder}
 * 및 can-signal-summary.md §5(무선 PRIMARY 패킷 묶음 목록) 참조.
 */
public class LogPacket {

    private long timestamp;   // 4B unsigned (ms 단위, HAL_GetTick())
    private byte level;       // 1B (LOG_LEVEL)
    private byte source;      // 1B (LOG_SOURCE)
    private byte key;         // 1B (source별 key 네임스페이스)
    private byte[] value;     // 8B
    private byte checksum;    // 1B

    public LogPacket() {
        this.value = new byte[8];
    }

    /**
     * 16바이트 raw 데이터에서 파싱. checksum은 CRC-8(poly 0x07, init 0x00,
     * MSB-first, no reflect) — firmware Core/Src/packet_builder.c의 crc8()과 동일.
     * (과거엔 단순 XOR이었으나 펌웨어가 CRC-8로 전환됨에 따라 동일하게 맞춤)
     */
    public static LogPacket parse(byte[] data) {
        if (data == null || data.length != 16) {
            return null;
        }

        byte calc = crc8(data, 15);
        if (calc != data[15]) {
            return null; // checksum 불일치
        }

        LogPacket pkt = new LogPacket();
        ByteBuffer buf = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);

        pkt.timestamp = buf.getInt() & 0xFFFFFFFFL;  // unsigned 4B
        pkt.level = buf.get();
        pkt.source = buf.get();
        pkt.key = buf.get();
        buf.get(pkt.value, 0, 8);
        pkt.checksum = buf.get();

        return pkt;
    }

    /**
     * CRC-8 (다항식 0x07, init 0x00, no reflect/no final XOR) — CRC-8/SMBus.
     * 펌웨어 packet_builder.c의 테이블 기반 구현과 비트 단위로 동일한 결과를 낸다.
     */
    public static byte crc8(byte[] data, int len) {
        int crc = 0x00;
        for (int i = 0; i < len; i++) {
            crc ^= (data[i] & 0xFF);
            for (int b = 0; b < 8; b++) {
                if ((crc & 0x80) != 0) {
                    crc = ((crc << 1) ^ 0x07) & 0xFF;
                } else {
                    crc = (crc << 1) & 0xFF;
                }
            }
        }
        return (byte) crc;
    }

    // ---- value[8] 슬롯 판독 헬퍼 (전부 little-endian, STM32 native) ----

    public int u16(int offset) {
        return (value[offset] & 0xFF) | ((value[offset + 1] & 0xFF) << 8);
    }

    public short i16(int offset) {
        return (short) u16(offset);
    }

    public long u32(int offset) {
        return (value[offset] & 0xFFL)
                | ((value[offset + 1] & 0xFFL) << 8)
                | ((value[offset + 2] & 0xFFL) << 16)
                | ((value[offset + 3] & 0xFFL) << 24);
    }

    public int i32(int offset) {
        return (int) u32(offset);
    }

    public float f32(int offset) {
        return ByteBuffer.wrap(value, offset, 4).order(ByteOrder.LITTLE_ENDIAN).getFloat();
    }

    // Getters
    public long getTimestamp() { return timestamp; }
    public byte getLevel() { return level; }
    public byte getSource() { return source; }
    public byte getKey() { return key; }
    public byte[] getValue() { return value; }
    public byte getChecksum() { return checksum; }

    @Override
    public String toString() {
        return String.format("LogPacket[ts=%d, src=%d, key=0x%02X]", timestamp, source, key);
    }
}
