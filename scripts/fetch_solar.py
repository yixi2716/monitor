# -*- coding: utf-8 -*-
"""光伏看板 · 日频数据管道。

输出 site/data/solar/：
- latest.json        当日行情快照（ETF/个股/破净比例/成交占比/回撤/新闻）
- history.json       1年日线（图表 + MA20/超额计算）
- valuation.json     位置灯：灯⑥破净比例 + 灯⑦成交占比分位
- position_history.json  破净比例/成交占比逐日积累（分位与历史曲线）
- manual.json        从 config/solar_manual.json 复制（产业价格 + 公司先行指标）

取数（全部 Tushare，美国 runner 实测可达；不加 akshare 国内源，规避挂死风险）：
- 指数/ETF：index_daily(000300) + fund_daily(515790/516160/159566)
- 个股：daily（7 只代表股，算 MA20/广度）
- 灯⑥：daily_basic 全市场单日 PB，过滤光伏成分股池 → PB<1 家数 ÷ 总数
- 灯⑦：daily 全市场单日成交额，光伏池 Σamount ÷ 全市场 Σamount
- 宏观（10Y美债/汇率）：不重复抓取，直接复用 site/data/pharma/history.json 的
  tnx/usdcny 列（两页共享同源数据，铁律）

token：环境变量 TUSHARE_TOKEN，缺省时回落 fetch_pharma 同款（工作流免配 secret 也能跑）。
"""
import os
import sys
import json
import signal
import datetime
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "solar")
CONFIG_PATH = os.path.join(ROOT, "config", "solar_manual.json")
PHARMA_HISTORY = os.path.join(ROOT, "site", "data", "pharma", "history.json")
os.makedirs(SITE_DATA_DIR, exist_ok=True)

HARD_TIMEOUT = 420  # 与 fetch_daily 同款硬保险

TUSHARE_TOKEN = os.environ.get(
    "TUSHARE_TOKEN", "11d712645182771648bd9467e69bfc94b7183e2c23e78148c4ffdb33")

# 行情标的（与 solar_core.js STOCK_KEYS 对齐）
ETF_MAP = {
    "solar_etf": "515790.SH",      # 光伏ETF（华泰柏瑞中证光伏产业）
    "newenergy_etf": "516160.SH",  # 新能源ETF（南方中证新能源）
    "storage_etf": "159566.SZ",    # 储能ETF（易方达国证储能电池）
}
INDEX_MAP = {"hs300": "000300.SH"}
STOCKS = {
    "tongwei": "600438.SH",   # 通威股份（硅料）
    "zhonghuan": "002129.SZ", # TCL中环（硅片）
    "junda": "002865.SZ",     # 钧达股份（电池）
    "longi": "601012.SH",     # 隆基绿能（组件）
    "flat": "601865.SH",      # 福莱特（玻璃）
    "jiejia": "300724.SZ",    # 捷佳伟创（设备）
    "sungrow": "300274.SZ",   # 阳光电源（逆变器）
}

# 光伏产业链 A 股成分池（手工维护，约季度核对一次；用于破净比例与成交占比）
SOLAR_POOL = [
    "600438.SH", "688303.SH",                    # 硅料：通威、大全
    "002129.SZ", "603688.SH",                    # 硅片：中环、石英股份(坩埚)
    "002459.SZ", "688599.SH", "688223.SH", "688472.SH", "300118.SZ", "601012.SH",  # 组件：晶澳/天合/晶科/阿特斯/东方日升/隆基
    "600732.SH", "002865.SZ",                    # 电池：爱旭、钧达
    "300274.SZ", "300763.SZ", "688390.SH", "605117.SH", "688032.SH", "688348.SH",  # 逆变器：阳光/锦浪/固德威/德业/禾迈/昱能
    "601865.SH", "002623.SZ", "600586.SH",       # 玻璃：福莱特、亚玛顿、金晶
    "300724.SZ", "300751.SZ", "688516.SH", "603396.SH", "688556.SH",  # 设备：捷佳/迈为/奥特维/金辰/高测
    "603806.SH", "688680.SH", "603212.SH",       # 胶膜：福斯特、海优新材、赛伍技术
    "688503.SH",                                   # 银浆：聚和材料
]


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(name, obj):
    with open(os.path.join(SITE_DATA_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  写 site/data/solar/{name}")


def pct_rank(series, value):
    s = [v for v in series if v is not None]
    if len(s) < 30 or value is None:
        return None
    return round(sum(1 for v in s if v < value) / len(s), 4)


def fetch_news():
    from urllib.parse import quote
    q = quote("光伏 OR 多晶硅 OR 硅料 OR 组件 OR 硅片 when:3d")
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


def _main():
    import pandas as pd
    import tushare as ts

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    end = datetime.date.today().strftime("%Y%m%d")
    start_1y = (datetime.date.today() - datetime.timedelta(days=370)).strftime("%Y%m%d")
    start_40d = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y%m%d")

    print("[1/6] 拉指数/ETF/个股日线...")
    frames = {}

    def add_series(name, dates, closes):
        s = pd.Series(closes.astype(float).values,
                      index=pd.to_datetime(dates, format="%Y%m%d"), name=name)
        frames[name] = s

    try:
        df = pro.index_daily(ts_code=INDEX_MAP["hs300"], start_date=start_1y, end_date=end)
        df = df.sort_values("trade_date")
        add_series("hs300", df["trade_date"], df["close"])
        last_trade = str(df["trade_date"].iloc[-1])
        print(f"  hs300: {len(df)} 条, 最后交易日 {last_trade}")
    except Exception as e:
        print(f"  [warn] hs300 失败: {e}")
        last_trade = None

    for name, code in ETF_MAP.items():
        try:
            df = None
            for attempt in range(3):
                df = pro.fund_daily(ts_code=code, start_date=start_1y, end_date=end)
                if df is not None and len(df) > 0:
                    break
                print(f"  [warn] {code} 空(第{attempt+1}次)，1.5s后重试")
                __import__("time").sleep(1.5)
            if df is None or len(df) == 0:
                print(f"  [warn] {code} 重试后仍为空，跳过")
                continue
            df = df.sort_values("trade_date")
            add_series(name, df["trade_date"], df["close"])
            print(f"  {name}({code}): {len(df)} 条")
        except Exception as e:
            print(f"  [warn] {name} 失败: {e}")
        __import__("time").sleep(0.5)

    try:
        codes = ",".join(STOCKS.values())
        df = pro.daily(ts_code=codes, start_date=start_1y, end_date=end)
        rev = {v: k for k, v in STOCKS.items()}
        for code, grp in df.groupby("ts_code"):
            grp = grp.sort_values("trade_date")
            add_series(rev[code], grp["trade_date"], grp["close"])
        print(f"  个股: {df['ts_code'].nunique()} 只")
    except Exception as e:
        print(f"  [warn] 个股日线失败: {e}")

    if not frames:
        print("[fatal] 行情全部失败，保留旧数据")
        return

    px = pd.concat(frames.values(), axis=1, join="outer").sort_index()
    # 宏观复用医药页数据（同源共享，不重复请求）
    print("[2/6] 复用医药页宏观数据(tnx/usdcny)...")
    ph = load_json(PHARMA_HISTORY, [])
    macro = {r["date"]: r for r in ph if r.get("tnx") is not None or r.get("usdcny") is not None}
    px = px.tz_localize(None) if getattr(px.index, "tz", None) is not None else px
    px.index = px.index.normalize()
    px = px[~px.index.duplicated(keep="last")]
    tnx_col, usdcny_col = [], []
    for d in px.index:
        rec = macro.get(d.strftime("%Y-%m-%d"), {})
        tnx_col.append(rec.get("tnx"))
        usdcny_col.append(rec.get("usdcny"))
    px["tnx"] = tnx_col
    px["usdcny"] = usdcny_col

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

    print("[3/6] 灯⑥ 破净比例 + 灯⑦ 成交占比...")
    pb_ratio = pool_n = pb_date = None
    turnover_ratio = to_date = None
    if last_trade:
        # 灯⑥：全市场 daily_basic 单日 PB → 池内 PB<1 比例
        try:
            b = pro.daily_basic(trade_date=last_trade, fields="ts_code,pb")
            pool = b[b["ts_code"].isin(SOLAR_POOL)]
            pool = pool.dropna(subset=["pb"])
            pool_n = len(pool)
            if pool_n > 0:
                pb_ratio = round(float((pool["pb"] < 1).sum() / pool_n), 4)
                pb_date = last_trade
            print(f"  破净: {pb_ratio}（池 {pool_n} 只, {last_trade}）")
        except Exception as e:
            print(f"  [warn] daily_basic 失败: {e}")
        # 灯⑦：全市场成交额 → 池内 Σamount ÷ 全市场 Σamount
        try:
            d = pro.daily(trade_date=last_trade,
                          fields="ts_code,amount")
            tot = d["amount"].sum()
            sub = d[d["ts_code"].isin(SOLAR_POOL)]["amount"].sum()
            if tot > 0:
                turnover_ratio = round(float(sub / tot) * 100, 3)  # %
                to_date = last_trade
            print(f"  成交占比: {turnover_ratio}%")
        except Exception as e:
            print(f"  [warn] 成交额失败: {e}")

    print("[4/6] 位置历史积累 + 分位...")
    pos_hist = load_json(os.path.join(SITE_DATA_DIR, "position_history.json"), [])
    rec_date = datetime.datetime.strptime(last_trade, "%Y%m%d").strftime("%Y-%m-%d") if last_trade else datetime.date.today().isoformat()
    if pb_ratio is not None or turnover_ratio is not None:
        merged = {r["date"]: r for r in pos_hist}
        cur = merged.get(rec_date, {"date": rec_date})
        if pb_ratio is not None:
            cur["pb_ratio"] = pb_ratio
        if turnover_ratio is not None:
            cur["turnover_ratio"] = turnover_ratio
        merged[rec_date] = cur
        pos_hist = sorted(merged.values(), key=lambda x: x["date"])[-1500:]
        save_json("position_history.json", pos_hist)
    pb_pct = pct_rank([r.get("pb_ratio") for r in pos_hist], pb_ratio)
    to_pct = pct_rank([r.get("turnover_ratio") for r in pos_hist], turnover_ratio)

    save_json("valuation.json", {
        "date": rec_date,
        "lights": {
            "pb": {"ratio": pb_ratio, "count_lt1": int((pb_ratio or 0) * pool_n) if pb_ratio is not None and pool_n else None,
                   "pool": pool_n, "pct": pb_pct, "date": pb_date,
                   "src": f"Tushare daily_basic · 光伏池{pool_n}只 PB<1比例"},
            "turnover": {"ratio": turnover_ratio, "pct": to_pct, "date": to_date,
                         "src": "Tushare daily成交额 · 光伏池Σ÷全市场Σ"},
        },
    })

    print("[5/6] 写 latest.json / history.json...")
    solar_chg, hs_chg = chg("solar_etf"), chg("hs300")
    # 距1年最高点回撤
    sv = px["solar_etf"].dropna() if "solar_etf" in px.columns else []
    dd = None
    if len(sv) > 20:
        dd = round(1 - float(sv.iloc[-1]) / float(sv.max()), 4)

    data = {
        "date": rec_date,
        "hs300": val("hs300", 2), "hs300_chg": hs_chg,
        "solar_etf": val("solar_etf", 3), "solar_etf_chg": solar_chg,
        "newenergy_etf": val("newenergy_etf", 3), "newenergy_etf_chg": chg("newenergy_etf"),
        "storage_etf": val("storage_etf", 3), "storage_etf_chg": chg("storage_etf"),
        "tnx": val("tnx", 2), "usdcny": val("usdcny", 4),
        "excess": round(solar_chg - hs_chg, 2) if solar_chg is not None and hs_chg is not None else None,
        "dd_from_high": dd,
        "pb_ratio": pb_ratio, "turnover_ratio": turnover_ratio,
        "stocks": {k: {"close": val(k, 2), "chg": chg(k)} for k in STOCKS},
        "news": fetch_news(),
        "ai_analysis": "",
        "ai_error": "未自动生成，点击按钮手动生成",
    }

    # history.json（1年日线，全量重写 + 与旧字段级合并，同 fetch_pharma 保护）
    hist_path = os.path.join(SITE_DATA_DIR, "history.json")
    old_hist = load_json(hist_path, [])
    merged = {r["date"]: r for r in old_hist}
    for idx, row in px.iterrows():
        r = {"date": idx.strftime("%Y-%m-%d")}
        for k in list(ETF_MAP) + list(STOCKS) + ["hs300", "tnx", "usdcny"]:
            v = row.get(k)
            r[k] = float(v) if pd.notna(v) else None
        o = merged.get(r["date"])
        if o:
            for k, v in r.items():
                if v is None and o.get(k) is not None:
                    r[k] = o[k]
        merged[r["date"]] = r
    core = ["hs300", "solar_etf"]
    hist = sorted((r for d, r in merged.items() if any(r.get(k) is not None for k in core)),
                  key=lambda x: x["date"])[-400:]
    save_json("history.json", hist)

    # 写入保护：核心行情缺失不覆盖 latest.json
    latest_path = os.path.join(SITE_DATA_DIR, "latest.json")
    if data.get("solar_etf") is None or data.get("hs300") is None:
        print(f"  [skip] 行情缺失，latest.json 保留旧数据")
    else:
        if not data.get("news"):
            old = load_json(latest_path, {})
            if old.get("news"):
                data["news"] = old["news"]
                print(f"  [keep] 新闻为空，保留旧新闻 {len(old['news'])} 条")
        save_json("latest.json", data)

    print("[6/6] 同步手工产业数据...")
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            save_json("manual.json", json.load(f))
    else:
        print("  [warn] config/solar_manual.json 不存在，跳过")

    print(f"done: 光伏ETF {data.get('solar_etf')} ({solar_chg:+.2f}%) 破净 {pb_ratio} 成交占比 {turnover_ratio}%")


def main():
    has_alarm = hasattr(signal, "SIGALRM")
    if has_alarm:
        def _handler(signum, frame):
            raise TimeoutError(f"光伏数据抓取超过 {HARD_TIMEOUT}s，强制结束（保留旧数据）")
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(HARD_TIMEOUT)
    try:
        _main()
    except TimeoutError as e:
        print(f"[fatal] {e}")
    finally:
        if has_alarm:
            signal.alarm(0)


if __name__ == "__main__":
    main()
