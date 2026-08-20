@echo off
REM ============================================================
REM 教育舆情监测周报 · 一键安装脚本（Windows / Git Bash）
REM 把本仓库克隆到 %USERPROFILE%\.workbuddy\skills\edu-public-opinion-monitor，
REM 即可在 WorkBuddy 中以「技能」方式调用。
REM
REM 用法（在 Git Bash 或 PowerShell 中）：
REM   ./install.bat                                              REM 用默认仓库地址
REM   ./install.bat https://github.com/Edward1018/repo.git        REM 自定义仓库
REM   ./install.bat <repo-url> <target-dir>                      REM 完全自定义
REM
REM 默认仓库：https://github.com/Edward1018/edu-public-opinion-monitor.git
REM 默认目标：%USERPROFILE%\.workbuddy\skills\edu-public-opinion-monitor
REM ============================================================

setlocal

set REPO_URL=%1
if "%REPO_URL%"=="" set REPO_URL=https://github.com/Edward1018/edu-public-opinion-monitor.git

set TARGET_DIR=%2
if "%TARGET_DIR%"=="" set TARGET_DIR=%USERPROFILE%\.workbuddy\skills\edu-public-opinion-monitor

echo 📦 仓库  : %REPO_URL%
echo 📂 目标  : %TARGET_DIR%
echo.

REM 目标已存在则中止
if exist "%TARGET_DIR%" (
    echo ❌ 目标目录已存在：%TARGET_DIR%
    echo    如需更新，请先删除或改名后再重跑。
    echo    命令：rmdir /s /q "%TARGET_DIR%"
    exit /b 1
)

REM 检查 git
where git >nul 2>&1
if errorlevel 1 (
    echo ❌ 未检测到 git，请先安装 Git for Windows 后重试。
    echo    下载：https://git-scm.com/download/win
    exit /b 1
)

for %%I in ("%TARGET_DIR%") do set PARENT=%%~dpI
if not exist "%PARENT%" mkdir "%PARENT%"

git clone "%REPO_URL%" "%TARGET_DIR%"
if errorlevel 1 (
    echo ❌ 克隆失败，请检查仓库地址或网络。
    exit /b 1
)

echo.
echo ✅ 安装成功！
echo.
echo 下一步：
echo   1. 打开 WorkBuddy
echo   2. 在对话中输入：用教育舆情监测技能跑一次今日周报
echo   3. 首次运行需要连接器（qq-mail 发邮件 / bazhuayu 真实小红书）
echo      可在「专家中心 → 连接器」按需启用
echo.
echo 卸载：
echo   rmdir /s /q "%TARGET_DIR%"
echo.
echo 更新：
echo   cd /d "%TARGET_DIR%" ^&^& git pull

endlocal