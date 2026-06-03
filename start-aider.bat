@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ═══════════════════════════════════════════
REM  启动 Aider（自动读取项目配置）
REM ═══════════════════════════════════════════

cd /d "%~dp0"

REM 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在，请先创建 .venv
    pause
    exit /b 1
)

REM 加载 .env：优先从 AGENT_ENV_PATH 环境变量指定的路径，回退到项目目录
if defined AGENT_ENV_PATH (
    if exist "%AGENT_ENV_PATH%" (
        for /f "usebackq tokens=1,* delims==" %%a in ("%AGENT_ENV_PATH%") do (
            set "%%a=%%b"
        )
        echo [INFO] 已从 %AGENT_ENV_PATH% 加载配置
    ) else (
        echo [警告] AGENT_ENV_PATH 指向的文件不存在: %AGENT_ENV_PATH%
    )
) else (
    if exist ".env" (
        for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
            set "%%a=%%b"
        )
        echo [INFO] 已从项目目录 .env 加载配置
    )
)

REM 检查 aider 是否安装
.venv\Scripts\python.exe -c "import aider" 2>nul
if errorlevel 1 (
    echo [信息] 正在安装 aider-chat...
    .venv\Scripts\pip.exe install aider-chat --quiet
)

echo.
echo ╔══════════════════════════════════════════╗
echo ║  启动 Aider - 宝青坊项目                 ║
echo ╠══════════════════════════════════════════╣
echo ║  Architect: Claude 4 (规划方案)          ║
echo ║  Editor:    DeepSeek Coder (执行修改)    ║
echo ╠══════════════════════════════════════════╣
echo ║  常用命令:                                ║
echo ║  /add <file>   - 添加文件到上下文          ║
echo ║  /drop <file>  - 移除文件                ║
echo ║  /test         - 运行测试                ║
echo ║  /commit       - 提交修改                ║
echo ║  /undo         - 撤销上次修改            ║
echo ║  /quit         - 退出                    ║
echo ╚══════════════════════════════════════════╝
echo.

REM 启动 aider（自动读取 .aider.conf.yml）
.venv\Scripts\python.exe -m aider.main --config .aider.conf.yml

pause
