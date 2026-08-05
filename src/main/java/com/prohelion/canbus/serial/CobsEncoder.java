package com.prohelion.canbus.serial;

public class CobsEncoder {

    /**
     * COBS 인코딩: 0x00을 제거하고 프레이밍
     * 결과 끝에 0x00 구분자 포함
     */
    public static byte[] encode(byte[] data) {
        byte[] output = new byte[data.length + data.length / 254 + 2];
        int outIdx = 1;
        int codeIdx = 0;
        byte code = 1;

        for (byte b : data) {
            if (b == 0) {
                output[codeIdx] = code;
                code = 1;
                codeIdx = outIdx++;
            } else {
                output[outIdx++] = b;
                code++;
                if (code == 0xFF) {
                    output[codeIdx] = code;
                    code = 1;
                    codeIdx = outIdx++;
                }
            }
        }
        output[codeIdx] = code;
        output[outIdx++] = 0x00; // 패킷 구분자

        byte[] result = new byte[outIdx];
        System.arraycopy(output, 0, result, 0, outIdx);
        return result;
    }
}
