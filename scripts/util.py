# -*- coding: utf-8 -*-
"""共用工具：JSON 读写、git 提交、日期。"""
import json
import os
import subprocess
import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")


def load_json(name: str, default=None):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(name: str, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_config(name: str, default=None):
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git_push(message: str):
    """供 Actions 使用：提交 data/ 变更。失败不抛异常（本地调试时无 git remote）"""
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("[warn] not a git work tree; git push skipped")
            return
        subprocess.run(["git", "config", "user.name", "data-bot"], check=True)
        subprocess.run(["git", "config", "user.email", "bot@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "data/"], check=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if r.returncode != 0:
            subprocess.run(["git", "commit", "-m", message], check=True)
            subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"[warn] git push skipped: {e}")


def today_str():
    return datetime.date.today().isoformat()
