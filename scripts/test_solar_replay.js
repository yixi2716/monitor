/* 光伏看板 · 历史回放测试（任务书 7.1 生死线）
 *
 * 测试 A：2024年8月末底部 —— 价格/组件价在底部、破净>60%、成交占比<10%分位、无临近事件
 *         期望：位置灯亮 + 🔵底部区 或 🟡埋伏区（若输出"规避"=阈值混淆底部与顶部，必须修正）
 * 测试 B：2026年2月顶部/分化 —— 捷佳伟创150元顶部、主链未跟涨
 *         期望：灯④广度=灭，整体非 🟢趋势确认
 * 测试 C：过热覆盖规则 —— 距前高回撤<15% 且广度满格 → 强制 ⚫
 *
 * 运行：node scripts/test_solar_replay.js
 */
const SC = require("./solar_core.js");

let failures = 0;
function check(name, cond, detail) {
  const tag = cond ? "PASS" : "FAIL";
  if (!cond) failures++;
  console.log(`  [${tag}] ${name}${detail ? " — " + detail : ""}`);
}
function show(label, st) {
  console.log(`  组合状态: ${st.label}`);
}

/* 构造 n 天日线：generator(i) 返回 {solar_etf, hs300, tongwei, ...}，i 从 0（最早）到 n-1 */
function buildHist(n, gen) {
  const hist = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(2024, 0, 1);
    d.setDate(d.getDate() + i);
    const rec = { date: d.toISOString().slice(0, 10) };
    Object.assign(rec, gen(i));
    hist.push(rec);
  }
  return hist;
}
/* 单调路径生成器：从 start 出发每天乘 (1+drift)，可加噪声项 */
function path(start, drift) { let v = start; return () => { v *= (1 + drift); return +v.toFixed(4); }; }

const NOISY = { tongwei: 0, zhonghuan: 0, junda: 0, longi: 0, flat: 0, jiejia: 0, sungrow: 0 };

/* ================= 测试 A：2024年8月末 · 底部识别 ================= */
console.log("== 测试 A：2024年8月末 · 底部识别 ==");
{
  // 光伏ETF 从 1.0 连跌 120 天到 0.60 附近（超跌），hs300 缓跌
  const pSolar = path(1.0, -0.004);
  const p300 = path(4000, -0.0008);
  const stocksDown = {};
  Object.keys(NOISY).forEach(k => { stocksDown[k] = path(20, -0.003); });
  const hist = buildHist(120, (i) => {
    const r = { solar_etf: pSolar(), hs300: p300(), storage_etf: path ? undefined : undefined };
    Object.keys(stocksDown).forEach(k => { r[k] = stocksDown[k](); });
    return r;
  });
  const L = { solar_etf_chg: -0.8, storage_etf_chg: 0.4 }; // 光伏跌、储能涨 → ⑤ 不亮
  // 组件周度价：底部阴跌（近4周环比为负 → ① 不亮）
  const manual = { industry_prices: { module: [
    { date: "2024-07-25", value: 0.92 }, { date: "2024-08-01", value: 0.91 },
    { date: "2024-08-08", value: 0.90 }, { date: "2024-08-15", value: 0.89 },
    { date: "2024-08-22", value: 0.88 }, { date: "2024-08-29", value: 0.87 }
  ] } };
  const cal = []; // 无临近事件

  const t = SC.computeTiming(hist, L, manual);
  const pbSt = SC.pbLight(0.72);   // 破净 72%
  const toSt = SC.posLight(0.04);  // 成交占比分位 4%
  const posOn = (pbSt === "on" ? 1 : 0) + (toSt === "on" ? 1 : 0);
  const pol = SC.policyState(cal, "2024-08-29");
  const dd = 0.42; // 距前高回撤 42%
  const st = SC.combineState({ posOn, posTotal: 2, pol, timingLit: t.lit, breadthLit: t.breadthLit, ddFromHigh: dd });

  console.log(`  时机灯 ${t.lit}/5 亮 · 灯④广度 ${t.breadthLit} · 位置灯 ${posOn}/2 亮 · 灯⑧ ${pol}`);
  show("A", st);
  check("A: 位置灯亮（破净>60% 且 成交分位<10%）", posOn === 2, `posOn=${posOn}`);
  check("A: 组合状态为 🔵底部区 或 🟡埋伏区", st.key === "bottom" || st.key === "ambush", `key=${st.key}`);
  check("A: 不是 🔴规避（底部与顶部未被混淆）", st.key !== "avoid");
}

/* ================= 测试 B：2026年2月 · 顶部/分化识别 ================= */
console.log("== 测试 B：2026年2月 · 顶部/分化（捷佳150元顶部，主链未跟涨） ==");
{
  // 光伏ETF 上行趋势（站上MA20），但 7 只代表股里只有捷佳伟创站上 MA20
  const pSolar = path(0.8, 0.002);
  const p300 = path(3900, 0.0002);
  const stocks = {};
  Object.keys(NOISY).forEach(k => { stocks[k] = path(20, -0.001); }); // 其余阴跌
  const pJiejia = path(100, 0.008); // 捷佳独涨（顶部）
  const hist = buildHist(120, () => {
    const r = { solar_etf: pSolar(), hs300: p300() };
    Object.keys(stocks).forEach(k => { r[k] = k === "jiejia" ? pJiejia() : stocks[k](); });
    return r;
  });
  const L = { solar_etf_chg: 1.2, storage_etf_chg: -0.3 }; // 储能跌 → ⑤ 不亮
  const manual = { industry_prices: { module: [ // 组件价仍在阴跌 → ① 不亮
    { date: "2026-01-08", value: 0.80 }, { date: "2026-01-15", value: 0.80 },
    { date: "2026-01-22", value: 0.79 }, { date: "2026-01-29", value: 0.79 },
    { date: "2026-02-05", value: 0.78 }, { date: "2026-02-12", value: 0.78 }
  ] } };
  const cal = [{ date: "2026-03-05", event: "两会(预估)", level: 3 }]; // 无 level≥4 临近事件
  const t = SC.computeTiming(hist, L, manual);
  const pbSt = SC.pbLight(0.15);
  const toSt = SC.posLight(0.85);
  const posOn = (pbSt === "on" ? 1 : 0) + (toSt === "on" ? 1 : 0);
  const pol = SC.policyState(cal, "2026-02-12");
  const dd = 0.05; // 距前高仅回撤5%（高位）——但广度只有1，不应触发过热
  const st = SC.combineState({ posOn, posTotal: 2, pol, timingLit: t.lit, breadthLit: t.breadthLit, ddFromHigh: dd });

  console.log(`  时机灯 ${t.lit}/5 亮 · 灯④广度 ${t.breadthLit} · 位置灯 ${posOn}/2 亮 · 灯⑧ ${pol}`);
  show("B", st);
  check("B: 灯④广度=灭（扩散失败，捷佳独涨不算广度）", t.breadthLit < 4 && !t.rows[3].on, `breadth=${t.breadthLit}`);
  check("B: 整体非 🟢趋势确认", st.key !== "trend", `key=${st.key}`);
  check("B: 高位+广度不足 ≠ 过热（⚫需广度满格）", st.key !== "overheat");
  check("B: 整体偏谨慎（neutral/avoid）", st.key === "neutral" || st.key === "avoid", `key=${st.key}`);
}

/* ================= 测试 C：过热覆盖规则 ================= */
console.log("== 测试 C：过热覆盖（距前高<15% 且 广度满格 → 强制 ⚫） ==");
{
  const pSolar = path(1.5, 0.001);
  const p300 = path(4200, 0.0005);
  const hist = buildHist(120, () => {
    const r = { solar_etf: pSolar(), hs300: p300() };
    Object.keys(NOISY).forEach(k => { r[k] = path ? undefined : undefined; });
    // 全部 7 只都强势上行 → 广度满格
    ["tongwei", "zhonghuan", "junda", "longi", "flat", "jiejia", "sungrow"].forEach((k, idx) => {
      r[k] = +(20 * Math.pow(1.003 + idx * 0.0002, 120)).toFixed(4) * (1 + 0.003 * idx);
    });
    return r;
  });
  // 修正：需要递增序列，直接构造强势个股
  for (let i = 0; i < hist.length; i++) {
    ["tongwei", "zhonghuan", "junda", "longi", "flat", "jiejia", "sungrow"].forEach((k, idx) => {
      hist[i][k] = +(30 * Math.pow(1.004 + idx * 0.0003, i)).toFixed(4);
    });
  }
  const L = { solar_etf_chg: 2.1, storage_etf_chg: 1.5 };
  const manual = { industry_prices: { module: [
    { date: "2026-01-08", value: 0.86 }, { date: "2026-01-15", value: 0.87 },
    { date: "2026-01-22", value: 0.88 }, { date: "2026-01-29", value: 0.89 },
    { date: "2026-02-05", value: 0.90 }, { date: "2026-02-12", value: 0.91 }
  ] } };
  const t = SC.computeTiming(hist, L, manual);
  const st = SC.combineState({
    posOn: 0, posTotal: 2, pol: "none",
    timingLit: t.lit, breadthLit: t.breadthLit, ddFromHigh: 0.08
  });
  console.log(`  时机灯 ${t.lit}/5 亮 · 灯④广度 ${t.breadthLit}`);
  show("C", st);
  check("C: 广度满格（7/7）", t.breadthLit === 7);
  check("C: 触发 ⚫过热区覆盖（即使时机灯多亮）", st.key === "overheat", `key=${st.key}`);
}

console.log(failures === 0 ? "\n全部测试通过 ✓" : `\n${failures} 项失败 ✗`);
process.exit(failures === 0 ? 0 : 1);
