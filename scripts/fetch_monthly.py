# -*- coding: utf-8 -*-
"""每月 15 日运行：从农业农村部公告提取能繁母猪存栏。

风控链：正则提取 → 数值范围校验(3000~4500万头) → LLM 结果默认 need_review。
"""
import os
import re
import json
import html as html_mod
import requests
from util import load_json, save_json, git_push, today_str

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
SOW_MIN, SOW_MAX = 3000, 4500  # 万头，合理性校验区间
NORMAL_HOLDING = 3750          # 政策正常保有量（万头）

# 农业农村部新闻栏目列表页（近30天文章会出现在前若干页）
# 注：moa 站内搜索为 JS 动态渲染，静态抓取不可用，故退化为遍历栏目列表页；
# 若当月无"生猪+存栏"标题文章则返回空串，由人工在浏览器检索后补录。
MOA_LIST_URLS = [
    "http://www.moa.gov.cn/xw/zwdt/",   # 政务动态
    "http://www.moa.gov.cn/xw/bmdt/",   # 部门动态
    "http://www.moa.gov.cn/gk/tzgg_1/", # 通知公告
    "http://www.moa.gov.cn/xw/gg/",     # 公告
    "http://www.moa.gov.cn/xw/szyw/",   # 时政要闻
]
MOA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def _get_text(url: str) -> str:
    r = requests.get(url, headers=MOA_HEADERS, timeout=30)
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def fetch_moa_announcement() -> str:
    """抓取农业农村部"生猪生产情况"类公告正文。

    策略：遍历栏目列表页，找标题同时含"生猪/能繁母猪"与"存栏"的近30天文章，
    取正文纯文本。页面结构不稳定时返回空串，由 workflow 侧提示人工补录。
    """
    import datetime
    limit_date = (datetime.date.today() - datetime.timedelta(days=35)).isoformat()
    for list_url in MOA_LIST_URLS:
        try:
            text = _get_text(list_url)
        except Exception as e:
            print(f"[warn] moa list {list_url} failed: {e}")
            continue
        # 抓文章链接：href + 标题
        links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I)
        for href, title in links:
            title_clean = html_mod.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if not (("生猪" in title_clean or "能繁母猪" in title_clean)
                    and "存栏" in title_clean):
                continue
            url = href if href.startswith("http") else (
                "http://www.moa.gov.cn" + href if href.startswith("/") else
                list_url.rstrip("/") + "/" + href.lstrip("./"))
            try:
                art = _get_text(url)
            except Exception as e:
                print(f"[warn] moa article {url} failed: {e}")
                continue
            # 正文容器优先取 #zoom，退化取全部 <p>
            body = ""
            m = re.search(r'<div[^>]+id=["\']zoom["\'][^>]*>(.*?)</div>', art, re.S | re.I)
            seg = m.group(1) if m else art
            paras = [html_mod.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                     for p in re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S | re.I)]
            body = "\n".join(p for p in paras if p)
            if not body:
                body = html_mod.unescape(re.sub(r"<[^>]+>", " ", seg))
            # 日期过滤：正文或标题带发布日期，简单按正文是否提到存栏判定
            if "存栏" not in body and "存栏" not in title_clean:
                continue
            print(f"[info] moa article found: {title_clean} ({url})")
            return body[:20000]
    print("[warn] no moa announcement fetched; skipped")
    return ""


def regex_extract(text: str):
    patterns = [
        r"能繁母猪存栏[为约达]?([\d.]+)\s*万头",
        r"能繁母猪[为约达]?([\d.]+)\s*万头",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    return None


def llm_extract(text: str) -> dict:
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "deepseek-chat",
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content":
                 "从农业农村部的生猪生产公告中提取数据，只输出JSON。"
                 'schema: {"sow_wan": number|null, "mom_pct": number|null, '
                 '"yoy_pct": number|null, "holding_pct": number|null}。'
                 "sow_wan=能繁母猪期末存栏(万头)；mom_pct=环比(%)；"
                 "yoy_pct=同比(%)；holding_pct=占正常保有量比例(%)。"},
                {"role": "user", "content": text[:8000]}
            ],
        }, timeout=60)
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def main():
    text = fetch_moa_announcement()
    if not text.strip():
        print("[warn] no announcement fetched; skipped")
        return

    val = regex_extract(text)
    manual = load_json("manual.json", {})
    if val is not None and SOW_MIN < val < SOW_MAX:
        rec = {"sow_wan": val, "source": "regex",
               "need_review": False, "date": today_str()}
    elif API_KEY:
        try:
            out = llm_extract(text)
        except Exception as e:
            print(f"[warn] llm extract failed: {e}")
            out = {}
        val = out.get("sow_wan")
        if val is None or not (SOW_MIN < val < SOW_MAX):
            rec = {"sow_wan": None, "source": "llm",
                   "need_review": True, "date": today_str(),
                   "raw": out, "note": "LLM提取值越界或为空，需人工核对"}
        else:
            rec = {"sow_wan": val, "mom_pct": out.get("mom_pct"),
                   "holding_pct": out.get("holding_pct"),
                   "source": "llm", "need_review": True, "date": today_str()}
    else:
        rec = {"sow_wan": None, "source": "none",
               "need_review": True, "date": today_str()}

    rec["holding_pct"] = rec.get("holding_pct") or (
        round(val / NORMAL_HOLDING * 100, 1) if val else None)
    manual["sow"] = rec
    save_json("manual.json", manual)
    git_push(f"data: sow {today_str()}")
    print("sow record:", rec)


if __name__ == "__main__":
    main()
