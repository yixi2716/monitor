# -*- coding: utf-8 -*-
"""
黄金追踪看板：从 Yahoo Finance 拉 6 个 ticker 日线，计算指标、识别定价模式、生成信号。
输出 data/gold/latest.json + data/gold/history.json，并同步到 site/data/gold/。
"""
import os
import sys
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET

# 本地开发走代理；GitHub Actions runner 在美国直连即可
if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")

import yfinance as yf
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "gold")

TICKERS = {
    "GC": "GC=F",        # COMEX 黄金期货（美元/盎司）
    "GLD": "GLD",        # SPDR 黄金 ETF（美元/股，约 1/10 盎司）
    "DXY": "DX-Y.NYB",   # 美元指数
    "VIX": "^VIX",       # 恐慌指数
    "TIP": "TIP",        # iShares TIPS ETF（实际利率反向代理）
    "TNX": "^TNX",       # 10 年美债收益率（%）
    "ZQ": "ZQ=F",        # 30 天联邦基金期货（隐含政策利率预期）
    "CL": "CL=F",        # WTI 原油（美元/桶，地缘风险代理）
}


def fetch_all(period="1y"):
    """拉 6 个 ticker，按日期 inner join 对齐（统一去掉时区，按交易日对齐）。"""
    frames = {}
    for name, sym in TICKERS.items():
        df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
        if df.empty:
            raise RuntimeError(f"{sym} 返回空数据")
        s = df["Close"].rename(name)
        # 统一转成 naive 日期（去掉时区，避免 NY/Chicago 时区差导致 join 空）
        s.index = s.index.tz_localize(None).normalize()
        frames[name] = s
    px = pd.concat(frames.values(), axis=1, join="inner")
    px = px.sort_index()
    px = px.dropna(how="any")
    return px


def compute(px: pd.DataFrame):
    """计算技术指标、滚动相关性、价差。返回 (history_df, latest_dict)"""
    out = pd.DataFrame(index=px.index)
    out["gold"] = px["GC"]
    out["gld"] = px["GLD"]
    out["dxy"] = px["DXY"]
    out["vix"] = px["VIX"]
    out["tip"] = px["TIP"]
    out["tnx"] = px["TNX"]

    # 日收益率
    ret = px.pct_change()
    # 均线
    out["ma20"] = px["GC"].rolling(20).mean()
    out["ma50"] = px["GC"].rolling(50).mean()
    # 20 日波动率（年化 %）
    out["vol20"] = ret["GC"].rolling(20).std() * np.sqrt(252) * 100
    # 期现价差：GC 美元/盎司 / 10 ≈ GLD 美元/股；差值 = GC/10 - GLD
    out["basis"] = px["GC"] / 10.0 - px["GLD"]
    # 20 日滚动相关性
    out["corr_gold_dxy"] = ret["GC"].rolling(20).corr(ret["DXY"])
    out["corr_gold_tip"] = ret["GC"].rolling(20).corr(ret["TIP"])
    out["corr_gold_vix"] = ret["GC"].rolling(20).corr(ret["VIX"])
    return out


def detect_mode(df: pd.DataFrame):
    """A=利率敏感 / B=避险驱动 / C=央行购金 / M=混合。返回 (mode, conf, evidence[])"""
    last = df.iloc[-1]
    c_dxy = last["corr_gold_dxy"]
    c_tip = last["corr_gold_tip"]
    c_vix = last["corr_gold_vix"]
    vix = last["vix"]
    vix_5d_chg = (last["vix"] / df["vix"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    dxy_1d = (last["dxy"] / df["dxy"].iloc[-2] - 1) * 100 if len(df) >= 2 else 0
    gold_1d = (last["gold"] / df["gold"].iloc[-2] - 1) * 100 if len(df) >= 2 else 0

    # C 模式：与 TIP、DXY 都脱钩，且美元强时金价抗跌
    decoupled = (abs(c_tip) < 0.2) and (abs(c_dxy) < 0.3)
    resilient = dxy_1d > 0.5 and gold_1d > -1.0  # 美元涨但金价没怎么跌
    # B 模式：VIX 高或急升，且黄金与 VIX 正相关
    safe_haven = (vix > 20 or vix_5d_chg > 30) and (c_vix > 0.4)
    # A 模式：实际利率主导
    rate_driven = abs(c_tip) > 0.5 and abs(c_dxy) < 0.3

    evid = []
    if rate_driven:
        mode = "A"
        conf = "高" if abs(c_tip) > 0.6 else "中"
        evid = [
            f"黄金与 TIP（实际利率代理）20日相关性 {c_tip:+.2f}，实际利率主导",
            f"黄金与 DXY 相关性仅 {c_dxy:+.2f}，美元因素次要",
            "关注美联储议息与美债收益率走势",
        ]
    elif safe_haven:
        mode = "B"
        conf = "高" if vix > 22 else "中"
        evid = [
            f"VIX 当前 {vix:.1f}（{'高位' if vix > 20 else '5日急升' + format(vix_5d_chg, '+.0f') + '%'}）",
            f"黄金与 VIX 20日相关性 {c_vix:+.2f}，避险买盘驱动",
            "关注地缘政治 / 金融风险事件",
        ]
    elif decoupled and resilient:
        mode = "C"
        conf = "中"
        evid = [
            f"美元今日 {dxy_1d:+.2f}%，但黄金仅 {gold_1d:+.2f}%（抗跌）",
            f"黄金与 TIP 相关性 {c_tip:+.2f}、与 DXY 相关性 {c_dxy:+.2f}，传统框架脱钩",
            "结构性买盘（央行购金 / 实物需求）支撑",
        ]
    else:
        mode = "M"
        conf = "低"
        evid = [
            f"黄金与 TIP 相关性 {c_tip:+.2f}，与 DXY 相关性 {c_dxy:+.2f}",
            f"VIX {vix:.1f}，与 VIX 相关性 {c_vix:+.2f}",
            "多因子混合驱动，无单一主导逻辑",
        ]
    return mode, conf, evid


def build_signals(df: pd.DataFrame):
    """5 条信号 + 综合评分。返回 (signals[], score, summary)"""
    last = df.iloc[-1]
    signals = []

    # 1. 美元
    dxy = last["dxy"]
    if dxy > 101:
        s = {"name": "美元信号", "text": f"DXY {dxy:.1f} > 101，压制金价", "dir": "bear"}
    elif dxy < 99:
        s = {"name": "美元信号", "text": f"DXY {dxy:.1f} < 99，利好金价", "dir": "bull"}
    else:
        s = {"name": "美元信号", "text": f"DXY {dxy:.1f}，区间震荡", "dir": "neutral"}
    signals.append(s)

    # 2. 利率（TIP 5 日变化：TIP 跌 = 实际利率升 = 利空）
    tip_5d = (last["tip"] / df["tip"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    if tip_5d < -1.0:
        s = {"name": "利率信号", "text": f"TIP 5日 {tip_5d:+.2f}%，实际利率上行 → 利空", "dir": "bear"}
    elif tip_5d > 1.0:
        s = {"name": "利率信号", "text": f"TIP 5日 {tip_5d:+.2f}%，实际利率下行 → 利好", "dir": "bull"}
    else:
        s = {"name": "利率信号", "text": f"TIP 5日 {tip_5d:+.2f}%，实际利率平稳", "dir": "neutral"}
    signals.append(s)

    # 3. 避险
    vix = last["vix"]
    if vix > 20:
        s = {"name": "避险信号", "text": f"VIX {vix:.1f} > 20，避险买盘 → 利好", "dir": "bull"}
    elif vix < 15:
        s = {"name": "避险信号", "text": f"VIX {vix:.1f} < 15，风险偏好高 → 利空", "dir": "bear"}
    else:
        s = {"name": "避险信号", "text": f"VIX {vix:.1f}，中性", "dir": "neutral"}
    signals.append(s)

    # 4. 情绪（VIX 5 日涨幅）
    vix_5d = (vix / df["vix"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    if vix_5d > 30:
        s = {"name": "情绪信号", "text": f"VIX 5日 {vix_5d:+.0f}%，恐慌急升 → 避险利好", "dir": "bull"}
    elif vix_5d < -20:
        s = {"name": "情绪信号", "text": f"VIX 5日 {vix_5d:+.0f}%，恐慌退潮 → 利空", "dir": "bear"}
    else:
        s = {"name": "情绪信号", "text": f"VIX 5日 {vix_5d:+.0f}%，情绪平稳", "dir": "neutral"}
    signals.append(s)

    # 5. 实物（GLD vs GC 5 日强弱）
    gld_5d = (last["gld"] / df["gld"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    gc_5d = (last["gold"] / df["gold"].iloc[-6] - 1) * 100 if len(df) >= 6 else 0
    if gld_5d > gc_5d + 0.5:
        s = {"name": "实物信号", "text": f"GLD 5日 {gld_5d:+.2f}% 强于期货 {gc_5d:+.2f}%，实物需求支撑", "dir": "bull"}
    elif gld_5d < gc_5d - 0.5:
        s = {"name": "实物信号", "text": f"GLD 5日 {gld_5d:+.2f}% 弱于期货 {gc_5d:+.2f}%，期货投机偏热", "dir": "bear"}
    else:
        s = {"name": "实物信号", "text": f"GLD 与期货同步（5日 {gld_5d:+.2f}% vs {gc_5d:+.2f}%）", "dir": "neutral"}
    signals.append(s)

    score = sum(1 if s["dir"] == "bull" else (-1 if s["dir"] == "bear" else 0) for s in signals)
    if score >= 2:
        summary = f"{score:+d}（偏多）"
    elif score <= -2:
        summary = f"{score:+d}（偏空）"
    else:
        summary = f"{score:+d}（中性）"
    return signals, score, summary


def fetch_iran_news(limit=6):
    """从 Google News RSS 拉最近 7 天美伊相关新闻。返回 [{date, text, url, src}]，失败返回 []。"""
    url = ("https://news.google.com/rss/search?q=Iran+US+nuclear+when:7d"
           "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        items = root.findall(".//item")[:limit]
        out = []
        for it in items:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            # Google News 标题格式 "主标题 - 来源名"
            src = ""
            if " - " in title:
                title, src = title.rsplit(" - ", 1)
            # pubDate: "Mon, 28 Sep 2026 10:00:00 GMT"
            date_str = ""
            if pub:
                try:
                    dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = pub[:16]
            out.append({"date": date_str, "text": title, "url": link, "src": src or "Google News"})
        return out
    except Exception as e:
        print(f"    [warn] Google News RSS 拉取失败: {e}")
        return []


def main():
    print("[1/4] 拉取 Yahoo Finance 数据...")
    px = fetch_all(period="1y")
    print(f"    拿到 {len(px)} 个交易日，{px.index[0].date()} ~ {px.index[-1].date()}")

    print("[2/4] 计算指标...")
    df = compute(px)
    df = df.dropna(subset=["ma50"])  # 前 50 日没 MA50，截掉

    print("[3/4] 模式识别 + 信号生成...")
    mode, conf, evid = detect_mode(df)
    signals, score, summary = build_signals(df)

    # === 美联储宏观信息 ===
    cfg_path = os.path.join(ROOT, "config", "gold_macro.json")
    macro = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                macro = json.load(f)
        except Exception:
            macro = {}
    # ZQ 隐含利率
    zq_price = float(px["ZQ"].iloc[-1])
    zq_implied = round(100.0 - zq_price, 2)  # ZQ 期货价格 = 100 - 隐含联邦基金利率
    fed_upper = float(macro.get("fed_funds_upper", 4.0))
    fed_bp_diff = round((zq_implied - fed_upper) * 100, 0)  # 与当前政策利率上限差多少 bp
    # 距离下次 FOMC 天数
    next_fomc_str = macro.get("next_fomc", "")
    days_to_fomc = None
    if next_fomc_str:
        try:
            nxt = datetime.datetime.strptime(next_fomc_str, "%Y-%m-%d").date()
            today = df.index[-1].date()
            days_to_fomc = (nxt - today).days
        except Exception:
            pass
    macro_block = {
        "funds_range": macro.get("fed_funds_range", ""),
        "last_change": macro.get("last_change", ""),
        "next_label": macro.get("next_fomc_label", ""),
        "next_date": next_fomc_str,
        "days_to_next": days_to_fomc,
        "upcoming": macro.get("upcoming_fomc", []),
        "zq_price": round(zq_price, 2),
        "zq_implied_rate": zq_implied,
        "market_bp_vs_current": fed_bp_diff,
        "market_expectation": (
            f"市场预期下次会议维持不变" if abs(fed_bp_diff) < 10
            else (f"市场预期加息 {int(abs(fed_bp_diff))}bp" if fed_bp_diff > 0
                  else f"市场预期降息 {int(abs(fed_bp_diff))}bp")
        ),
        "source_url": macro.get("source", ""),
    }

    # === 地缘风险（美伊局势）===
    geo_path = os.path.join(ROOT, "config", "gold_geopolitics.json")
    geo = {}
    if os.path.exists(geo_path):
        try:
            with open(geo_path, encoding="utf-8") as f:
                geo = json.load(f)
        except Exception:
            geo = {}
    cl_price = float(px["CL"].iloc[-1])
    cl_chg = (cl_price / float(px["CL"].iloc[-2]) - 1) * 100 if len(px) >= 2 else 0
    # 自动爬 Google News RSS 美伊新闻，失败则用 config 里的静态事件
    auto_events = fetch_iran_news(limit=6)
    events = auto_events if auto_events else geo.get("events", [])
    print(f"    地缘新闻: {len(auto_events)} 条自动抓取" if auto_events else "    地缘新闻: 使用 config 静态事件")
    geo_block = {
        "level": geo.get("level", ""),
        "level_color": geo.get("level_color", "orange"),
        "headline": geo.get("headline", ""),
        "summary": geo.get("summary", ""),
        "updated": geo.get("updated", ""),
        "events": events,
        "gold_impact": geo.get("gold_impact", ""),
        "wti_price": round(cl_price, 2),
        "wti_chg": round(cl_chg, 2),
        "news_auto": bool(auto_events),
    }

    last = df.iloc[-1]
    prev = df.iloc[-2]
    gold_chg = (last["gold"] / prev["gold"] - 1) * 100
    vix_chg = (last["vix"] / prev["vix"] - 1) * 100
    dxy_chg = (last["dxy"] / prev["dxy"] - 1) * 100

    mode_names = {
        "A": "A · 利率敏感型", "B": "B · 避险驱动型",
        "C": "C · 央行购金型", "M": "M · 混合驱动",
    }

    latest = {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "gold": round(float(last["gold"]), 2),
        "gold_chg": round(gold_chg, 2),
        "ma20": round(float(last["ma20"]), 2),
        "ma50": round(float(last["ma50"]), 2),
        "above_ma20": bool(last["gold"] > last["ma20"]),
        "above_ma50": bool(last["gold"] > last["ma50"]),
        "dxy": round(float(last["dxy"]), 2),
        "dxy_chg": round(dxy_chg, 2),
        "vix": round(float(last["vix"]), 2),
        "vix_chg": round(vix_chg, 2),
        "tip": round(float(last["tip"]), 2),
        "tnx": round(float(last["tnx"]), 2),
        "corr_gold_dxy": round(float(last["corr_gold_dxy"]), 2),
        "corr_gold_tip": round(float(last["corr_gold_tip"]), 2),
        "corr_gold_vix": round(float(last["corr_gold_vix"]), 2),
        "basis": round(float(last["basis"]), 2),
        "vol20": round(float(last["vol20"]), 1),
        "mode": mode,
        "mode_name": mode_names[mode],
        "confidence": conf,
        "evidence": evid,
        "signals": signals,
        "score": score,
        "score_summary": summary,
        "recent10": [],
        "macro": macro_block,
        "geopolitics": geo_block,
    }

    # 最近 10 天表
    for i in range(-10, 0):
        r = df.iloc[i]
        d = df.index[i].strftime("%Y-%m-%d")
        recent_chg = (r["gold"] / df.iloc[i - 1]["gold"] - 1) * 100 if i > -len(df) else 0
        latest["recent10"].append({
            "date": d,
            "gold": round(float(r["gold"]), 1),
            "gold_chg": round(recent_chg, 2),
            "dxy": round(float(r["dxy"]), 2),
            "vix": round(float(r["vix"]), 2),
            "tip": round(float(r["tip"]), 2),
        })

    # 历史序列（给 ECharts）
    history = []
    for i in range(len(df)):
        r = df.iloc[i]
        history.append({
            "date": df.index[i].strftime("%Y-%m-%d"),
            "gold": round(float(r["gold"]), 1),
            "ma20": round(float(r["ma20"]), 1) if not np.isnan(r["ma20"]) else None,
            "ma50": round(float(r["ma50"]), 1) if not np.isnan(r["ma50"]) else None,
            "dxy": round(float(r["dxy"]), 2),
            "vix": round(float(r["vix"]), 2),
            "tip": round(float(r["tip"]), 2),
            "basis": round(float(r["basis"]), 2),
            "corr_dxy": round(float(r["corr_gold_dxy"]), 2) if not np.isnan(r["corr_gold_dxy"]) else None,
            "corr_tip": round(float(r["corr_gold_tip"]), 2) if not np.isnan(r["corr_gold_tip"]) else None,
            "corr_vix": round(float(r["corr_gold_vix"]), 2) if not np.isnan(r["corr_gold_vix"]) else None,
        })

    print("[4/4] 写 JSON...")
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "gold_latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, "gold_history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)

    # 信号历史（每天追加一条，供前端画热力图/评分柱状图）
    sig_row = {
        "date": latest["date"],
        "score": score,
        "mode": mode,
        "dirs": [s["dir"] for s in signals],  # 5 个方向，顺序：美元/利率/避险/情绪/实物
    }
    sig_hist_path = os.path.join(DATA_DIR, "gold_signal_history.json")
    sig_hist = []
    if os.path.exists(sig_hist_path):
        try:
            with open(sig_hist_path, encoding="utf-8") as f:
                sig_hist = json.load(f)
        except Exception:
            sig_hist = []
    sig_hist = [r for r in sig_hist if r.get("date") != latest["date"]]
    sig_hist.append(sig_row)
    sig_hist.sort(key=lambda r: r["date"])
    sig_hist = sig_hist[-180:]  # 保留最近 180 天

    # 同步到 site/data/gold/（GitHub Pages 静态目录）
    with open(os.path.join(SITE_DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(SITE_DATA_DIR, "history.json"), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)
    with open(os.path.join(SITE_DATA_DIR, "signal_history.json"), "w", encoding="utf-8") as f:
        json.dump(sig_hist, f, ensure_ascii=False, indent=2)
    with open(sig_hist_path, "w", encoding="utf-8") as f:
        json.dump(sig_hist, f, ensure_ascii=False, indent=2)

    print(f"  金价 ${latest['gold']} ({latest['gold_chg']:+.2f}%)")
    print(f"  模式: {latest['mode_name']} 置信度 {latest['confidence']}")
    print(f"  综合评分: {latest['score_summary']}")
    print("done.")


if __name__ == "__main__":
    main()
