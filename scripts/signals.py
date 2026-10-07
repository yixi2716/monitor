# -*- coding: utf-8 -*-
"""信号灯规则引擎：合并 latest.json + manual.json，输出 signals.json。

规则阈值集中在 config/rules.json，便于后续调整。
所有规则由确定性代码执行；LLM 提取结果（manual.json 中 need_review=True）不参与计算。
"""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "..", "config", "rules.json")

DEFAULT_RULES = [
    {"id": "sow_culling", "name": "能繁母猪去化",
     "desc": "存栏环比降幅≥1% 且连续3个月",
     "field": "sow_mom", "op": "<=", "threshold": -1.0},
    {"id": "holding_green", "name": "产能进绿色区下沿",
     "desc": "占正常保有量 ≤ 96%",
     "field": "sow_holding_pct", "op": "<=", "threshold": 96.0},
    {"id": "price_floor", "name": "价格站稳成本线",
     "desc": "现货猪价 ≥ 14 元/公斤",
     "field": "spot_pig", "op": ">=", "threshold": 14.0},
    {"id": "profit_turn", "name": "脱离深亏区",
     "desc": "猪粮比 ≥ 6",
     "field": "pig_grain_ratio", "op": ">=", "threshold": 6.0},
    {"id": "futures_contango", "name": "期货远月升水",
     "desc": "LH远月合约收盘价 > 近月",
     "field": "lh_far_near_spread", "op": ">", "threshold": 0},
    {"id": "frozen_ok", "name": "冻品库容消化",
     "desc": "库容率 ≤ 60%",
     "field": "frozen_capacity_pct", "op": "<=", "threshold": 60.0},
]

OPS = {"<=": lambda a, b: a is not None and a <= b,
       ">=": lambda a, b: a is not None and a >= b,
       ">":  lambda a, b: a is not None and a > b,
       "<":  lambda a, b: a is not None and a < b}


def main():
    from util import load_json, save_json, today_str
    rules = json.load(open(RULES_PATH, encoding="utf-8")) if os.path.exists(RULES_PATH) \
        else DEFAULT_RULES

    latest = load_json("latest.json", {})
    manual = load_json("manual.json", {})
    sow = manual.get("sow", {})
    weekly = manual.get("weekly_indicators", {})

    # far-near spread：fetch_daily 已写入 latest.derived
    fn_spread = latest.get("derived", {}).get("lh_far_near_spread")

    # 冻品库容：仅当周报记录已人工复核(need_review=false)才启用
    frozen = None
    for rec in weekly.values():
        if isinstance(rec, dict) and not rec.get("need_review") and rec.get("frozen_capacity_pct") is not None:
            frozen = rec["frozen_capacity_pct"]
            break

    values = {
        "sow_mom": sow.get("mom_pct") if not sow.get("need_review") else None,
        "sow_holding_pct": sow.get("holding_pct") if not sow.get("need_review") else None,
        "spot_pig": latest.get("spot_pig"),
        "pig_grain_ratio": latest.get("pig_grain_ratio"),
        "lh_far_near_spread": fn_spread,
        "frozen_capacity_pct": frozen,
    }

    signals, green = [], 0
    for r in rules:
        ok = OPS[r["op"]](values.get(r["field"]), r["threshold"])
        status = "green" if ok else ("gray" if values.get(r["field"]) is None else "yellow")
        if ok:
            green += 1
        signals.append({"id": r["id"], "name": r["name"], "desc": r["desc"],
                        "status": status,
                        "value": values.get(r["field"]), "threshold": r["threshold"],
                        "source": r.get("source") or []})

    n = len(signals)
    verdict = ("拐点确认区" if green >= n - 1 else
               "磨底观察中" if green >= 3 else "下行/出清阶段")
    save_json("signals.json", {
        "date": today_str(), "score": f"{green}/{n}", "verdict": verdict,
        "signals": signals,
        "pending_review": [k for k, v in {
            "sow": sow, **{f"weekly_{i}": w for i, w in enumerate(weekly.values())}
        }.items() if isinstance(v, dict) and v.get("need_review")],
    })
    print(f"signals: {green} / {n} {verdict}")

    # DeepSeek AI 综合分析
    try:
        import urllib.request, datetime
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if api_key:
            sig_lines = "\n".join(f"  - {s['name']}（{s['status']}）：{s['desc']}" for s in signals)
            prompt = f"""你是生猪周期分析师。基于以下今日信号，用中文给 200-300 字综合判断。
要求：1) 一句话定调当前周期位置 2) 最关键的信号是什么 3) 未来一个月盯什么 4) 不要套话和免责声明
今日数据：
- 现货猪价：{latest.get('spot_pig','?')} 元/公斤
- 猪粮比：{latest.get('pig_grain_ratio','?')}
- LH期货：{latest.get('futures',{}).get('生猪',{}).get('close','?')}
- {n}个信号灯（{green}绿/{n-green}非绿）：
{sig_lines}
"""
            body = json.dumps({
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是严谨的生猪周期分析师。"},
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
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            analysis = resp["choices"][0]["message"]["content"].strip()
            sig = json.load(open(os.path.join(HERE, "..", "data", "signals.json"), encoding="utf-8"))
            sig["ai_analysis"] = analysis
            sig["ai_date"] = today_str()
            save_json("signals.json", sig)
            print(f"AI 分析生成成功（{len(analysis)} 字）")
    except Exception as e:
        print(f"[warn] AI 分析失败: {e}")


if __name__ == "__main__":
    main()
