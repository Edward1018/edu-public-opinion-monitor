#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育舆情监测 · 采集助手（仅标准库，无依赖）

配合 SKILL.md 的「逐源采集循环」使用：agent 对每个信息源做 WebSearch/WebFetch
后，用本脚本把结果规范写入 data/YYYY-MM-DD_raw.json，避免手工拼 JSON 出错。

用法:
    # 1) 新建当日采集骨架
    python scripts/collect.py new 2026-08-20

    # 2) 逐条追加（自动按 title 去重；L3 必须带 dimension 字段）
    python scripts/collect.py add 2026-08-20 --item '{"layer":"L1","source":"教育部官网","url":"http://...","title":"...","summary":"...","pub_date":"2026-08-15","heat":5}'
    python scripts/collect.py add 2026-08-20 --item '{"layer":"L3","source":"小红书","dimension":"高热笔记","url":"https://www.xiaohongshu.com/search_result?keyword=...","title":"...","summary":"...","pub_date":"2026-08-16","heat":4}'

    # 3) 查看当前进度
    python scripts/collect.py status 2026-08-20

字段说明:
    layer     : L1 / L2 / L3
    source    : 必须与 config/sources.json 中某源的 name 完全一致（L3 可统一写“小红书”）
    dimension : 仅 L3 需要，取 sources.json L3 四维度之一
                （关键词搜索 / 高热笔记 / 同类账号 / 评论区）
    url       : 真实可点击来源链接（邮件/网页均依赖它）
    title     : 条目标题
    summary   : 一句话摘要
    pub_date  : 发布日期 YYYY-MM-DD（落在展示窗口内才会进主榜）
    heat      : 编辑基准热 1-5（新政策默认 5；高热舆情 4-5）
"""
import json
import os
import sys
import argparse
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")


def path_of(date):
    return os.path.join(DATA_DIR, f"{date}_raw.json")


def new(date):
    p = path_of(date)
    if os.path.exists(p):
        print(f"[WARN] 已存在: {p}（如需重置请先删除）")
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"date": date, "note": "采集自 collect.py", "items": []},
                  f, ensure_ascii=False, indent=2)
    print(f"[OK] 已创建骨架: {p}")


def load(date):
    p = path_of(date)
    if not os.path.exists(p):
        print(f"[ERROR] 不存在: {p}，请先 `collect.py new {date}`")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def add(date, item):
    raw = load(date)
    items = raw.setdefault("items", [])
    key = (item.get("title") or "").strip().lower()
    if key and any((it.get("title") or "").strip().lower() == key for it in items):
        print("[SKIP] 重复条目，已忽略")
        return
    layer = item.get("layer")
    if layer == "L3" and not item.get("dimension"):
        print("[WARN] L3 条目缺少 dimension（关键词搜索/高热笔记/同类账号/评论区），已补默认『高热笔记』")
        item["dimension"] = "高热笔记"
    items.append(item)
    with open(path_of(date), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已追加（共 {len(items)} 条）: {item.get('title', '')[:40]}")


def status(date):
    raw = load(date)
    c = Counter(it.get("layer") for it in raw.get("items", []))
    l3d = Counter(it.get("dimension") for it in raw.get("items", []) if it.get("layer") == "L3")
    print(f"日期 {date}: 共 {len(raw.get('items', []))} 条  "
          f"L1 {c.get('L1', 0)} / L2 {c.get('L2', 0)} / L3 {c.get('L3', 0)}")
    if l3d:
        print("  L3 维度: " + "  ".join(f"{k or '未标注'} {v}" for k, v in l3d.items()))


def main():
    ap = argparse.ArgumentParser(description="教育舆情采集助手")
    sub = ap.add_subparsers(dest="cmd")
    p_new = sub.add_parser("new"); p_new.add_argument("date")
    p_add = sub.add_parser("add"); p_add.add_argument("date"); p_add.add_argument("--item", required=True)
    p_st = sub.add_parser("status"); p_st.add_argument("date")
    args = ap.parse_args()
    if args.cmd == "new":
        new(args.date)
    elif args.cmd == "add":
        try:
            item = json.loads(args.item)
        except Exception as e:
            print(f"[ERROR] --item 不是合法 JSON: {e}")
            sys.exit(1)
        add(args.date, item)
    elif args.cmd == "status":
        status(args.date)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
