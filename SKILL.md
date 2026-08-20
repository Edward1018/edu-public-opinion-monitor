---
name: 教育舆情监测周报
description: 三层（政策源头 / 行业动态 / 小红书家长舆情）教育舆情采集、整理与监测周报生成的自动化工作流。每周六 09:00 自动运行，亦可手动触发。仅做信息收集与监测，不含选题策划、内容制作、发布等运营动作。
---

# 教育舆情监测周报（Skill）

本技能是一个**纯舆情监测**工具：采集 → 去重/关键词分类/热度评估 → 生成**监测周报**（网页 + Markdown + 邮件版）。它告诉你"本周教育领域发生了什么、哪些值得关注"，但**不替你决定该做什么内容**。

> 完整执行细节（schema、命令、邮件约束、扩展方式）见同目录 `README.md`，本技能只给 agent 一张"执行地图"，复杂步骤以 README 为准。

## 🗣️ 首选入口 — 对话安装与调用（用户视角）

本技能**首选通过对话完成安装与调用**，用户不需要手动敲任何命令。

### 对话安装（首次使用）

当用户说**「帮我安装 <GitHub URL 或 user/repo>」**时，agent 自动识别并执行 git clone。识别规则：

- 用户说 `user/repo`（如 `Edward1018/edu-public-opinion-monitor`）→ 补全为 `https://github.com/Edward1018/edu-public-opinion-monitor.git`
- 用户说完整 URL（如 `https://github.com/Edward1018/edu-public-opinion-monitor.git`）→ 直接用
- 目标目录固定为 `~/.workbuddy/skills/<repo-basename>/`（与 git clone 默认名一致）

agent 执行：

```bash
# 示例：Edward1018/edu-public-opinion-monitor
REPO="https://github.com/Edward1018/edu-public-opinion-monitor.git"
NAME="edu-public-opinion-monitor"
TARGET="$HOME/.workbuddy/skills/$NAME"

# 安全检查：目标已存在则中止，避免覆盖用户已有数据
if [ -e "$TARGET" ]; then
    echo "❌ 已存在：$TARGET（如需更新请先 rm -rf $TARGET）"
    exit 1
fi

command -v git >/dev/null || { echo "❌ 未安装 git"; exit 1; }
mkdir -p "$(dirname "$TARGET")"
git clone "$REPO" "$TARGET"

# 验证技能文件存在
if [ -f "$TARGET/SKILL.md" ]; then
    echo "✅ 已安装到 $TARGET（含 SKILL.md，可作为技能调用）"
else
    echo "⚠️ 已克隆但未发现 SKILL.md，请确认仓库结构"
fi
```

执行成功后回复用户：

```
✅ 已安装到 ~/.workbuddy/skills/edu-public-opinion-monitor/
接下来对 agent 说"用教育舆情监测技能跑一次今日周报"即可调用。
首次运行需要按需连接 qq-mail（发邮件）/ bazhuayu（L3 真实小红书）。
```

> **安全约束**：对话安装只做 `git clone` + 验证 SKILL.md 存在，**不自动执行任何 setup/install 脚本**。更新用 `cd ~/.workbuddy/skills/edu-public-opinion-monitor && git pull`。

### 对话调用（日常使用）

以下任意一句都能触发本技能（agent 自动按下方「执行步骤」跑完整流程）：

- 「用教育舆情监测技能跑一次今日周报」
- 「生成本周教育舆情周报」
- 「跑一下教育舆情监测」
- 「周六定时跑一下舆情监测」

可选追加参数（agent 自动映射为脚本参数）：

- 「…生成 HTML 版」/「…生成邮件版」
- 「…聚合近 14 天」（即 `--days 14`）
- 「…发到我的邮箱」（自动用 qq-mail 连接器发送）

## 触发场景

- 用户说"生成本周教育舆情周报""跑一下舆情监测""周六定时舆情周报"。
- 用户把本技能作为定时任务（每周六 09:00）触发。
- 用户上传/提供一份 `data/YYYY-MM-DD_raw.json` 后要求生成报告。

## ⚠️ 依赖连接器（务必先确认，否则抓取会失败）

| 连接器 | 是否必选 | 用途 | 缺失后果 |
|--------|----------|------|----------|
| **qq-mail**（QQ邮箱） | **必选**（仅发送环节） | 通过 `SendMessage` 把邮件版周报发到**你自己**的邮箱 | 无法发邮件，但报告仍可生成本地查看 |
| **bazhuayu**（八爪鱼） | 可选 | 获取 L3 小红书**真实**笔记/互动数据（替代公开搜索近似） | L3 退化为公开搜索近似，仍可用 |
| **WebSearch / WebFetch** | 内置（无需配置） | L1/L2/L3 三层实时采集的默认手段 | 无（除非运行环境禁用网络） |

**排查要点**：若采集环节"抓不到数据"，先确认：
1. 运行环境是否具备 WebSearch/WebFetch 能力（内置，一般可用）；
2. 若要真实小红书数据，需用户先连接 **bazhuayu** 连接器，否则跳过或用 WebSearch 近似；
3. 若只要"发邮件"，必须连接 **qq-mail** 且绑定的是**用户自己的** QQ 邮箱（本技能不写死任何邮箱地址）。

## 执行步骤（agent 照做）

### 1. 逐源采集（保证每层遗漏 ≤3 个来源）
先建骨架，再**遍历 `config/sources.json` 的每一个来源**逐一检索并追加：
```bash
python3 scripts/collect.py new YYYY-MM-DD
```
对每个 source 执行一次检索，结果用 `collect.py add` 写入（`source` 必须与该源 `name` 完全一致）：
- **L1 政策源头**：先 WebFetch 该源 `url`（官网）；若官网无新动态，再用 WebSearch「<源名> 2026年8月 教育 政策/招生/中考」补一轮。`heat` 新政策默认 5。国家级（教育部官网、国务院政策文件库）务必命中。
- **L2 行业动态**：WebSearch 该源 `wechat`（微信搜狗检索链接），检索词「<源名> 2026 教育 动态/财报/观点」，`source` 写该源 `name`。
- **L3 小红书（家长舆情）**：**优先用 bazhuayu 连接器**按四个维度分别采集；未接 bazhuayu 则用 WebSearch 对每个维度关键词检索。`source` 统一写「小红书」，`dimension` 必须取四维度之一（关键词搜索 / 高热笔记 / 同类账号 / 评论区）。
- 每采到一条即追加：
```bash
python3 scripts/collect.py add YYYY-MM-DD --item '{"layer":"L1","source":"深圳市教育局","url":"https://...","title":"...","summary":"...","pub_date":"2026-08-16","heat":4}'
python3 scripts/collect.py add YYYY-MM-DD --item '{"layer":"L3","source":"小红书","dimension":"高热笔记","url":"https://...","title":"...","summary":"...","pub_date":"2026-08-16","heat":4}'
```
- 采集完用 `python3 scripts/collect.py status YYYY-MM-DD` 核对各层条数。
- **目标**：每个来源的 `name` 尽量都被命中；对"本周确实无新闻"的平行源（如某地教委）允许空缺，但**每层遗漏不超过 3 个来源**。
- 当天若已存在 `raw.json` 则跳过采集，直接复用。

### 2. 生成网页版 + Markdown 周报
```bash
python3 scripts/generate_report.py YYYY-MM-DD --days 7
# 输出 output/YYYY-MM-DD_report.html 与 .md
```

### 3. 生成邮件版（内联样式，标题=可点击超链接）
```bash
python3 scripts/build_email.py YYYY-MM-DD
# 输出 output/YYYY-MM-DD_email.html
```

### 4. （可选）发送邮件
通过 **qq-mail** 连接器 `SendMessage`：
- 收件人 = **用户自己的邮箱**；
- `body_format = "HTML"`；
- `body` = `output/YYYY-MM-DD_email.html` 的完整内容（**整份内联进正文**，勿只发链接）。

## 输出物
- `output/YYYY-MM-DD_report.html`：可视化周报（信息源覆盖、热点关键词、三层条目、🔍关注点）。
- `output/YYYY-MM-DD_report.md`：同内容 Markdown。
- `output/YYYY-MM-DD_email.html`：邮件版（手机端可渲染，标题可点击）。

## 关键约束（避免踩坑）
- **超链接必须指向真实来源 URL**，切勿改回本地路径或预览网址（否则收件人打不开）。
- 报告末尾「🔍 关注点」是**中性监测提示**（强热点/跨层共振/合规风险/采集缺口/政策落地/高热关键词），**不含任何内容运营或选题建议**。
- 本技能不含个人邮箱，发送由运行者自己的 qq-mail 决定收件人。

## 频率
**每周六 09:00 一次**（定时任务 `FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0`）。
