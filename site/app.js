/* pig-cycle-monitor 仪表盘渲染逻辑
 * 数据加载：GitHub Pages 下 fetch('data/*.json')；本地 file:// 下回退 window.__PIG_DATA__（内联）。
 */
(function () {
  "use strict";

  var DATA = {
    latest: null,
    history: null,
    signals: null,
    manual: null
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
      { key: "manual", url: "data/manual.json" }
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
      card.appendChild(body);
      box.appendChild(card);
    });
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
      grid: { left: 56, right: 56, top: 36, bottom: 28 },
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
      grid: { left: 48, right: 24, top: 24, bottom: 28 },
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

  /* ---------- 主入口 ---------- */
  function renderAll() {
    renderHeader();
    renderSignals();
    renderPending();
    if (window.echarts) {
      renderPriceChart();
      renderRatioChart();
      renderCurveChart();
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
