# -*- coding: utf-8 -*-
"""
医药板块监测：从 Yahoo Finance 拉医药相关 ETF/指数，抓新闻，生成 AI 分析。
输出 data/pharma/latest.json + data/pharma/history.json。
"""
import os, sys, json, time, datetime, urllib.request, xml.etree.ElementTree as ET

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
    "hs_inn_etf": "513120.SS",  # 港股创新药ETF（广发，跟踪中证香港创新药指数，18A主力）
    "tnx": "^TNX",               # 10Y美债
    "usdcny": "CNY=X",           # 人民币汇率
}


def fetch_history():
    """拉取近1年日线，用于页面图表（每日全量重写，幂等）。
    A股标的优先走 tushare（稳定），Yahoo 仅作兜底；港美标的走 Yahoo。"""
    frames = {}
    for name, sym in TICKERS.items():
        s = None
        if name in TUSHARE_MAP:
            # A股：tushare 优先
            try:
                s = fetch_tushare_daily(name)
                if s is not None:
                    print(f"  [ok] history {name} tushare ({len(s)} 条)")
            except Exception as e:
                print(f"  [warn] history {name} tushare 失败: {str(e)[:60]}")
                s = None
        if s is None or len(s) < 100:
            # Yahoo 兜底（港美标的直接走这里）
            s = None
            for attempt in range(3):
                try:
                    df = yf.Ticker(sym).history(period="1y", interval="1d", auto_adjust=False)
                    if df.empty:
                        print(f"  [warn] history {sym} 空(第{attempt+1}次)")
                    else:
                        s = df["Close"].rename(name).dropna()
                        s.index = s.index.tz_localize(None).normalize()
                        if len(s) >= 100:
                            break
                        # Yahoo 限流时会返回只有个别行的退化数据，视为失败
                        print(f"  [warn] history {sym} 数据退化仅{len(s)}行(第{attempt+1}次)")
                        s = None
                except Exception as e:
                    print(f"  [warn] history {name} 失败(第{attempt+1}次): {str(e)[:80]}")
                time.sleep(3)
        if s is not None and len(s) > 0:
            frames[name] = s
        time.sleep(0.5)  # 温和请求，避免限流
    if not frames:
        return None
    import pandas as pd
    px = pd.concat(frames.values(), axis=1, join="outer").sort_index().round(4)
    return px


# A股标的的 tushare 兜底映射（Yahoo 限流时使用，token 见文件顶部）
TUSHARE_MAP = {
    "hs300": ("index", "000300.SH"),
    "med_etf": ("etf", "512010.SH"),
    "inn_etf": ("etf", "159992.SZ"),
    "cxo_etf": ("etf", "512170.SH"),
    "tcm_etf": ("etf", "159647.SZ"),
    "meddev_etf": ("etf", "159883.SZ"),
    "vaccine_etf": ("etf", "516160.SH"),
    "hs_inn_etf": ("etf", "513120.SH"),
}

def fetch_tushare_daily(name):
    """用 tushare 拉 A股指数/ETF 近一年日线（Yahoo 限流兜底）"""
    import pandas as pd
    import tushare as ts
    kind, code = TUSHARE_MAP[name]
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    end = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=370)).strftime("%Y%m%d")
    if kind == "index":
        df = pro.index_daily(ts_code=code, start_date=start, end_date=end)
    else:
        df = pro.fund_daily(ts_code=code, start_date=start, end_date=end)
    if df is None or len(df) == 0:
        return None
    df = df.sort_values("trade_date")
    dates = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    s = pd.Series(df["close"].astype(float).values, index=dates, name=name)
    return s


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




def main():
    print("[1/4] 拉行情...")
    frames = {}
    for name, sym in TICKERS.items():
        try:
            df = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=False)
            if df.empty:
                print(f"  [warn] {sym} 空")
                continue
            s = df["Close"].rename(name).dropna()
            if len(s) == 0:
                print(f"  [warn] {sym} 全NaN，跳过")
                continue
            s.index = s.index.tz_localize(None).normalize()
            frames[name] = s
            print(f"  {name}: {s.iloc[-1]:.2f}")
        except Exception as e:
            print(f"  [warn] {sym} 失败: {e}")
        # Yahoo 失败/限流时，A股标的走 tushare 实时兜底
        if name not in frames and name in TUSHARE_MAP:
            try:
                s = fetch_tushare_daily(name)
                if s is not None and len(s) >= 2:
                    frames[name] = s
                    print(f"  [ok] {name} 由 tushare 兜底 ({len(s)} 条)")
            except Exception as e:
                print(f"  [warn] {name} tushare 兜底失败: {str(e)[:60]}")
        time.sleep(1)  # 温和请求，避免 Yahoo 限流

    import pandas as pd
    px = pd.concat(frames.values(), axis=1, join="inner").sort_index()
    if px.empty:
        # 各 ticker 日期交集为空时退回 outer join + ffill
        px = pd.concat(frames.values(), axis=1, join="outer").sort_index()
    # 周末/假日最后一行可能是 NaN 空bar，向前填充用最近交易日收盘价
    pxf = px.ffill()
    last = pxf.iloc[-1]
    prev = pxf.iloc[-2] if len(pxf) >= 2 else last

    def val(k, nd):
        v = last.get(k)
        if k in px.columns and pd.notna(v):
            return round(float(v), nd)
        return None

    def chg(k):
        a, b = last.get(k), prev.get(k)
        if k in px.columns and pd.notna(a) and pd.notna(b) and b:
            return round((float(a) / float(b) - 1) * 100, 2)
        return None

    med_chg, hs_chg = chg("med_etf"), chg("hs300")
    data = {
        "date": datetime.date.today().isoformat(),
        "hs300": val("hs300", 2),
        "hs300_chg": hs_chg,
        "med_etf": val("med_etf", 3),
        "med_etf_chg": med_chg,
        "inn_etf": val("inn_etf", 3),
        "inn_etf_chg": chg("inn_etf"),
        "cxo_etf": val("cxo_etf", 3),
        "cxo_etf_chg": chg("cxo_etf"),
        "tcm_etf": val("tcm_etf", 3),
        "tcm_etf_chg": chg("tcm_etf"),
        "meddev_etf": val("meddev_etf", 3),
        "meddev_etf_chg": chg("meddev_etf"),
        "vaccine_etf": val("vaccine_etf", 3),
        "vaccine_etf_chg": chg("vaccine_etf"),
        "hsi_health": val("hsi_health", 2),
        "hsi_health_chg": chg("hsi_health"),
        "hs_inn_etf": val("hs_inn_etf", 3),
        "hs_inn_etf_chg": chg("hs_inn_etf"),
        "tnx": val("tnx", 2),
        "usdcny": val("usdcny", 4),
        "excess": round(med_chg - hs_chg, 2) if med_chg is not None and hs_chg is not None else None,
    }

    # Tushare 北向资金
    print("[1.5/4] 拉北向资金...")
    nm = fetch_north_money()
    data.update(nm)

    print("[2/4] 抓新闻...")
    data["news"] = fetch_news()
    print(f"  {len(data['news'])} 条新闻")

    print("[3/4] AI 分析（前端手动生成，自动跑不调 API）...")
    data["ai_analysis"] = ""
    data["ai_error"] = "未自动生成，点击按钮手动生成"

    print("[4/4] 写文件...")
    # 历史走势（1年日线，供页面图表；每日全量重写，幂等）
    hist_path = os.path.join(SITE_DATA_DIR, "history.json")
    px_hist = fetch_history()
    if px_hist is not None:
        hist = []
        for idx, row in px_hist.iterrows():
            rec = {"date": idx.strftime("%Y-%m-%d")}
            for k in TICKERS.keys():
                v = row.get(k)
                rec[k] = float(v) if pd.notna(v) else None
            hist.append(rec)
        # 保护1：核心字段全空的行直接丢弃（周末/假日/拉取失败产生的空行，避免页面显示 0）
        core_keys = ["hs300", "med_etf", "inn_etf", "hsi_health"]
        hist = [r for r in hist if any(r.get(k) is not None for k in core_keys)]
        # 保护2：与旧数据字段级合并——同一天已有字段不被 None 覆盖
        old_hist = []
        if os.path.exists(hist_path):
            try:
                with open(hist_path, "r", encoding="utf-8") as f:
                    old_hist = json.load(f)
            except Exception:
                old_hist = []
        merged = {r["date"]: r for r in old_hist}
        for r in hist:
            o = merged.get(r["date"])
            if o:
                for k, v in r.items():
                    if v is None and o.get(k) is not None:
                        r[k] = o[k]
            merged[r["date"]] = r
        # 保护3：合并后再次丢弃核心字段全空的行（清掉旧文件里的空行，如周末全 null 行）
        merged = {d: r for d, r in merged.items() if any(r.get(k) is not None for k in core_keys)}
        hist = sorted(merged.values(), key=lambda x: x["date"])[-400:]
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
        print(f"  history.json: {len(hist)} 条")
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
    import shutil
    latest_path = os.path.join(DATA_DIR, "latest.json")
    # 写入保护：核心行情缺失（周末/假日/限流）时不覆盖 latest.json，保留上一交易日数据，仅更新北向资金
    if data.get("med_etf") is None or data.get("hs300") is None:
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            if data.get("north_money") is not None:
                old["north_money"] = data["north_money"]
                old["north_date"] = data.get("north_date") or old.get("north_date", "")
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(old, f, ensure_ascii=False, indent=2)
            shutil.copy(latest_path, os.path.join(SITE_DATA_DIR, "latest.json"))
            print(f"  [skip] 行情缺失，latest.json 保留 {old.get('date')} 的数据")
        except Exception as e:
            print(f"  [warn] latest.json 保护写入失败: {e}")
    else:
        # 新闻抓取失败（网络抖动）时不清空旧新闻
        if not data.get("news") and os.path.exists(latest_path):
            try:
                with open(latest_path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if old.get("news"):
                    data["news"] = old["news"]
                    print(f"  [keep] 新闻为空，保留旧新闻 {len(old['news'])} 条")
            except Exception:
                pass
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        shutil.copy(latest_path, os.path.join(SITE_DATA_DIR, "latest.json"))
        print(f"done: 医药ETF {data['med_etf']} ({data['med_etf_chg']:+.2f}%)")


if __name__ == "__main__":
    main()
