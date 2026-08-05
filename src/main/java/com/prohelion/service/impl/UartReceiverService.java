package com.prohelion.service.impl;

import java.io.ByteArrayOutputStream;

import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import com.fazecast.jSerialComm.SerialPort;
import com.fazecast.jSerialComm.SerialPortDataListener;
import com.fazecast.jSerialComm.SerialPortEvent;
import com.prohelion.canbus.model.LogPacket;
import com.prohelion.canbus.model.VehicleSnapshot;
import com.prohelion.canbus.serial.CobsDecoder;
import com.prohelion.canbus.serial.WscTelemetryDecoder;

/**
 * UART(RFD900x/LoRa)로 COBS 프레임을 수신하여 LOG 패킷을 파싱하고
 * {@link VehicleSnapshot}(실시간 대시보드 상태)에 반영하는 서비스.
 */
@Service
public class UartReceiverService {

    private static final Logger LOG = LoggerFactory.getLogger(UartReceiverService.class);

    private static final byte TYPE_CAN_DATA = 0x01;
    private static final byte TYPE_MESSAGE = 0x02;

    @Value("${uart.rx.port:NONE}")
    private String portName;

    @Value("${uart.rx.baudrate:57600}")
    private int baudRate;

    @Value("${uart.rx.enabled:false}")
    private boolean enabled;

    @Autowired
    private VehicleSnapshot vehicleSnapshot;

    private SerialPort serialPort;
    private ByteArrayOutputStream frameBuffer = new ByteArrayOutputStream();

    @PostConstruct
    public void start() {
        if (!enabled || "NONE".equals(portName)) {
            LOG.info("UART receiver disabled (uart.rx.enabled={}, uart.rx.port={})", enabled, portName);
            return;
        }

        try {
            serialPort = SerialPort.getCommPort(portName);
            serialPort.setBaudRate(baudRate);
            serialPort.setNumDataBits(8);
            serialPort.setNumStopBits(1);
            serialPort.setParity(SerialPort.NO_PARITY);

            if (!serialPort.openPort()) {
                LOG.error("Failed to open UART RX port: {}", portName);
                return;
            }

            LOG.info("UART receiver started on {} @ {} bps", portName, baudRate);

            serialPort.addDataListener(new SerialPortDataListener() {
                @Override
                public int getListeningEvents() {
                    return SerialPort.LISTENING_EVENT_DATA_RECEIVED;
                }

                @Override
                public void serialEvent(SerialPortEvent event) {
                    byte[] data = event.getReceivedData();
                    synchronized (frameBuffer) {
                        for (byte b : data) {
                            if (b == 0x00) {
                                processFrame(frameBuffer.toByteArray());
                                frameBuffer.reset();
                            } else {
                                frameBuffer.write(b);
                                if (frameBuffer.size() > 256) {
                                    LOG.warn("Frame buffer overflow, resetting");
                                    vehicleSnapshot.recordFramingError();
                                    frameBuffer.reset();
                                }
                            }
                        }
                    }
                }
            });

        } catch (Exception ex) {
            LOG.error("UART receiver init error: {}", ex.getMessage());
        }
    }

    /**
     * COBS 프레임 처리:
     * 1. COBS 디코딩
     * 2. 타입 헤더 확인 (0x01 = CAN/LOG 데이터)
     * 3. 16B LOG 패킷 파싱 (CRC-8 검증 포함)
     * 4. source+key → VehicleSnapshot 반영 (WscTelemetryDecoder)
     */
    void processFrame(byte[] cobsFrame) {
        if (cobsFrame.length == 0) return;

        byte[] decoded = CobsDecoder.decode(cobsFrame);
        if (decoded == null || decoded.length < 2) {
            LOG.debug("COBS decode failed or too short");
            vehicleSnapshot.recordFramingError();
            return;
        }

        byte type = decoded[0];

        if (type == TYPE_CAN_DATA) {
            // 타입 헤더 제거 → 16B LOG 패킷
            if (decoded.length != 17) {  // 1B type + 16B log
                LOG.debug("Invalid LOG packet length: {}", decoded.length);
                vehicleSnapshot.recordFramingError();
                return;
            }

            byte[] logData = new byte[16];
            System.arraycopy(decoded, 1, logData, 0, 16);

            LogPacket pkt = LogPacket.parse(logData);
            if (pkt == null) {
                LOG.debug("LOG packet parse/checksum failed");
                vehicleSnapshot.recordChecksumFailure();
                return;
            }

            vehicleSnapshot.recordFrameOk();
            WscTelemetryDecoder.apply(vehicleSnapshot, pkt);
            LOG.debug("Received: {}", pkt);

        } else if (type == TYPE_MESSAGE) {
            // 텍스트 메시지 수신 (향후 구현)
            String msg = new String(decoded, 1, decoded.length - 1);
            LOG.info("UART message received: {}", msg);
        }
    }

    @PreDestroy
    public void stop() {
        if (serialPort != null && serialPort.isOpen()) {
            serialPort.closePort();
            LOG.info("UART receiver stopped");
        }
    }
}
