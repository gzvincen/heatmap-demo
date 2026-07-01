#!/usr/bin/env bash
# 停止病理热力图查看器服务
# Usage: ./stop.sh

cd "$(dirname "$0")"

if [ -f .serve.pid ]; then
    PID=$(cat .serve.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "已停止服务 (PID: $PID)"
    else
        echo "进程 $PID 不存在，可能已停止"
    fi
    rm -f .serve.pid
else
    # 回退：通过端口查找进程
    PID=$(lsof -ti :8000 2>/dev/null)
    if [ -n "$PID" ]; then
        kill "$PID"
        echo "已停止服务 (端口 8000, PID: $PID)"
    else
        echo "服务未运行"
    fi
fi
