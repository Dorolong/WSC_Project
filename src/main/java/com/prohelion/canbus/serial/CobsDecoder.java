package com.prohelion.canbus.serial;

/**
 * COBS 디코딩: 0x00 delimiter로 분리된 프레임을 원본 데이터로 복원
 */
public class CobsDecoder {

    /**
     * COBS 디코딩 (0x00 delimiter 제외된 데이터 입력)
     * @param encoded COBS 인코딩된 바이트 (0x00 제외)
     * @return 디코딩된 원본 바이트, 실패 시 null
     */
    public static byte[] decode(byte[] encoded) {
        if (encoded == null || encoded.length == 0) {
            return null;
        }

        byte[] output = new byte[encoded.length];
        int outIdx = 0;
        int idx = 0;

        while (idx < encoded.length) {
            int code = encoded[idx++] & 0xFF;
            if (code == 0) {
                return null; // 잘못된 COBS 데이터
            }

            int dataLen = code - 1;
            if (idx + dataLen > encoded.length) {
                return null; // 데이터 부족
            }

            for (int i = 0; i < dataLen; i++) {
                output[outIdx++] = encoded[idx++];
            }

            // 마지막 그룹이 아니고 code < 0xFF이면 0x00 삽입
            if (idx < encoded.length && code < 0xFF) {
                output[outIdx++] = 0x00;
            }
        }

        byte[] result = new byte[outIdx];
        System.arraycopy(output, 0, result, 0, outIdx);
        return result;
    }
}
