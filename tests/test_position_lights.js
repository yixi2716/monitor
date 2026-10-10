/* 位置信号回测：测试A（2026-06-20 底部识别）+ 测试B（2021-02 顶部识别）+ 边界态
 * 运行：node tests/test_position_lights.js
 */
const PL = require("../site/position_logic.js");

let pass = 0, fail = 0;
function check(name, actual, expectKey) {
  const ok = actual.key === expectKey;
  console.log(`${ok ? "✅" : "❌"} ${name}: 输出「${actual.label}」 期望 ${expectKey} ${ok ? "" : "← 不符"}`);
  ok ? pass++ : fail++;
}

// 任务书预填日历
const CALENDAR = [
  { date: "2026-10-20", event: "ESMO年会(10/20-24)", type: "学术会议", level: 3 },
  { date: "2026-10-25", event: "A股三季报密集披露", type: "财报", level: 2 },
  { date: "2026-11-10", event: "医保谈判结果窗口(预估)", type: "政策", level: 5 },
  { date: "2027-06-26", event: "医保目录初审窗口(按2026年节奏预估)", type: "政策", level: 5 },
];
// 6月底回测用的日历（含 6/26 医保初审 level 5）
const CAL_JUN = CALENDAR.concat([{ date: "2026-06-26", event: "医保目录初审窗口", type: "政策", level: 5 }]);

console.log("=== 灯态映射 ===");
check("分位8%→亮", { key: PL.posLight(0.08) === "on" ? "on" : "?" }, "on");
check("分位20%→半亮", { key: PL.posLight(0.20) === "half" ? "half" : "?" }, "half");
check("分位37%→灭", { key: PL.posLight(0.3747) === "off" ? "off" : "?" }, "off");
check("分位null→灰", { key: PL.posLight(null) === "na" ? "na" : "?" }, "na");

console.log("\n=== 灯⑧ 日历 ===");
check("事件前6天→黄", { key: PL.policyState(CAL_JUN, "2026-06-20") }, "yellow");
check("事件当天→红", { key: PL.policyState(CAL_JUN, "2026-06-26") }, "red");
check("事件后1天→红", { key: PL.policyState(CAL_JUN, "2026-06-27") }, "red");
check("事件后2天→黄", { key: PL.policyState(CAL_JUN, "2026-06-28") }, "yellow");
check("11-10事件距10-10共31天→灭", { key: PL.policyState(CALENDAR, "2026-10-10") }, "none");
check("超14天→灭", { key: PL.policyState([{ date: "2026-12-31", event: "x", type: "政策", level: 5 }], "2026-10-10") }, "none");

console.log("\n=== 测试A：2026-06-20 底部识别 ===");
// 模拟当时：PE分位8%、成交占比分位5% → 位置两灯亮；日历黄灯；时机五灯仅1亮
{
  const posOn = [PL.posLight(0.08), PL.posLight(0.05)].filter(s => s === "on").length;
  const posTotal = [PL.posLight(0.08), PL.posLight(0.05)].filter(s => s !== "na").length;
  const pol = PL.policyState(CAL_JUN, "2026-06-20");
  const st = PL.combineState({ posOn, posTotal, pol, timingLit: 1, pePct: 0.08 });
  check("6/20 快照 → 埋伏区/底部区", st, st.key === "ambush" || st.key === "bottom" ? st.key : "avoid");
  console.log(`   (posOn=${posOn} posTotal=${posTotal} pol=${pol} timingLit=1)`);
}

console.log("\n=== 测试B：2021-02 顶部识别 ===");
{
  const st = PL.combineState({ posOn: 0, posTotal: 2, pol: "none", timingLit: 5, pePct: 0.95 });
  check("PE分位95% + 时机5灯 → 过热区(强制覆盖)", st, "overheat");
}

console.log("\n=== 边界态 ===");
check("位置全灰 → 数据积累中", PL.combineState({ posOn: 0, posTotal: 0, pol: "none", timingLit: 1, pePct: null }), "na");
check("位置2亮+时机≤2+无事件 → 底部区", PL.combineState({ posOn: 2, posTotal: 2, pol: "none", timingLit: 2, pePct: 0.06 }), "bottom");
check("位置1亮+时机5灯 → 趋势确认", PL.combineState({ posOn: 1, posTotal: 2, pol: "none", timingLit: 4, pePct: 0.4 }), "trend");
check("位置1+灭+时机1 → 规避", PL.combineState({ posOn: 1, posTotal: 2, pol: "none", timingLit: 1, pePct: 0.4 }), "avoid");
check("位置1亮+时机3灯(真值表未覆盖) → 中性观察", PL.combineState({ posOn: 1, posTotal: 2, pol: "none", timingLit: 3, pePct: 0.2 }), "neutral");

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);
