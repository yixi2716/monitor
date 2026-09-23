# -*- coding: utf-8 -*-
"""一次性：把能繁母猪季度历史并入 manual.json（供待复核）并同步 site/data。"""
import json
import os
import datetime

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


manual = load_json(os.path.join(DATA, "manual.json"))
manual["sow"] = {
    "sow_wan": 3780,
    "mom_pct": -3.2,
    "yoy_pct": -6.5,
    "holding_pct": 100.8,
    "source": "manual-backfill",
    "need_review": True,
    "date": datetime.date.today().isoformat(),
    "data_date": "2026-06-30",
    "note": "农业农村部二季度末全国能繁母猪存栏3780万头（环比约-3.2%，同比-6.5%）。核对官方原文后把 need_review 改为 false 即点亮信号。"
}
save_json(os.path.join(DATA, "manual.json"), manual)
save_json(os.path.join(SITE_DATA, "manual.json"), manual)
print("manual.sow updated:", json.dumps(manual["sow"], ensure_ascii=False))
