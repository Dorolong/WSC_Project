$(function() {
	var timers = [];
	
	// setup plot
    var defaultChartOptions = {
        series: { color: '#DA262E', shadowSize: 0, lines: { show: true, fill: false } }, // drawing is faster without shadows
        // yaxis: { min: lowErrorThreshold - (lowErrorThreshold/10) , max: highErrorThreshold + (highErrorThreshold/10)},
        xaxis: { mode: 'time', timeformat: '%H:%M:%S', timezone: 'browser' },
        grid: {
			borderWidth: 1,
			minBorderMargin: 20,
			labelMargin: 10,
			backgroundColor: {
				colors: ["#fff", "#e4f4f4"]
			},
			margin: {
				top: 8,
				bottom: 20,
				left: 20
			}/*,
			markings: function(axes) {
				var markings = [];
				var xaxis = axes.xaxis;
				for (var x = Math.floor(xaxis.min); x < xaxis.max; x += xaxis.tickSize * 2) {
					markings.push({ xaxis: { from: x, to: x + xaxis.tickSize }, color: "rgba(232, 232, 255, 0.2)" });
				}
				return markings;
			}*/
		}
    };
	
	$('select.device-select').on('change', function(event) {
		var s = $(this);
		
		$.ajax({
			async: false,
			url: '/measurements.json?deviceId=' + s.val(),
			dataType:'json',
			success: function(result) {
				var mOpts = '<option value="">-- Please select a measurement --</option>';
				$.each(result, function(idx, value) {
					mOpts += '<option value="' + value.id + '">' + value.name + '</option>';
				});
				
				s.closest('div.control-group').next().find('select.measurement-select').html($(mOpts));
			}
		});
	});
	
	$('select.measurement-select').on('change', function(event) {
		var s = $(this);
		
		$.ajax({
			async: false,
			url: '/datapoints.json?measurementId=' + s.val(),
			dataType:'json',
			success: function(result) {
				var mOpts = '<option value="">-- Please select a data point --</option>';
				$.each(result, function(idx, value) {
					mOpts += '<option value="' + value.dataPointCanId + '">' + value.name + '</option>';
				});
				
				s.closest('div.control-group').next().find('select.dataPoint-select').html($(mOpts));
			}
		});
	});
	
	$('select.dataPoint-select').on('change', function(event) {
		var theChart = $(this).parents('form').siblings('div');
		var theDeviceId = $(this).val();
		var tIdx = parseInt($(this).attr('data-chart-idx'));
		var switchStatus = $(this).closest('div.control-group').next().find('div.live-data-switch').bootstrapSwitch('status');
		
		if (timers[tIdx]) {
			clearTimeout(timers[tIdx]);
		}
		
		if (switchStatus && theDeviceId) {
			var thePlot = $.plot(theChart, getData(theDeviceId), defaultChartOptions);
			updateData(thePlot, theDeviceId, switchStatus, tIdx);
		} else {
			$.plot(theChart, [[]], defaultChartOptions);
		}
	});
	
	$('.live-data-switch').on('switch-change', function (e, data) {
	    /*var $el = $(data.el), 
	      value = data.value;
	    
	    console.log(e, $el, value);*/
	    
	    $(this).closest('div.control-group').prev().find('select').change();
	});
	
	function updateData(thePlot, theDeviceId, switchStatus, timerIndex) {
		if (switchStatus) {
			thePlot.setData(getData(theDeviceId));
			thePlot.setupGrid();
			thePlot.draw();
			
			timers[timerIndex] = setTimeout(function() { 
				updateData(thePlot, theDeviceId, switchStatus, timerIndex); 
			}, 1000);
		}
	}
	
	function getData(deviceLkup) {
    	var points = [];
    	$.ajax({
			// have to use synchronous here, else the function 
			// will return before the data is fetched
			async: false,
			url: '/measurement-data.json?deviceId=' + deviceLkup,
			dataType:'json',
			success: function(result) {
				// We only want data from the last minute otherwise
				// the graph renders incorrectly
				
				// First get the most recent time from the list by iterating and looking
				var lastTime = Date.parse(result[result.length-1].timestamp);
				
				for (var i = 0; i < result.length; i++) {
					if (Date.parse(result[i].timestamp) > lastTime) 
						lastTime = Date.parse(result[i].timestamp);
				}
				
				var fromTime = lastTime - 60000;
				
				//console.log("last time" + lastTime );
				//console.log("from time" + fromTime );
				
				for (var i = 0; i < result.length; i++) {
					if ( Date.parse(result[i].timestamp) >= fromTime) points.push([Date.parse(result[i].timestamp), result[i].fv]);
		            // console.log(new Date(result[i].timestamp), result[i].floatValue);
				}
			}
		});/*
    	var het = [], hwt = [], lwt = [], let = [];
    	for (var i = 0; i < points.length; i++) {
            het.push([i, highErrorThreshold]);
            hwt.push([i, highWarningThreshold]);
            lwt.push([i, lowWarningThreshold]);
            let.push([i, lowErrorThreshold]);
		}*/
    	
    	return [
	        {data: points, label: 'Data'}/*,
	        {data: het, label: 'High Error Theshold'},
	        {data: hwt, label: 'High Warning Theshold'},
	        {data: lwt, label: 'Low Warning Theshold'},
	        {data: let, label: 'Low Error Theshold'}*/];
    }
	
	function getDataPointValue(md) {
		return (!md.fv ? (!md.iv ? (!md.cv ? (md ? md : undefined) : md.cv) : md.iv) : Number(md.fv.toFixed(2)));
	}

	function setCellValue(msrmntData) {
		var value = getDataPointValue(msrmntData);
		$("td#"+msrmntData.dataPointCanId).text(value);
		$("td#"+msrmntData.dataPointCanId).attr({'class': msrmntData.state});
	}

	function getDPData(canId) {

		$.ajax({
			async: false,
			url: '/index.json?canId=' + canId,
			dataType:'json',
			success: function(result) {
				for (var i = 0; i < result.length; i++) {
					setCellValue(result[i]);
				}
			}
		});
	}
	
	function getCmuData(cmuIdx) {
		$.ajax({
			async: false,
			url: '/cmu.json?cmuIdx=' + cmuIdx,
			dataType:'json',
			success: function(result) {
				for (var i = 0; i < result.length; i++) {
					setCellValue(result[i]);
				}
			}
		});
	}
	
	function getConfiguredDataSet(url, data) {
		void function(url, data) {
			$.ajax({
				async: false,
				url: url,
				data: data,
				dataType:'json',
				success: function(result) {
					for (var prop in result) {
						if (result[prop] && typeof(result[prop]) === 'object') {
							// It's a measurementdata
							$('#' + prop + (data ? data['ptIdx'] : '')).attr({'class': result[prop].state}).text(getDataPointValue(result[prop]));
						} else if (!result[prop]) {
							$('#' + prop).attr({'class': 'Error'}).text(result[prop]);
						} else {
							$('#' + prop).text(result[prop]);
						}
					}
				}
			});
		}(url, data);
	}

    // ===== F1 스타일 대시보드 (단일 차량, /wsc.json 기반) =====
    // 이 섹션은 index.html의 f1-* 요소가 있을 때만 동작한다 (없는 페이지에서는 전부 no-op).

    var TOTAL_ROUTE_KM = 3000; // 다윈→애들레이드 공식 확정 거리로 추후 조정
    var mpptMaxSeen = [50, 50, 50]; // 막대 스케일용 - 유닛별 지금까지 관측된 최대 출력(W)으로 자동 스케일

    // 지도(SVG viewBox 0 0 1024 1024) 위 경로 웨이포인트 — 실좌표를 눈대중으로 픽셀 보정한 값.
    // pct: 다윈(0)→애들레이드(100) 누적 주행거리 비율. GPS 연동 전까지는 오도미터 기반 pct로 이 위를 보간한다.
    var ROUTE_WAYPOINTS = [
        { pct: 0,    x: 445, y: 90 },  // Darwin
        { pct: 10.5, x: 478, y: 148 }, // Katherine
        { pct: 33,   x: 526, y: 296 }, // Tennant Creek
        { pct: 49.5, x: 518, y: 414 }, // Alice Springs
        { pct: 74,   x: 540, y: 568 }, // Coober Pedy
        { pct: 90,   x: 612, y: 668 }, // Port Augusta
        { pct: 100,  x: 630, y: 695 }  // Adelaide
    ];

    // pct(0~100) 위치의 지도 좌표 + 그 지점까지의 "주행 완료" 폴리라인 포인트 문자열을 반환
    function pointOnRoute(pct) {
        pct = Math.max(0, Math.min(100, pct));
        var pts = [ROUTE_WAYPOINTS[0].x + ',' + ROUTE_WAYPOINTS[0].y];
        for (var i = 0; i < ROUTE_WAYPOINTS.length - 1; i++) {
            var a = ROUTE_WAYPOINTS[i], b = ROUTE_WAYPOINTS[i + 1];
            if (pct >= b.pct) {
                pts.push(b.x + ',' + b.y);
                continue;
            }
            if (pct > a.pct) {
                var f = (pct - a.pct) / (b.pct - a.pct);
                var x = a.x + (b.x - a.x) * f;
                var y = a.y + (b.y - a.y) * f;
                pts.push(x.toFixed(1) + ',' + y.toFixed(1));
                return { x: x, y: y, points: pts.join(' ') };
            }
            break;
        }
        var last = ROUTE_WAYPOINTS[ROUTE_WAYPOINTS.length - 1];
        return { x: last.x, y: last.y, points: pts.join(' ') };
    }

    function setText(id, value, decimals) {
        var el = document.getElementById(id);
        if (!el) return;
        if (value === undefined || value === null || isNaN(value)) { el.textContent = '-'; return; }
        el.textContent = Number(value).toFixed(decimals === undefined ? 1 : decimals);
    }

    function setPill(id, lastUpdate, now, liveMs, staleMs) {
        var el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('live', 'stale', 'dead');
        var age = now - (lastUpdate || 0);
        if (!lastUpdate || age > staleMs) { el.classList.add('dead'); el.lastChild.textContent = 'OFFLINE'; }
        else if (age > liveMs) { el.classList.add('stale'); el.lastChild.textContent = 'WEAK'; }
        else { el.classList.add('live'); el.lastChild.textContent = 'LIVE'; }
    }

    // SOC 배터리 바 (BOT/TOP 공용) — id 접미사(prefix)로 어느 유닛인지 구분
    function setBatteryBar(prefix, socPct) {
        var fill = document.getElementById('f1-batt-fill-' + prefix);
        if (fill) {
            fill.style.width = Math.max(0, Math.min(100, socPct)) + '%';
            fill.style.background = socPct > 25 ? 'var(--f1-green)' : (socPct > 10 ? 'var(--f1-amber)' : 'var(--f1-red)');
        }
        setText('f1-batt-pct-' + prefix, socPct, 1);
    }

    // 출력전류(Bus Current) 추이 — MPPT/throttle trace 자리를 대신하는 실데이터 그래프
    var traceHistory = [];
    var traceChartOptions = {
        series: { shadowSize: 0, lines: { show: true, fill: true, fillColor: 'rgba(51,201,234,0.15)' }, color: '#33c9ea' },
        xaxis: { mode: 'time', timeformat: '%H:%M:%S', timezone: 'browser', color: '#7c8aa0', font: { color: '#7c8aa0' } },
        yaxis: { color: '#7c8aa0', font: { color: '#7c8aa0' } },
        grid: { borderWidth: 1, borderColor: '#223046', backgroundColor: null }
    };

    function updateTraceChart(busCurrentA) {
        if (!$('#f1-trace-chart').length) return;
        var now = new Date().getTime();
        traceHistory.push([now, busCurrentA || 0]);
        var cutoff = now - 60000;
        while (traceHistory.length > 0 && traceHistory[0][0] < cutoff) traceHistory.shift();
        $.plot($('#f1-trace-chart'), [{ data: traceHistory }], traceChartOptions);
    }

    // MPPT 전체 이력 그래프 (기존 #mppt-chartdiv 유지)
    var mpptHistory1 = [], mpptHistory2 = [], mpptHistory3 = [];
    var miniChartOptions = {
        series: { shadowSize: 0, lines: { show: true, fill: false } },
        xaxis: { mode: 'time', timeformat: '%H:%M:%S', timezone: 'browser' },
        yaxis: { min: 0 },
        grid: { borderWidth: 1, backgroundColor: { colors: ["#fff", "#e4f4f4"] } },
        legend: { position: 'nw', noColumns: 1 }
    };

    function updateMpptChart(mppt) {
        if (!$('#mppt-chartdiv').length) return;
        var now = new Date().getTime();
        var p = [0, 0, 0];
        for (var i = 0; i < 3; i++) {
            var m = mppt[i] || {};
            p[i] = (m.outVoltageV || 0) * (m.outCurrentA || 0);
        }
        mpptHistory1.push([now, p[0]]);
        mpptHistory2.push([now, p[1]]);
        mpptHistory3.push([now, p[2]]);
        var cutoff = now - 120000;
        while (mpptHistory1.length > 0 && mpptHistory1[0][0] < cutoff) mpptHistory1.shift();
        while (mpptHistory2.length > 0 && mpptHistory2[0][0] < cutoff) mpptHistory2.shift();
        while (mpptHistory3.length > 0 && mpptHistory3[0][0] < cutoff) mpptHistory3.shift();
        $.plot($('#mppt-chartdiv'), [
            { data: mpptHistory1, label: 'MPPT 1', color: '#DA262E' },
            { data: mpptHistory2, label: 'MPPT 2', color: '#2E8BDA' },
            { data: mpptHistory3, label: 'MPPT 3', color: '#DAA62E' }
        ], miniChartOptions);
    }

    function formatEta(hours) {
        if (hours === null || hours === undefined || !isFinite(hours) || hours < 0) return '--:--';
        var h = Math.floor(hours);
        var m = Math.round((hours - h) * 60);
        if (m === 60) { h += 1; m = 0; }
        return h + '시간 ' + (m < 10 ? '0' : '') + m + '분';
    }

    function renderF1Dashboard(dto) {
        if (!document.getElementById('f1-link-pill')) return; // 이 페이지에 F1 대시보드 없음

        var now = dto.serverTime || Date.now();
        var bot = dto.bmsBot || {};
        var top = dto.bmsTop || {};
        var motor = dto.motor || {};
        var mppt = dto.mppt || [];
        var lv = dto.bmsLv || {};

        setPill('f1-link-pill', dto.lastFrameTime, now, 1500, 6000);
        setText('f1-frames', dto.totalFrames, 0);
        setText('f1-errors', (dto.checksumFailures || 0) + (dto.framingErrors || 0), 0);

        // 상태 배지 — BOT/TOP fault flags 기준
        var hasFault = !!(bot.faultFlags || top.faultFlags);
        var badge = document.getElementById('f1-status-badge');
        if (badge) {
            if (hasFault) { badge.textContent = '⚠ 경고 (FAULT)'; badge.className = 'f1-status-badge alert'; }
            else { badge.textContent = '정상 주행'; badge.className = 'f1-status-badge ok'; }
        }
        var led = document.getElementById('status-led');
        if (led && led.length !== 0) {
            $(led).css({ 'background-color': hasFault ? '#E74C3C' : '#2ECC71', 'box-shadow': hasFault ? '0 0 8px rgba(231,76,60,0.9)' : '0 0 6px rgba(46,204,113,0.8)' });
        }

        // 속도 / RPM / 팩 전력 / 온도
        var speedKmh = (motor.vehicleSpeedMs || 0) * 3.6;
        setText('f1-speed', speedKmh, 0);
        setText('f1-rpm', motor.rpm, 0);
        setText('f1-packpower', (bot.packVoltageV || 0) * (bot.packCurrentA || 0), 0);
        setText('f1-heatsink', motor.heatsinkTempC, 1);
        setText('f1-motortemp', motor.motorTempC, 1);
        updateTraceChart(motor.busCurrentA);

        // SOC 배터리 바 — BOT/TOP 둘 다 표시
        setBatteryBar('bot', bot.socPercent || 0);
        setBatteryBar('top', top.socPercent || 0);

        // 원시 텔레메트리
        document.getElementById('f1-busv').innerHTML = (motor.busVoltageV || 0).toFixed(1) + '<span class="u">V</span>';
        document.getElementById('f1-busi').innerHTML = (motor.busCurrentA || 0).toFixed(1) + '<span class="u">A</span>';
        document.getElementById('f1-packv').innerHTML = (bot.packVoltageV || 0).toFixed(1) + '<span class="u">V</span>';
        document.getElementById('f1-packi').innerHTML = (bot.packCurrentA || 0).toFixed(1) + '<span class="u">A</span>';
        document.getElementById('f1-raw-rpm').innerHTML = (motor.rpm || 0) + '<span class="u">rpm</span>';
        var mpptTotal = 0;
        for (var i = 0; i < 3; i++) {
            var m = mppt[i] || {};
            var pW = (m.outVoltageV || 0) * (m.outCurrentA || 0);
            mpptTotal += pW;
            mpptMaxSeen[i] = Math.max(mpptMaxSeen[i], pW);
            var bar = document.getElementById('f1-mppt-bar-' + i);
            if (bar) bar.style.width = Math.min(100, (pW / mpptMaxSeen[i]) * 100) + '%';
            var val = document.getElementById('f1-mppt-val-' + i);
            if (val) val.innerHTML = '<b>' + pW.toFixed(0) + 'W</b> ' + (m.outVoltageV || 0).toFixed(0) + 'V/' + (m.outCurrentA || 0).toFixed(1) + 'A';
        }
        document.getElementById('f1-mppt-total').innerHTML = mpptTotal.toFixed(0) + '<span class="u">W</span>';
        updateMpptChart(mppt);

        // TOP은 전류 센서가 없어 전압만 온다(CAN_수신_데이터_정리본.xlsx BMS(HV) 시트 0x046 설명 참고)
        document.getElementById('f1-packv-top').innerHTML = (top.packVoltageV || 0).toFixed(1) + '<span class="u">V</span>';
        // 보조배터리(12V, LV) 팩 전압 — 컨택터/팬/제어보드 전원 상태 확인용
        document.getElementById('f1-lv-packv').innerHTML = ((lv.packVoltageMv || 0) / 1000).toFixed(2) + '<span class="u">V</span>';

        // 주행거리 / 경로 진행률 / ETA
        var distKm = (motor.odometerM || 0) / 1000;
        var pct = Math.max(0, Math.min(100, (distKm / TOTAL_ROUTE_KM) * 100));
        document.getElementById('f1-dist-label').textContent = distKm.toFixed(1) + ' / ' + TOTAL_ROUTE_KM.toLocaleString() + '+ km';
        document.getElementById('f1-dist-bar').style.width = pct + '%';
        document.getElementById('f1-timeline-fill').style.width = pct + '%';
        document.getElementById('f1-timeline-marker').style.left = pct + '%';

        // 경로 지도 마커 — 실제 호주 윤곽 위 웨이포인트를 주행거리 비율로 보간한 위치
        var routePos = pointOnRoute(pct);
        var marker = document.getElementById('f1-route-marker');
        if (marker) { marker.setAttribute('cx', routePos.x.toFixed(1)); marker.setAttribute('cy', routePos.y.toFixed(1)); }
        var doneLine = document.getElementById('f1-route-done');
        if (doneLine) doneLine.setAttribute('points', routePos.points);

        // ETA (현재 속도 유지 가정)
        var remainKm = Math.max(0, TOTAL_ROUTE_KM - distKm);
        var etaHours = speedKmh > 1 ? remainKm / speedKmh : null;
        document.getElementById('f1-eta').textContent = formatEta(etaHours);

        // 현재 드라이버 — 다른 화면에서 바꾼 값도 폴링으로 같이 반영되도록 매번 동기화
        setActiveDriverButton(dto.currentDriver);
    }

    // 드라이버 선택 — 서버(VehicleSnapshot)에 저장해서 이 화면을 보는 모두에게 동일하게 보이도록 함
    function setActiveDriverButton(driver) {
        var btns = document.querySelectorAll('.f1-driver-btn');
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle('active', String(driver) === btns[i].getAttribute('data-driver'));
        }
    }

    $(document).on('click', '.f1-driver-btn', function () {
        var driver = $(this).attr('data-driver');
        setActiveDriverButton(driver); // 낙관적 갱신 — 서버 응답 기다리지 않고 즉시 반영
        $.ajax({ url: '/driver.json', method: 'POST', data: { driver: driver } });
    });

    function pollWscSnapshot() {
        $.ajax({
            url: '/wsc.json',
            dataType: 'json',
            success: function (dto) {
                renderF1Dashboard(dto);
            }
        });
    }

    function update() {
        pollWscSnapshot();
        setTimeout(update, 700);
    }

    update();
});
