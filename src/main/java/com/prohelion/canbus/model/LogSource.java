package com.prohelion.canbus.model;

/**
 * LOG_SOURCE enum (WSC_Transmitter_Code_V1 Core/Inc/types.h와 동일한 순서/값).
 * LOG 패킷의 {@code source} 필드 값 → 의미.
 */
public final class LogSource {
    public static final int SRC_SYS = 0;
    public static final int SRC_BMS_BOT = 1;
    public static final int SRC_BMS_TOP = 2;
    public static final int SRC_MPPT1 = 3;
    public static final int SRC_MPPT2 = 4;
    public static final int SRC_MPPT3 = 5;
    public static final int SRC_MOTOR = 6;
    public static final int SRC_BMS_LV = 7;
    public static final int SRC_RESERVED1 = 8;
    public static final int SRC_RESERVED2 = 9;
    public static final int SRC_CAN_ERR = 10;
    public static final int SRC_SPI_ERR = 11;
    public static final int SRC_UART_ERR = 12;
    public static final int SRC_SD_ERR = 13;

    private LogSource() { }
}
