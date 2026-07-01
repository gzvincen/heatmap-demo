@echo off
REM 启动病理热力图查看器服务
REM Usage: serve.bat [port]

cd /d "%~dp0"

if "%1"=="" (
    python serve.py
) else (
    python serve.py %1
)
