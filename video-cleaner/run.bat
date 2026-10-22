@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [错误] 找不到 Python 环境: %PY%
    echo 请先运行 install.bat 完成部署。
    pause
    exit /b 1
)

echo ==============================================
echo   抖音短视频水印清除
echo ==============================================

if "%~1"=="" (
    echo 未拖入文件，将处理 input\ 目录下的全部 mp4
    echo.
    "%PY%" "%~dp0scripts\dewatermark.py" -i "%~dp0input" -o "%~dp0output"
) else (
    echo 处理: %~1
    echo.
    "%PY%" "%~dp0scripts\dewatermark.py" -i "%~1" -o "%~dp0output"
)

echo.
echo 处理结束，成品在 output\ 目录。
pause
