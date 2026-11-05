@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where pwsh >nul 2>nul
if %errorlevel%==0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
)

if %errorlevel% neq 0 (
    echo.
    echo 启动失败，请查看上面的错误信息。
    pause
)
endlocal
