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
    # 本地调试可 set HTTP_PROXY=http://127.0.0.1:12000 走代理；默认不设（东财/新浪/Tushare 国内直连）
    pass

import yfinance as yf
import pandas as pd
import numpy as np

try:
    import akshare as ak
    HAS_AK = True
except Exception:
    HAS_AK = False
    print("    [warn] akshare 不可用，沪铜数据跳过")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_quote import EM, em_kline, fred_series

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
    "cper": "CPER",        # 全球最大铜ETF（资金情绪）
    "copx": "COPX",        # 全球矿业ETF（铜相关）
}

# A股铜标的：走 Tushare（Yahoo 的 A股数据延迟约一天，且 inner join 会把
# 整个行情框拖回上周五——2026-10-12 事故：三只A股周五收盘被标成当天数据）
ASTOCKS = {
    "lymy": "603993.SH",   # 洛阳钼业
    "tl": "000630.SZ",     # 铜陵有色
    "jxt": "600362.SH",    # 江西铜业
}
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "").strip() \
    or "11d712645182771648bd9467e69bfc94b7183e2c23e78148c4ffdb33"


def fetch_astocks():
    """A股三只铜标的走 Tushare 日线。失败返回 None（调用方回落 Yahoo）。
    接口偶发返回空表，空结果重试3次。"""
    try:
        import time
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        end = datetime.date.today().strftime("%Y%m%d")
        start = (datetime.date.today() - datetime.timedelta(days=370)).strftime("%Y%m%d")
        df = None
        for attempt in range(3):
            df = pro.daily(ts_code=",".join(ASTOCKS.values()), start_date=start, end_date=end)
            if df is not None and len(df) > 0:
                break
            print(f"    [warn] A股标的 tushare 空(第{attempt+1}次)，2s后重试")
            time.sleep(2)
        if df is None or len(df) == 0:
            return None
        rev = {v: k for k, v in ASTOCKS.items()}
        frames = {}
        for code, grp in df.groupby("ts_code"):
            grp = grp.sort_values("trade_date")
            frames[rev[code]] = pd.Series(
                grp["close"].astype(float).values,
                index=pd.to_datetime(grp["trade_date"], format="%Y%m%d"), name=rev[code])
        return pd.concat(frames.values(), axis=1, join="outer").sort_index()
    except Exception as e:
        print(f"    [warn] A股标的 Tushare 失败，回落 Yahoo: {str(e)[:80]}")
        return None


def fetch_astocks_yahoo():
    frames = {}
    ymap = {"lymy": "603993.SS", "tl": "000630.SZ", "jxt": "600362.SS"}
    for name, sym in ymap.items():
        try:
            df = yf.Ticker(sym).history(period="1y", interval="1d", auto_adjust=False)
            if df.empty:
                continue
            s = df["Close"].rename(name)
            s.index = s.index.tz_localize(None).normalize()
            frames[name] = s
        except Exception as e:
            print(f"    [warn] A股标的 Yahoo 兜底 {sym} 失败: {e}")
    if not frames:
        return None
    return pd.concat(frames.values(), axis=1, join="outer").sort_index()


def fetch_all(period="1y"):
    """外盘行情：东财外盘主力 + FRED 宏观 为主，Yahoo 兜底/补充。
    Yahoo 对 GitHub Actions 的 IP 频繁 429（2026-10-13 起铜数据停更的根因），
    不再作为唯一来源；HG 全部失败时直接退出并报 ::error::。"""
    frames = {}
    # 1) 东财外盘主力连续合约
    em_map = {"HG": EM["HG"], "DXY": EM["DXY"], "CL": EM["CL"], "X": EM["SI"]}
    for name, secid in em_map.items():
        s = em_kline(secid)
        if s is not None:
            frames[name] = s.rename(name)
            print(f"    [em] {name:3s} 最新 {s.index[-1].strftime('%Y-%m-%d')} = {float(s.iloc[-1]):.2f}")
        else:
            print(f"    [warn] 东财 {name}({secid}) 失败，转 Yahoo 兜底")
    # 2) FRED 宏观（VIX / 10Y美债），DGS10 即百分数值，与旧 ^TNX 口径一致
    for name, sid in [("VIX", "VIXCLS"), ("TNX", "DGS10")]:
        s = fred_series(sid)
        if s is not None:
            frames[name] = s.rename(name)
            print(f"    [fred] {name} 最新 {s.index[-1].strftime('%Y-%m-%d')} = {float(s.iloc[-1]):.2f}")
        else:
            print(f"    [warn] FRED {sid} 失败，转 Yahoo 兜底")
    # 3) Yahoo：ETF/利率期货补充 + 上面失败品种兜底
    for name, sym in TICKERS.items():
        if name in frames:
            continue
        try:
            df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
            if df.empty:
                print(f"    [warn] Yahoo {sym} 空数据")
                continue
            s = df["Close"].rename(name)
            s.index = s.index.tz_localize(None).normalize()
            frames[name] = s
        except Exception as e:
            print(f"    [warn] Yahoo {sym} 拉取失败: {str(e)[:60]}")
    if "HG" not in frames:
        print("::error:: COMEX铜所有数据源（东财/Yahoo）均失败，本次铜数据未更新")
        raise SystemExit(1)
    if "DXY" not in frames:
        print("::warning:: 美元指数缺失，相关信号降级")
    # outer join + ffill：单标的数据延迟不再拖垮整个行情框（inner join 的旧坑）
    px = pd.concat(frames.values(), axis=1, join="outer").sort_index().ffill()
    return px


def fetch_copper_news(limit=6):
    """Google News RSS 抓铜矿/库存/关税新闻。"""
    url = ("https://news.google.com/rss/search?q=copper+price+OR+copper+mine+OR+LME+copper+inventory+OR+Section+232+copper+tariff+when:7d"
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
    news_lines = "\n".join(f"  - [{n['date']}] {n['text']}" for n in data.get("news", [])[:8])

    lme_stock_str = f"{data['lme_stock']:,} 吨" if data.get("lme_stock") else "未获取"
    shfe_stock_str = f"{data['shfe_stock']:,} 吨（日变{data.get('shfe_stock_chg',0):+d}）" if data.get("shfe_stock") else "未获取"
    shfe_cu_str = f"¥{data['shfe_cu']:,.0f}/吨" if data.get("shfe_cu") else "未获取"
    ratio_str = f"{data['shfe_lme_ratio']:.3f}" if data.get("shfe_lme_ratio") else "未获取"

    prompt = f"""你是大宗商品分析师，每日跟踪铜市场。基于以下数据，按要求输出。

【核心数据】
- COMEX铜：${data['copper']:.2f}/磅（{data['copper_chg']:+.2f}%），MA20=${data['ma20']:.2f}，MA50=${data['ma50']:.2f}
- 沪铜主力：{shfe_cu_str}
- 沪伦比值：{ratio_str}（>1 进口有利）
- DXY美元指数：{data['dxy']:.2f}
- VIX：{data['vix']:.1f}，10Y美债：{data['tnx']:.2f}%
- WTI原油：${data['wti']:.2f}，铜油比：{data.get('cu_oil_ratio',0):.1f}
- LME库存：{lme_stock_str}（{data.get('lme_stock_date','')}）
- 沪铜库存：{shfe_stock_str}（{data.get('shfe_stock_date','')}）
- LME Cash-3M升贴水：未获取
- 铜精矿TC：未获取
- CFTC铜非商业净持仓：未获取

【每日信号】
{sig_lines}

【最近新闻】
{news_lines}

【输出要求】
1. 涨跌归因：拆解今日铜价变动主要由什么驱动（宏观美元/利率、供给、需求预期、或美国232铜关税政策）
2. 库存与价差：结合库存和升贴水判断当前是紧张还是宽松格局
3. 内外盘：沪伦比值说明内外盘强弱，特别注意美国232关税对COMEX溢价的影响
4. 资金信号：基于已有信号判断趋势是否健康
5. 短期展望：偏多/偏空/震荡 + 关键价位
6. 风险点：1-2条（包含关税政策变化风险）

要求：200-300字，普通人能懂，不要套话和免责声明，未获取的数据不要编造。"""
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
    ax = fetch_astocks()
    if ax is None:
        ax = fetch_astocks_yahoo()
    if ax is not None:
        px = px.join(ax, how="outer").sort_index().ffill()
        print(f"    A股标的: 已并入 tushare 日线 {ax.index[-1].strftime('%Y-%m-%d')}")
    latest = px.iloc[-1]
    prev = px.iloc[-2]
    copper = float(latest["HG"])
    copper_chg = (copper / float(prev["HG"]) - 1) * 100

    ma20 = float(px["HG"].tail(20).mean())
    ma50 = float(px["HG"].tail(50).mean())

    # 宏观单项缺失（如 FRED/Yahoo 同时不通）时沿用上次值，不让整个看板停更
    prev_file = os.path.join(SITE_DATA_DIR, "latest.json")
    old = {}
    if os.path.exists(prev_file):
        try:
            old = json.load(open(prev_file, encoding="utf-8"))
        except Exception:
            old = {}
    def _field(col, old_key):
        v = latest.get(col)
        if v is None or pd.isna(v):
            ov = old.get(old_key)
            if ov is not None:
                print(f"    [warn] {col} 缺失，沿用上次值 {ov}")
                return float(ov)
            print(f"::warning:: {col} 无数据且无历史值，记 0")
            return 0.0
        return float(v)

    dxy = _field("DXY", "dxy")
    vix = _field("VIX", "vix")
    tnx = _field("TNX", "tnx")
    wti = _field("CL", "wti")
    cu_oil = (copper * 2204.62) / wti if wti else 0  # 美元/磅→美元/吨，再除以油价

    # 沪铜主力（akshare 新浪）
    shfe_cu = None
    shfe_cu_date = None
    lme_stock = None
    lme_stock_date = None
    shfe_stock = None
    shfe_stock_chg = None
    shfe_stock_date = None
    if HAS_AK:
        try:
            df_cu = ak.futures_zh_daily_sina(symbol="CU0")
            last_cu = df_cu.iloc[-1]
            shfe_cu = round(float(last_cu["close"]), 2)
            shfe_cu_date = str(last_cu["date"])
            print(f"    沪铜主力: {shfe_cu} 元/吨 ({shfe_cu_date})")
        except Exception as e:
            print(f"    [warn] 沪铜拉取失败: {e}")
        try:
            df_lme = ak.macro_euro_lme_stock()
            last_lme = df_lme.iloc[-1]
            lme_stock = int(last_lme["铜-库存"])
            lme_stock_date = str(last_lme["日期"])
            print(f"    LME铜库存: {lme_stock:,} 吨 ({lme_stock_date})")
        except Exception as e:
            print(f"    [warn] LME库存拉取失败: {e}")
        try:
            df_shfe = ak.futures_inventory_em(symbol="沪铜")
            last_shfe = df_shfe.iloc[-1]
            shfe_stock = int(last_shfe["库存"])
            shfe_stock_chg = int(last_shfe["增减"])
            shfe_stock_date = str(last_shfe["日期"])
            print(f"    沪铜库存: {shfe_stock:,} 吨 ({shfe_stock_date})")
        except Exception as e:
            print(f"    [warn] 沪铜库存拉取失败: {e}")

    # 沪伦比值 = 沪铜(元/吨) / (COMEX铜 美元/磅 × 2204.62 磅/吨) × 汇率
    # 简化：用 DXY 反推汇率近似，或直接用 7.2 汇率
    usd_cny = 7.2  # 近似汇率
    comex_per_ton = copper * 2204.62  # 美元/吨
    shfe_lme_ratio = round(shfe_cu / (comex_per_ton * usd_cny), 3) if shfe_cu else None

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
    # 提取铜股数据（A股标的已并入 px，取各自最近两个有效值）
    stock_data = {}
    for k in ["lymy", "tl", "jxt"]:
        s = px[k].dropna() if k in px.columns else []
        if len(s) >= 2:
            stock_data[k] = round(float(s.iloc[-1]), 2)
            stock_data[k+"_chg"] = round((float(s.iloc[-1]) / float(s.iloc[-2]) - 1) * 100, 2)
        else:
            stock_data[k] = 0
            stock_data[k+"_chg"] = 0

    latest_data = {
        "date": datetime.date.today().isoformat(),
        "copper": copper, "copper_chg": copper_chg,
        "ma20": ma20, "ma50": ma50,
        "dxy": dxy, "vix": vix, "tnx": tnx, "wti": wti,
        "cu_oil_ratio": cu_oil,
        "shfe_cu": shfe_cu, "shfe_cu_date": shfe_cu_date,
        "shfe_lme_ratio": shfe_lme_ratio,
        "lme_stock": lme_stock, "lme_stock_date": lme_stock_date,
        "shfe_stock": shfe_stock, "shfe_stock_chg": shfe_stock_chg, "shfe_stock_date": shfe_stock_date,
        "lymy": stock_data["lymy"], "lymy_chg": stock_data["lymy_chg"],
        "tl": stock_data["tl"], "tl_chg": stock_data["tl_chg"],
        "jxt": stock_data["jxt"], "jxt_chg": stock_data["jxt_chg"],
        "cper": round(float(px["cper"].iloc[-1]), 2) if "cper" in px.columns else 0,
        "cper_chg": round((px["cper"].iloc[-1]/px["cper"].iloc[-2]-1)*100, 2) if "cper" in px.columns and len(px)>=2 else 0,
        "copx": round(float(px["copx"].iloc[-1]), 2) if "copx" in px.columns else 0,
        "copx_chg": round((px["copx"].iloc[-1]/px["copx"].iloc[-2]-1)*100, 2) if "copx" in px.columns and len(px)>=2 else 0,
        "signals": signals, "score": score,
        "news": news,
    }
    # AI 分析改为前端手动触发，自动跑不调 API 省 token
    latest_data["ai_analysis"] = ""
    latest_data["ai_error"] = "未自动生成，点击按钮手动生成"
    latest_data["ai_date"] = latest_data["date"]

    # 历史
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    hist_path = os.path.join(SITE_DATA_DIR, "history.json")
    try:
        hist = json.load(open(hist_path, encoding="utf-8"))
    except Exception:
        hist = []

    # 第一次跑：把拉到的历史都写进去
    if not hist:
        hist = []
        for idx, row in px.iterrows():
            rec = {"date": idx.strftime("%Y-%m-%d")}
            for k in ["HG", "DXY", "cper", "copx", "lymy", "tl", "jxt"]:
                if k in px.columns and pd.notna(row[k]):
                    # HG 统一存为 copper，与每日追加分支的字段名保持一致
                    rec["copper" if k == "HG" else k.lower()] = float(row[k])
            hist.append(rec)
    else:
        # 追加今天的数据
        rec = {"date": latest_data["date"], "copper": copper, "dxy": dxy, "score": score}
        for k in ["cper", "copx", "lymy", "tl", "jxt"]:
            if k in px.columns:
                s = px[k].dropna()
                if len(s):
                    rec[k] = float(s.iloc[-1])
        if hist[-1]["date"] == latest_data["date"]:
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
