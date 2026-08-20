#!/usr/bin/env bash
# ============================================================
# 教育舆情监测周报 · 一键安装脚本（macOS / Linux）
# 把本仓库克隆到 ~/.workbuddy/skills/edu-public-opinion-monitor，
# 即可在 WorkBuddy 中以「技能」方式调用。
#
# 用法：
#   ./install.sh                                          # 用默认仓库地址
#   ./install.sh https://github.com/Edward1018/repo.git   # 自定义仓库
#   ./install.sh <repo-url> <目标目录>                     # 完全自定义
#
# 默认仓库：https://github.com/Edward1018/edu-public-opinion-monitor.git
# 默认目标：$HOME/.workbuddy/skills/edu-public-opinion-monitor
# ============================================================

set -e

SKILL_NAME="edu-public-opinion-monitor"
DEFAULT_REPO="https://github.com/Edward1018/edu-public-opinion-monitor.git"
DEFAULT_TARGET="$HOME/.workbuddy/skills/$SKILL_NAME"

REPO_URL="${1:-$DEFAULT_REPO}"
TARGET_DIR="${2:-$DEFAULT_TARGET}"

echo "📦 仓库  : $REPO_URL"
echo "📂 目标  : $TARGET_DIR"
echo ""

# 目标已存在则中止，避免覆盖用户已有数据
if [ -e "$TARGET_DIR" ]; then
    echo "❌ 目标目录已存在：$TARGET_DIR"
    echo "   如需更新，请先改名或删除后再重跑。"
    echo "   命令：rm -rf \"$TARGET_DIR\""
    exit 1
fi

# 检查 git
if ! command -v git >/dev/null 2>&1; then
    echo "❌ 未检测到 git，请先安装 Git 后重试。"
    echo "   macOS: xcode-select --install"
    echo "   Linux: sudo apt install git / yum install git"
    exit 1
fi

mkdir -p "$(dirname "$TARGET_DIR")"
git clone "$REPO_URL" "$TARGET_DIR"

cat <<EOF

✅ 安装成功！

下一步：
  1. 打开 WorkBuddy
  2. 在对话中输入：用教育舆情监测技能跑一次今日周报
  3. 首次运行需要连接器（qq-mail 发邮件 / bazhuayu 真实小红书）
     可在「专家中心 → 连接器」按需启用

卸载：
  rm -rf "$TARGET_DIR"

更新：
  cd "$TARGET_DIR" && git pull
EOF