# -*- coding: utf-8 -*-
"""signals.py 规则引擎分支自测（验收标准第2条）。

构造多组 latest.json/manual.json，验证 signals.json 的 score/verdict/status 分支。
运行：python scripts/selftest_signals.py
"""
import os
import tempfile
import shutil

import util

CASES = []


def case(name, latest, manual, expect_score, expect_verdict, expect_statuses=None):
    CASES.append((name, latest, manual, expect_score, expect_verdict, expect_statuses or []))


def run_all():
    tmp = tempfile.mkdtemp(prefix="pig_selftest_")
    try:
        import signals
        failed = 0
        for name, latest, manual, exp_score, exp_verdict, exp_statuses in CASES:
            util.DATA_DIR = tmp
            util.save_json("latest.json", latest)
            util.save_json("manual.json", manual)
            signals.main()
            sig = util.load_json("signals.json")
            ok = (sig.get("score") == exp_score
                  and sig.get("verdict") == exp_verdict)
            if exp_statuses:
                actual = [s["status"] for s in sig.get("signals", [])]
                ok = ok and actual == exp_statuses
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: "
                  f"score={sig.get('score')} verdict={sig.get('verdict')}"
                  + (f" statuses={actual}" if exp_statuses else ""))
            if not ok:
                failed += 1
        return failed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    # 场景1：全部数据缺失 → 全灰，下行/出清
    case("全数据缺失", {}, {}, "0/6", "下行/出清阶段",
         ["gray"] * 6)

    # 场景2：所有信号满足 → 拐点确认区
    case("全部满足", {
        "spot_pig": 15.2, "pig_grain_ratio": 6.8,
        "derived": {"lh_far_near_spread": 420},
    }, {
        "sow": {"mom_pct": -1.8, "holding_pct": 93.5, "need_review": False},
        "weekly_indicators": {"u1": {"frozen_capacity_pct": 52, "need_review": False}},
    }, "6/6", "拐点确认区", ["green"] * 6)

    # 场景3：3个信号满足 → 磨底观察中
    case("部分满足", {
        "spot_pig": 15.2, "pig_grain_ratio": 6.8,
        "derived": {"lh_far_near_spread": -120},
    }, {
        "sow": {"mom_pct": -2.0, "holding_pct": 97, "need_review": False},
        "weekly_indicators": {"u1": {"frozen_capacity_pct": 65, "need_review": False}},
    }, "3/6", "磨底观察中",
        ["green", "yellow", "green", "green", "yellow", "yellow"])

    # 场景4：能繁母猪 need_review=True → 产能信号不参与计算（灰态）
    case("sow待复核", {
        "spot_pig": 15.2, "pig_grain_ratio": 6.8,
        "derived": {"lh_far_near_spread": 420},
    }, {
        "sow": {"mom_pct": -1.8, "holding_pct": 93.5, "need_review": True},
        "weekly_indicators": {"u1": {"frozen_capacity_pct": 52, "need_review": True}},
    }, "3/6", "磨底观察中",
        ["gray", "gray", "green", "green", "green", "gray"])

    # 场景5：周报复核通过后冻品信号启用；未复核保持灰
    case("周报复核启用", {
        "spot_pig": 15.2, "pig_grain_ratio": 6.8,
        "derived": {"lh_far_near_spread": 420},
    }, {
        "sow": {"mom_pct": -1.8, "holding_pct": 93.5, "need_review": False},
        "weekly_indicators": {
            "u1": {"frozen_capacity_pct": 62, "need_review": True},
            "u2": {"frozen_capacity_pct": 58, "need_review": False},
        },
    }, "6/6", "拐点确认区",
        ["green", "green", "green", "green", "green", "green"])

    failed = run_all()
    print("-" * 40)
    print(f"selftest {'ALL PASS' if failed == 0 else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
