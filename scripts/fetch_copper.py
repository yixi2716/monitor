# -*- coding: utf-8 -*-
"""
铜追踪看板：Yahoo Finance 拉 COMEX铜/美元/美债/VIX/原油，Google News RSS 抓矿端新闻。
输出 data/copper/latest.json + history.json，同步到 site/data/copper/。
"""
import os
import sys
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET

if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")

import yfinance as yf
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "copper")

TICKERS = {
    "HG": "HG=F",          # COMEX 铜期货（美元/磅）
    "DXY": "DX-Y.NYB",     # 美元指数
    "VIX": "^VIX",         # 恐慌指数
    "TNX": "^TNX",         # 10Y 美债
    "CL": "CL=F",          # WTI 原油（铜油比）
    "ZQ": "ZQ=F",          # Fed 基金期货（利率预期）
    "X": "SLV",            # 白银 ETF（工业金属情绪代理）
}


def fetch_all(period="1y"):
    frames = {}
    for name, sym in TICKERS.items():
        try:
            df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
            if df.empty:
                print(f"    [warn] {sym} 空数据")
                continue
            s = df["Close"].rename(name)
            s.index = s.index.tz_localize(None).normalize()
            frames[name] = s
        except Exception as e:
            print(f"    [warn] {sym} 拉取失败: {e}")
    px = pd.concat(frames.values(), axis=1, join="inner").sort_index()
    return px


def fetch_copper_news(limit=6):
    """Google News RSS 抓铜矿/库存/关税新闻。"""
    url = ("https://news.google.com/rss/search?q=copper+price+OR+copper+mine+OR+LME+copper+inventory+when:7d"
           "&hl=en-US&gl=US&ceid=US:en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            tree = ET.fromstring(r.read())
    except Exception as e:
        print(f"    [warn] 铜新闻抓取失败: {e}")
        return []
    items = []
    for item in list(tree.iter("item"))[:limit]:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub = item.findtext("pubDate", "")
        try:
            dt = datetime.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
            date = dt.strftime("%Y-%m-%d")
        except Exception:
            date = ""
        # 标题通常是 "新闻标题 - 来源"
        parts = title.rsplit(" - ", 1)
        text = parts[0] if len(parts) == 2 else title
        src = parts[1] if len(parts) == 2 else "Google News"
        items.append({"date": date, "text": text, "src": src, "url": link})
    return items


def call_deepseek(data: dict):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return "", "未配置 DEEPSEEK_API_KEY"
    sig_lines = "\n".join(f"  - {s['name']}（{s['dir']}）：{s['text']}" for s in data.get("signals", []))
    news_lines = "\n".join(f"  - [{n['date']}] {n['text']}" for n in data.get("news", [])[:6])
    prompt = f"""你是铜宏观分析师。基于以下今日铜价看板数据和最近新闻，用中文给 250-350 字综合判断。
要求：1) 一句话定调 2) 当前主导因素 1-2 个 3) 最近新闻里值得注意的事 4) 未来一周风险点 5) 不要套话和免责声明 6) 普通人能懂

今日数据：
- COMEX铜：${data['copper']:.2f}/磅（{data['copper_chg']:+.2f}%），MA20={data['ma20']:.2f}，MA50={data['ma50']:.2f}
- DXY={data['dxy']:.2f}，VIX={data['vix']:.1f}，10Y={data['tnx']:.2f}%，WTI=${data['wti']:.2f}
- 铜油比：{data.get('cu_oil_ratio',0):.1f}
- 5条信号：
{sig_lines}
- 综合评分：{data['score']}

最近矿端/库存/关税新闻：
{news_lines}
"""
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是严谨的大宗商品分析师，擅长把数据翻译成通俗判断。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if "error" in resp:
            return "", str(resp["error"])[:300]
        text = resp["choices"][0]["message"]["content"].strip()
        return text, ""
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}"
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def main():
    print("[1/4] 拉行情...")
    px = fetch_all(period="1y")
    latest = px.iloc[-1]
    prev = px.iloc[-2]
    copper = float(latest["HG"])
    copper_chg = (copper / float(prev["HG"]) - 1) * 100

    ma20 = float(px["HG"].tail(20).mean())
    ma50 = float(px["HG"].tail(50).mean())
    dxy = float(latest["DXY"])
    vix = float(latest["VIX"])
    tnx = float(latest["TNX"])
    wti = float(latest["CL"])
    cu_oil = (copper * 2204.62) / wti if wti else 0  # 美元/磅→美元/吨，再除以油价

    # 信号
    signals = []
    # 1. 铜 vs MA20
    if copper > ma20:
        signals.append({"name": "铜价站上MA20", "dir": "bull", "text": f"${copper:.2f} > MA20 ${ma20:.2f}"})
    else:
        signals.append({"name": "铜价低于MA20", "dir": "bear", "text": f"${copper:.2f} < MA20 ${ma20:.2f}"})
    # 2. 美元
    if dxy < 100:
        signals.append({"name": "美元偏弱", "dir": "bull", "text": f"DXY {dxy:.2f} < 100，利多铜价"})
    elif dxy > 103:
        signals.append({"name": "美元偏强", "dir": "bear", "text": f"DXY {dxy:.2f} > 103，压制铜价"})
    else:
        signals.append({"name": "美元中性", "dir": "neutral", "text": f"DXY {dxy:.2f}"})
    # 3. VIX
    if vix > 25:
        signals.append({"name": "避险升温", "dir": "bear", "text": f"VIX {vix:.1f} > 25，风险偏好下降"})
    else:
        signals.append({"name": "风险偏好正常", "dir": "neutral", "text": f"VIX {vix:.1f}"})
    # 4. 铜油比
    if cu_oil > 45:
        signals.append({"name": "铜油比偏高", "dir": "bull", "text": f"铜油比 {cu_oil:.1f}，工业景气预期强"})
    elif cu_oil < 35:
        signals.append({"name": "铜油比偏低", "dir": "bear", "text": f"铜油比 {cu_oil:.1f}，工业需求偏弱"})
    else:
        signals.append({"name": "铜油比中性", "dir": "neutral", "text": f"铜油比 {cu_oil:.1f}"})
    # 5. 利率
    if tnx > 5.0:
        signals.append({"name": "实际利率高企", "dir": "bear", "text": f"10Y {tnx:.2f}%，压制金属估值"})
    else:
        signals.append({"name": "利率环境友好", "dir": "bull", "text": f"10Y {tnx:.2f}%"})

    bull = sum(1 for s in signals if s["dir"] == "bull")
    bear = sum(1 for s in signals if s["dir"] == "bear")
    score = bull - bear

    print("[2/4] 抓新闻...")
    news = fetch_copper_news()

    print("[3/4] AI 分析...")
    latest_data = {
        "date": datetime.date.today().isoformat(),
        "copper": copper, "copper_chg": copper_chg,
        "ma20": ma20, "ma50": ma50,
        "dxy": dxy, "vix": vix, "tnx": tnx, "wti": wti,
        "cu_oil_ratio": cu_oil,
        "signals": signals, "score": score,
        "news": news,
    }
    try:
        analysis, ai_err = call_deepseek(latest_data)
        latest_data["ai_error"] = ai_err
    except Exception as e:
        analysis = ""
        latest_data["ai_error"] = f"{type(e).__name__}: {e}"
    latest_data["ai_analysis"] = analysis
    latest_data["ai_date"] = latest_data["date"]

    # 历史
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    hist_path = os.path.join(SITE_DATA_DIR, "history.json")
    try:
        hist = json.load(open(hist_path, encoding="utf-8"))
    except Exception:
        hist = []
    rec = {"date": latest_data["date"], "copper": copper, "dxy": dxy, "score": score}
    if not hist:
        # 第一次跑：把拉到的 1 年历史都写进去
        hist = [{"date": idx.strftime("%Y-%m-%d"), "copper": float(row["HG"])}
                for idx, row in px.iterrows()]
    elif hist[-1]["date"] == latest_data["date"]:
        hist[-1] = rec
    else:
        hist.append(rec)
    hist = hist[-300:]

    print("[4/4] 写文件...")
    with open(os.path.join(SITE_DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest_data, f, ensure_ascii=False, indent=2)
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)

    print(f"done: copper=${copper:.2f} chg={copper_chg:+.2f}% score={score} news={len(news)}")


if __name__ == "__main__":
    main()
