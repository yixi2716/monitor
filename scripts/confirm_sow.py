# -*- coding: utf-8 -*-
"""一次性：确认能繁母猪数据（need_review=false）+ 录入冻品库容周报 → 点亮信号。"""
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

# 1) 能繁母猪：官方数据已核对（农业农村部发布会 2026-07-24）
sow = manual.get("sow", {})
sow["need_review"] = False
sow["source"] = "农业农村部国新办发布会"
sow["note"] = "农业农村部二季度末全国能繁母猪存栏3780万头（环比约-3.2%，同比-6.5%）。已人工核对官方原文。"
manual["sow"] = sow

# 2) 冻品库容：华金期货周报 2026-09-14（8月数据）
manual.setdefault("weekly_indicators", {})
manual["weekly_indicators"]["frozen_202608"] = {
    "frozen_capacity_pct": 32.28,
    "need_review": False,
    "date": datetime.date.today().isoformat(),
    "data_date": "2026-08-31",
    "source": "华金期货周报 2026-09-14",
    "note": "8月冻品库容率32.28%，来源华金期货生猪周报。"
}

save_json(os.path.join(DATA, "manual.json"), manual)
save_json(os.path.join(SITE_DATA, "manual.json"), manual)
print("manual updated: sow.need_review=false, frozen=32.28")
