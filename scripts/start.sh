#!/usr/bin/env bash
# audio2srt API 启动脚本
#
# 用法:
#   scripts/start.sh                 # 前台启动，默认 127.0.0.1:8000
#   PORT=8123 scripts/start.sh       # 指定端口
#   nohup scripts/start.sh > data/server.log 2>&1 &   # 后台启动
#
# 若当前 .venv 没有安装 openai-whisper/torch，脚本会尝试复用参考项目 venv
# （路径可用 AUDIO2SRT_WHISPER_SITE 覆盖）。
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
VENV="${VENV:-.venv}"
DATA_DIR="${AUDIO2SRT_DATA_DIR:-$PWD/data}"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "未找到虚拟环境: $VENV（请先 python -m venv .venv && pip install -r requirements.txt）" >&2
  exit 1
fi

mkdir -p "$DATA_DIR"

# openai-whisper 体积大：未安装时允许复用已有环境（仅本地开发便利）
if ! "$PY" -c "import whisper" >/dev/null 2>&1; then
  CANDIDATE="${AUDIO2SRT_WHISPER_SITE:-$PWD/../audio2srt/.venv/lib/python3.12/site-packages}"
  if [ -d "$CANDIDATE" ] && PYTHONPATH="$CANDIDATE" "$PY" -c "import whisper" >/dev/null 2>&1; then
    export PYTHONPATH="$CANDIDATE${PYTHONPATH:+:$PYTHONPATH}"
    echo "[start] 复用外部 whisper/torch: $CANDIDATE"
  else
    echo "[start] 当前环境缺少 openai-whisper，请先执行: pip install -r requirements.txt" >&2
    exit 1
  fi
fi

echo $$ > "$DATA_DIR/server.pid"
echo "[start] http://$HOST:$PORT  pid=$(cat "$DATA_DIR/server.pid")  pid_file=$DATA_DIR/server.pid"

exec "$PY" main.py --host "$HOST" --port "$PORT"
