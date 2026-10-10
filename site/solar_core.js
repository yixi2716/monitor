/* 光伏看板 · 信号计算纯函数（前端 solar.html 与 node 回放测试共用，单一事实源）
 *
 * 输入：数据快照（history 日线数组 + latest 当日值 + manual 手工产业数据 + calendar 政策日历）
 * 输出：灯态与组合状态。不做任何网络请求，不依赖 DOM。
 *
 * 监测逻辑四层：位置（左侧）× 时机（右侧）× 政策 × 产业。
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.SolarCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* 子板块代表（与 fetch_solar.py STOCKS 保持一致） */
  var STOCK_KEYS = ["tongwei", "zhonghuan", "junda", "longi", "flat", "jiejia", "sungrow"];
  var STOCK_NAMES = {
    tongwei: "通威(硅料)", zhonghuan: "中环(硅片)", junda: "钧达(电池)",
    longi: "隆基(组件)", flat: "福莱特(玻璃)", jiejia: "捷佳伟创(设备)", sungrow: "阳光电源(逆变器)"
  };

  function valid(arr) { return arr.filter(function (v) { return v != null && isFinite(v); }); }

  function ma(arr, n) {
    var a = valid(arr);
    if (a.length < n) return null;
    var s = 0;
    for (var i = a.length - n; i < a.length; i++) s += a[i];
    return s / n;
  }

  /* 近 n 日收益率（用最近 n+1 个有效点） */
  function chgN(arr, n) {
    var a = valid(arr);
    if (a.length < n + 1) return null;
    return (a[a.length - 1] / a[a.length - 1 - n] - 1) * 100;
  }

  /* ============ 时机五灯（日频） ============ */
  /* hist: [{date, solar_etf, storage_etf, hs300, tongwei, ...}] 新→旧或旧→新均可，内部按原顺序取末尾 */
  function computeTiming(hist, L, manual) {
    var rows = [];
    var last = hist[hist.length - 1] || {};

    // ① 商品价格趋势：TOPCon 组件周度价的近 4 个环比全部为正（数据来自手工维护的硅业分会/InfoLink 报价序列）
    var mod = ((manual || {}).industry_prices || {}).module || [];
    var l1 = { name: "① 商品价格趋势", desc: "", on: false, na: true };
    if (mod.length >= 5) {
      var moms = [];
      for (var i = mod.length - 4; i < mod.length; i++) {
        var p = mod[i - 1].value, c = mod[i].value;
        moms.push(p > 0 ? (c / p - 1) * 100 : null);
      }
      var ok = moms.every(function (m) { return m != null && m > 0; });
      var lastV = mod[mod.length - 1].value;
      var lastD = mod[mod.length - 1].date;
      l1.desc = "TOPCon 组件 " + lastV.toFixed(3) + " 元/W（" + lastD + "）· 近4周环比 "
        + moms.map(function (m) { return m == null ? "—" : (m >= 0 ? "+" : "") + m.toFixed(1) + "%"; }).join(" / ")
        + "（全正亮）";
      l1.on = ok; l1.na = false;
    } else {
      l1.desc = "组件周度价序列不足 5 点（手工维护中，硅业分会每周三报价）";
    }
    rows.push(l1);

    // ② 板块趋势：光伏ETF 收盘 > MA20
    var solarArr = hist.map(function (h) { return h.solar_etf; });
    var ma20 = ma(solarArr, 20);
    var lastSolar = last.solar_etf != null ? last.solar_etf : valid(solarArr).slice(-1)[0];
    rows.push({
      name: "② 板块趋势",
      desc: lastSolar != null
        ? "光伏ETF " + lastSolar.toFixed(3) + (ma20 != null ? " vs MA20 " + ma20.toFixed(3) : "（历史不足20日）")
        : "光伏ETF 数据缺失",
      on: ma20 != null && lastSolar != null && lastSolar > ma20,
      na: ma20 == null
    });

    // ③ 超额动量：近20日 光伏ETF - 沪深300 超额转正
    var s20 = chgN(solarArr, 20), h20 = chgN(hist.map(function (h) { return h.hs300; }), 20);
    var exOk = (s20 != null && h20 != null) ? (s20 - h20) > 0 : null;
    rows.push({
      name: "③ 超额动量",
      desc: exOk != null
        ? "近20日 光伏 " + s20.toFixed(2) + "% vs 沪深300 " + h20.toFixed(2) + "%（超额 " + (s20 - h20).toFixed(2) + "%）"
        : "历史不足 21 个交易日，无法计算（数据积累后恢复）",
      on: !!exOk, na: exOk == null
    });

    // ④ 子板块广度：7 只代表股中站上 MA20 的数量 ≥4 亮
    var parts = [], cnt = 0, validCnt = 0;
    STOCK_KEYS.forEach(function (k) {
      var m = ma(hist.map(function (h) { return h[k]; }), 20);
      var v = valid(hist.map(function (h) { return h[k]; })).slice(-1)[0];
      if (m == null || v == null) { parts.push(STOCK_NAMES[k] + ": —"); return; }
      validCnt++;
      var up = v > m;
      if (up) cnt++;
      parts.push(STOCK_NAMES[k] + (up ? ":↑" : ":↓"));
    });
    rows.push({
      name: "④ 子板块广度",
      desc: validCnt + " 只可比中 " + cnt + " 只站上 MA20（≥4 亮）· " + parts.join(" "),
      on: validCnt > 0 && cnt >= 4,
      na: validCnt === 0
    });

    // ⑤ 兄弟板块共振：储能ETF × 光伏ETF 当日双涨
    var sChg = L.storage_etf_chg, pChg = L.solar_etf_chg;
    var resOk = sChg != null && pChg != null && sChg > 0 && pChg > 0;
    rows.push({
      name: "⑤ 兄弟板块共振",
      desc: "储能ETF " + (sChg != null ? (sChg >= 0 ? "+" : "") + sChg + "%" : "缺失")
        + " × 光伏ETF " + (pChg != null ? (pChg >= 0 ? "+" : "") + pChg + "%" : "缺失") + "（双涨亮）",
      on: resOk,
      na: sChg == null || pChg == null
    });

    var lit = rows.filter(function (r) { return r.on; }).length;
    return { rows: rows, lit: lit, breadthLit: cnt, breadthValid: validCnt };
  }

  /* ============ 位置灯（左侧） ============ */
  /* 灯⑥ 破净比例：光伏成分股中 PB<1 家数 ÷ 总数（光伏版"估值位置灯"，阈值型） */
  function pbLight(ratio) {
    if (ratio === null || ratio === undefined || isNaN(ratio)) return "na";
    if (ratio >= 0.60) return "on";
    if (ratio >= 0.40) return "half";
    return "off";
  }
  /* 灯⑦ 成交占比分位：<10% 亮、10~30% 半亮、>30% 灭（与医药页同规则） */
  function posLight(pct) {
    if (pct === null || pct === undefined || isNaN(pct)) return "na";
    if (pct < 0.10) return "on";
    if (pct < 0.30) return "half";
    return "off";
  }

  /* 政策日历 → 灯⑧：距 level≥4 事件 ≤1天=红、≤14天=黄（与医药页同规则） */
  function policyState(calendar, today) {
    var best = null;
    (calendar || []).forEach(function (ev) {
      if ((ev.level || 0) < 4) return;
      var days = Math.round((new Date(ev.date + "T00:00:00") - new Date(today + "T00:00:00")) / 86400000);
      var dist = Math.abs(days);
      if (best === null || dist < best) best = dist;
    });
    if (best === null) return "none";
    if (best <= 1) return "red";
    if (best <= 14) return "yellow";
    return "none";
  }

  /* ============ 组合状态真值表 ============ */
  /* inp: {posOn, posTotal, pol, timingLit, breadthLit, ddFromHigh}
   * posOn    位置灯"亮"的数量（⑥⑦，阈值型直接计数）
   * posTotal 位置灯非"灰"的数量（全灰=数据积累中）
   * pol      灯⑧ none/yellow/red
   * timingLit 时机五灯亮数
   * breadthLit 灯④站上MA20家数（过热覆盖用）
   * ddFromHigh 光伏ETF 距1年最高点回撤（0~1，null=不知）
   */
  function combineState(inp) {
    if (inp.posTotal === 0)
      return { key: "na", label: "⚪ 数据积累中（位置信号不足，暂不组合）", color: "#6e7681" };
    // 过热覆盖：距前高回撤 <15% 且 广度满格 → 强制 ⚫
    if (inp.ddFromHigh != null && !isNaN(inp.ddFromHigh) && inp.ddFromHigh < 0.15 && (inp.breadthLit || 0) >= 7)
      return { key: "overheat", label: "⚫ 过热区（距前高回撤<15% 且 子板块广度满格，强制覆盖）", color: "#6e7681" };
    if (inp.posOn >= 2 && inp.timingLit <= 2) {
      if (inp.pol === "red" || inp.pol === "yellow")
        return { key: "ambush", label: "🟡 埋伏区（估值到位，事件临近，可分批建仓）", color: "#d29922" };
      return { key: "bottom", label: "🔵 底部区（估值到位，等待催化）", color: "#58a6ff" };
    }
    if (inp.timingLit >= 4) return { key: "trend", label: "🟢 趋势确认（加仓/持有）", color: "#3fb950" };
    if (inp.posOn <= 1 && inp.pol === "none" && inp.timingLit <= 1)
      return { key: "avoid", label: "🔴 规避", color: "#f85149" };
    return { key: "neutral", label: "⚪ 中性观察（位置/时机信号不一致，等待明确）", color: "#8b949e" };
  }

  return {
    STOCK_KEYS: STOCK_KEYS, STOCK_NAMES: STOCK_NAMES,
    computeTiming: computeTiming,
    pbLight: pbLight, posLight: posLight, policyState: policyState,
    combineState: combineState, ma: ma, chgN: chgN
  };
});
