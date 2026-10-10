/* pig-cycle-monitor 仪表盘渲染逻辑
 * 数据加载：GitHub Pages 下 fetch('data/*.json')；本地 file:// 下回退 window.__PIG_DATA__（内联）。
 */
(function () {
  "use strict";

  var DATA = {
    latest: null,
    history: null,
    signals: null,
    manual: null,
    sow_history: null,
    stocks: null
  };

  function el(id) { return document.getElementById(id); }

  function fmt(v, digits) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    if (isNaN(n)) return String(v);
    return n.toFixed(digits === undefined ? 2 : digits);
  }

  function loadData() {
    var inline = window.__PIG_DATA__ || {};
    var jobs = [
      { key: "latest", url: "data/latest.json" },
      { key: "history", url: "data/history.json" },
      { key: "signals", url: "data/signals.json" },
      { key: "manual", url: "data/manual.json" },
      { key: "sow_history", url: "data/sow_history.json" },
      { key: "stocks", url: "data/pig/stocks.json" }
    ];
    return Promise.all(jobs.map(function (j) {
      return fetch(j.url)
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (d) { DATA[j.key] = d; })
        .catch(function () {
          if (inline[j.key] !== undefined) { DATA[j.key] = inline[j.key]; }
        });
    }));
  }

  /* ---------- 顶部状态条 ---------- */
  function renderHeader() {
    var s = DATA.signals || {};
    var verdict = s.verdict || "数据加载中";
    var score = s.score || "0/0";
    var date = s.date || (DATA.latest && DATA.latest.date) || "";
    el("verdict").textContent = verdict;
    el("score").textContent = score;
    el("date").textContent = date ? "数据日期 " + date : "";
    var cls = "down";
    if (verdict === "拐点确认区") cls = "peak";
    else if (verdict === "磨底观察中") cls = "watch";
    el("verdict").className = "verdict " + cls;
    renderPigKPI();
  }

  function renderPigKPI() {
    var L = DATA.latest || {};
    var box = document.getElementById("pig-kpi");
    if (!box) return;
    var items = [];
    if (L.spot_pig) items.push({label: "生猪出栏价", value: L.spot_pig.toFixed(1)+" 元/kg", sub: "全国均价"});
    if (L.futures && L.futures.生猪) items.push({label: "LH期货主力", value: L.futures.生猪.close.toFixed(0)+" 元/吨", sub: "大商所"});
    if (L.pig_grain_ratio) items.push({label: "猪粮比", value: L.pig_grain_ratio.toFixed(2), sub: L.pig_grain_ratio<5?'过度亏损':L.pig_grain_ratio>9?'过高':'正常'});
    if (L.soybean_meal) items.push({label: "豆粕期货", value: L.soybean_meal.toFixed(0)+" 元/吨", sub: "饲料成本"});
    if (L.self_profit !== undefined) items.push({label: "自繁自养利润", value: L.self_profit.toFixed(1)+" 元/kg", sub: L.self_profit<0?'亏损':L.self_profit>2?'盈利':'微利'});
    if (L.province_prices) {
      var pp = L.province_prices;
      if (pp.河南) items.push({label: "河南", value: pp.河南.toFixed(1), sub: "主产区"});
      if (pp.广东) items.push({label: "广东", value: pp.广东.toFixed(1), sub: "主销区"});
      if (pp.东北均价) items.push({label: "东北均价", value: pp.东北均价.toFixed(1), sub: "主产区"});
    }
    box.innerHTML = items.map(function(it){
      return '<div style="background:var(--card);padding:12px;border-radius:8px;border-left:3px solid var(--accent)"><div style="font-size:11px;color:var(--muted)">'+it.label+'</div><div style="font-size:20px;font-weight:700;margin:4px 0">'+it.value+'</div><div style="font-size:11px;color:var(--muted)">'+it.sub+'</div></div>';
    }).join('');
  }

  /* ---------- 信号灯卡片 ---------- */
  function renderSignals() {
    var box = el("signals");
    box.innerHTML = "";
    var list = (DATA.signals && DATA.signals.signals) || [];
    if (!list.length) {
      box.innerHTML = '<p class="empty">暂无信号数据。等待首次数据抓取完成后生成。</p>';
      return;
    }
    list.forEach(function (sig) {
      var card = document.createElement("div");
      card.className = "sig-card " + sig.status;
      var lamp = document.createElement("span");
      lamp.className = "lamp";
      card.appendChild(lamp);
      var body = document.createElement("div");
      body.className = "sig-body";
      var name = document.createElement("div");
      name.className = "sig-name";
      name.textContent = sig.name;
      var val = document.createElement("div");
      val.className = "sig-value";
      val.textContent = fmt(sig.value) + "  / 阈值 " + fmt(sig.threshold);
      var desc = document.createElement("div");
      desc.className = "sig-desc";
      desc.textContent = sig.desc;
      body.appendChild(name);
      body.appendChild(val);
      body.appendChild(desc);
      var src = sig.source || [];
      if (src.length) {
        var srcRow = document.createElement("div");
        srcRow.className = "sig-src";
        srcRow.appendChild(document.createTextNode("来源 "));
        src.forEach(function (s, i) {
          if (i > 0) srcRow.appendChild(document.createTextNode(" · "));
          if (s.url) {
            var a = document.createElement("a");
            a.href = s.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = s.text;
            srcRow.appendChild(a);
          } else {
            srcRow.appendChild(document.createTextNode(s.text));
          }
        });
        body.appendChild(srcRow);
      }
      card.appendChild(body);
      box.appendChild(card);
    });
  }

  function renderAI() {
    var el = document.getElementById("pig-ai");
    if (!el) return;
    var s = DATA.signals || {};
    if (s.ai_analysis) {
      el.textContent = s.ai_analysis;
    } else {
      el.innerHTML = '<span style="color:var(--muted)">今日 AI 分析暂未生成。</span>';
    }
    // 按日期存档（可翻阅历史；有存档优先展示存档）
    if (window.AIArchive && DATA.latest) {
      AIArchive.init({ commodity: "pig", baseDir: "data/", displayEl: "pig-ai", dataDate: DATA.latest.date });
    }
  }

  /* ---------- 待复核区 ---------- */
  function renderPending() {
    var box = el("pending-list");
    box.innerHTML = "";
    var pending = (DATA.signals && DATA.signals.pending_review) || [];
    if (!pending.length) {
      box.innerHTML = '<p class="empty">当前没有待复核条目。</p>';
      return;
    }
    pending.forEach(function (key) {
      var item = document.createElement("div");
      item.className = "pending-item";
      var tag = document.createElement("code");
      tag.textContent = key;
      var note = document.createElement("span");
      var src = key === "sow" ? (DATA.manual && DATA.manual.sow) : null;
      note.textContent = src && src.note ? " · " + src.note : " · 需人工核对原始公告后，将 need_review 改为 false 并推送";
      item.appendChild(tag);
      item.appendChild(note);
      box.appendChild(item);
    });
    el("pending-count").textContent = pending.length + " 条";
  }

  /* ---------- 图表 ---------- */
  var charts = {};

  function chart(id) {
    var node = el(id);
    if (!node) return null;
    if (charts[id]) return charts[id];
    charts[id] = echarts.init(node);
    return charts[id];
  }

  function resizeAll() {
    Object.keys(charts).forEach(function (k) { charts[k].resize(); });
  }

  var AXIS = {
    line: "#2A3A32",
    text: "#8FA39A",
    split: "#1E2C25"
  };

  /* dataZoom：默认显示最近 60 个交易日，可拖动/滚轮回看全历史 */
  function zoomRange(dates) {
    var start = Math.max(0, dates.length - 60);
    return { startValue: start, endValue: dates.length - 1 };
  }

  function makeZoom(dates) {
    var r = zoomRange(dates);
    return [
      { type: "inside", startValue: r.startValue, endValue: r.endValue,
        zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: "slider", startValue: r.startValue, endValue: r.endValue,
        height: 18, bottom: 4, borderColor: "transparent",
        backgroundColor: "#16211C", fillerColor: "rgba(232,147,74,0.16)",
        handleStyle: { color: "#E8934A", borderColor: "#E8934A" },
        dataBackground: { lineStyle: { color: "#3A4D43" }, areaStyle: { color: "rgba(90,120,105,0.2)" } },
        textStyle: { color: "#8FA39A" } }
    ];
  }

  /* 价格走势：现货猪价(左轴) + LH期货收盘(右轴) */
  function renderPriceChart() {
    var c = chart("chart-price");
    if (!c) return;
    var hist = DATA.history || [];
    var dates = hist.map(function (h) { return h.date; });
    var spots = hist.map(function (h) { return h.spot_pig; });
    var lh = hist.map(function (h) { return h.lh_close; });
    c.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["现货猪价(元/公斤)", "LH期货(元/吨)"], textStyle: { color: "#8FA39A" }, top: 0 },
      grid: { left: 56, right: 56, top: 36, bottom: 60 },
      dataZoom: makeZoom(dates),
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: AXIS.line } },
        axisLabel: { color: AXIS.text }
      },
      yAxis: [
        {
          type: "value", name: "元/公斤", nameTextStyle: { color: AXIS.text },
          splitLine: { lineStyle: { color: AXIS.split } },
          axisLabel: { color: AXIS.text }
        },
        {
          type: "value", name: "元/吨", nameTextStyle: { color: AXIS.text },
          splitLine: { show: false },
          axisLabel: { color: AXIS.text }
        }
      ],
      series: [
        {
          name: "现货猪价(元/公斤)", type: "line", data: spots,
          smooth: true, symbol: "none", lineStyle: { width: 2, color: "#E8934A" },
          areaStyle: { color: "rgba(232,147,74,0.08)" }
        },
        {
          name: "LH期货(元/吨)", type: "line", yAxisIndex: 1, data: lh,
          smooth: true, symbol: "none", lineStyle: { width: 2, color: "#5FA8D9" }
        }
      ]
    }, true);
  }

  /* 猪粮比带状图：参考线 5.5(一级预警) 与 9(过度上涨) */
  function renderRatioChart() {
    var c = chart("chart-ratio");
    if (!c) return;
    var hist = DATA.history || [];
    var dates = hist.map(function (h) { return h.date; });
    var ratios = hist.map(function (h) { return h.pig_grain_ratio; });
    c.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 24, top: 24, bottom: 60 },
      dataZoom: makeZoom(dates),
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: AXIS.line } },
        axisLabel: { color: AXIS.text }
      },
      yAxis: {
        type: "value", name: "猪粮比", nameTextStyle: { color: AXIS.text },
        min: 4, max: 11,
        splitLine: { lineStyle: { color: AXIS.split } },
        axisLabel: { color: AXIS.text }
      },
      series: [{
        type: "line", data: ratios, smooth: true, symbol: "none",
        lineStyle: { width: 2, color: "#3FBF7F" },
        markLine: {
          silent: true,
          symbol: "none",
          label: { color: "#C9D4CE", fontSize: 11, position: "insideEndTop" },
          lineStyle: { type: "dashed" },
          data: [
            { yAxis: 5.5, lineStyle: { color: "#E0B341" }, label: { formatter: "5.5 预警" } },
            { yAxis: 9, lineStyle: { color: "#D96A5C" }, label: { formatter: "9 过热" } },
            { yAxis: 6, lineStyle: { color: "#3FBF7F" }, label: { formatter: "6 盈亏" } }
          ]
        }
      }]
    }, true);
  }

  /* 期货期限结构：LH 各合约收盘价柱状图 */
  function renderCurveChart() {
    var c = chart("chart-curve");
    if (!c) return;
    var derived = (DATA.latest && DATA.latest.derived) || {};
    var curve = derived.lh_curve || {};
    var syms = Object.keys(curve).sort();
    if (!syms.length) {
      c.setOption({
        backgroundColor: "transparent",
        title: { text: "暂无 LH 合约数据", textStyle: { color: "#8FA39A", fontSize: 13 } }
      }, true);
      return;
    }
    var vals = syms.map(function (s) { return curve[s]; });
    c.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 56, right: 24, top: 24, bottom: 28 },
      xAxis: {
        type: "category", data: syms,
        axisLine: { lineStyle: { color: AXIS.line } },
        axisLabel: { color: AXIS.text }
      },
      yAxis: {
        type: "value", name: "元/吨", nameTextStyle: { color: AXIS.text },
        splitLine: { lineStyle: { color: AXIS.split } },
        axisLabel: { color: AXIS.text }
      },
      series: [{
        type: "bar", data: vals, barWidth: "55%",
        itemStyle: {
          color: function (p) {
            var diff = vals[p.dataIndex] - vals[0];
            return diff >= 0 ? "#3FBF7F" : "#D96A5C";
          }
        }
      }]
    }, true);
  }

  /* 能繁母猪存栏（季度）：柱状 + 正常保有量参考线 */
  function renderSowChart() {
    var c = chart("chart-sow");
    if (!c) return;
    var list = DATA.sow_history || [];
    if (!list.length) {
      c.setOption({
        backgroundColor: "transparent",
        title: { text: "暂无能繁母猪数据", textStyle: { color: "#8FA39A", fontSize: 13 } }
      }, true);
      return;
    }
    var dates = list.map(function (r) { return r.date; });
    var vals = list.map(function (r) { return r.sow_wan; });
    c.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: function (ps) {
          var i = ps[0].dataIndex;
          var r = list[i];
          var s = ps[0].axisValue + "<br/>能繁母猪: " + r.sow_wan + " 万头";
          if (r.mom_pct !== null && r.mom_pct !== undefined) s += "<br/>环比: " + r.mom_pct + "%";
          if (r.yoy_pct !== null && r.yoy_pct !== undefined) s += " / 同比: " + r.yoy_pct + "%";
          if (r.holding_pct !== null && r.holding_pct !== undefined) s += "<br/>占正常保有量: " + r.holding_pct + "%";
          s += "<br/><span style='color:#8FA39A'>" + (r.note || r.source || "") + "</span>";
          return s;
        }
      },
      grid: { left: 60, right: 24, top: 24, bottom: 28 },
      xAxis: {
        type: "category", data: dates,
        axisLine: { lineStyle: { color: AXIS.line } },
        axisLabel: { color: AXIS.text }
      },
      yAxis: {
        type: "value", name: "万头", nameTextStyle: { color: AXIS.text },
        min: function (v) { return Math.floor(v.min / 100) * 100; },
        splitLine: { lineStyle: { color: AXIS.split } },
        axisLabel: { color: AXIS.text }
      },
      series: [{
        type: "bar", data: vals, barWidth: "45%",
        itemStyle: { color: "#E8934A" },
        label: { show: true, position: "top", color: "#C9D4CE", fontSize: 11 },
        markLine: {
          silent: true, symbol: "none",
          label: { color: "#8FA39A", fontSize: 11, position: "insideEndTop" },
          lineStyle: { type: "dashed", color: "#5FA8D9" },
          data: [{ yAxis: 3750, label: { formatter: "3750 正常保有量" } }]
        }
      }]
    }, true);
  }

  /* ---------- A股猪企：股价 vs 猪价联动 ---------- */
  var STOCK_NAMES = { muyuan: "牧原股份", wens: "温氏股份", xinxiwang: "新希望" };
  var STOCK_COLORS = { muyuan: "#5FA8D9", wens: "#3FBF7F", xinxiwang: "#BC8CFF" };

  function spotMap() {
    var m = {};
    (DATA.history || []).forEach(function (h) { if (h.spot_pig != null) m[h.date] = h.spot_pig; });
    return m;
  }

  /* 归一化序列（首个非空值=100），自动跨 null 断点连线 */
  function normArr(dates, get) {
    var base = null;
    return dates.map(function (d) {
      var v = get(d);
      if (v == null) return null;
      if (base == null) base = v;
      return +(v / base * 100).toFixed(2);
    });
  }

  function renderStockChart() {
    var c = chart("chart-stock");
    if (!c) return;
    var stocks = DATA.stocks || [];
    if (!stocks.length) {
      c.setOption({ backgroundColor: "transparent", title: { text: "暂无 A股猪企数据（明晚自动更新后显示）", textStyle: { color: "#8FA39A", fontSize: 13 } } }, true);
      return;
    }
    var dates = stocks.map(function (r) { return r.date; });
    var sm = spotMap();
    var series = [{
      name: "生猪现货(归一)", type: "line", data: normArr(dates, function (d) { return sm[d]; }),
      smooth: true, symbol: "none", connectNulls: true,
      lineStyle: { width: 2.5, color: "#E8934A", type: "dashed" }
    }];
    ["muyuan", "wens", "xinxiwang"].forEach(function (k) {
      series.push({
        name: STOCK_NAMES[k], type: "line",
        data: normArr(dates, function (d) {
          for (var i = 0; i < stocks.length; i++) if (stocks[i].date === d) return stocks[i][k];
          return null;
        }),
        smooth: true, symbol: "none", connectNulls: true,
        lineStyle: { width: 1.8, color: STOCK_COLORS[k] }
      });
    });
    c.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["生猪现货(归一)", "牧原股份", "温氏股份", "新希望"], textStyle: { color: "#8FA39A" }, top: 0 },
      grid: { left: 44, right: 20, top: 36, bottom: 60 },
      dataZoom: makeZoom(dates),
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: AXIS.line } },
        axisLabel: { color: AXIS.text }
      },
      yAxis: {
        type: "value", name: "期初=100", nameTextStyle: { color: AXIS.text }, scale: true,
        splitLine: { lineStyle: { color: AXIS.split } },
        axisLabel: { color: AXIS.text }
      },
      series: series
    }, true);
  }

  /* 股价日变动 与 猪价日变动 的配对样本（仅共同交易日） */
  function pairedChanges() {
    var sm = spotMap();
    var stocks = DATA.stocks || [];
    var pairs = { muyuan: [], wens: [], xinxiwang: [] };
    for (var i = 1; i < stocks.length; i++) {
      var a = stocks[i - 1], b = stocks[i];
      var sp0 = sm[a.date], sp1 = sm[b.date];
      if (sp0 == null || sp1 == null || !sp0) continue;
      var pc = (sp1 / sp0 - 1) * 100;
      ["muyuan", "wens", "xinxiwang"].forEach(function (k) {
        if (a[k] != null && b[k] != null && a[k] !== 0) pairs[k].push([pc, (b[k] / a[k] - 1) * 100]);
      });
    }
    return pairs;
  }

  function corrSlope(pairs) {
    var n = pairs.length;
    if (n < 10) return null;
    var mx = 0, my = 0;
    pairs.forEach(function (p) { mx += p[0]; my += p[1]; });
    mx /= n; my /= n;
    var sxy = 0, sxx = 0, syy = 0;
    pairs.forEach(function (p) {
      sxy += (p[0] - mx) * (p[1] - my);
      sxx += (p[0] - mx) * (p[0] - mx);
      syy += (p[1] - my) * (p[1] - my);
    });
    if (!sxx || !syy) return null;
    return { n: n, corr: sxy / Math.sqrt(sxx * syy), beta: sxy / sxx };
  }

  function renderSens() {
    var box = el("stock-sens");
    if (!box) return;
    var stocks = DATA.stocks || [];
    if (!stocks.length) {
      box.innerHTML = '<p class="empty">暂无 A股猪企数据（明晚自动更新后显示）。</p>';
      return;
    }
    var pairs = pairedChanges();
    var last = stocks[stocks.length - 1];
    var rows = ["muyuan", "wens", "xinxiwang"].map(function (k) {
      var c120 = corrSlope(pairs[k]);
      var c60 = corrSlope(pairs[k].slice(-60));
      return { key: k, price: last[k], c60: c60, c120: c120 };
    });
    var html = '<table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr style="color:var(--muted);font-size:12px;text-align:left"><th style="padding:6px 8px;border-bottom:1px solid var(--border)">标的</th><th style="padding:6px 8px;border-bottom:1px solid var(--border)">现价</th><th style="padding:6px 8px;border-bottom:1px solid var(--border)">60日相关</th><th style="padding:6px 8px;border-bottom:1px solid var(--border)">120日相关</th><th style="padding:6px 8px;border-bottom:1px solid var(--border)">敏感度(120日)</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      function cell(v, suffix, invert) {
        if (!v) return '<td style="padding:6px 8px;border-bottom:1px solid var(--border);color:var(--muted)">数据不足</td>';
        var good = invert ? v.corr < 0.3 : v.corr > 0.4;
        var col = good ? "var(--green)" : (Math.abs(v.corr) > 0.4 ? "var(--yellow)" : "var(--muted)");
        return '<td style="padding:6px 8px;border-bottom:1px solid var(--border);color:' + col + '">' + (v.corr >= 0 ? "+" : "") + v.corr.toFixed(2) + (suffix || "") + '</td>';
      }
      var betaCell = !r.c120 ? '<td style="padding:6px 8px;border-bottom:1px solid var(--border);color:var(--muted)">数据不足</td>'
        : '<td style="padding:6px 8px;border-bottom:1px solid var(--border);color:var(--text)">猪价+1% → 股价 ' + (r.c120.beta >= 0 ? "+" : "") + r.c120.beta.toFixed(2) + '%</td>';
      html += '<tr><td style="padding:6px 8px;border-bottom:1px solid var(--border);font-weight:700">' + STOCK_NAMES[r.key] + '</td>' +
        '<td style="padding:6px 8px;border-bottom:1px solid var(--border)">' + fmt(r.price) + '</td>' +
        cell(r.c60) + cell(r.c120) + betaCell + '</tr>';
    });
    html += '</tbody></table>';
    box.innerHTML = html;
  }

  /* ---------- 主入口 ---------- */
  function renderAll() {
    renderHeader();
    renderSignals();
    renderAI();
    renderPending();
    renderSens();
    if (window.echarts) {
      renderPriceChart();
      renderRatioChart();
      renderSowChart();
      renderCurveChart();
      renderStockChart();
    } else {
      el("chart-price").innerHTML = '<p class="empty">ECharts 加载失败，请检查网络后刷新。</p>';
    }
  }

  function init() {
    if (window.echarts) {
      window.addEventListener("resize", resizeAll);
    }
    var refresh = el("btn-refresh");
    if (refresh) {
      refresh.addEventListener("click", function () { location.reload(); });
    }
    loadData().then(function () {
      var loaded = DATA.latest || DATA.signals || DATA.history;
      if (!loaded) {
        el("verdict").textContent = "数据加载失败";
        el("score").textContent = "—";
        document.querySelectorAll(".block").forEach(function (b) {
          b.insertAdjacentHTML("beforeend",
            '<p class="empty">无法读取 data/*.json。请确认站点已部署数据文件（data 目录随 Pages 构建发布）。</p>');
        });
        return;
      }
      renderAll();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

const DEEPSEEK_KEY = "sk-238f37694a504056b4178fb33d6613b6";

async function regeneratePigAI(){
  const el = document.getElementById("pig-ai");
  el.textContent = "分析中...";
  try {
    const [L, S] = await Promise.all([
      fetch("data/latest.json",{cache:"no-store"}).then(r=>r.json()),
      fetch("data/signals.json",{cache:"no-store"}).then(r=>r.json())
    ]);
    const sigLines = (S.signals||[]).map(s=>`  - ${s.name}（${s.status}）：${s.desc}`).join("\n");
    const pp = L.province_prices || {};
    const henan = pp.河南 ? pp.河南 : "未获取";
    const guangdong = pp.广东 ? pp.广东 : "未获取";
    const northeast = pp.东北均价 ? pp.东北均价 : "未获取";
    const soybean = L.soybean_meal ? L.soybean_meal : "未获取";
    const profit = L.self_profit !== undefined ? L.self_profit : "未获取";
    const lhClose = L.futures && L.futures.生猪 ? L.futures.生猪.close : "未获取";

    const prompt = `你是生猪产业分析师，每日跟踪生猪市场。基于以下数据，按要求输出。

【核心数据】
- 全国生猪出栏均价：${L.spot_pig||"未获取"} 元/公斤
- 主产区河南：${henan} 元/公斤
- 主销区广东：${guangdong} 元/公斤
- 东北均价：${northeast} 元/公斤
- 大商所LH期货主力：${lhClose} 元/吨
- 猪粮比：${L.pig_grain_ratio||"未获取"}
- 豆粕价格：${soybean} 元/吨
- 自繁自养利润：${profit} 元/公斤
- ${(S.signals||[]).length}个信号灯（${(S.signals||[]).filter(s=>s.status==="green").length}绿）：
${sigLines}

【输出要求】
1. 周期定位：当前处于猪周期哪个阶段（去产能/筑底/上行/恢复/下行）
2. 短期供需：当前供给压力 vs 季节性需求
3. 价格驱动：今日变动是现货供需/期货资金/政策消息驱动
4. 期现结构：基差和月差反映的市场预期
5. 短期展望：现货猪价方向 + 期货关键价位
6. 周期提示：下一个关键观察点
7. 需关注事件：收储放储、产能数据发布日

要求：200-300字，普通人能懂，不要套话和免责声明，未获取的数据不要编造。`;

    const resp = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + DEEPSEEK_KEY,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [
          {role: "system", content: "你是严谨的生猪产业分析师。"},
          {role: "user", content: prompt}
        ],
        temperature: 0.3,
        max_tokens: 500
      })
    });
    const data = await resp.json();
    if(data.error) throw new Error(data.error.message);
    el.textContent = data.choices[0].message.content;
    if (window.AIArchive) AIArchive.setCurrent(data.choices[0].message.content);
  } catch(e) {
    el.innerHTML = '<span style="color:#f85149">生成失败: '+e.message+'</span>';
  }
}
