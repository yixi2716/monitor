# -*- coding: utf-8 -*-
"""一次性回填：过去 N 个月价格历史 → data/history.json（合并现有记录）。

- 期货：akshare 新浪日线一次拿全（LH0 生猪主力、C0 玉米主力）
- 现货：生意社 futures_spot_price 逐日回溯（历史日期均有数据；连续失败即跳过记 gap）
- 猪粮比：现货(元/公斤) ÷ 玉米期货折算(元/公斤)，与 fetch_daily 口径一致
运行：python scripts/backfill_history.py [月份数，默认6]
"""
import os
import re
import sys
import time
import json
import datetime
import akshare as ak

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
SITE_DATA = os.path.join(HERE, "..", "site", "data")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main():
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    start = (datetime.date.today()
             - datetime.timedelta(days=int(months * 30.5))).isoformat()
    print(f"backfill window: {start} ~ today ({months} months)")

    # 期货日线
    lh = ak.futures_zh_daily_sina(symbol="LH0")
    corn = ak.futures_zh_daily_sina(symbol="C0")
    lh = lh[lh["date"].astype(str) >= start]
    corn_by_date = {str(r["date"]): float(r["close"]) for _, r in corn.iterrows()}
    print(f"futures rows: LH={len(lh)}")

    # 现有历史（合并去重）
    hist = load_json(os.path.join(DATA, "history.json"), [])
    existing = {r.get("date"): r for r in hist if r.get("date")}

    new = 0
    gaps = 0
    dates = [str(d) for d in lh["date"]]
    for i, d in enumerate(dates):
        if d in existing:
            continue
        lh_close = round(float(lh.iloc[i]["close"]), 2)
        spot = None
        ratio = None
        try:
            s = ak.futures_spot_price(date=d.replace("-", ""), vars_list=["LH"])
            if s is not None and len(s):
                spot = round(float(s["spot_price"].iloc[0]) / 1000.0, 2)
            else:
                gaps += 1
        except Exception as e:
            print(f"[warn] spot {d} failed: {e}")
            gaps += 1
        corn_close = corn_by_date.get(d)
        if spot and corn_close:
            ratio = round(spot / (corn_close / 1000.0), 2)
        existing[d] = {"date": d, "spot_pig": spot,
                       "lh_close": lh_close, "pig_grain_ratio": ratio}
        new += 1
        if new % 10 == 0:
            print(f"  ... {new} days done ({d})")
        time.sleep(1.0)  # 降低生意社风控概率

    out = sorted(existing.values(), key=lambda r: r["date"])
    out = out[-1500:]
    save_json(os.path.join(DATA, "history.json"), out)
    save_json(os.path.join(SITE_DATA, "history.json"), out)
    print(f"done: total={len(out)} new={new} spot_gaps={gaps}")


if __name__ == "__main__":
    main()
