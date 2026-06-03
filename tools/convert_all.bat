@echo off
chcp 65001 >nul
echo ========================================
echo   FBX to GLB 批量转换工具
echo ========================================
echo.
echo 正在检查 Blender 路径...

set "BLENDER_EXE=D:\Program Files\Blender Foundation\Blender 5.1\blender.exe"

REM 如果上面找不到，尝试 5.1.2
if not exist "%BLENDER_EXE%" (
    set "BLENDER_EXE=D:\Program Files\Blender Foundation\Blender 5.1.2\blender.exe"
)

if not exist "%BLENDER_EXE%" (
    echo ❌ 未找到 Blender: %BLENDER_EXE%
    echo 请手动修改此脚本中的 BLENDER_EXE 路径
    pause
    exit /b 1
)

echo ✅ 找到 Blender: %BLENDER_EXE%
echo.
echo 开始批量转换...
echo.

"%BLENDER_EXE%" --background --python "%~dp0fbx_to_glb_batch.py"

echo.
echo ========================================
echo   转换完成！
echo ========================================
pause
