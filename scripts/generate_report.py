#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育舆情监测 · 监测周报生成器（仅标准库，无依赖）
读取当日采集的原始数据 data/YYYY-MM-DD_raw.json 与关键词库 config/keywords.json，
完成去重、近N日过滤、关键词分类、热度统计，输出 output/YYYY-MM-DD_report.html / .md。

特性：
  - 仅展示「近 N 日」（默认 7 天）信息
  - 每层按 pub_date 由新到旧排序，仅展示最新 top-N 条「高热度」内容
    （高热度阈值 --min-heat，默认 3；L1 新政策内容默认高热度）
  - 新增「信息源覆盖情况」面板，对照 config/sources.json 标注每个渠道是否已采集

仅依赖 Python 标准库。
用法:
    python scripts/generate_report.py [YYYY-MM-DD] [--days 7] [--top 5] [--min-heat 3]
若省略日期，默认取今天（本地时区）。
"""
import json
import os
import re
import sys
import html
import argparse
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE, "config")
DATA_DIR = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "output")

LAYER_NAME = {
    "L1": "政策源头（官方信息）",
    "L2": "行业动态（大V/机构/公众号）",
    "L3": "小红书生态（舆情/爆款）",
}
# config/sources.json 中的 layer key -> 展示层 id
CFG_LAYER_MAP = {"L1_policy": "L1", "L2_industry": "L2", "L3_xiaohongshu": "L3"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def parse_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def normalize(s):
    return (s or "").strip().lower()


def dedupe(items):
    seen = {}
    order = []
    for it in items:
        key = normalize(it.get("title")) or normalize(it.get("url")) or normalize(it.get("summary"))
        if not key:
            continue
        if key in seen:
            old = seen[key]
            merged = dict(old)
            for k, v in it.items():
                if v and not old.get(k):
                    merged[k] = v
            seen[key] = merged
        else:
            seen[key] = dict(it)
            order.append(key)
    return [seen[k] for k in order]


def categorize(item, categories):
    text = ((item.get("title", "") or "") + " " + (item.get("summary", "") or "")).lower()
    matched = []
    for cat, kws in categories.items():
        for kw in kws:
            if kw.lower() in text:
                matched.append(cat)
                break
    return matched


def match_keywords(item, categories):
    """返回该条目命中的全部关键词（用于跨源印证统计）。"""
    text = ((item.get("title", "") or "") + " " + (item.get("summary", "") or "")).lower()
    kws = []
    for cat, lst in categories.items():
        for kw in lst:
            if kw.lower() in text:
                kws.append(kw)
    return kws


def compute_heat(it, cross_count, min_cross=2,
                 low_reads=500, low_likes=100,
                 high_reads=2000, high_likes=200):
    """综合热度（1-5），互动量**双向**作用，并返回拆解明细。

    - editorial   : 采集时人工基准热（新政策默认高）
    - cross_boost : 跨源印证（共享关键词的其他独立源 >=2 → +1； >=4 → +2）
    - eng_boost   : 互动量加权（reads>=2000 / likes>=200 / saves>=500 → +1；
                    reads>=10000 / likes>=1000 → +2）
    - eng_penalty : 互动量降权（标记为 "low"，或 reads<500 / likes<100 → -1）

    关键修正：互动量既会“降权”也会“加权”——一篇阅读 2000+ 但编辑基准热
    偏低的单源文章，现在会因 eng_boost 上浮而入选，不再被误杀。
    """
    editorial = int(it.get("heat", 3))
    if cross_count >= 4:
        cross_boost = 2
    elif cross_count >= min_cross:
        cross_boost = 1
    else:
        cross_boost = 0

    eng = it.get("engagement")
    eng_boost = 0
    eng_penalty = 0
    if eng == "low":
        eng_penalty = 1
    elif isinstance(eng, dict):
        r = eng.get("reads")
        lk = eng.get("likes")
        sv = eng.get("saves")
        if r is not None:
            if r >= 10000:
                eng_boost = max(eng_boost, 2)
            elif r >= high_reads:
                eng_boost = max(eng_boost, 1)
            elif r < low_reads:
                eng_penalty = 1
        if lk is not None:
            if lk >= 1000:
                eng_boost = max(eng_boost, 2)
            elif lk >= high_likes:
                eng_boost = max(eng_boost, 1)
            elif lk < low_likes:
                eng_penalty = 1
        if sv is not None and sv >= 500:
            eng_boost = max(eng_boost, 1)

    final = max(1, min(5, editorial + cross_boost + eng_boost - eng_penalty))

    if cross_boost >= 1 and eng_boost >= 1:
        conf = "强热点"
    elif cross_boost >= 1:
        conf = "多源印证"
    elif eng_boost >= 1:
        conf = "高互动"
    elif eng_penalty:
        conf = "低互动"
    else:
        conf = "常规"

    return final, {
        "editorial": editorial,
        "cross_boost": cross_boost,
        "eng_boost": eng_boost,
        "eng_penalty": eng_penalty,
        "cross_count": cross_count,
        "final": final,
        "confidence": conf,
    }


def keyword_heat(items, categories):
    freq = {}
    for cat, kws in categories.items():
        for kw in kws:
            c = 0
            for it in items:
                text = ((it.get("title", "") or "") + " " + (it.get("summary", "") or "")).lower()
                if kw.lower() in text:
                    c += 1
            if c > 0:
                freq[kw] = {"count": c, "category": cat}
    return freq


def _unit_of(layer_id, s):
    """将来源归入『覆盖单元』：一条单元被命中即代表该组整体覆盖。

    - L1：国家级两个 mandatory 源各自为独立单元（必须命中）；其余省级/市级
          合并为「地方教育主管部门」一个单元（任一地市教委命中即算覆盖）。
    - L2：按 type 合并（头部博主/教育媒体/机构官方号/教育类公众号）。
    - L3：四个维度各自为独立单元（关键词搜索/高热笔记/同类账号/评论区）。
    """
    if layer_id == "L1":
        if s.get("mandatory") or s.get("level") == "国家级":
            return s.get("name", "")
        return "地方教育主管部门（省级/市级）"
    if layer_id == "L2":
        return s.get("type", s.get("name", ""))
    if layer_id == "L3":
        return s.get("dimension", s.get("name", ""))
    return s.get("name", "")


def build_coverage(cfg, all_item_sources, layer_item_counts=None, items=None):
    """对照 config/sources.json，标注每个渠道是否已在本次采集中出现。

    采用「覆盖单元」口径：平行来源（多个省级/市级教委、同类公众号）合并为一个
    单元，任一命中即视为该组覆盖；同时保留逐源明细（真实命中情况不隐藏）。
    L3（小红书）四个维度必须真正采到对应维度的条目才算覆盖
    （不再『有数据即整层满格』）。
    """
    layer_item_counts = layer_item_counts or {}
    items = items or []
    coverage = []
    for cfg_key, layer_id in CFG_LAYER_MAP.items():
        layer_cfg = cfg.get("layers", {}).get(cfg_key)
        if not layer_cfg:
            continue
        sources = []
        for s in layer_cfg.get("sources", []):
            name = s.get("name", "")
            base = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
            covered = False
            for src in all_item_sources:
                if base and base in src:
                    covered = True
                    break
                if src and src in name:
                    covered = True
                    break
            # L3：必须真实采到对应维度的条目
            if layer_id == "L3":
                dim = s.get("dimension", "")
                covered = any(
                    (it.get("layer") == "L3" and (it.get("dimension") or "") == dim)
                    for it in items
                )
            sources.append({"name": name, "covered": covered,
                            "url": s.get("url", ""), "unit": _unit_of(layer_id, s)})
        # 汇总覆盖单元
        units = {}
        for s in sources:
            u = s["unit"]
            units.setdefault(u, {"total": 0, "covered": 0})
            units[u]["total"] += 1
            if s["covered"]:
                units[u]["covered"] += 1
        unit_list = [{"name": u, "covered": v["covered"], "total": v["total"]}
                     for u, v in units.items()]
        cov_n = sum(1 for s in sources if s["covered"])
        coverage.append({
            "layer_id": layer_id,
            "layer_name": layer_cfg.get("name", layer_id),
            "total": len(sources),
            "covered": cov_n,
            "sources": sources,
            "units": unit_list,
        })
    return coverage


def render_coverage(coverage):
    blocks = ""
    for c in coverage:
        pct = int(round(100 * c["covered"] / c["total"])) if c["total"] else 0
        unit_html = ""
        for u in c.get("units", []):
            upct = int(round(100 * u["covered"] / u["total"])) if u["total"] else 0
            unit_html += (f'<span class="unit">{html.escape(u["name"])} '
                          f'{u["covered"]}/{u["total"]}</span>')
        rows = ""
        for s in c["sources"]:
            badge = "✅ 已采集" if s["covered"] else "⬜ 未覆盖"
            cls = "ok" if s["covered"] else "miss"
            rows += (f'<div class="crow"><span class="cname">{html.escape(s["name"])}</span>'
                     f'<span class="cbadge {cls}">{badge}</span></div>')
        blocks += (
            f'<section class="cov"><h3>{html.escape(c["layer_name"])}'
            f'<span class="cpct">{c["covered"]}/{c["total"]}（{pct}%）</span></h3>'
            f'<div class="units">覆盖单元：{unit_html}</div>'
            f'<div class="crows">{rows}</div></section>'
        )
    return blocks


def build_watchpoints(report):
    """自动生成「关注点」：基于数据的中性监测提示（不含任何内容运营/选题建议）。

    聚焦六类信号：强热点、跨层共振、合规风险、采集缺口、政策落地、高热关键词。
    返回 [(level, text), ...]，level ∈ {高, 中, 低}，text 为纯文本（渲染时再做转义）。
    """
    displayed = report.get("displayed", [])
    heat = report.get("keyword_heat", {})
    coverage = report.get("coverage", [])
    extension = report.get("extension", [])
    points = []

    # 1) 强热点 / 高热度条目
    strong = [it for it in displayed
              if (it.get("_heat_bd", {}) or {}).get("final", 0) >= 5
              or (it.get("_heat_bd", {}) or {}).get("confidence") == "强热点"]
    for it in strong[:3]:
        bd = it.get("_heat_bd", {}) or {}
        title = it.get("title", "")
        src = it.get("source", "")
        points.append(("高", f"强热点：{title}（{src}）综合热度 {bd.get('final')}，"
                            f"置信度「{bd.get('confidence')}」，建议重点跟进其后续演化。"))

    # 2) 跨层共振关键词：同一关键词出现在 ≥2 个不同信息层
    kw_layers = {}
    for it in displayed:
        for kw in it.get("_kws", []):
            kw_layers.setdefault(kw, set()).add(it.get("layer"))
    crossed = [kw for kw, ls in kw_layers.items() if len(ls) >= 2]
    if crossed:
        top_cross = sorted(crossed, key=lambda k: heat.get(k, {}).get("count", 0), reverse=True)[:3]
        points.append(("中", f"跨层共振：关键词「{('、'.join(top_cross))}」同时出现在多个信息层"
                            f"（政策/行业/小红书），政策与舆情同向，值得持续留意。"))

    # 3) 合规风险关键词命中
    risk_kws = {"小黑班", "无证", "违规", "隐形补习", "黑作坊", "地下"}
    risk_hits = set()
    for it in displayed + extension:
        text = ((it.get("title", "") or "") + " " + (it.get("summary", "") or "")).lower()
        for rk in risk_kws:
            if rk in text:
                risk_hits.add(rk)
    if risk_hits:
        points.append(("高", f"合规关注：监测到「{('、'.join(sorted(risk_hits)))}」相关讨论，"
                            f"涉及违规补习/机构合规风险，建议留意监管动态与舆情走向。"))

    # 4) 采集缺口（未覆盖信息源）
    gaps = []
    for c in coverage:
        for s in c["sources"]:
            if not s["covered"]:
                gaps.append(f"{c['layer_name']}·{s['name']}")
    if gaps:
        shown = "、".join(gaps[:5])
        more = f"等共 {len(gaps)} 个" if len(gaps) > 5 else ""
        points.append(("中", f"采集缺口：{shown}{more} 信息源本窗口未覆盖，可择机补采以提升完整度。"))

    # 5) 国家级新政策落地
    national = [it for it in displayed if it.get("source") in {"教育部官网", "国务院政策文件库"}]
    if national:
        points.append(("高", f"政策落地：本周监测到国家级政策源（{national[0].get('source', '')}）发布新动态，"
                            f"关注其对招生、课程与机构的后续影响。"))

    # 6) 高热关键词（关注度集中）
    top_kws = [k for k, v in sorted(heat.items(), key=lambda x: -x[1]["count"])[:6]]
    if top_kws:
        points.append(("低", f"高热关键词：{('、'.join(top_kws))} 本窗口命中最集中，反映当前舆论焦点。"))

    return points


def render_item_html(it):
    """单条舆情卡片：综合热度星标 + 置信度/多源/互动徽标 + 热度拆解 + 互动量。"""
    title = html.escape(it.get("title", "(无标题)"))
    url = it.get("url", "")
    src = html.escape(it.get("source", ""))
    pub = html.escape(it.get("pub_date", ""))
    bd = it.get("_heat_bd", {}) or {}
    heat_n = bd.get("final", int(it.get("heat", 1)))
    stars = "🔥" * max(0, min(5, heat_n))
    conf = bd.get("confidence", "常规")
    badges = ""
    if bd.get("cross_count", 0) >= 2:
        badges += f' <span class="badge-ms">🔗 多源印证×{bd.get("cross_count")}</span>'
    if bd.get("eng_boost", 0) >= 1:
        badges += ' <span class="badge-hi">📈 高互动</span>'
    if bd.get("eng_penalty", 0) >= 1:
        badges += ' <span class="badge-lo">⚠️ 低互动</span>'
    conf_cls = {"强热点": "c-strong", "多源印证": "c-ms", "高互动": "c-hi",
                "低互动": "c-lo", "常规": "c-nor"}.get(conf, "c-nor")
    badges += f' <span class="badge-conf {conf_cls}">{conf}</span>'
    bd_text = (f"热度拆解：基准 {bd.get('editorial', int(it.get('heat', 1)))} "
               f"+跨源 {bd.get('cross_boost', 0)} +互动 {bd.get('eng_boost', 0)} "
               f"−降权 {bd.get('eng_penalty', 0)} = <b>{heat_n}</b>")
    eng = it.get("engagement")
    eng_text = ""
    if isinstance(eng, dict):
        parts = []
        for k, lbl in (("reads", "阅读"), ("likes", "赞"), ("saves", "藏"), ("comments", "评")):
            if eng.get(k) is not None:
                parts.append(f"{lbl} {eng[k]}")
        if parts:
            eng_text = " ｜ " + " · ".join(parts)
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in it.get("_cats", []))
    link = f'<a href="{html.escape(url)}" target="_blank">{title}</a>' if url else title
    ext = it.get("_ext_reason")
    ext_tag = f' <span class="badge-ext">📌 延展·{ext}</span>' if ext else ""
    return (
        f'<li><div class="it"><span class="hl">{stars}</span>{link}{badges}{ext_tag}'
        f'<span class="meta">【{src}】{pub}</span></div>'
        f'<div class="bd">{bd_text}{eng_text}</div>'
        f'<div class="sum">{html.escape(it.get("summary", ""))}</div>'
        f'<div class="tags">{tags}</div></li>'
    )


def render_html(report):
    date = report["date"]
    window = report["window"]  # (start, end)
    displayed = report["displayed"]  # list of items actually shown
    cats = report["categories"]
    heat = report["keyword_heat"]
    stats = report["stats"]
    coverage = report["coverage"]
    min_heat = report["min_heat"]
    top_n = report["top_n"]
    method = report.get("method", "")

    by_layer = {}
    for it in displayed:
        by_layer.setdefault(it.get("layer", "L?"), []).append(it)

    maxc = max([v["count"] for v in heat.values()], default=1) or 1
    heat_rows = ""
    for kw, v in sorted(heat.items(), key=lambda x: -x[1]["count"]):
        w = int(round(100 * v["count"] / maxc))
        heat_rows += (
            f'<div class="krow"><span class="kname">{html.escape(kw)}'
            f'<span class="ktag">{html.escape(v["category"])}</span></span>'
            f'<span class="kbar"><i style="width:{w}%"></i></span>'
            f'<span class="knum">{v["count"]}</span></div>'
        )
    if not heat_rows:
        heat_rows = '<div class="muted">本窗口内无关键词命中</div>'

    layer_blocks = ""
    for lid in ["L1", "L2", "L3"]:
        group = by_layer.get(lid, [])
        if not group:
            continue
        rows = "".join(render_item_html(it) for it in group)
        layer_blocks += (
            f'<section class="layer"><h2>{html.escape(LAYER_NAME.get(lid, lid))}'
            f'<span class="cnt">综合热度 Top{top_n} · 共 {len(group)} 条</span></h2>'
            f'<ul class="items">{rows}</ul></section>'
        )

    # 高互动延展关注区块
    ext_items = report.get("extension", [])
    ext_html = ""
    if ext_items:
        ext_rows = "".join(render_item_html(it) for it in ext_items)
        ext_html = (
            f'<section class="layer ext"><h2>📌 高互动延展关注'
            f'<span class="cnt">窗口外(8~30天)·高互动/多源印证 · 共 {len(ext_items)} 条</span></h2>'
            f'<ul class="items">{ext_rows}</ul></section>'
        )

    # 自动生成「关注点」（中性监测提示，不含内容运营/选题建议）
    watchpoints = build_watchpoints(report)
    if watchpoints:
        wp_rows = ""
        for lvl, txt in watchpoints:
            cls = {"高": "wp-high", "中": "wp-mid", "低": "wp-low"}.get(lvl, "wp-low")
            wp_rows += (f'<div class="wprow"><span class="wpbadge {cls}">{lvl}</span>'
                        f'<span class="wptxt">{html.escape(txt)}</span></div>')
        wp_html = (f'<div class="panel"><h2>🔍 关注点（自动生成，仅供参考）</h2>{wp_rows}</div>')
    else:
        wp_html = '<div class="panel"><h2>🔍 关注点</h2><div class="muted">本窗口暂无明显关注点。</div></div>'

    cov_html = render_coverage(coverage)
    method_html = (f'<div class="panel"><h2>🔥 热点评估方法</h2>'
                   f'<p class="muted">{html.escape(method)}</p></div>')

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>教育舆情监测周报 {date}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f7fa;color:#1f2933}}
.header{{background:linear-gradient(135deg,#2b6cb0,#2c5282);color:#fff;padding:22px 28px}}
.header h1{{margin:0;font-size:22px}}
.header .sub{{opacity:.85;margin-top:6px;font-size:13px}}
.wrap{{max-width:1060px;margin:0 auto;padding:20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{flex:1;min-width:140px;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.card .n{{font-size:26px;font-weight:700;color:#2b6cb0}}
.card .l{{font-size:12px;color:#667}}
.panel{{background:#fff;border-radius:10px;padding:18px 20px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.panel h2{{margin:0 0 12px;font-size:16px;border-left:4px solid #2b6cb0;padding-left:10px}}
.krow{{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}}
.kname{{width:170px;display:flex;align-items:center;gap:6px}}
.ktag{{font-size:11px;background:#eef2f7;color:#556;border-radius:4px;padding:1px 5px}}
.kbar{{flex:1;background:#eef2f7;border-radius:6px;height:14px;overflow:hidden}}
.kbar i{{display:block;height:100%;background:linear-gradient(90deg,#f6ad55,#ed8936)}}
.knum{{width:28px;text-align:right;color:#667}}
.layer h2{{font-size:16px;margin:0 0 10px;border-left:4px solid #38a169;padding-left:10px}}
.cnt{{font-size:12px;color:#889;font-weight:400;margin-left:8px}}
.items{{list-style:none;padding:0;margin:0}}
.items li{{padding:12px 0;border-bottom:1px solid #f0f2f5}}
.it{{font-size:15px;font-weight:600}}
.it a{{color:#2b6cb0;text-decoration:none}}
.it a:hover{{text-decoration:underline}}
.hl{{color:#ed8936;margin-right:6px}}
.meta{{font-size:12px;color:#889;font-weight:400;margin-left:8px}}
.sum{{font-size:13px;color:#445;margin:6px 0;line-height:1.6}}
.tags .tag{{display:inline-block;font-size:11px;background:#ebf4ff;color:#2b6cb0;border-radius:4px;padding:2px 7px;margin:3px 4px 0 0}}
.badge-ms{{display:inline-block;font-size:11px;background:#fffaf0;color:#b7791f;border:1px solid #f6e05e;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}}
.badge-hi{{display:inline-block;font-size:11px;background:#ebf8ff;color:#2b6cb0;border:1px solid #90cdf4;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}}
.badge-lo{{display:inline-block;font-size:11px;background:#fff5f5;color:#c53030;border:1px solid #feb2b2;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}}
.badge-conf{{display:inline-block;font-size:11px;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}}
.badge-conf.c-strong{{background:#c6f6d5;color:#22543d;border:1px solid #68d391}}
.badge-conf.c-ms{{background:#fffaf0;color:#b7791f;border:1px solid #f6e05e}}
.badge-conf.c-hi{{background:#ebf8ff;color:#2b6cb0;border:1px solid #90cdf4}}
.badge-conf.c-lo{{background:#fff5f5;color:#c53030;border:1px solid #feb2b2}}
.badge-conf.c-nor{{background:#f0f2f5;color:#667;border:1px solid #e2e8f0}}
.badge-ext{{display:inline-block;font-size:11px;background:#faf5ff;color:#6b46c1;border:1px solid #d6bcfa;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}}
.bd{{font-size:11.5px;color:#7a8699;margin:5px 0 2px}}
.bd b{{color:#2b6cb0}}
.layer.ext{{border:1px dashed #b794f4;background:#faf8ff;border-radius:10px;padding:14px 18px;margin:16px 0}}
.layer.ext h2{{border-left-color:#805ad5}}
.cov h3{{font-size:15px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}}
.cpct{{font-size:12px;color:#556;font-weight:400}}
.crows{{display:flex;flex-wrap:wrap;gap:6px 14px}}
.crow{{display:flex;align-items:center;gap:6px;font-size:12.5px;width:46%;min-width:220px}}
.units{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}}
.unit{{font-size:11px;background:#eef2f7;color:#475569;border-radius:4px;padding:2px 8px;white-space:nowrap}}
.cname{{flex:1}}
.cbadge{{font-size:11px;border-radius:4px;padding:1px 6px;white-space:nowrap}}
.cbadge.ok{{background:#e6fffa;color:#0f766e}}
.cbadge.miss{{background:#fff5f5;color:#c0392b}}
.muted{{color:#99a;font-size:13px}}
.wprow{{display:flex;gap:10px;align-items:flex-start;margin:8px 0;font-size:13px;color:#334;line-height:1.6}}
.wpbadge{{display:inline-block;font-size:11px;border-radius:4px;padding:1px 7px;white-space:nowrap;margin-top:2px}}
.wp-high{{background:#fff5f5;color:#c53030}}
.wp-mid{{background:#fffaf0;color:#b7791f}}
.wp-low{{background:#f0f2f5;color:#667}}
footer{{text-align:center;color:#aab;font-size:12px;padding:20px}}
</style></head>
<body>
<div class="header"><h1>📊 教育舆情监测周报</h1>
<div class="sub">日期：{date} ｜ 展示窗口：{window[0]} ~ {window[1]}（每层 Top{top_n}·综合热度≥{min_heat}）｜ 自动生成</div></div>
<div class="wrap">
<div class="cards">
<div class="card"><div class="n">{stats['total']}</div><div class="l">本窗口合计</div></div>
<div class="card"><div class="n">{stats['L1']}</div><div class="l">政策源头</div></div>
<div class="card"><div class="n">{stats['L2']}</div><div class="l">行业动态</div></div>
<div class="card"><div class="n">{stats['L3']}</div><div class="l">小红书舆情</div></div>
</div>
<div class="panel"><h2>📡 信息源覆盖情况（对照 sources.json）</h2>{cov_html}</div>
<div class="panel"><h2>🔥 热点关键词命中</h2>{heat_rows}</div>
{method_html}
{layer_blocks}
{ext_html}
{wp_html}
</div>
<footer>教育舆情监测系统 v2 · 生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</footer>
</body></html>"""
    return html_doc


def render_md(report):
    date = report["date"]
    window = report["window"]
    displayed = report["displayed"]
    heat = report["keyword_heat"]
    stats = report["stats"]
    coverage = report["coverage"]
    lines = [f"# 教育舆情监测周报（{date}）", ""]
    lines.append(f"展示窗口：{window[0]} ~ {window[1]}（近1周高热度）")
    lines.append(f"- 本窗口合计 {stats['total']} 条（政策 {stats['L1']} / 行业 {stats['L2']} / 小红书 {stats['L3']}）")
    lines.append("")

    lines.append("## 信息源覆盖情况")
    for c in coverage:
        lines.append(f"- {c['layer_name']}：{c['covered']}/{c['total']} 已采集")
        for u in c.get("units", []):
            lines.append(f"  - 覆盖单元 {u['name']}：{u['covered']}/{u['total']}")
        for s in c["sources"]:
            mark = "✅" if s["covered"] else "⬜"
            lines.append(f"  - {mark} {s['name']}")
    lines.append("")

    lines.append("## 热点关键词")
    for kw, v in sorted(heat.items(), key=lambda x: -x[1]["count"]):
        lines.append(f"- {kw}（{v['category']}）：{v['count']} 条")
    lines.append("")

    def _md_item(it):
        bd = it.get("_heat_bd", {}) or {}
        heat_n = bd.get("final", int(it.get("heat", 1)))
        stars = "🔥" * max(0, min(5, heat_n))
        title = it.get("title", "(无标题)")
        url = it.get("url", "")
        src = it.get("source", "")
        pub = it.get("pub_date", "")
        conf = bd.get("confidence", "常规")
        flags = []
        if bd.get("cross_count", 0) >= 2:
            flags.append(f"🔗多源印证×{bd.get('cross_count')}")
        if bd.get("eng_boost", 0) >= 1:
            flags.append("📈高互动")
        if bd.get("eng_penalty", 0) >= 1:
            flags.append("⚠️低互动")
        if it.get("_ext_reason"):
            flags.append(f"📌延展·{it.get('_ext_reason')}")
        flags.append(f"[{conf}]")
        out = [f"- {stars} [{title}]({url}) —— {src} {pub} {' '.join(flags)}".rstrip()]
        if it.get("summary"):
            out.append(f"  - {it.get('summary')}")
        out.append(
            f"  - 热度拆解：基准 {bd.get('editorial', int(it.get('heat', 1)))} "
            f"+跨源 {bd.get('cross_boost', 0)} +互动 {bd.get('eng_boost', 0)} "
            f"−降权 {bd.get('eng_penalty', 0)} = {heat_n}"
        )
        eng = it.get("engagement")
        if isinstance(eng, dict):
            parts = [f"{lbl} {eng[k]}" for k, lbl in (("reads", "阅读"), ("likes", "赞"),
                      ("saves", "藏"), ("comments", "评")) if eng.get(k) is not None]
            if parts:
                out.append(f"  - 互动量：{' · '.join(parts)}")
        return out

    for lid in ["L1", "L2", "L3"]:
        group = [it for it in displayed if it.get("layer") == lid]
        if not group:
            continue
        lines.append(f"## {LAYER_NAME.get(lid, lid)}（Top{len(group)} 综合热度）")
        for it in group:
            lines.extend(_md_item(it))
        lines.append("")

    ext_items = report.get("extension", [])
    if ext_items:
        lines.append("## 📌 高互动延展关注（窗口外 8~30 天）")
        for it in ext_items:
            lines.extend(_md_item(it))
        lines.append("")

    wps = build_watchpoints(report)
    if wps:
        lines.append("## 🔍 关注点（自动生成，仅供参考）")
        for lvl, txt in wps:
            lines.append(f"- **[{lvl}]** {txt}")
        lines.append("")

    lines.append("## 热点评估方法")
    lines.append(f"- {report.get('method', '')}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=today_str())
    ap.add_argument("--days", type=int, default=7, help="展示近 N 日（默认 7）")
    ap.add_argument("--top", type=int, default=5, help="每层展示高热度条数（默认 5）")
    ap.add_argument("--min-heat", type=int, default=3, help="高热度阈值（默认 3）")
    args = ap.parse_args()

    date = args.date
    raw_path = os.path.join(DATA_DIR, f"{date}_raw.json")
    kw_path = os.path.join(CONFIG_DIR, "keywords.json")
    src_path = os.path.join(CONFIG_DIR, "sources.json")
    if not os.path.exists(raw_path):
        print(f"[ERROR] 未找到原始数据: {raw_path}")
        sys.exit(1)
    if not os.path.exists(kw_path):
        print(f"[ERROR] 未找到关键词库: {kw_path}")
        sys.exit(1)

    raw = load_json(raw_path)
    kw_cfg = load_json(kw_path)
    categories = kw_cfg.get("categories", {})
    src_cfg = load_json(src_path) if os.path.exists(src_path) else {}

    # 全量去重（用于覆盖统计）
    all_items = dedupe(raw.get("items", []))
    all_sources = [it.get("source", "") for it in all_items]
    layer_item_counts = {}
    for it in all_items:
        lid = it.get("layer", "L?")
        layer_item_counts[lid] = layer_item_counts.get(lid, 0) + 1
    coverage = build_coverage(src_cfg, all_sources, layer_item_counts, all_items)

    # 近 N 日窗口过滤
    d = parse_date(date)
    if d is None:
        print(f"[ERROR] 无法解析日期: {date}")
        sys.exit(1)
    start = d - datetime.timedelta(days=args.days - 1)
    end = d
    window_items = []
    for it in all_items:
        pd = parse_date(it.get("pub_date", ""))
        if pd is None:
            continue
        if start <= pd <= end:
            window_items.append(it)

    for it in all_items:
        it["_cats"] = categorize(it, categories)
        it["_kws"] = match_keywords(it, categories)

    # 跨源印证：统计与每条共享关键词的“其他独立信息源”数量（基于窗口内条目）
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
        final, bd = compute_heat(it, it["_cross"])
        it["_heat_final"] = final
        it["_heat_bd"] = bd
        it["_multisource"] = it["_cross"] >= 2

    heat = keyword_heat(window_items, categories)

    # 每层：综合热度过滤 -> 按日期新到旧、综合热度降序 -> Top N
    displayed = []
    layer_stats = {"L1": 0, "L2": 0, "L3": 0}
    # L1 国家级政策源（教育部官网 / 国务院政策文件库）必须出现
    NATIONAL_SOURCES = {"教育部官网", "国务院政策文件库"}

    def _sort_key(x):
        return (parse_date(x.get("pub_date", "")) or datetime.date.min,
                x.get("_heat_final", int(x.get("heat", 1))))

    for lid in ["L1", "L2", "L3"]:
        group = [it for it in window_items if it.get("layer") == lid]
        group = [it for it in group if it.get("_heat_final", int(it.get("heat", 1))) >= args.min_heat]
        group.sort(key=_sort_key, reverse=True)
        if lid == "L1" and group:
            top = group[:args.top]
            has_national = any(it.get("source") in NATIONAL_SOURCES for it in top)
            if not has_national:
                # 候选国家级条目（综合热度高、窗口内）
                nat_pool = [it for it in group if it.get("source") in NATIONAL_SOURCES]
                if nat_pool:
                    # 用最弱（综合热度最低、日期最旧）的本地条目换取最高国家级条目
                    weakest = min(top, key=lambda x: (x.get("_heat_final", int(x.get("heat", 1))),
                                                      parse_date(x.get("pub_date", "")) or datetime.date.min))
                    idx = top.index(weakest)
                    top[idx] = nat_pool[0]
                    top.sort(key=_sort_key, reverse=True)
            group = top
        group = group[:args.top]
        displayed.extend(group)
        layer_stats[lid] = len(group)

    # 高互动延展关注：超出 7 天窗口（8~30 天）但互动量高/多源印证，避免硬货被漏掉
    ext_start = start - datetime.timedelta(days=23)  # 窗口起点再往前 23 天 ≈ 30 天跨度
    extension = []
    for it in all_items:
        pd = parse_date(it.get("pub_date", ""))
        if pd is None or not (ext_start <= pd < start):
            continue
        bd = it.get("_heat_bd", {})
        if bd.get("eng_boost", 0) >= 1 or bd.get("cross_count", 0) >= 2:
            it["_ext_reason"] = "高互动" if bd.get("eng_boost", 0) >= 1 else "多源印证"
            extension.append(it)
    extension.sort(key=lambda x: (x.get("_heat_final", 0),
                                  parse_date(x.get("pub_date", "")) or datetime.date.min),
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
        "综合热度(1-5) = 编辑基准热 + 跨源印证加权 + 互动量加权 - 互动量降权，四者透明可见：\n"
        "· 编辑基准热：采集时人工评定（新政策默认高）；\n"
        "· 跨源印证：与本条共享关键词的其他独立信息源 ≥2 个 +1，≥4 个 +2（多源共同出现=更可信）；\n"
        "· 互动量加权：阅读≥2000 / 点赞≥200 / 收藏≥500 +1，阅读≥10000 / 点赞≥1000 +2；\n"
        "· 互动量降权：标记为 low，或 阅读<500 / 点赞<100 → -1。\n"
        "置信度标签：强热点(跨源+高互动) / 多源印证 / 高互动 / 低互动 / 常规。\n"
        "主榜仅取近 {days} 天窗口内综合热度≥{mh} 的条目；超出窗口但互动量高/多源印证的硬货，"
        "单独进入「高互动延展关注」区，避免被漏掉。"
    ).format(days=args.days, mh=args.min_heat)
    report = {
        "date": date, "window": (start.isoformat(), end.isoformat()),
        "displayed": displayed, "categories": categories, "keyword_heat": heat,
        "extension": extension,
        "stats": stats, "coverage": coverage, "min_heat": args.min_heat, "top_n": args.top,
        "method": method_text,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    html_path = os.path.join(OUT_DIR, f"{date}_report.html")
    md_path = os.path.join(OUT_DIR, f"{date}_report.md")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(report))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(report))

    print(f"[OK] 报告已生成（窗口 {start.isoformat()}~{end.isoformat()}，每层 Top{args.top}，heat>={args.min_heat}）")
    print(f"  HTML: {html_path}")
    print(f"  MD:   {md_path}")
    print(f"  展示: 总计 {stats['total']} ｜ L1 {stats['L1']} ｜ L2 {stats['L2']} ｜ L3 {stats['L3']}")
    print(f"  命中关键词数: {len(heat)}")
    print("  信息源覆盖:")
    for c in coverage:
        print(f"    {c['layer_name']}: {c['covered']}/{c['total']}")


if __name__ == "__main__":
    main()
