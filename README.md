# 教育舆情监测（周报）工具

三层信息源采集 → 整理 → 输出**监测周报**的自动化工作流。每周六 09:00 自动运行，亦可手动执行。  
本工具只做**信息收集与监测**，不包含选题策划、内容制作、发布与复盘等运营动作——那些是需要你（或你的 agent）在拿到周报后自行决定的事。

> 定位说明：这是一个**纯舆情监测**工具。它告诉你"本周教育领域发生了什么、哪些值得关注"，但**不替你决定该做什么内容**。报告末尾的「🔍 关注点」是基于数据自动生成的中性提示（强热点 / 跨层共振 / 合规风险 / 采集缺口 / 政策落地 / 高热关键词），仅供参考。

## 🚀 快速开始（首选：对话安装与调用）

本工具**推荐通过 WorkBuddy 对话完成安装与调用**，零命令行。

### 三句话上手

1. 对 WorkBuddy 说：**"帮我安装 Edward1018/edu-public-opinion-monitor"**  
   （也可以直接说完整 URL：`"帮我安装 https://github.com/Edward1018/edu-public-opinion-monitor.git"`）  
   agent 识别 GitHub 地址 → 执行 `git clone https://github.com/Edward1018/edu-public-opinion-monitor.git ~/.workbuddy/skills/edu-public-opinion-monitor` → 验证 SKILL.md 存在 → 告诉你安装位置。
2. 对 WorkBuddy 说：**"用教育舆情监测技能跑一次今日周报"**  
   agent 会自动：建骨架 → 逐源采集 → 生成 HTML/MD → 生成邮件版 →（如已连 qq-mail）发邮件。
3. （可选）让 WorkBuddy 设为**每周六 09:00**定时任务，自动跑。

### 不想用对话？也有命令行方式

- **一键脚本**：`./install.sh`（macOS/Linux）或 `install.bat`（Windows）— 见「一键安装脚本」章节
- **纯脚本**：`git clone … && python3 scripts/generate_report.py …` — 见「手动运行」章节

> 安装后首次使用前，请在 WorkBuddy「连接器」按需启用 **QQ邮箱**（发邮件）和 **八爪鱼**（L3 真实小红书）。

## 目录结构

```
教育舆情监测/
├── config/
│   ├── sources.json      # 三层信息源注册表（政策/行业/小红书）+ 重点城市
│   └── keywords.json     # 关键词库（政策类/升学类/学科类/方法类/机构运营类），持续更新
├── scripts/
│   ├── generate_report.py    # 监测周报生成器（仅标准库，无第三方依赖）
│   ├── build_email.py        # 邮件版报告生成器（内联样式，标题=可点击超链接）
│   └── collect.py            # 采集助手：new 建骨架 / add 追加单条 / status 看进度
├── data/
│   └── YYYY-MM-DD_raw.json   # 当日采集的原始数据（agent 写入）
├── output/
│   ├── YYYY-MM-DD_report.html / .md  # 生成的周报（可视化 / Markdown）
│   └── YYYY-MM-DD_email.html         # 邮件版周报（内联、超链接可用）
├── .gitignore
└── README.md
```

## 三层信息源

| 层  | 名称          | 监测重点                       | 频率            |
| -- | ----------- | -------------------------- | ------------- |
| L1 | 政策源头（官方）    | 新课标、中考改革、招生细则、学区划分、双减、违规补习 | 国家级每日 / 省市级每周 |
| L2 | 行业动态（大V/机构） | 行业热点、AI教育、课程趋势、竞品动向、政策解读   | 每日 / 每周       |
| L3 | 小红书生态（家长舆情） | 家长搜索热词、高热笔记议题、同类账号讨论、评论区痛点 | 每日            |

重点城市：北京、上海、广州、深圳、杭州、南京、成都。

## 原始数据 schema（data/YYYY-MM-DD_raw.json）

```json
{
  "date": "2026-08-12",
  "items": [
    {
      "layer": "L1",            // L1 / L2 / L3
      "source": "教育部官网",
      "url": "https://...",
      "title": "标题",
      "summary": "摘要（中文，可含来源URL）",
      "pub_date": "2026-08-12",
      "heat": 4                 // 1-5 编辑评估热度
    }
  ]
}
```

> 采集动作（WebSearch / WebFetch / 八爪鱼等）由 agent 按下面「真实采集工作流」逐源执行，结果用 `scripts/collect.py` 规范写入 `data/`。

## 真实采集工作流（逐源循环，保证每层遗漏 ≤3 个来源）

目标：遍历 `config/sources.json` 的**每一个**来源并尽量命中；对"本周确实无新闻"的平行源（如某地教委）才允许空缺，但**每层遗漏不超过 3 个来源**。覆盖率面板会把"平行来源"合并为「覆盖单元」（如所有省级/市级教委 → 地方教育主管部门，任一命中即覆盖），同时在明细里保留逐源真实命中情况，不掩盖缺口。

### 步骤

1. **建骨架**
   ```bash
   python3 scripts/collect.py new YYYY-MM-DD
   ```
2. **逐源采集并追加**（agent 对每个 source 执行一次检索）
   - **L1 政策源头**：先 WebFetch 该源 `url`（官网）；无新动态再用 WebSearch「`<源名>` 2026年8月 教育 政策/招生/中考」补一轮。`source` 写该源 `name`，`heat` 新政策默认 5。**国家级（教育部官网、国务院政策文件库）务必命中**。
   - **L2 行业动态**：WebSearch 该源 `wechat`（微信搜狗检索链接），词「`<源名>` 2026 教育 动态/财报/观点」，`source` 写该源 `name`。
   - **L3 小红书（家长舆情）**：**优先用 bazhuayu 连接器**按四维度分别采集；未接则 WebSearch 每维度关键词。`source` 写「小红书」，`dimension` 取四维度之一（关键词搜索 / 高热笔记 / 同类账号 / 评论区）。
3. **追加单条**（自动按标题去重）
   ```bash
   python3 scripts/collect.py add YYYY-MM-DD --item '{"layer":"L1","source":"深圳市教育局","url":"https://...","title":"...","summary":"...","pub_date":"2026-08-16","heat":4}'
   python3 scripts/collect.py add YYYY-MM-DD --item '{"layer":"L3","source":"小红书","dimension":"高热笔记","url":"https://...","title":"...","summary":"...","pub_date":"2026-08-16","heat":4}'
   ```
4. **核对进度**
   ```bash
   python3 scripts/collect.py status YYYY-MM-DD
   ```
5. 采完再走下方「手动运行」的生成步骤。

## 手动运行

环境要求：Python 3.8+（脚本仅用标准库，无需 `pip install`）。

```bash
# 进入仓库根目录
cd /path/to/教育舆情监测

# 1) 生成网页版 + Markdown 周报（默认聚合近 7 天：--days 7）
python3 scripts/generate_report.py 2026-08-12
#    输出 output/2026-08-12_report.html 与 2026-08-12_report.md

# 2) 生成邮件版（内联样式 HTML，每条标题为指向真实来源的可点击超链接）
python3 scripts/build_email.py 2026-08-12
#    输出 output/2026-08-12_email.html
```

参数：`[YYYY-MM-DD]`（省略取今天）、`--days 7`（聚合窗口，默认 7）、`--top 5`（每层条数）、`--min-heat 3`（高热度阈值）。

## 邮件发送（关键约束）

- **为何内嵌正文**：直接发送本地预览/文件路径链接，收件人无法打开。现改为**把整份报告内联进邮件正文**（即 `build_email.py` 生成的 `_email.html`），任何设备打开邮件即可阅读。
- **超链接必须可用**：每条舆情标题都是 `<a href="真实来源URL">` 的可点击链接。`build_email.py` 会刻意把双引号转成单引号以兼容 JSON（`doc.replace('"',"'")`），但 `href` 始终指向 `data` 中的真实 `url`——**切勿改回本地路径或预览网址**，否则链接打不开。
- **发到谁**：通过 **qq-mail** 连接器 `SendMessage` 发送，`body_format="HTML"`，`body` 为 `_email.html` 的完整内容。  
  **收件人邮箱由你自己决定**——在 WorkBuddy 的 qq-mail 连接器中绑定**你自己的 QQ 邮箱**即可，本仓库不写死任何个人邮箱（详见下方「隐私」）。
- **频率**：**每周六 09:00 一次**（见「自动化」）。

## 🔍 关注点（自动生成）

报告末尾的「关注点」由 `generate_report.py` 的 `build_watchpoints()` 基于当周数据自动生成，中性、不含运营建议，分三级：

- **高**：强热点条目、合规风险（如「小黑班」等违规补习讨论）、国家级政策落地。
- **中**：跨层共振（同一关键词同时出现在政策/行业/小红书多层）、采集缺口（信息源未覆盖）。
- **低**：本窗口高热关键词（舆论焦点汇总）。

> 如果你只要"纯信息网页、完全不要任何建议板块"，把 `generate_report.py` / `build_email.py` 里调用 `build_watchpoints` 的那几行删掉即可，其余逻辑不受影响。

## 自动化（每周六 09:00 监测周报）

单个定时任务即可覆盖全流程：

**教育舆情监测周报（每周六）** `FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0`

任务逻辑（agent 执行）：

1. 若 `data/YYYY-MM-DD_raw.json`（当天，周六）不存在，先按三层采集并写入（WebSearch/WebFetch）；
2. 运行 `scripts/generate_report.py --days 7` 生成周报；
3. 运行 `scripts/build_email.py` 生成邮件版；
4. 通过 qq-mail 连接器 `SendMessage` 发送：收件人填**你自己的邮箱**，正文为 `_email.html` 完整内容，`body_format="HTML"`。

> 采集与发送取决于运行环境的 agent 能力和你连接的 qq-mail 账号；仓库本身只是"生成器 + 配置"。

## 别人如何复用 / 调用本工具

**方式 A：作为脚本工具（任何人，有 Python 即可）**

```bash
git clone <本仓库地址>
cd 教育舆情监测
# 准备数据：按 data/YYYY-MM-DD_raw.json 的 schema 放入采集结果
python3 scripts/generate_report.py 2026-08-12 --days 7
python3 scripts/build_email.py   2026-08-12
```

说明：三层"采集"依赖 agent 的 WebSearch/WebFetch；若只用脚本，需**自己按 schema 准备好 `data/YYYY-MM-DD_raw.json`**（仓库 `data/` 可作为示例），再跑生成器。生成器本身不联网。

**方式 B：作为 WorkBuddy 项目 / 技能（推荐，能自动采集）**  
因为本 README 就是写给 agent 的执行指令，对方可以：

- 把克隆下来的文件夹作为 **WorkBuddy 项目**打开，直接对 agent 说"按 README 生成本周监测周报"；或
- 在 `~/.workbuddy/skills/` 下建一个 `教育舆情监测/` 技能，里面放一个 `SKILL.md` 写"`read` 同目录 README.md，按其中步骤完成三层采集→生成→邮件"，即可作为可复用技能调用。

## 隐私

- **不含个人邮箱**：README 与脚本中**没有任何写死的私人邮箱**；发送时由运行者自己的 qq-mail 连接器决定收件人。
- **`.gitignore` 已忽略**：`.workbuddy/`（你的记忆/自动化配置）、`__pycache__/`、`.pyc`、`output/`（可重建的生成物）。请勿把这些提交上去。
- 提交 GitHub 时建议使用 GitHub 隐私邮箱（`你的ID+用户名@users.noreply.github.com`）作为 git 提交身份，避免暴露真实邮箱。

## 扩展方式

1. **新增信息源**：编辑 `config/sources.json`，在对应 layer 的 `sources` 数组追加 `{name, url, focus, freq}`。
2. **更新关键词**：编辑 `config/keywords.json` 的 `categories`（及 `hot_seed_keywords`），生成器自动做命中匹配与热度统计。本次已补充：小黑班、线下测评、诊断、线下试听、小低年级启蒙、班型体系讨论、定制班。
3. **小红书深度监测**：当前 L3 通过公开搜索近似获取家长热词与高热议题。如需真实笔记/互动数据，接入八爪鱼（bazhuayu）连接器，按四维度采集后用 `scripts/collect.py add` 写入 `data/`，复用同一生成器。
4. **调整报告样式**：修改 `scripts/generate_report.py` 的 `render_html` / `render_md`。
5. **调整邮件样式**：修改 `scripts/build_email.py` 的 `render_email_html`，保持标题为可点击超链接、内联样式适配手机端。
6. **调整关注点口径**：修改 `scripts/generate_report.py` 的 `build_watchpoints()`（规则见函数内注释：强热点/跨层共振/合规风险/采集缺口/政策落地/高热关键词）。

## 上传到 GitHub（详细步骤）

> 目标：把本仓库作为公开项目托管，供他人 clone / 安装为技能。

**1. 一次性准备**

- 注册 GitHub 账号（github.com）。
- 配置 git 提交身份，建议用 **GitHub 隐私邮箱**避免暴露真实邮箱：
  ```bash
  git config --global user.email "你的ID+用户名@users.noreply.github.com"
  git config --global user.name "你的昵称"
  ```
- 生成 Personal Access Token（PAT）：GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)，**勾选 `repo` 权限**，复制保存（只显示一次）。

**2. 在 GitHub 新建仓库**  
New repository → 名称建议 `edu-public-opinion-monitor`（或 `教育舆情监测`）→ 可见性 **Public** → **不要**勾选 "Initialize with README"（本地已有）→ Create repository。

**3. 本地初始化并提交**

```bash
cd /path/to/教育舆情监测
git init            # 若已是 git 仓库（本仓库当前已是 main 分支），可跳过此行
git add .
git commit -m "教育舆情监测周报工具：纯监测，含三层采集/生成/邮件"
```

> `.gitignore` 已忽略 `.workbuddy/`、`__pycache__/`、`*.pyc`、`output/`、`*.log`——不会把生成物和你的私人配置（邮箱/自动化）提交上去。

**4. 关联远端并推送**

```bash
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

> 若账号开启了两步验证/邮箱登录，**push 时用 PAT 作为密码**，用户名填 GitHub 账号。

**5. 后续更新**

```bash
git add .
git commit -m "更新说明"
git push
```

（也可用 GitHub Desktop / VS Code 图形界面完成 3–5 步。）

## 别人如何安装 / 调用本技能（含连接器配置）

> **前置提醒**：本工具"抓取数据"依赖运行环境的连接器/网络能力。**安装后必须先配好连接器，否则采集会失败或退化为近似结果**——这是最常见的踩坑点。

### 方式 A：作为 WorkBuddy 技能安装（推荐，能自动采集 + 定时）

1. **拿到仓库**
   ```bash
   git clone https://github.com/你的用户名/仓库名.git
   # 或直接 GitHub 页面 Download ZIP 解压
   ```

2. **放入技能目录**  
   把整个文件夹重命名为 `edu-public-opinion-monitor`（与 git clone 默认名一致），放到：
   ```
   ~/.workbuddy/skills/edu-public-opinion-monitor/
   ```
   最终结构应为：
   ```
   ~/.workbuddy/skills/edu-public-opinion-monitor/
   ├── SKILL.md          ← 技能入口（agent 读它执行）
   ├── README.md         ← 完整执行细节
   ├── config/  sources.json  keywords.json
   ├── scripts/ generate_report.py  build_email.py
   └── data/    （空，运行时代理写入 raw.json）
   ```
   > Windows 上 `~` 通常是 `C:\Users\你的用户名\.workbuddy\`。
3. **配置连接器（关键，防抓取失败）**
   | 连接器                                                        | 必选？         | 用途                               | 不配的后果                   |
   | ---------------------------------------------------------- | ----------- | -------------------------------- | ----------------------- |
   | **qq-mail（QQ邮箱）**                                          | **必选（仅发送）** | 通过 `SendMessage` 把周报发到**你自己**的邮箱 | 收不到邮件；报告仍可本地生成查看        |
   | **bazhuayu（八爪鱼）**                                          | 可选          | 获取 L3 小红书**真实**笔记/互动数据           | L3 退化为 WebSearch 近似，仍可用 |
   | **WebSearch / WebFetch**                                   | 内置（无需配置）    | L1/L2/L3 默认采集手段                  | 一般默认可用；若环境禁用网络则抓不到      |
   | 在 WorkBuddy 左侧「连接器」入口逐一连接：QQ邮箱绑定**你自己的**邮箱；如需真实小红书数据再连八爪鱼。 |             |                                  |                         |
4. **触发**
   - 对 agent 说："按 SKILL.md 生成本周教育舆情监测周报"；或
   - 建定时任务 `FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0`，每周六 09:00 自动运行。

### 方式 B：作为脚本工具（任何人，有 Python 即可，无 agent 也能用）

```bash
git clone https://github.com/你的用户名/仓库名.git
cd 教育舆情监测
# 自己按 data/YYYY-MM-DD_raw.json 的 schema 准备好采集结果
python3 scripts/generate_report.py 2026-08-20 --days 7
python3 scripts/build_email.py   2026-08-20
```

说明：生成器本身**不联网**；三层"采集"依赖运行环境的 agent（WebSearch/WebFetch/bazhuayu）或你**手动**填 `data/`。只想看报告、不想配连接器时，用方式 B 即可。

### 连接器问题排查

| 现象              | 原因                                            | 解决                                   |
| --------------- | --------------------------------------------- | ------------------------------------ |
| L3 小红书数据空/不准    | 未连 bazhuayu 且 WebSearch 受限                    | 连接八爪鱼，或放宽 WebSearch 查询               |
| 完全抓不到任何数据       | 环境无网络 / 无 WebSearch 权限                        | 确认具备 WebSearch/WebFetch；或手动填 `data/` |
| 报告生成了但没收到邮件     | 未连 qq-mail 或收件人错                              | 连接 QQ邮箱并绑定自己的邮箱，确认 `SendMessage` 收件人 |
| 推送 GitHub 被拒    | 未用 PAT / 未开权限                                 | 用 classic PAT（勾选 `repo`）作密码重新 push   |
| 技能装好但 agent 不识别 | 文件夹未放在 `~/.workbuddy/skills/` 下或缺少 `SKILL.md` | 检查目录层级，确保 `SKILL.md` 直接在技能目录内        |
