#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育舆情监测 · 邮件版报告生成器
复用 generate_report.py 的数据处理与热点模型，输出「内联样式」HTML，
可直接作为 QQ邮箱 body（body_format=HTML）发送，手机端也能正常渲染，
且每条舆情标题均为可点击超链接（<a href>）。

用法:
    python scripts/build_email.py [YYYY-MM-DD] [--days 7] [--top 5] [--min-heat 3]
若不传日期，默认取 generate_report 的日期逻辑（脚本内 today_str 兼容）。
输出: output/YYYY-MM-DD_email.html（同时打印到 stdout 供工具调用读取）
"""
import os
import sys
import html
import importlib.util
import datetime
import argparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BASE, "scripts")
DATA_DIR = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "output")

# 动态加载 generate_report 模块，复用其数据处理函数与热点模型
_spec = importlib.util.spec_from_file_location(
    "gr", os.path.join(SCRIPTS_DIR, "generate_report.py"))
gr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gr)

LAYER_NAME = gr.LAYER_NAME
CFG_LAYER_MAP = gr.CFG_LAYER_MAP
NATIONAL_SOURCES = {"教育部官网", "国务院政策文件库"}


def build_report(date, days=7, top=5, min_heat=3):
    """复制 generate_report.main 的流水线，返回与网页版一致的 report 字典。"""
    raw_path = os.path.join(DATA_DIR, f"{date}_raw.json")
    kw_path = os.path.join(BASE, "config", "keywords.json")
    src_path = os.path.join(BASE, "config", "sources.json")
    if not os.path.exists(raw_path):
        print(f"[ERROR] 未找到原始数据: {raw_path}")
        sys.exit(1)
    raw = gr.load_json(raw_path)
    kw_cfg = gr.load_json(kw_path)
    categories = kw_cfg.get("categories", {})
    src_cfg = gr.load_json(src_path) if os.path.exists(src_path) else {}

    all_items = gr.dedupe(raw.get("items", []))
    all_sources = [it.get("source", "") for it in all_items]
    layer_item_counts = {}
    for it in all_items:
        lid = it.get("layer", "L?")
        layer_item_counts[lid] = layer_item_counts.get(lid, 0) + 1
    coverage = gr.build_coverage(src_cfg, all_sources, layer_item_counts)

    d = gr.parse_date(date)
    if d is None:
        print(f"[ERROR] 无法解析日期: {date}")
        sys.exit(1)
    start = d - datetime.timedelta(days=days - 1)
    end = d
    window_items = []
    for it in all_items:
        pd = gr.parse_date(it.get("pub_date", ""))
        if pd is None:
            continue
        if start <= pd <= end:
            window_items.append(it)

    for it in all_items:
        it["_cats"] = gr.categorize(it, categories)
        it["_kws"] = gr.match_keywords(it, categories)

    kw_sources = {}
    for it in window_items:
        for kw in it["_kws"]:
            kw_sources.setdefault(kw, set()).add(it.get("source"))
    for it in all_items:
        others = set()
        for kw in it["_kws"]:
            others |= kw_sources.get(kw, set())
        others.discard(it.get("source"))
        it["_cross"] = len(others)
        final, bd = gr.compute_heat(it, it["_cross"])
        it["_heat_final"] = final
        it["_heat_bd"] = bd
        it["_multisource"] = it["_cross"] >= 2

    heat = gr.keyword_heat(window_items, categories)

    displayed = []
    layer_stats = {"L1": 0, "L2": 0, "L3": 0}

    def _sort_key(x):
        return (gr.parse_date(x.get("pub_date", "")) or datetime.date.min,
                x.get("_heat_final", int(x.get("heat", 1))))

    for lid in ["L1", "L2", "L3"]:
        group = [it for it in window_items if it.get("layer") == lid]
        group = [it for it in group
                 if it.get("_heat_final", int(it.get("heat", 1))) >= min_heat]
        group.sort(key=_sort_key, reverse=True)
        if lid == "L1" and group:
            topg = group[:top]
            has_national = any(it.get("source") in NATIONAL_SOURCES for it in topg)
            if not has_national:
                nat_pool = [it for it in group if it.get("source") in NATIONAL_SOURCES]
                if nat_pool:
                    weakest = min(topg, key=lambda x: (x.get("_heat_final", int(x.get("heat", 1))),
                                                       gr.parse_date(x.get("pub_date", "")) or datetime.date.min))
                    idx = topg.index(weakest)
                    topg[idx] = nat_pool[0]
                    topg.sort(key=_sort_key, reverse=True)
            group = topg
        group = group[:top]
        displayed.extend(group)
        layer_stats[lid] = len(group)

    ext_start = start - datetime.timedelta(days=23)
    extension = []
    for it in all_items:
        pd = gr.parse_date(it.get("pub_date", ""))
        if pd is None or not (ext_start <= pd < start):
            continue
        bd = it.get("_heat_bd", {})
        if bd.get("eng_boost", 0) >= 1 or bd.get("cross_count", 0) >= 2:
            it["_ext_reason"] = "高互动" if bd.get("eng_boost", 0) >= 1 else "多源印证"
            extension.append(it)
    extension.sort(key=lambda x: (x.get("_heat_final", 0),
                                  gr.parse_date(x.get("pub_date", "")) or datetime.date.min),
                   reverse=True)
    extension = extension[:5]

    stats = {
        "total": len(displayed),
        "L1": layer_stats["L1"],
        "L2": layer_stats["L2"],
        "L3": layer_stats["L3"],
        "multi": sum(1 for it in displayed if it.get("_multisource")),
        "extension": len(extension),
    }
    method_text = (
        "综合热度(1-5) = 编辑基准热 + 跨源印证加权 + 互动量加权 - 互动量降权，四者透明可见："
        "编辑基准热：采集时人工评定（新政策默认高）；"
        "跨源印证：与本条共享关键词的其他独立信息源 ≥2 个 +1，≥4 个 +2；"
        "互动量加权：阅读≥2000 / 点赞≥200 / 收藏≥500 +1，阅读≥10000 / 点赞≥1000 +2；"
        "互动量降权：标记为 low，或 阅读<500 / 点赞<100 → -1。"
        "置信度：强热点(跨源+高互动) / 多源印证 / 高互动 / 低互动 / 常规。"
        "主榜仅取近 {days} 天窗口内综合热度≥{mh} 的条目；超出窗口但互动量高/多源印证的硬货，"
        "单独进入「高互动延展关注」区。"
    ).format(days=days, mh=min_heat)
    return {
        "date": date, "window": (start.isoformat(), end.isoformat()),
        "displayed": displayed, "categories": categories, "keyword_heat": heat,
        "extension": extension, "stats": stats, "coverage": coverage,
        "min_heat": min_heat, "top_n": top, "method": method_text,
    }


def render_email_item(it):
    """单条舆情卡片（内联样式，标题为可点击超链接）。"""
    title = html.escape(it.get("title", "(无标题)"))
    url = it.get("url", "")
    src = html.escape(it.get("source", ""))
    pub = html.escape(it.get("pub_date", ""))
    bd = it.get("_heat_bd", {}) or {}
    heat_n = bd.get("final", int(it.get("heat", 1)))
    stars = "🔥" * max(0, min(5, heat_n))
    conf = bd.get("confidence", "常规")
    conf_color = {"强热点": "#22543d", "多源印证": "#b7791f", "高互动": "#2b6cb0",
                  "低互动": "#c53030", "常规": "#667"}.get(conf, "#667")

    badges = ""
    if bd.get("cross_count", 0) >= 2:
        badges += (' <span style="display:inline-block;font-size:11px;background:#fffaf0;'
                   'color:#b7791f;border:1px solid #f6e05e;border-radius:4px;padding:1px 6px;'
                   f'margin-left:6px">🔗 多源印证×{bd.get("cross_count")}</span>')
    if bd.get("eng_boost", 0) >= 1:
        badges += (' <span style="display:inline-block;font-size:11px;background:#ebf8ff;'
                   'color:#2b6cb0;border:1px solid #90cdf4;border-radius:4px;padding:1px 6px;'
                   'margin-left:6px">📈 高互动</span>')
    if bd.get("eng_penalty", 0) >= 1:
        badges += (' <span style="display:inline-block;font-size:11px;background:#fff5f5;'
                   'color:#c53030;border:1px solid #feb2b2;border-radius:4px;padding:1px 6px;'
                   'margin-left:6px">⚠️ 低互动</span>')
    badges += (f' <span style="display:inline-block;font-size:11px;background:#f0f2f5;'
               f'color:{conf_color};border:1px solid #e2e8f0;border-radius:4px;'
               f'padding:1px 6px;margin-left:6px">{conf}</span>')

    bd_text = (f"热度拆解：基准 {bd.get('editorial', int(it.get('heat', 1)))} "
               f"+跨源 {bd.get('cross_boost', 0)} +互动 {bd.get('eng_boost', 0)} "
               f"−降权 {bd.get('eng_penalty', 0)} = {heat_n}")
    eng = it.get("engagement")
    eng_text = ""
    if isinstance(eng, dict):
        parts = []
        for k, lbl in (("reads", "阅读"), ("likes", "赞"), ("saves", "藏"), ("comments", "评")):
            if eng.get(k) is not None:
                parts.append(f"{lbl} {eng[k]}")
        if parts:
            eng_text = " ｜ " + " · ".join(parts)
    tags = "".join(
        f'<span style="display:inline-block;font-size:11px;background:#ebf4ff;color:#2b6cb0;'
        f'border-radius:4px;padding:2px 7px;margin:3px 4px 0 0">{html.escape(t)}</span>'
        for t in it.get("_cats", []))
    if url:
        link = (f'<a href="{html.escape(url)}" style="color:#1a73e8;text-decoration:underline;'
                f'font-size:15px;font-weight:600">{title}</a>')
    else:
        link = f'<span style="font-size:15px;font-weight:600">{title}</span>'
    ext = it.get("_ext_reason")
    ext_tag = (f' <span style="display:inline-block;font-size:11px;background:#faf5ff;'
               f'color:#6b46c1;border:1px solid #d6bcfa;border-radius:4px;padding:1px 6px;'
               f'margin-left:6px">📌 延展·{html.escape(ext)}</span>') if ext else ""

    return (
        f'<div style="padding:12px 0;border-bottom:1px solid #eef0f3">'
        f'{stars} {link}{badges}{ext_tag}'
        f'<div style="font-size:12px;color:#889;margin-top:4px">【{src}】{pub}</div>'
        f'<div style="font-size:11.5px;color:#7a8699;margin:5px 0 2px">{bd_text}{eng_text}</div>'
        f'<div style="font-size:13px;color:#445;margin:6px 0;line-height:1.6">'
        f'{html.escape(it.get("summary", ""))}</div>'
        f'<div>{tags}</div></div>'
    )


def render_email_coverage(coverage):
    blocks = ""
    for c in coverage:
        pct = int(round(100 * c["covered"] / c["total"])) if c["total"] else 0
        rows = ""
        for s in c["sources"]:
            badge = "✅ 已采集" if s["covered"] else "⬜ 未覆盖"
            bcolor = "#0f766e" if s["covered"] else "#c0392b"
            bbg = "#e6fffa" if s["covered"] else "#fff5f5"
            rows += (f'<span style="display:inline-block;font-size:12.5px;width:46%;min-width:220px;'
                     f'color:#334">'
                     f'<span style="display:inline-block;font-size:11px;border-radius:4px;'
                     f'padding:1px 6px;margin-right:6px;background:{bbg};color:{bcolor}">{badge}</span>'
                     f'{html.escape(s["name"])}</span>')
        blocks += (
            f'<div style="background:#fff;border-radius:10px;padding:14px 16px;margin:12px 0;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="font-size:15px;font-weight:600;margin-bottom:8px">'
            f'{html.escape(c["layer_name"])} '
            f'<span style="font-size:12px;color:#556;font-weight:400">'
            f'{c["covered"]}/{c["total"]}（{pct}%）</span></div>'
            f'<div>{rows}</div></div>'
        )
    return blocks


def render_email_html(report, compact=False):
    date = report["date"]
    window = report["window"]
    cats = report["categories"]
    heat = report["keyword_heat"]
    stats = report["stats"]
    coverage = report["coverage"]
    min_heat = report["min_heat"]
    top_n = report["top_n"]

    by_layer = {}
    for it in report["displayed"]:
        by_layer.setdefault(it.get("layer", "L?"), []).append(it)

    maxc = max([v["count"] for v in heat.values()], default=1) or 1
    heat_rows = ""
    for kw, v in sorted(heat.items(), key=lambda x: -x[1]["count"]):
        w = int(round(100 * v["count"] / maxc))
        heat_rows += (
            f'<div style="display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px">'
            f'<span style="width:170px;display:flex;align-items:center;gap:6px">'
            f'{html.escape(kw)}'
            f'<span style="font-size:11px;background:#eef2f7;color:#556;border-radius:4px;'
            f'padding:1px 5px">{html.escape(v["category"])}</span></span>'
            f'<span style="flex:1;background:#eef2f7;border-radius:6px;height:14px;overflow:hidden">'
            f'<i style="display:block;height:100%;width:{w}%;'
            f'background:#ed8936"></i></span>'
            f'<span style="width:28px;text-align:right;color:#667">{v["count"]}</span></div>'
        )
    if not heat_rows:
        heat_rows = '<div style="color:#99a;font-size:13px">本窗口内无关键词命中</div>'

    layer_blocks = ""
    for lid in ["L1", "L2", "L3"]:
        group = by_layer.get(lid, [])
        if not group:
            continue
        rows = "".join(render_email_item(it) for it in group)
        layer_blocks += (
            f'<div style="background:#fff;border-radius:10px;padding:14px 18px;margin:12px 0;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            f'<div style="font-size:16px;font-weight:600;margin-bottom:6px;'
            f'border-left:4px solid #38a169;padding-left:10px">'
            f'{html.escape(LAYER_NAME.get(lid, lid))}'
            f'<span style="font-size:12px;color:#889;font-weight:400;margin-left:8px">'
            f'综合热度 Top{top_n} · 共 {len(group)} 条</span></div>'
            f'<div>{rows}</div></div>'
        )

    ext_items = report.get("extension", [])
    ext_html = ""
    if ext_items:
        ext_rows = "".join(render_email_item(it) for it in ext_items)
        ext_html = (
            f'<div style="border:1px dashed #b794f4;background:#faf8ff;border-radius:10px;'
            f'padding:14px 18px;margin:12px 0">'
            f'<div style="font-size:16px;font-weight:600;margin-bottom:6px;'
            f'border-left:4px solid #805ad5;padding-left:10px">📌 高互动延展关注'
            f'<span style="font-size:12px;color:#889;font-weight:400;margin-left:8px">'
            f'窗口外(8~30天) · 共 {len(ext_items)} 条</span></div>'
            f'<div>{ext_rows}</div></div>'
        )

    # 自动生成「关注点」（中性监测提示，不含内容运营/选题建议）
    wps = gr.build_watchpoints(report)
    wp_html = ""
    if wps:
        wp_rows = ""
        for lvl, txt in wps:
            color = {"高": "#c53030", "中": "#b7791f", "低": "#667"}.get(lvl, "#667")
            bg = {"高": "#fff5f5", "中": "#fffaf0", "低": "#f0f2f5"}.get(lvl, "#f0f2f5")
            wp_rows += (
                '<div style="display:flex;gap:10px;align-items:flex-start;margin:8px 0;'
                'font-size:13px;color:#334;line-height:1.6">'
                f'<span style="display:inline-block;font-size:11px;border-radius:4px;padding:1px 7px;'
                f'background:{bg};color:{color};white-space:nowrap;margin-top:2px">{lvl}</span>'
                f'<span>{html.escape(txt)}</span></div>'
            )
        wp_html = (
            '<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;'
            'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            '<div style="font-size:16px;font-weight:600;margin:0 0 12px;border-left:4px solid #2b6cb0;'
            'padding-left:10px">🔍 关注点（自动生成，仅供参考）</div>' + wp_rows + '</div>'
        )
    else:
        wp_html = (
            '<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;'
            'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
            '<div style="font-size:16px;font-weight:600;margin:0 0 12px;border-left:4px solid #2b6cb0;'
            'padding-left:10px">🔍 关注点</div>'
            '<div style="color:#99a;font-size:13px">本窗口暂无明显关注点。</div></div>'
        )

    cov_html = render_email_coverage(coverage)
    cov_block = (
        '<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;'
        'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
        '<div style="font-size:16px;font-weight:600;margin:0 0 12px;border-left:4px solid #2b6cb0;'
        'padding-left:10px">📡 信息源覆盖情况（对照 sources.json）</div>' + cov_html + '</div>'
    ) if not compact else ""
    heat_block = (
        '<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;'
        'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
        '<div style="font-size:16px;font-weight:600;margin:0 0 12px;border-left:4px solid #2b6cb0;'
        'padding-left:10px">🔥 热点关键词命中</div>' + heat_rows + '</div>'
    ) if not compact else ""
    method_block = (
        '<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;'
        'box-shadow:0 1px 3px rgba(0,0,0,.06)">'
        '<div style="font-size:16px;font-weight:600;margin:0 0 12px;border-left:4px solid #2b6cb0;'
        'padding-left:10px">🔥 热点评估方法</div>'
        '<div style="color:#7a8699;font-size:13px">' + html.escape(report.get('method', ''))
        + '</div></div>'
    ) if not compact else ""
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f5f7fa;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2933">
<div style="background:#2b6cb0;color:#fff;padding:22px 28px">
<div style="font-size:22px;font-weight:700;margin:0">📊 教育舆情监测周报</div>
<div style="opacity:.85;margin-top:6px;font-size:13px">日期：{date} ｜ 展示窗口：{window[0]} ~ {window[1]}（每层 Top{top_n}·综合热度≥{min_heat}）｜ 自动生成</div>
</div>
<div style="max-width:1060px;margin:0 auto;padding:20px">
<div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0">
<div style="flex:1;min-width:140px;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)"><div style="font-size:26px;font-weight:700;color:#2b6cb0">{stats['total']}</div><div style="font-size:12px;color:#667">本窗口合计</div></div>
<div style="flex:1;min-width:140px;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)"><div style="font-size:26px;font-weight:700;color:#2b6cb0">{stats['L1']}</div><div style="font-size:12px;color:#667">政策源头</div></div>
<div style="flex:1;min-width:140px;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)"><div style="font-size:26px;font-weight:700;color:#2b6cb0">{stats['L2']}</div><div style="font-size:12px;color:#667">行业动态</div></div>
<div style="flex:1;min-width:140px;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)"><div style="font-size:26px;font-weight:700;color:#2b6cb0">{stats['L3']}</div><div style="font-size:12px;color:#667">小红书舆情</div></div>
</div>
<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)">{cov_block}</div>
<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)">{heat_block}</div>
<div style="background:#fff;border-radius:10px;padding:18px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)">{method_block}</div>
{layer_blocks}
{ext_html}
{wp_html}
<div style="text-align:center;color:#aab;font-size:12px;padding:20px">教育舆情监测系统 · 生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>
</body></html>"""
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=gr.today_str())
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-heat", type=int, default=3)
    ap.add_argument("--compact", action="store_true",
                    help="精简模式：仅保留三层舆情条目与延展区（含超链接），"
                         "省略覆盖/关键词/方法面板，便于邮件直接内联发送")
    args = ap.parse_args()

    report = build_report(args.date, args.days, args.top, args.min_heat)
    doc = render_email_html(report, compact=args.compact)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{args.date}_email.html")
    # 1) 属性改为单引号，避免邮件 body(JSON) 中双引号转义导致调用失败
    doc = doc.replace('"', "'")
    # 2) 在标签边界处换行，保证单行 < 2000 字符，便于阅读/核对且不截断
    wrapped = doc.replace("><", ">\n<")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    print(f"[OK] 邮件版HTML已生成: {out_path} ({len(wrapped)} bytes)")


if __name__ == "__main__":
    main()
