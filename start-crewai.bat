@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ═══════════════════════════════════════════
REM  启动 CrewAI 任务编排
REM ═══════════════════════════════════════════

cd /d "%~dp0"

REM 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在
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

echo.
echo ╔══════════════════════════════════════════╗
echo ║  CrewAI 任务启动 - 宝青坊项目            ║
echo ╠══════════════════════════════════════════╣

REM 显示可用模型
if defined ANTHROPIC_API_KEY echo ║  [✓] Claude 4 可用                      ║
if defined OPENAI_API_KEY     echo ║  [✓] GPT-4o 可用                        ║
if defined DEEPSEEK_API_KEY    echo ║  [✓] DeepSeek 可用                      ║

echo ╠══════════════════════════════════════════╣
echo ║  用法: python crew_setup.py --task       ║
echo ║  "描述" --type [bug^|feature^|refactor]   ║
echo ╚══════════════════════════════════════════╝
echo.

REM 检查 crewai 是否安装
.venv\Scripts\python.exe -c "import crewai" 2>nul
if errorlevel 1 (
    echo [信息] 正在安装 crewai...
    .venv\Scripts\pip.exe install crewai[tools] litellm --quiet
)

REM 如果没有参数，显示帮助
if "%~1"=="" (
    echo 示例任务:
    echo   start-crewai.bat --task "修复 motion_extractor 坐标系转换 bug" --type bug
    echo   start-crewai.bat --task "添加新闻演播室场景支持" --type feature
    echo   start-crewai.bat --task "重构 action_planner 模块" --type refactor
    echo.
    echo 直接运行会启动交互模式...
    pause
    goto :interactive
)

REM 有参数时直接运行
.venv\Scripts\python.exe crew_setup.py %*
goto :end

:interactive
echo.
echo 请输入任务描述（直接回车退出）:
set /p "TASK="
if "!TASK!"=="" goto :end

echo 请选择类型:
echo   1. bug - 修复 bug
echo   2. feature - 新功能
echo   3. refactor - 重构
echo   4. asset - 资产处理
set /p "TYPE=输入数字 (1-4, 默认1): "

set "TYPE_ARG=bug"
if "!TYPE!"=="2" set "TYPE_ARG=feature"
if "!TYPE!"=="3" set "TYPE_ARG=refactor"
if "!TYPE!"=="4" set "TYPE_ARG=asset"

echo.
echo 启动任务...
.venv\Scripts\python.exe crew_setup.py --task "!TASK!" --type !TYPE_ARG! -v

:end
pause
