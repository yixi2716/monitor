# -*- coding: utf-8 -*-
"""
医药板块监测：从 Yahoo Finance 拉医药相关 ETF/指数，抓新闻，生成 AI 分析。
输出 data/pharma/latest.json + data/pharma/history.json。
"""
import os, sys, json, datetime, urllib.request, xml.etree.ElementTree as ET

if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:12000")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:12000")

import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "pharma")
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "pharma")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SITE_DATA_DIR, exist_ok=True)

# 医药相关 ETF/指数（yfinance ticker）
TICKERS = {
    "hs300": "000300.SS",        # 沪深300（基准）
    "med_etf": "512010.SS",      # 易方达沪深300医药卫生ETF
    "inn_etf": "159992.SZ",      # 银华创新药ETF
    "cxo_etf": "512170.SS",      # 医疗ETF（CXO代理）
    "tcm_etf": "159647.SZ",      # 中药ETF
    "meddev_etf": "159883.SZ",   # 医疗器械ETF
    "vaccine_etf": "516160.SS",  # 疫苗ETF
    "hsi_health": "000012.HK",  # 恒生医疗保健指数
    "tnx": "^TNX",               # 10Y美债
    "usdcny": "CNY=X",           # 人民币汇率
}


def fetch_news():
    url = ("https://news.google.com/rss/search?q="
           "innovative+drug+OR+CXO+OR+pharma+OR+biotech+when:3d")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub = item.findtext("pubDate", "")
            try:
                d = datetime.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y-%m-%d")
            except Exception:
                d = pub[:16]
            items.append({"date": d, "text": title, "url": link})
        return items
    except Exception as e:
        print(f"  [warn] 新闻失败: {e}")
        return []


def call_deepseek(data):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return "", "未配置 DEEPSEEK_API_KEY"
    news_lines = "\n".join(f"  - [{n['date']}] {n['text']}" for n in data.get("news", [])[:6])
    prompt = f"""你是医药行业分析师。基于以下数据，用中文给 200-300 字综合判断。

【板块数据】
- 沪深300：{data.get('hs300','?')}（{data.get('hs300_chg',0):+.2f}%）
- 医药ETF：{data.get('med_etf','?')}（{data.get('med_etf_chg',0):+.2f}%）
- 创新药ETF：{data.get('inn_etf','?')}（{data.get('inn_etf_chg',0):+.2f}%）
- 恒生医疗：{data.get('hsi_health','?')}（{data.get('hsi_health_chg',0):+.2f}%）
- 10Y美债：{data.get('tnx','?')}%
- 人民币汇率：{data.get('usdcny','?')}
- 医药相对沪深300超额：{data.get('excess',0):+.2f}%

【最近新闻】
{news_lines}

【输出要求】
1. 今日板块涨跌归因（是大盘带动还是独立行情，哪个子板块领涨）
2. 政策/研发事件催化
3. 宏观利率和汇率对创新药/CXO的影响
4. 短期展望（偏多/偏空/震荡）+ 关键位置
5. 需关注的风险点

要求：200-300字，普通人能懂，不要套话，未获取的数据不要编造。"""
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是严谨的医药行业分析师。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3, "max_tokens": 500,
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
        return resp["choices"][0]["message"]["content"].strip(), ""
    except Exception as e:
        return "", str(e)[:200]


def main():
    print("[1/4] 拉行情...")
    frames = {}
    for name, sym in TICKERS.items():
        try:
            df = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=False)
            if df.empty:
                print(f"  [warn] {sym} 空")
                continue
            s = df["Close"].rename(name)
            s.index = s.index.tz_localize(None).normalize()
            frames[name] = s
            print(f"  {name}: {s.iloc[-1]:.2f}")
        except Exception as e:
            print(f"  [warn] {sym} 失败: {e}")

    import pandas as pd
    px = pd.concat(frames.values(), axis=1, join="inner").sort_index()
    last = px.iloc[-1]
    prev = px.iloc[-2] if len(px) >= 2 else last

    def chg(k):
        if k in px.columns and prev[k]:
            return (last[k] / prev[k] - 1) * 100
        return 0

    data = {
        "date": datetime.date.today().isoformat(),
        "hs300": round(float(last.get("hs300", 0)), 2),
        "hs300_chg": round(chg("hs300"), 2),
        "med_etf": round(float(last.get("med_etf", 0)), 3),
        "med_etf_chg": round(chg("med_etf"), 2),
        "inn_etf": round(float(last.get("inn_etf", 0)), 3),
        "inn_etf_chg": round(chg("inn_etf"), 2),
        "cxo_etf": round(float(last.get("cxo_etf", 0)), 3),
        "cxo_etf_chg": round(chg("cxo_etf"), 2),
        "tcm_etf": round(float(last.get("tcm_etf", 0)), 3),
        "tcm_etf_chg": round(chg("tcm_etf"), 2),
        "meddev_etf": round(float(last.get("meddev_etf", 0)), 3),
        "meddev_etf_chg": round(chg("meddev_etf"), 2),
        "vaccine_etf": round(float(last.get("vaccine_etf", 0)), 3),
        "vaccine_etf_chg": round(chg("vaccine_etf"), 2),
        "hsi_health": round(float(last.get("hsi_health", 0)), 2),
        "hsi_health_chg": round(chg("hsi_health"), 2),
        "tnx": round(float(last.get("tnx", 0)), 2),
        "usdcny": round(float(last.get("usdcny", 0)), 4),
        "excess": round(chg("med_etf") - chg("hs300"), 2),
    }

    print("[2/4] 抓新闻...")
    data["news"] = fetch_news()
    print(f"  {len(data['news'])} 条新闻")

    print("[3/4] AI分析...")
    try:
        analysis, err = call_deepseek(data)
        data["ai_analysis"] = analysis
        data["ai_error"] = err
    except Exception as e:
        data["ai_error"] = str(e)

    print("[4/4] 写文件...")
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    import shutil
    shutil.copy(os.path.join(DATA_DIR, "latest.json"), os.path.join(SITE_DATA_DIR, "latest.json"))
    print(f"done: 医药ETF {data['med_etf']} ({data['med_etf_chg']:+.2f}%)")


if __name__ == "__main__":
    main()
