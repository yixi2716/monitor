# -*- coding: utf-8 -*-
"""每日收盘后运行：期货主力连续 + LH 全合约期限结构 + 生意社现货猪价 + 猪粮比。

数据链路（确定性代码，不做 AI 判断）：
- 期货：akshare 新浪财经接口（主力连续 LH0/C0/M0，全合约曲线见 fetch_lh_curve）；
- 现货：生意社猪价（元/公斤）；
- 任一接口失效时跳过该项并在历史中记 gap（None），不得写入伪造值。
"""
import akshare as ak
import re
from util import load_json, save_json, git_push, today_str, load_config

FUTURES_MAIN = [("LH0", "生猪"), ("C0", "玉米"), ("M0", "豆粕")]


def fetch_futures():
    """主力连续收盘价，返回 {name: {close, date}}"""
    out = {}
    for sym, name in FUTURES_MAIN:
        try:
            df = ak.futures_zh_daily_sina(symbol=sym)
            last = df.iloc[-1]
            out[name] = {"close": round(float(last["close"]), 2),
                         "date": str(last["date"])}
        except Exception as e:
            print(f"[warn] futures {name} failed: {e}")
    return out


def fetch_lh_curve(min_position=1000):
    """LH 全部挂牌合约最新价（期限结构）。

    TODO-2 实现：akshare 生意社"期货现货基差"接口同时返回现货与全合约，
    另用新浪"生猪"实时行情一次返回全部挂牌合约。
    剔除流动性极差合约（持仓 < min_position，通常是临近交割的僵尸合约）后，
    取近月(交割月最近)与远月(交割月最远)最新价，计算升贴水 spread。
    失败返回 None，由调用方留 gap。
    """
    try:
        df = ak.futures_zh_realtime(symbol="生猪")
        cols = {str(c).lower(): c for c in df.columns}
        price_col = cols.get("trade") or cols.get("close")
        rows = []
        for _, r in df.iterrows():
            sym = str(r.get("symbol", "")).strip().upper()
            # 只保留真实挂牌合约（LH+4位数字，如 LH2611），排除 LH0/LH00 连续合约
            if not re.fullmatch(r"LH\d{4}", sym):
                continue
            position = float(r.get("position") or 0)
            if position < min_position:
                continue
            rows.append({"symbol": sym, "price": float(r[price_col])})
        if len(rows) < 2:
            print(f"[warn] lh curve: only {len(rows)} valid contracts (df rows={len(df)})")
            return None
        rows.sort(key=lambda x: x["symbol"])  # 合约代码即交割月份排序
        curve = {r["symbol"]: round(r["price"], 2) for r in rows}
        near, far = rows[0], rows[-1]
        return {"curve": curve, "near": near["symbol"], "far": far["symbol"],
                "lh_far_near_spread": round(far["price"] - near["price"], 2)}
    except Exception as e:
        print(f"[warn] lh curve failed: {e}")
        return None


def fetch_spot_pig(max_back=2):
    """生意社现货猪价（元/公斤）。接口参数日期格式 YYYYMMDD。

    注意：vars_list 需传列表 ["LH"]；传字符串 "LH" 会被逐字符匹配到
    塑料期货 L，取回错误品种。现货价单位为元/吨，换算为元/公斤。
    当日数据未发布（凌晨/非交易日）时返回空表，向前回溯最近 max_back 个
    自然日取最近有效值；全部缺失返回 None（历史记 gap）。
    """
    import datetime
    import time
    for offset in range(max_back + 1):
        d = (datetime.date.today() - datetime.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = ak.futures_spot_price(date=d, vars_list=["LH"])
            if df is None or len(df) == 0:
                print(f"[warn] spot pig {d}: empty table")
            else:
                spot_ton = float(df["spot_price"].iloc[0])
                return round(spot_ton / 1000.0, 2)  # 元/吨 → 元/公斤
        except Exception as e:
            print(f"[warn] spot pig {d} failed: {e}")
        time.sleep(2)
    return None


def main():
    data = load_json("latest.json")
    futures = fetch_futures()
    spot = fetch_spot_pig()
    prices_cfg = load_config("prices.json", {})
    curve = fetch_lh_curve(min_position=prices_cfg.get("lh_min_position", 1000))

    data["date"] = today_str()
    data["futures"] = futures
    if curve:
        data["derived"] = {**data.get("derived", {}),
                           "lh_curve": curve["curve"],
                           "lh_near": curve["near"], "lh_far": curve["far"],
                           "lh_far_near_spread": curve["lh_far_near_spread"]}
    if spot is not None:
        data["spot_pig"] = spot

    # 猪粮比：猪价(元/公斤) ÷ 玉米价(元/公斤)。玉米优先期货收盘折算，否则 config 兜底。
    corn_kg = None
    corn_fut = futures.get("玉米", {}).get("close")
    if corn_fut:
        corn_kg = corn_fut / 1000.0  # 期货元/吨→元/公斤
    else:
        corn_kg = prices_cfg.get("corn_spot_kg")
    if spot is not None and corn_kg:
        data["pig_grain_ratio"] = round(spot / corn_kg, 2)

    save_json("latest.json", data)

    # 追加历史（供前端画图）：同日期幂等更新，避免重复运行产生同日多行
    hist = load_json("history.json", [])
    rec = {"date": today_str(),
           "spot_pig": data.get("spot_pig"),
           "lh_close": futures.get("生猪", {}).get("close"),
           "pig_grain_ratio": data.get("pig_grain_ratio")}
    if hist and hist[-1].get("date") == today_str():
        hist[-1] = rec
    else:
        hist.append(rec)
    hist = hist[-1500:]
    save_json("history.json", hist)

    git_push(f"data: daily {today_str()}")
    print(f"daily fetch done: spot={data.get('spot_pig')} ratio={data.get('pig_grain_ratio')}")


if __name__ == "__main__":
    main()
