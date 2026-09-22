# -*- coding: utf-8 -*-
"""每月10日运行。

① 巨潮资讯网(cninfo)抓取上市猪企销售月报公告列表；
② 对已解析出的月报正文用 DeepSeek 提取出栏量与均价（正文为 PDF 时提取受限，
   退化为仅记录公告标题，供人工查阅）；
③ 对配置的期货公司免费生猪周报URL，提取出栏体重/冻品库容/二育占比。
提取结果一律 need_review=True，写入 manual.json 待人工确认。
"""
import os
import json
import requests
from util import load_json, save_json, git_push, today_str

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

PIG_COMPANIES = {  # 证券代码 -> 简称（可按实际情况补充/删减）
    "002714": "牧原股份",
    "300498": "温氏股份",
    "000876": "新希望",
}

# 免费公开的期货生猪周报地址。需人工确认链接稳定后填入；
# 留空则跳过周报提取（前端该信号保持灰态）。
WEEKLY_REPORT_URLS = [
    # "https://...",  # 例：某期货公司生猪周报页
]

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_TOP = "http://www.cninfo.com.cn/new/information/topSearch/query"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
}


def _org_id(code: str):
    """通过 cninfo 检索接口拿 orgId，拼 stock 参数。"""
    r = requests.post(CNINFO_TOP, data={"keyWord": code},
                      headers=HEADERS, timeout=30)
    for item in r.json():
        if item.get("code") == code and item.get("category") in ("A股", "B股"):
            return item.get("orgId")
    return None


def fetch_monthly_reports(code: str, days: int = 45):
    """cninfo 公告检索：近 days 天全部公告，本地按标题过滤销售简报。

    不同猪企公告标题用词不同（"销售简报"/"销售情况简报"/"销售月报"），
    故 searchkey 置空拉全量后按关键词过滤，避免漏抓。
    返回 [(公司, 公告标题, 正文文本)]。正文为 PDF 时无法就地解析，
    返回空串（main 中将标题记入 manual 待人工查阅）。
    """
    import datetime
    org = _org_id(code)
    if not org:
        print(f"[warn] cninfo org not found for {code}")
        return []
    se_start = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    se_end = datetime.date.today().isoformat()
    out = []
    for page in (1, 2):
        data = {
            "pageNum": page, "pageSize": 30, "column": "szse", "tabName": "fulltext",
            "plate": "", "stock": f"{code},{org}", "searchkey": "",
            "secid": "", "category": "", "trade": "",
            "seDate": f"{se_start}~{se_end}", "sortName": "", "sortType": "",
            "isHLtitle": True,
        }
        r = requests.post(CNINFO_QUERY, data=data, headers=HEADERS, timeout=30)
        r.raise_for_status()
        anns = r.json().get("announcements") or []
        if not anns:
            break
        for a in anns:
            title = a.get("announcementTitle", "")
            if not any(k in title for k in ("销售简报", "销售情况简报", "销售月报")):
                continue
            out.append((title, ""))  # 正文 PDF 暂不解析，返回标题
    return out


def llm_extract(text: str, schema: str) -> dict:
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "deepseek-chat", "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"从文本提取数据，只输出JSON。{schema}"},
                {"role": "user", "content": text[:8000]}],
        }, timeout=60)
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def main():
    manual = load_json("manual.json", {})
    monthly = {}
    for code, name in PIG_COMPANIES.items():
        try:
            reports = fetch_monthly_reports(code)
        except Exception as e:
            print(f"[warn] cninfo fetch failed for {code}: {e}")
            continue
        titles = []
        for title, body in reports:
            titles.append(title)
            if not body:
                continue
            try:
                out = llm_extract(body, '{"sales_wan_tou": number|null, '
                                        '"avg_price": number|null}。'
                                        'sales_wan_tou=商品猪销量(万头)，avg_price=均价(元/公斤)')
                if out.get("sales_wan_tou"):
                    monthly[name] = {**out, "need_review": True, "title": title}
            except Exception as e:
                print(f"[warn] llm extract failed for {name}: {e}")
        if titles:
            monthly.setdefault(name, {})["titles"] = titles

    weekly = {}
    for url in WEEKLY_REPORT_URLS:
        try:
            body = requests.get(url, timeout=30).text
            out = llm_extract(body, '{"slaughter_weight_kg": number|null, '
                                    '"frozen_capacity_pct": number|null, '
                                    '"eryu_pct": number|null}。'
                                    '分别是出栏体重(公斤)、冻品库容率(%)、二次育肥占比(%)')
            weekly[url] = {**out, "need_review": True}
        except Exception as e:
            print(f"[warn] weekly {url} failed: {e}")

    if monthly:
        manual.setdefault("company_monthly", {})[today_str()[:7]] = monthly
    if weekly:
        manual["weekly_indicators"] = weekly
    save_json("manual.json", manual)
    git_push(f"data: reports {today_str()}")
    print("reports done:", json.dumps(monthly, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
