$(function () {

	function setCell(id, value, decimals) {
		var el = document.getElementById(id);
		if (!el) return;
		if (value === undefined || value === null || isNaN(value)) return;
		el.textContent = Number(value).toFixed(decimals === undefined ? 1 : decimals);
	}

	function setText(id, text) {
		var el = document.getElementById(id);
		if (el) el.textContent = text;
	}

	function classifyCell(el, value, warnLo, warnHi, alertLo, alertHi) {
		if (!el) return;
		var cls = 'okay';
		if (value !== undefined && !isNaN(value)) {
			if ((alertLo !== undefined && value <= alertLo) || (alertHi !== undefined && value >= alertHi)) cls = 'alert';
			else if ((warnLo !== undefined && value <= warnLo) || (warnHi !== undefined && value >= warnHi)) cls = 'warning';
		}
		el.className = cls;
	}

	// 16개(BOT/TOP) 또는 8개(LV) 셀 전압을 한 행의 td들로 렌더링
	function renderCellRow(tbodyId, cells) {
		var tbody = document.getElementById(tbodyId);
		if (!tbody || !cells) return;
		var min = Math.min.apply(null, cells.filter(function (v) { return v > 0; }));
		var max = Math.max.apply(null, cells);
		var row = '<tr>';
		for (var i = 0; i < cells.length; i++) {
			var v = cells[i];
			var cls = 'okay';
			if (v === max && v > 0) cls = 'warning';
			if (v === min && v > 0) cls = 'alert';
			row += '<td class="' + cls + '" title="셀 ' + i + '">' + (v || 0) + '</td>';
		}
		row += '</tr>';
		tbody.innerHTML = row;
	}

	function renderBmsUnit(prefix, u) {
		u = u || {};
		setCell(prefix + '-soc', u.socPercent, 1);
		setCell(prefix + '-stackV', u.stackVoltageV, 1);
		setCell(prefix + '-packV', u.packVoltageV, 1);
		if (document.getElementById(prefix + '-current')) setCell(prefix + '-current', u.packCurrentA, 1);
		setCell(prefix + '-maxCell', u.maxCellMv, 0);
		setCell(prefix + '-minCell', u.minCellMv, 0);
		setCell(prefix + '-temp', u.cellTempC, 1);
		setText(prefix + '-alarm', (u.alarm || 0) === 0 ? '정상' : ('0x' + u.alarm.toString(16)));
		var faultEl = document.getElementById(prefix + '-fault');
		if (faultEl) {
			if (u.faultFlags) { faultEl.textContent = '⚠ 0x' + u.faultFlags.toString(16); faultEl.className = 'alert'; }
			else { faultEl.textContent = '정상'; faultEl.className = 'okay'; }
		}
		classifyCell(document.getElementById(prefix + '-soc'), u.socPercent, 25, undefined, 10, undefined);
		classifyCell(document.getElementById(prefix + '-temp'), u.cellTempC, undefined, 50, undefined, 60);

		renderCellRow(prefix + '-cell-row', u.cellMv || []);

		setCell(prefix + '-ts1', u.cellTempTs1C, 1);
		setCell(prefix + '-fet', u.fetTempC, 1);
		setCell(prefix + '-int', u.intTempC, 1);
		setCell(prefix + '-cfetoff', u.cfetoffTempC, 1);
		setCell(prefix + '-hdq', u.hdqTempC, 1);
		setCell(prefix + '-maxT', u.maxCellTempC, 1);
		setCell(prefix + '-minT', u.minCellTempC, 1);
		setCell(prefix + '-avgT', u.avgCellTempC, 1);
	}

	var prechargeStates = ['오류', '대기', '측정', '프리차지', '구동', '활성'];

	function renderBmsLv(lv) {
		lv = lv || {};
		setCell('lv-soc', lv.socPercent, 1);
		setCell('lv-ah', lv.socAh, 2);
		setCell('lv-packV', (lv.packVoltageMv || 0) / 1000, 2);
		setCell('lv-packI', (lv.packCurrentMa || 0) / 1000, 2);
		renderCellRow('lv-cell-row', lv.cellMv || []);

		setCell('lv-minCmu', lv.minCellCmu, 0);
		setCell('lv-minCell', lv.minCellIdx, 0);
		setCell('lv-minV', lv.minCellMv, 0);
		setCell('lv-maxCmu', lv.maxCellCmu, 0);
		setCell('lv-maxCell', lv.maxCellIdx, 0);
		setCell('lv-maxV', lv.maxCellMv, 0);

		setCell('lv-cmuI', (lv.cmuCurrentMa || 0) / 1000, 2);
		setCell('lv-fanContactorI', (lv.fanContactorCurrentMa || 0) / 1000, 2);
		setCell('lv-fan0', lv.fanSpeed0Rpm, 0);
		setCell('lv-fan1', lv.fanSpeed1Rpm, 0);

		setCell('lv-chargeVErr', lv.chargeVErrMv, 0);
		setCell('lv-tempMargin', lv.chargeTempMarginC, 1);
		setCell('lv-dischargeVErr', lv.dischargeVErrMv, 0);
		setCell('lv-totalCap', lv.totalCapacityAh, 0);

		setText('lv-timerElapsed', lv.prechargeTimerElapsed ? '경과' : '진행중');
		setCell('lv-timerCnt', lv.prechargeTimerCnt, 0);
		setText('lv-prechargeState', prechargeStates[lv.prechargeState] || ('#' + lv.prechargeState));
		setText('lv-contactor', '0x' + (lv.contactorStatus || 0).toString(16));

		setCell('lv-fwBuild', lv.fwBuild, 0);
		setCell('lv-cmuCount', lv.cmuCount, 0);
		setText('lv-statusFlags', '0x' + (lv.statusFlags || 0).toString(16));
		setCell('lv-threshFalling', lv.balanceThreshFallingMv, 0);
		setCell('lv-threshRising', lv.balanceThreshRisingMv, 0);
		setCell('lv-balanceAh', lv.balanceAh, 2);
		setCell('lv-balancePct', lv.balancePercent, 1);
	}

	function update() {
		$.ajax({
			url: '/wsc.json',
			dataType: 'json',
			success: function (dto) {
				renderBmsUnit('bot', dto.bmsBot);
				renderBmsUnit('top', dto.bmsTop);
				renderBmsLv(dto.bmsLv);
			},
			complete: function () {
				setTimeout(update, 800);
			}
		});
	}

	update();
});
