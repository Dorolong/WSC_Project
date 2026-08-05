package com.prohelion.service.impl;

import javax.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import com.fazecast.jSerialComm.SerialPort;
import com.prohelion.canbus.serial.CobsEncoder;

@Service
public class UartMessageService {

    private static final Logger LOG = LoggerFactory.getLogger(UartMessageService.class);

    // 메시지 타입 헤더
    public static final byte TYPE_CAN_DATA = 0x01;
    public static final byte TYPE_MESSAGE = 0x02;

    // application.properties에서 설정 (나중에 채울 것)
    @Value("${uart.port:NONE}")
    private String portName;

    @Value("${uart.baudrate:9600}")
    private int baudRate;

    private SerialPort serialPort;

    /**
     * COBS 프레이밍된 메시지를 UART로 전송
     * 패킷 형식: [TYPE_MESSAGE][메시지 바이트들...] → COBS 인코딩 → [COBS...][0x00]
     */
    public boolean sendMessage(String message) {
        if ("NONE".equals(portName)) {
            LOG.warn("UART port not configured (uart.port=NONE). Message not sent: {}", message);
            return false;
        }

        try {
            byte[] msgBytes = message.getBytes("UTF-8");

            // 타입 헤더 + 메시지 결합
            byte[] payload = new byte[1 + msgBytes.length];
            payload[0] = TYPE_MESSAGE;
            System.arraycopy(msgBytes, 0, payload, 1, msgBytes.length);

            // COBS 인코딩
            byte[] cobsFrame = CobsEncoder.encode(payload);

            // 시리얼 포트 열고 전송
            if (openPort()) {
                serialPort.writeBytes(cobsFrame, cobsFrame.length);
                LOG.info("UART message sent ({} bytes): {}", cobsFrame.length, message);
                return true;
            }
        } catch (Exception ex) {
            LOG.error("Failed to send UART message: {}", ex.getMessage());
        }
        return false;
    }

    private boolean openPort() {
        if (serialPort != null && serialPort.isOpen()) {
            return true;
        }
        try {
            serialPort = SerialPort.getCommPort(portName);
            serialPort.setBaudRate(baudRate);
            serialPort.setNumDataBits(8);
            serialPort.setNumStopBits(1);
            serialPort.setParity(SerialPort.NO_PARITY);
            serialPort.setComPortTimeouts(SerialPort.TIMEOUT_WRITE_BLOCKING, 0, 1000);

            if (serialPort.openPort()) {
                LOG.info("UART port opened: {} @ {} bps", portName, baudRate);
                return true;
            } else {
                LOG.error("Failed to open UART port: {}", portName);
                return false;
            }
        } catch (Exception ex) {
            LOG.error("UART port error: {}", ex.getMessage());
            return false;
        }
    }

    @PreDestroy
    public void close() {
        if (serialPort != null && serialPort.isOpen()) {
            serialPort.closePort();
            LOG.info("UART port closed");
        }
    }
}
