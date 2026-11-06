#!/usr/bin/env bash
# 停止由 scripts/start.sh 启动的服务（依据 data/server.pid）
set -euo pipefail

cd "$(dirname "$0")/.."

DATA_DIR="${AUDIO2SRT_DATA_DIR:-$PWD/data}"
PID_FILE="$DATA_DIR/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "未找到 pid 文件: $PID_FILE（可用 pgrep -f 'uvicorn app.main:app' 查找进程）"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "已发送停止信号 pid=$PID"
else
  echo "进程不存在: pid=$PID"
fi

rm -f "$PID_FILE"
