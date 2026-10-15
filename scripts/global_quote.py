# -*- coding: utf-8 -*-
"""
外盘行情公共取数模块：东方财富外盘期货 + FRED 宏观序列。
背景：Yahoo Finance 对数据中心 IP（GitHub Actions）频繁 429 限流，
导致 fetch_copper / fetch_gold 整个崩溃、数据长期停滞（2026-10-13 事故）。
东财外盘期货(push2his)对 UA/TLS 指纹敏感，Python urllib 会被掐连接，
统一走 curl 子进程；FRED 免 key 直链 CSV。
"""
import subprocess
import datetime
import pandas as pd

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _curl(url, timeout=20, tries=3):
    """curl 子进程 GET，返回文本；失败返回 None。"""
    for i in range(tries):
        try:
            out = subprocess.run(
                ["curl", "-s", "-m", str(timeout), "-A", UA, url],
                capture_output=True, timeout=timeout + 5)
            txt = out.stdout.decode("utf-8", "ignore").strip()
            if txt and not txt.startswith("<"):
                return txt
        except Exception:
            pass
    return None


def em_kline(secid, days=370):
    """东财外盘期货日K，返回 date-indexed close Series；失败返回 None。
    secid 形如 '101.HG00Y'（101=COMEX 102=NYMEX 100=全球指数）。"""
    beg = (datetime.date.today() - datetime.timedelta(days=days + 40)).strftime("%Y%m%d")
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=" + secid
           + "&fields1=f1,f2&fields2=f51,f53&klt=101&fqt=0&beg=" + beg + "&end=20500101")
    txt = _curl(url)
    if not txt:
        return None
    try:
        import json
        data = json.loads(txt).get("data") or {}
        klines = data.get("klines") or []
        if not klines:
            return None
        rows = [k.split(",") for k in klines]
        s = pd.Series([float(r[1]) for r in rows],
                      index=pd.to_datetime([r[0] for r in rows]), name=secid)
        return s[~s.index.duplicated(keep="last")].sort_index()
    except Exception:
        return None


def fred_series(series_id, days=370):
    """FRED 免 key 日频 CSV（如 VIXCLS / DGS10），失败返回 None。"""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series_id
    txt = _curl(url, timeout=25)
    if not txt or not txt.startswith("DATE"):
        return None
    try:
        from io import StringIO
        df = pd.read_csv(StringIO(txt), na_values=".")
        col = [c for c in df.columns if c != "DATE"][0]
        df["DATE"] = pd.to_datetime(df["DATE"])
        cutoff = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=days + 40))
        df = df[df["DATE"] >= cutoff]
        s = pd.Series(df[col].astype(float).values, index=df["DATE"], name=series_id)
        return s.dropna()
    except Exception:
        return None


# 常用品种映射（东财外盘）
EM = {
    "HG": "101.HG00Y",    # COMEX 铜（美元/磅）
    "GC": "101.GC00Y",    # COMEX 黄金
    "SI": "101.SI00Y",    # COMEX 白银
    "CL": "102.CL00Y",    # NYMEX WTI 原油
    "DXY": "100.UDI",     # 美元指数
    "SPX": "100.SPX",     # 标普500
}
