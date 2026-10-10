# -*- coding: utf-8 -*-
"""医药看板 · BD 出海产业引擎数据：月度 License-out 首付款 + NMPA 创新药获批。

口径说明（重要）：
- License-out 首付款：无免费结构化数据库。本脚本每日抓 Google News 近 60 天
  含"首付款"金额的报道，正则提取金额（美元/人民币）后按月累计。
  仅覆盖"标题里同时出现首付款与金额"的交易，系统性低估，适合看趋势不适合看绝对值。
  可在 config/bd_manual.json 里按月填入手工核对值（如医药魔方月度统计），手工值优先。
- NMPA 月度创新药获批数：官方无免费 API。auto_count 为"近60天获批相关新闻数"
  （线索，非官方计数）；在 config/bd_manual.json 的 nmpa_monthly 填官方值后优先显示。

输出 site/data/pharma/bd.json
"""
import os, sys, json, time, datetime, urllib.request, xml.etree.ElementTree as ET
from urllib.parse import quote
import re

if os.environ.get("HTTP_PROXY") is None and sys.platform == "win32":
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:12000")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:12000")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA_DIR = os.path.join(ROOT, "site", "data", "pharma")
CONFIG_PATH = os.path.join(ROOT, "config", "bd_manual.json")
os.makedirs(SITE_DATA_DIR, exist_ok=True)

# 已知行业锚点（手工录入，仅作参考线展示，不参与月度累计）
ANCHORS = [
    {"label": "2026H1 首付款约64.5亿美元(医药魔方)", "value_usd": 10.75,
     "note": "半年合计64.5亿，月均约10.75亿美元"},
    {"label": "2026H1 交易总额约997亿美元", "value_usd": None, "note": "半年合计"},
]

QUERIES_BD = [
    '"license-out" 创新药 首付款 when:60d',
    '"license out" 中国 创新药 upfront when:60d',
    '创新药 出海 授权 首付款 when:60d',
]
QUERIES_NMPA = [
    'NMPA 批准 创新药 上市 when:60d',
    '创新药 获批上市 国家药监局 when:60d',
]

AMOUNT_RE = re.compile(
    r"(?:首付款|首付|upfront)[^，。,.]{0,20}?(\d+(?:\.\d+)?)\s*(亿美[元金]|百万美[元金]|千万美[元金]|亿美[元金]|亿元|亿人民币|百万人民币)",
    re.IGNORECASE)
ANY_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿美[元金]|百万美[元金]|千万美[元金]|亿元|亿人民币)")


def to_usd(num, unit):
    u = unit.replace("金", "元")
    if "亿美元" in u:
        return float(num)
    if "百万美元" in u:
        return float(num) / 100.0
    if "千万美元" in u:
        return float(num) / 100.0
    if "亿元" in u or "亿人民币" in u:
        return float(num) / 7.2  # 粗略汇率，仅作量级参考
    return None


def fetch_news(query, limit=20):
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            root = ET.fromstring(r.read())
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = item.findtext("link") or ""
            pub = (item.findtext("pubDate") or "").strip()
            try:
                d = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
            except Exception:
                d = pub[:16]
            if title:
                items.append({"date": d, "title": title, "url": link})
        return items
    except Exception as e:
        print(f"  [warn] 新闻拉取失败({query[:20]}...): {str(e)[:60]}")
        return []


def load_manual():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    today = datetime.date.today()
    print("[1/3] 抓 License-out 首付款新闻...")
    deals = {}
    bd_path = os.path.join(SITE_DATA_DIR, "bd.json")
    if os.path.exists(bd_path):
        try:
            with open(bd_path, encoding="utf-8") as f:
                old = json.load(f)
            for d in old.get("deals", []):
                deals[d["url"] or d["title"]] = d
        except Exception:
            old = {}
    new_cnt = 0
    for q in QUERIES_BD:
        for it in fetch_news(q):
            key = it["url"] or it["title"]
            if key in deals:
                continue
            m = AMOUNT_RE.search(it["title"])
            if not m:
                continue
            usd = to_usd(m.group(1), m.group(2))
            if usd is None:
                continue
            month = it["date"][:7]
            deals[key] = {"date": it["date"], "month": month, "title": it["title"],
                          "amount_usd": round(usd, 3), "url": it["url"]}
            new_cnt += 1
        time.sleep(1)
    print(f"  累计 deals {len(deals)} 条（新增 {new_cnt}）")

    # 月度汇总（最近18个月）
    monthly = {}
    for d in deals.values():
        m = d["month"]
        if m not in monthly:
            monthly[m] = {"month": m, "total_usd": 0.0, "count": 0}
        monthly[m]["total_usd"] += d["amount_usd"]
        monthly[m]["count"] += 1
    months = sorted(monthly.keys())[-18:]
    monthly_list = [{"month": m, "total_usd": round(monthly[m]["total_usd"], 2),
                     "count": monthly[m]["count"]} for m in months]

    print("[2/3] NMPA 获批新闻线索...")
    nmpa_auto = {}
    for q in QUERIES_NMPA:
        for it in fetch_news(q, limit=30):
            if it["date"][:4] not in ("2025", "2026", "2027"):
                continue
            m = it["date"][:7]
            nmpa_auto[m] = nmpa_auto.get(m, 0) + 1
        time.sleep(1)
    print(f"  近60天线索 {sum(nmpa_auto.values())} 条，涉及月份 {sorted(nmpa_auto.keys())}")

    manual = load_manual()
    # 手工月度首付款覆盖自动值
    manual_up = manual.get("monthly_upfront", {})
    for row in monthly_list:
        if row["month"] in manual_up:
            row["manual"] = True
            row["total_usd"] = manual_up[row["month"]]
    for m, v in manual_up.items():
        if m not in months:
            monthly_list.append({"month": m, "total_usd": v, "count": None, "manual": True})
    monthly_list.sort(key=lambda x: x["month"])

    manual_nmpa = manual.get("nmpa_monthly", {})
    nmpa_months = sorted(set(list(nmpa_auto.keys()) + list(manual_nmpa.keys())))[-18:]
    nmpa_list = []
    for m in nmpa_months:
        nmpa_list.append({"month": m,
                          "count": manual_nmpa.get(m, nmpa_auto.get(m, 0)),
                          "manual": m in manual_nmpa,
                          "auto_clues": nmpa_auto.get(m, 0)})

    out = {
        "updated": today.isoformat(),
        "monthly_upfront": monthly_list,
        "nmpa": {"months": nmpa_list,
                 "note": "count 为手工维护的官方计数(config/bd_manual.json)；无手工值时为近60天获批新闻线索数(高估情绪、非官方口径)"},
        "deals": sorted(deals.values(), key=lambda x: x["date"], reverse=True)[:30],
        "anchors": ANCHORS,
        "disclaimer": "首付款月度额来自公开新闻正则提取，仅覆盖标题含金额的报道，系统性低估；看趋势不看绝对值。",
    }
    with open(bd_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[3/3] 写 bd.json：{len(monthly_list)} 个月度, {len(nmpa_list)} 个 NMPA 月")
    print("done.")


if __name__ == "__main__":
    main()
