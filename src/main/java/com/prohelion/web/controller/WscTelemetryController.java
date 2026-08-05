package com.prohelion.web.controller;

import java.util.Collections;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

import com.prohelion.canbus.model.VehicleSnapshot;

/**
 * WSC 무선 텔레메트리(RFD900x/LoRa 수신) 실시간 상태 JSON API.
 * 기존 "대시보드"(index.html)와 "BMS 요약"(bms.html) 페이지가 이 엔드포인트를
 * 폴링해서 값을 채운다 — 별도 페이지가 아니라 기존 화면에 통합되어 있다.
 * 값의 출처는 {@link com.prohelion.service.impl.UartReceiverService}(실 하드웨어) 또는
 * {@link com.prohelion.service.impl.WscSimulatorService}(하드웨어 없을 때 시뮬레이션).
 */
@Controller
@RequestMapping(value = "/")
public class WscTelemetryController {

    @Autowired
    private VehicleSnapshot vehicleSnapshot;

    @RequestMapping(value = { "/wsc.json" }, method = RequestMethod.GET)
    public @ResponseBody VehicleSnapshot.Dto getWscSnapshot() {
        return vehicleSnapshot.toDto();
    }

    /**
     * 현재 운전 중인 드라이버 지정 (1~3) — 텔레메트리가 아니라 팀이 대시보드에서 수동으로 바꾸는
     * 운영 정보. 서버에 저장해두고 /wsc.json에 실어 내려서 이 값을 보는 모든 화면이 동일하게 갱신된다.
     */
    @RequestMapping(value = { "/driver.json" }, method = RequestMethod.POST)
    public @ResponseBody Map<String, Object> setDriver(@RequestParam int driver) {
        vehicleSnapshot.setCurrentDriver(driver);
        return Collections.singletonMap("currentDriver", vehicleSnapshot.toDto().currentDriver);
    }
}
