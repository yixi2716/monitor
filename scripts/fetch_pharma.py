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

# Tushare token（GitHub Secrets 里配 TUSHARE_TOKEN）
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "11d712645182771648bd9467e69bfc94b7183e2c23e78148c4ffdb33")

def fetch_north_money():
    """用 Tushare 拉北向资金每日净买入（单位：万元）"""
    try:
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        today = datetime.date.today().strftime("%Y%m%d")
        week_ago = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
        df = pro.moneyflow_hsgt(start_date=week_ago, end_date=today)
        if df is not None and len(df) > 0:
            latest = df.iloc[0]
            return {
                "north_money": float(latest["north_money"]),  # 北向净买入（万元）
                "north_date": latest["trade_date"],
            }
    except Exception as e:
        print(f"  [warn] 北向资金拉取失败: {e}")
    return {"north_money": None, "north_date": ""}

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
    "hsi_health": "^HSI",       # 恒生指数（代理，000012.HK已退市）
    "tnx": "^TNX",               # 10Y美债
    "usdcny": "CNY=X",           # 人民币汇率
}


def fetch_news():
    from urllib.parse import quote
    q = quote("医药 OR 创新药 OR 集采 OR 医保局 OR 药监局 OR CXO when:3d")
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
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
        return "", "未配置 DEEPSEEK_API_KEY", []
    news_lines = "\n".join(f"  - [{n['date']}] {n['text']}" for n in data.get("news", [])[:8])
    prompt = f"""请作为医药板块分析师，基于以下数据对今日A股医药行业进行跟踪分析，并给出多时间维度预测。

【核心数据】
- 沪深300：{data.get('hs300','?')}（{data.get('hs300_chg',0):+.2f}%）
- 医药ETF：{data.get('med_etf','?')}（{data.get('med_etf_chg',0):+.2f}%）
- 创新药ETF：{data.get('inn_etf','?')}（{data.get('inn_etf_chg',0):+.2f}%）
- CXO医疗ETF：{data.get('cxo_etf','?')}（{data.get('cxo_etf_chg',0):+.2f}%）
- 中药ETF：{data.get('tcm_etf','?')}（{data.get('tcm_etf_chg',0):+.2f}%）
- 医疗器械ETF：{data.get('meddev_etf','?')}（{data.get('meddev_etf_chg',0):+.2f}%）
- 恒生医疗：{data.get('hsi_health','?')}（{data.get('hsi_health_chg',0):+.2f}%）
- 10Y美债：{data.get('tnx','?')}%
- 美元/人民币：{data.get('usdcny','?')}
- 医药相对沪深300超额：{data.get('excess',0):+.2f}%

【当日新闻】
{news_lines}

【分析要求】
1. 涨跌归因：政策/事件/利率/大盘贝塔？领涨子板块逻辑
2. 子板块结构分化分析
3. 港股联动 + 美债利率影响
4. 政策扫描
5. 情绪判断

【输出格式】
先给 200 字综合分析，然后用 JSON 格式输出以下预测（不要加其他文字）：
```json
{{
  "1d": "明日方向: 涨/跌/震荡, 概率60%",
  "1w": "一周涨跌幅区间: -2%~+3%",
  "1m": "一月目标区间: 0.51-0.54",
  "3m": "三月目标区间: 0.50-0.56",
  "6m": "半年目标区间: 0.49-0.58",
  "1y": "一年目标区间: 0.48-0.62",
  "key_logic": "核心逻辑一句话"
}}
```
预测基于医药ETF(512010)当前价 {data.get('med_etf','?')}。"""
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是严谨的医药行业分析师。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3, "max_tokens": 800,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = resp["choices"][0]["message"]["content"].strip()
        # 提取 JSON 预测
        predictions = []
        import re
        m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                pred = json.loads(m.group(1))
                today = datetime.date.today().isoformat()
                base_price = data.get("med_etf", 0)
                horizons = [("1d", 1), ("1w", 7), ("1m", 30), ("3m", 90), ("6m", 180), ("1y", 365)]
                for h, days in horizons:
                    predictions.append({
                        "predict_date": today,
                        "horizon": h,
                        "days": days,
                        "base_price": base_price,
                        "text": pred.get(h, ""),
                        "key_logic": pred.get("key_logic", ""),
                        "verified": False,
                        "verify_date": None,
                        "actual_price": None,
                        "hit": None,
                    })
            except Exception as e:
                print(f"  [warn] 预测JSON解析失败: {e}")
        # 去掉 JSON 部分作为分析文本
        analysis = re.sub(r'```json.*?```', '', text, flags=re.DOTALL).strip()
        return analysis, "", predictions
    except Exception as e:
        return "", str(e)[:200], []


def verify_predictions(etf_price):
    """检查到期的预测，验证准确率"""
    pred_file = os.path.join(SITE_DATA_DIR, "predictions.json")
    if not os.path.exists(pred_file):
        return []
    with open(pred_file, "r", encoding="utf-8") as f:
        preds = json.load(f)
    today = datetime.date.today()
    newly_verified = 0
    for p in preds:
        if p.get("verified"):
            continue
        pred_date = datetime.date.fromisoformat(p["predict_date"])
        due = pred_date + datetime.timedelta(days=p["days"])
        if due <= today:
            p["verified"] = True
            p["verify_date"] = today.isoformat()
            p["actual_price"] = etf_price
            # 判断方向：从预测文本里提取"涨/跌/震荡"
            txt = p.get("text", "")
            base = p.get("base_price", 0)
            if base > 0:
                chg = (etf_price / base - 1) * 100
                if "涨" in txt and chg > 0.5:
                    p["hit"] = True
                elif "跌" in txt and chg < -0.5:
                    p["hit"] = True
                elif "震荡" in txt and abs(chg) <= 0.5:
                    p["hit"] = True
                else:
                    p["hit"] = False
                p["actual_chg"] = round(chg, 2)
                newly_verified += 1
    if newly_verified:
        with open(pred_file, "w", encoding="utf-8") as f:
            json.dump(preds, f, ensure_ascii=False, indent=2)
        print(f"  验证了 {newly_verified} 条预测")
    return preds


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

    # Tushare 北向资金
    print("[1.5/4] 拉北向资金...")
    nm = fetch_north_money()
    data.update(nm)

    print("[2/4] 抓新闻...")
    data["news"] = fetch_news()
    print(f"  {len(data['news'])} 条新闻")

    print("[3/4] AI分析+预测...")
    all_preds = []
    pred_file = os.path.join(SITE_DATA_DIR, "predictions.json")
    # 先验证到期预测
    etf_price = data.get("med_etf", 0)
    if etf_price > 0:
        all_preds = verify_predictions(etf_price)
    # AI 分析和预测改为前端手动触发，自动跑不调 API 省 token
    data["ai_analysis"] = ""
    data["ai_error"] = "未自动生成，点击按钮手动生成"
    # 保留已有的预测记录，不生成新预测
    pred_file = os.path.join(SITE_DATA_DIR, "predictions.json")
    try:
        with open(pred_file, "r", encoding="utf-8") as f:
            all_preds = json.load(f)
    except Exception:
        all_preds = []
    except Exception as e:
        data["ai_error"] = str(e)

    print("[4/4] 写文件...")
    # 把所有 NaN 替换成 None，否则 JSON 非法
    import math
    def clean_nan(obj):
        if isinstance(obj, dict):
            return {k: clean_nan(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_nan(v) for v in obj]
        elif isinstance(obj, float) and math.isnan(obj):
            return None
        return obj
    data = clean_nan(data)
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    import shutil
    shutil.copy(os.path.join(DATA_DIR, "latest.json"), os.path.join(SITE_DATA_DIR, "latest.json"))
    print(f"done: 医药ETF {data['med_etf']} ({data['med_etf_chg']:+.2f}%)")


if __name__ == "__main__":
    main()
