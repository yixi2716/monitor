# -*- coding: utf-8 -*-
"""A股生猪板块标的日线（供"股价 vs 猪价"联动图与敏感度表）。

拉 牧原/温氏/新希望 一年日线，outer join 对齐交易日，每日全量重写（幂等）。
输出 site/data/pig/stocks.json。
"""
import os
import sys
import json
import datetime

# 本地开发走代理；GitHub Actions runner 在美国直连即可
if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")

import yfinance as yf
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "pig")
os.makedirs(SITE_DATA_DIR, exist_ok=True)

TICKERS = {
    "muyuan": "002714.SZ",     # 牧原股份
    "wens": "300498.SZ",       # 温氏股份
    "xinxiwang": "000876.SZ",  # 新希望
}


def fetch_stocks(period="1y"):
    frames = {}
    for name, sym in TICKERS.items():
        df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
        if df.empty:
            print(f"  [warn] {sym} 返回空数据")
            continue
        s = df["Close"].rename(name)
        s.index = s.index.tz_localize(None).normalize()
        frames[name] = s
        print(f"  {sym}: {len(s)} 行 {s.index[0].date()} ~ {s.index[-1].date()}")
    if not frames:
        raise RuntimeError("全部标的拉取失败")
    px = pd.concat(frames.values(), axis=1, join="outer").sort_index()
    return px


def main():
    print("[1/2] 拉取 A股猪企日线...")
    px = fetch_stocks("1y")
    rows = []
    for idx, r in px.iterrows():
        rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "muyuan": round(float(r["muyuan"]), 2) if pd.notna(r.get("muyuan")) else None,
            "wens": round(float(r["wens"]), 2) if pd.notna(r.get("wens")) else None,
            "xinxiwang": round(float(r["xinxiwang"]), 2) if pd.notna(r.get("xinxiwang")) else None,
        })
    print(f"[2/2] 写 site/data/pig/stocks.json（{len(rows)} 行）...")
    with open(os.path.join(SITE_DATA_DIR, "stocks.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print("done.")


if __name__ == "__main__":
    main()
