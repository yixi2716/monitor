# -*- coding: utf-8 -*-
"""医药看板 · 位置信号（左侧）数据抓取：灯⑥估值分位 + 灯⑦成交占比分位。

取数路由（全部免费源，实测 2026-10-10）：
- 灯⑥: 申万医药生物 801150 十年价格分位（akshare index_hist_sw，全历史现成）
       + 中证 300医药 000913 的 PE1（akshare stock_zh_index_value_csindex，每日积累进
       pe_history.json；积累满 250 个交易日后自动切换为 PE 分位主信号）
- 灯⑦: 医药成交额占比的 3 年滚动分位
       分子: 801150 成交额（index_hist_sw，单位亿元）
       分母: 上证(000001) + 深证成指(399001) 成交额（stock_zh_index_daily_em，单位元→换算亿元）

每日全量重写 valuation.json / pe_history.json（幂等），供前端"位置信号"模块渲染。
"""
import os
import sys
import json
import datetime

# 本地开发：Yahoo/中证官网走代理；东财/申万等国内源直连（Windows 系统代理会干扰）
if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")
if sys.platform == "win32":
    # 东财走系统代理会被断连，仅对东财域名绕过代理（其余源仍走代理）
    _np = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = (_np + "," if _np else "") + "eastmoney.com"

import akshare as ak
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "pharma")
os.makedirs(SITE_DATA_DIR, exist_ok=True)

SW_CODE = "801150"        # 申万医药生物
PE_INDEX = "000913"       # 中证 300医药（csindex 估值）
PE_MIN_ROWS = 250         # PE 序列积累多少行后切换为分位主信号
TEN_Y = 2450              # 约 10 个交易年
THREE_Y = 750             # 约 3 个交易年


def _try_both(fn, label):
    """先按当前环境（代理）调用，失败则临时摘掉代理直连重试一次。
    Windows 注册表系统代理不受 HTTP_PROXY 影响，重试时必须同时置 NO_PROXY=*。"""
    try:
        return fn()
    except Exception as e1:
        saved = {k: os.environ.pop(k, None) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}
        os.environ["NO_PROXY"] = "*"
        try:
            print(f"    [retry] {label} 走代理失败({str(e1)[:60]})，改直连重试")
            return fn()
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


def load_json(name, default):
    path = os.path.join(SITE_DATA_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(name, obj):
    with open(os.path.join(SITE_DATA_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    print(f"  写 site/data/pharma/{name}")


def pct_rank(series, value):
    """value 在 series 中的分位 = 历史值 < value 的比例，0~1"""
    s = pd.Series([v for v in series if v is not None]).dropna()
    if len(s) < 30 or value is None:
        return None
    return round(float((s < value).mean()), 4)


def fetch_price_pct(df):
    """灯⑥过渡信号：801150 收盘的十年价格分位（df 由 main 统一拉取）"""
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").tail(TEN_Y)
    last = float(df["收盘"].iloc[-1])
    pct = pct_rank(df["收盘"].tolist(), last)
    return {
        "date": df["日期"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(last, 2),
        "pct": pct,
        "window_days": len(df),
        "src": "申万宏源研究 801150 日线 · 近10年",
    }


def fetch_pe():
    """中证 300医药 PE1：与积累历史合并，计算 PE 十年/积累期分位"""
    df = _try_both(lambda: ak.stock_zh_index_value_csindex(symbol=PE_INDEX), "csindex")
    df["日期"] = pd.to_datetime(df["日期"])
    new_rows = [{"date": r["日期"].strftime("%Y-%m-%d"), "pe": float(r["市盈率1"])}
                for _, r in df.iterrows() if pd.notna(r["市盈率1"])]
    hist = {r["date"]: r["pe"] for r in load_json("pe_history.json", [])}
    for r in new_rows:
        hist[r["date"]] = r["pe"]
    rows = [{"date": d, "pe": hist[d]} for d in sorted(hist)]
    save_json("pe_history.json", rows)
    last = rows[-1]
    pct = pct_rank([r["pe"] for r in rows], last["pe"]) if len(rows) >= PE_MIN_ROWS else None
    return {
        "date": last["date"],
        "pe": round(last["pe"], 2),
        "pct": pct,
        "rows": len(rows),
        "ready": len(rows) >= PE_MIN_ROWS,
        "src": "中证指数官网 000913 PE1 · 每日积累",
    }


def fetch_turnover_pct(sw):
    """灯⑦：医药成交额 / 全市场成交额 的 3 年滚动分位（801150 df 由 main 统一拉取）"""
    sw = sw.copy()
    sw["日期"] = pd.to_datetime(sw["日期"])
    sw = sw.sort_values("日期").tail(THREE_Y + 30)
    sw_amt = dict(zip(sw["日期"].dt.strftime("%Y-%m-%d"), sw["成交额"].astype(float)))  # 亿元

    # 全市场成交额：申万全A 801250（与分子同源同单位，东财接口在部分网络环境不可用）
    full = _try_both(lambda: ak.index_hist_sw(symbol="801250", period="day"), "index_hist_sw(801250)")
    full["日期"] = pd.to_datetime(full["日期"])
    full = full.sort_values("日期").tail(THREE_Y + 30)
    full_amt = dict(zip(full["日期"].dt.strftime("%Y-%m-%d"), full["成交额"].astype(float)))  # 亿元

    ratios = []
    for d, amt in sw_amt.items():
        if d in full_amt and full_amt[d] > 0:
            ratios.append((d, amt / full_amt[d]))
    ratios.sort()
    tail = ratios[-THREE_Y:]
    last_d, last_r = tail[-1]
    pct = pct_rank([r for _, r in tail], last_r)
    return {
        "date": last_d,
        "ratio": round(last_r * 100, 3),  # %
        "pct": pct,
        "window_days": len(tail),
        "src": "申万801150成交额 ÷ 申万全A(801250)成交额 · 3年滚动",
    }


def rolling_pct_series(dates, values, window):
    """最近 N 个观测点的滚动分位序列：每个点取过去 window 个值的 (历史值<当前) 比例"""
    out = []
    s = pd.Series(values, dtype=float)
    n = len(s)
    keep = min(n, 500)          # 只保留最近 500 天的曲线，文件不过大
    for i in range(max(1, n - keep), n):
        lo = max(0, i - window)
        w = s.iloc[lo:i]
        w = w.dropna()
        v = s.iloc[i]
        if len(w) < 30 or pd.isna(v):
            continue
        out.append({"date": dates[i], "pct": round(float((w < v).mean()), 4)})
    return out


def save_history(sw, price_light, turnover_light):
    """分位历史曲线数据（页面位置信号区图表用）"""
    sw = sw.copy()
    sw["日期"] = pd.to_datetime(sw["日期"])
    sw = sw.sort_values("日期").tail(TEN_Y)
    dates = sw["日期"].dt.strftime("%Y-%m-%d").tolist()
    closes = sw["收盘"].astype(float).tolist()
    price_hist = rolling_pct_series(dates, closes, TEN_Y)

    # 成交占比序列：与 fetch_turnover_pct 同口径
    sw_amt = dict(zip(dates, sw["成交额"].astype(float)))
    try:
        full = _try_both(lambda: ak.index_hist_sw(symbol="801250", period="day"), "index_hist_sw(801250)")
        full["日期"] = pd.to_datetime(full["日期"])
        full = full.sort_values("日期").tail(THREE_Y + 30)
        full_amt = dict(zip(full["日期"].dt.strftime("%Y-%m-%d"), full["成交额"].astype(float)))
    except Exception:
        full_amt = {}
    t_dates, t_ratios = [], []
    for d, amt in sw_amt.items():
        if d in full_amt and full_amt[d] > 0:
            t_dates.append(d)
            t_ratios.append(amt / full_amt[d])
    turnover_hist = rolling_pct_series(t_dates, t_ratios, THREE_Y)
    for r, ratio in zip(turnover_hist, t_ratios[-len(turnover_hist):]):
        r["ratio"] = round(ratio * 100, 3)

    pe_rows = load_json("pe_history.json", [])
    pe_hist = [{"date": r["date"], "pe": round(float(r["pe"]), 2)} for r in pe_rows if r.get("pe") is not None][-500:]

    save_json("valuation_history.json", {
        "date": datetime.date.today().strftime("%Y-%m-%d"),
        "price_pct": price_hist,
        "turnover_pct": turnover_hist,
        "pe": pe_hist,
        "note": "price_pct=801150十年价格分位; turnover_pct=医药成交占比3年分位; pe=000913 PE1原始值",
    })


def main():
    out = {"date": datetime.date.today().strftime("%Y-%m-%d"), "lights": {}}
    print("[0/3] 拉取 801150 日线（价格+成交额共用）...")
    try:
        sw_df = _try_both(lambda: ak.index_hist_sw(symbol=SW_CODE, period="day"), "index_hist_sw")
    except Exception as e:
        print(f"    [warn] 801150 拉取失败: {e}")
        sw_df = None

    print("[1/3] 灯⑥ 价格分位(过渡) + PE 积累...")
    try:
        out["lights"]["price"] = fetch_price_pct(sw_df) if sw_df is not None else {"pct": None, "src": "拉取失败"}
        print(f"    801150 十年价格分位: {out['lights']['price']['pct']}")
    except Exception as e:
        print(f"    [warn] 价格分位失败: {e}")
        out["lights"]["price"] = {"pct": None, "src": "拉取失败", "error": str(e)[:100]}
    try:
        out["lights"]["pe"] = fetch_pe()
        print(f"    300医药 PE: {out['lights']['pe']['pe']} 分位: {out['lights']['pe']['pct']} ({out['lights']['pe']['rows']}行)")
    except Exception as e:
        print(f"    [warn] PE 积累失败: {e}")
        out["lights"]["pe"] = {"pct": None, "src": "拉取失败", "error": str(e)[:100]}

    print("[2/3] 灯⑦ 成交占比 3 年分位...")
    try:
        out["lights"]["turnover"] = fetch_turnover_pct(sw_df) if sw_df is not None else {"pct": None, "src": "拉取失败"}
        print(f"    成交占比: {out['lights']['turnover']['ratio']}% 分位: {out['lights']['turnover']['pct']}")
    except Exception as e:
        print(f"    [warn] 成交占比失败: {e}")
        out["lights"]["turnover"] = {"pct": None, "src": "拉取失败", "error": str(e)[:100]}

    print("[3/3] 写 valuation.json")
    save_json("valuation.json", out)
    try:
        save_history(sw_df, out["lights"].get("price"), out["lights"].get("turnover"))
    except Exception as e:
        print(f"    [warn] 分位历史曲线失败: {e}")
    print("done.")


if __name__ == "__main__":
    main()
