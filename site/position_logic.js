/* 位置×时机 组合状态逻辑（纯函数，前端与 node 回测共用）
 * 铁律：时机五灯的计算逻辑不在这里，本文件只管左侧三灯的灯态映射与组合真值表。
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.PositionLogic = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* 估值/成交占比分位 → 灯态：<10% 亮(绿)、10~30% 半亮(黄)、>30% 灭、无数据 灰 */
  function posLight(pct) {
    if (pct === null || pct === undefined || isNaN(pct)) return "na";
    if (pct < 0.10) return "on";
    if (pct < 0.30) return "half";
    return "off";
  }

  /* 政策日历 → 灯⑧：距最近 level>=4 事件 ≤1天=红、≤14天=黄、否则灭。
   * calendar: [{date:"YYYY-MM-DD", event, type, level}]，today: "YYYY-MM-DD" */
  function policyState(calendar, today) {
    var best = null;
    (calendar || []).forEach(function (ev) {
      if ((ev.level || 0) < 4) return;
      var days = Math.round((new Date(ev.date + "T00:00:00") - new Date(today + "T00:00:00")) / 86400000);
      var dist = Math.abs(days);
      if (best === null || dist < best) best = dist;
    });
    if (best === null) return "none";
    if (best <= 1) return "red";   // 事件当天及前后各 1 天
    if (best <= 14) return "yellow";
    return "none";
  }

  /* 组合真值表（inputs 均为已解析的灯态计数）：
   * posOn    位置灯"亮"(绿)的数量（⑥⑦）
   * posTotal 位置灯非"灰"的数量（全灰=数据积累中，不套用真值表）
   * pol      灯⑧：none / yellow / red
   * timingLit 时机五灯亮数（灰灯不计数）
   * pePct    灯⑥所用分位（PE 未 ready 时传价格分位），用于过热覆盖 */
  function combineState(inp) {
    if (inp.posTotal === 0) return { key: "na", label: "⚪ 数据积累中（位置信号不足，暂不组合）", color: "#6e7681" };
    if (inp.pePct != null && !isNaN(inp.pePct) && inp.pePct > 0.70)
      return { key: "overheat", label: "⚫ 过热区（估值分位 >70%，强制覆盖其他状态）", color: "#6e7681" };
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

  return { posLight: posLight, policyState: policyState, combineState: combineState };
});
