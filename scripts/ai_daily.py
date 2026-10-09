# -*- coding: utf-8 -*-
"""每日 AI 综合分析生成 + 按日期存档。

在北京时间 0 点（workflow UTC 16:00）数据更新后统一运行：
1. 读取各品种 site/data 下的 latest.json（猪再读 signals/sow_history）
2. 用与前端一致的提示词调用 DeepSeek 生成当日分析
3. 写入 site/data/<品种>/ai_history.json（按日期为 key，可翻阅）
   - 若当天已有人工保存的存档（用户在页面上点过"存入档案"），不覆盖，
     以晚上 12 点前人工最后一次生成的为准
4. 同时回填 latest.json 的 ai_analysis 字段，页面即时可见

存档格式：{"2026-10-09": {"text": "...", "ts": "2026-10-09T16:00:01"}}
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "data"

BJ = timezone(timedelta(hours=8))


def now_bj():
    return datetime.now(BJ).isoformat(timespec="seconds")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def call_deepseek(prompt, system):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return "", "未配置 DEEPSEEK_API_KEY（GitHub Secrets 里没配）"
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
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
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if "error" in resp:
            return "", str(resp["error"])[:300]
        return resp["choices"][0]["message"]["content"].strip(), ""
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


# ---------------- 提示词（与各页面前端 regenerate 函数保持一致） ----------------

def prompt_gold(L):
    sig = "\n".join(f"  - {s['name']}（{s['dir']}）：{s['text']}" for s in (L.get("signals") or []))
    macro = L.get("macro") or {}
    geo = L.get("geopolitics") or {}
    shfe = f"¥{L['shfe_au']:.2f}/克" if L.get("shfe_au") else "未获取"
    ratio = f"{L['gold_silver_ratio']:.1f}" if L.get("gold_silver_ratio") else "未获取"
    cftc = f"{L['cftc_gold_net']:,} 张" if L.get("cftc_gold_net") else "未获取"
    return f"""你是贵金属分析师，每日跟踪黄金市场。基于以下数据，按要求输出。

【核心数据】
- COMEX黄金：${L['gold']:.2f}/盎司（{L['gold_chg']:+.2f}%），MA20=${L['ma20']:.2f}，MA50=${L['ma50']:.2f}
- 沪金主力：{shfe}
- 金银比：{ratio}（>80 避险升温）
- DXY美元指数：{L['dxy']:.2f}
- 10Y美债收益率：{L['tnx']:.2f}%
- VIX：{L['vix']:.1f}
- CFTC黄金净持仓：{cftc}（{macro.get('cftc_date', L.get('cftc_gold_date', ''))}）
- 美联储：当前利率 {macro.get('funds_range', '')}，距下次FOMC还有 {macro.get('days_to_next', '?')} 天，{macro.get('market_expectation', '')}
- 地缘局势：紧张度 {geo.get('level', '')}，WTI原油 ${geo.get('wti_price', '?')}
- SPDR GLD持仓量：未获取

【每日信号】
{sig}

【输出格式，严格按此结构】
1. 涨跌归因：今日金价波动主要由什么驱动（实际利率/美元/避险/资金技术），判断行情持续性
2. 宏观映射：实际利率和美元变动是否解释了金价波动，若有背离重点说明
3. 资金信号：CFTC净多头方向，投机盘是否过热
4. 内外盘：沪金反映国内需求强弱
5. 短期展望：偏多/偏空/震荡 + 关键支撑位/阻力位
6. 近期风险事件：未来一周重要数据/事件

要求：200-300字，普通人能懂，不要套话和免责声明，未获取的数据不要编造。"""


def prompt_copper(L):
    sig = "\n".join(f"  - {s['name']}（{s['dir']}）：{s['text']}" for s in (L.get("signals") or []))
    news = "\n".join(f"  - [{n.get('date', '')}] {n.get('text', '')}" for n in (L.get("news") or [])[:8])
    shfe_cu = f"¥{L['shfe_cu']:,.0f}/吨" if L.get("shfe_cu") else "未获取"
    ratio = f"{L['shfe_lme_ratio']:.3f}" if L.get("shfe_lme_ratio") else "未获取"
    lme = f"{L['lme_stock']:,} 吨" if L.get("lme_stock") else "未获取"
    shfe_stock = f"{L['shfe_stock']:,} 吨（日变{L.get('shfe_stock_chg', 0):+d}）" if L.get("shfe_stock") else "未获取"
    return f"""你是大宗商品分析师，每日跟踪铜市场。基于以下数据，按要求输出。

【核心数据】
- COMEX铜：${L['copper']:.2f}/磅（{L['copper_chg']:+.2f}%），MA20=${L.get('ma20', 0):.2f}，MA50=${L.get('ma50', 0):.2f}
- 沪铜主力：{shfe_cu}
- 沪伦比值：{ratio}（>1 进口有利）
- DXY美元指数：{L['dxy']:.2f}
- VIX：{L.get('vix', 0):.1f}，10Y美债：{L.get('tnx', 0):.2f}%
- WTI原油：${L.get('wti', 0):.2f}，铜油比：{L.get('cu_oil_ratio', 0):.1f}
- LME库存：{lme}（{L.get('lme_stock_date', '')}）
- 沪铜库存：{shfe_stock}（{L.get('shfe_stock_date', '')}）
- LME Cash-3M升贴水：未获取
- 铜精矿TC：未获取
- CFTC铜非商业净持仓：未获取

【每日信号】
{sig}

【最近新闻】
{news}

【输出要求】
1. 涨跌归因：拆解今日铜价变动主要由什么驱动（宏观美元/利率、供给、需求预期、或美国232铜关税政策）
2. 库存与价差：结合库存和升贴水判断当前是紧张还是宽松格局
3. 内外盘：沪伦比值说明内外盘强弱，特别注意美国232关税对COMEX溢价的影响
4. 资金信号：基于已有信号判断趋势是否健康
5. 短期展望：偏多/偏空/震荡 + 关键价位
6. 风险点：1-2条（包含关税政策变化风险）

要求：200-300字，普通人能懂，不要套话和免责声明，未获取的数据不要编造。"""


def prompt_pig(L, S, sow):
    sig_lines = "\n".join(f"  - {s['name']}（{s['status']}）：{s['desc']}" for s in (S.get("signals") or []))
    pp = L.get("province_prices") or {}
    greens = sum(1 for s in (S.get("signals") or []) if s.get("status") == "green")
    curve = L.get("derived") or {}
    spread = curve.get("lh_far_near_spread", "?")
    return f"""你是生猪产业分析师，每日跟踪生猪市场。基于以下数据，按要求输出。

【核心数据】
- 全国生猪出栏均价：{L.get('spot_pig', '未获取')} 元/公斤
- 主产区河南：{pp.get('河南', '未获取')} 元/公斤
- 主销区广东：{pp.get('广东', '未获取')} 元/公斤
- 东北均价：{pp.get('东北均价', '未获取')} 元/公斤
- 大商所LH期货主力：{(L.get('futures') or {}).get('生猪', {}).get('close', '未获取')} 元/吨
- 猪粮比：{L.get('pig_grain_ratio', '未获取')}
- 豆粕价格：{L.get('soybean_meal', '未获取')} 元/吨
- 自繁自养利润：{L.get('self_profit', '未获取')} 元/公斤
- 期货远月升水：{spread} 元/吨
- 能繁母猪存栏：{sow}（季度数据）
- {len(S.get('signals') or [])}个信号灯（{greens}绿）：
{sig_lines}

【输出要求】
1. 周期定位：当前处于猪周期哪个阶段（去产能/筑底/上行/恢复/下行）
2. 短期供需：当前供给压力 vs 季节性需求
3. 价格驱动：今日变动是现货供需/期货资金/政策消息驱动
4. 期现结构：基差和月差反映的市场预期
5. 短期展望：现货猪价方向 + 期货关键价位
6. 周期提示：下一个关键观察点
7. 需关注事件：收储放储、产能数据发布日

要求：200-300字，普通人能懂，不要套话和免责声明，未获取的数据不要编造。"""


def prompt_pharma(L):
    news = "\n".join(f"  - [{n.get('date', '')}] {n.get('text', '')}" for n in (L.get("news") or [])[:8])
    def pct(v):
        return f"{v:+.2f}" if isinstance(v, (int, float)) else "?"
    return f"""请作为医药板块分析师，基于以下数据对今日A股医药行业进行跟踪分析。

【核心数据】
- 沪深300：{L.get('hs300', '?')}（{pct(L.get('hs300_chg'))}%）
- 医药ETF：{L.get('med_etf', '?')}（{pct(L.get('med_etf_chg'))}%）
- 创新药ETF：{L.get('inn_etf', '?')}（{pct(L.get('inn_etf_chg'))}%）
- CXO医疗ETF：{L.get('cxo_etf', '?')}（{pct(L.get('cxo_etf_chg'))}%）
- 中药ETF：{L.get('tcm_etf', '?')}（{pct(L.get('tcm_etf_chg'))}%）
- 医疗器械ETF：{L.get('meddev_etf', '?')}（{pct(L.get('meddev_etf_chg'))}%）
- 疫苗ETF：{L.get('vaccine_etf', '?')}（{pct(L.get('vaccine_etf_chg'))}%）
- 恒生医疗：{L.get('hsi_health', '?')}（{pct(L.get('hsi_health_chg'))}%）
- 10Y美债：{L.get('tnx', '?')}%
- 美元/人民币：{L.get('usdcny', '?')}
- 医药相对沪深300超额：{pct(L.get('excess'))}%

【当日医药新闻】
{news}

【分析要求】
1. 涨跌归因：今日板块表现是政策驱动、事件催化（license-out/临床数据）、利率驱动还是大盘贝塔？领涨子板块背后的逻辑
2. 结构：子板块之间是否分化，资金在板块内部往哪里切换
3. 联动：港股创新药与A股是否共振，美债利率变动如何影响创新药/CXO估值
4. 政策扫描：集采/医保谈判/支付改革等政策对各子板块的短期情绪与中长期格局影响
5. 情绪：涨跌停家数、新闻热度判断板块情绪位置

【输出格式】
- 一段话行情解读（100字以内，明确主导驱动与子板块结构）
- 短期展望（板块方向 + 需跟踪的催化与风险）
- 当日重要个股/政策事件摘要（1-2条，附事件性质判断：一次性催化还是基本面变化）

如某项数据当日未更新，标注"未更新"并沿用最近值，不要编造数据。用中文，普通人能懂。"""


# ---------------- 品种配置 ----------------

def sow_brief():
    rows = load_json(SITE / "sow_history.json", []) or []
    if not rows:
        return "未获取"
    r = rows[-1]
    mom = f"环比{r['mom_pct']}%" if r.get("mom_pct") is not None else ""
    yoy = f"同比{r['yoy_pct']}%" if r.get("yoy_pct") is not None else ""
    return f"{r['date']}末 {r['sow_wan']}万头（{mom} {yoy}）"


COMMODITIES = [
    {
        "key": "pig", "name": "猪",
        "dir": SITE, "latest": "latest.json", "archive": "ai_history.json",
        "system": "你是严谨的生猪产业分析师。",
        "prompt": lambda: prompt_pig(
            load_json(SITE / "latest.json"),
            load_json(SITE / "signals.json"),
            sow_brief()),
        "write_back": False,  # 猪 latest.json 由 fetch_daily/signals 管理，只写档案
    },
    {
        "key": "gold", "name": "黄金",
        "dir": SITE / "gold", "latest": "latest.json", "archive": "ai_history.json",
        "system": "你是严谨的贵金属分析师。",
        "prompt": lambda: prompt_gold(load_json(SITE / "gold" / "latest.json")),
        "write_back": True,
    },
    {
        "key": "copper", "name": "铜",
        "dir": SITE / "copper", "latest": "latest.json", "archive": "ai_history.json",
        "system": "你是严谨的大宗商品分析师，擅长把数据翻译成通俗判断。",
        "prompt": lambda: prompt_copper(load_json(SITE / "copper" / "latest.json")),
        "write_back": True,
    },
    {
        "key": "pharma", "name": "医药",
        "dir": SITE / "pharma", "latest": "latest.json", "archive": "ai_history.json",
        "system": "你是严谨的医药行业分析师。",
        "prompt": lambda: prompt_pharma(load_json(SITE / "pharma" / "latest.json")),
        "write_back": True,
    },
]


def run_one(cfg):
    name = cfg["name"]
    latest_path = cfg["dir"] / cfg["latest"]
    arch_path = cfg["dir"] / cfg["archive"]
    L = load_json(latest_path)
    if not L or not L.get("date"):
        print(f"[{name}] 跳过：latest.json 缺失或无 date")
        return
    date = L["date"]
    archive = load_json(arch_path, {}) or {}

    if date in archive and archive[date].get("text"):
        print(f"[{name}] {date} 已有人工存档，不覆盖（以当日最后一次人工分析为准）")
        # 仍把已有存档回填到 latest.json，保证页面即时可见
        if cfg["write_back"] and not L.get("ai_analysis"):
            L["ai_analysis"] = archive[date]["text"]
            L["ai_date"] = date
            L["ai_error"] = ""
            save_json(latest_path, L, indent=2)
        return

    print(f"[{name}] 生成 {date} 的 AI 分析...")
    text, err = call_deepseek(cfg["prompt"](), cfg["system"])
    if err or not text:
        print(f"[{name}] 生成失败：{err or '空内容'}")
        return

    archive[date] = {"text": text, "ts": now_bj()}
    # 保留最近 400 天
    keep = sorted(archive.keys())[-400:]
    archive = {k: archive[k] for k in keep}
    save_json(arch_path, archive, indent=2)

    if cfg["write_back"]:
        L["ai_analysis"] = text
        L["ai_date"] = date
        L["ai_error"] = ""
        save_json(latest_path, L, indent=2)
    print(f"[{name}] 已存档 {date}（累计 {len(archive)} 天）")


def main():
    for cfg in COMMODITIES:
        try:
            run_one(cfg)
        except Exception as e:
            print(f"[{cfg['name']}] 异常：{type(e).__name__}: {e}")
        time.sleep(1)  # 避免触发 API 限流


if __name__ == "__main__":
    main()
