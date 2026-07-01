@echo off
REM 停止病理热力图查看器服务
REM Usage: stop.bat

cd /d "%~dp0"

if exist .serve.pid (
    for /f %%i in (.serve.pid) do (
        taskkill /PID %%i /F >nul 2>&1
        if errorlevel 1 (
            echo 进程 %%i 不存在，可能已停止
        ) else (
            echo 已停止服务 (PID: %%i)
        )
    )
    del .serve.pid
) else (
    echo PID 文件不存在，尝试通过进程名停止...
    taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *serve.py*" >nul 2>&1
    if errorlevel 1 (
        echo 未找到 serve.py 进程
    ) else (
        echo 已停止服务
    )
)
