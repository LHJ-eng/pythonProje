#!/usr/bin/env bash
# 本地一键启动（Linux / macOS）。Windows 请参考 README 手动执行命令。
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d ".venv" ]; then
  echo "==> 创建虚拟环境 .venv"
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi" >/dev/null 2>&1; then
  echo "==> 安装依赖"
  pip install -r requirements.txt
fi

if [ ! -f ".env" ]; then
  echo "==> 未找到 .env，已从 .env.example 复制，请修改其中的 APP_PASSWORD"
  cp .env.example .env
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "==> 启动 DataHarvester: http://${HOST}:${PORT}"
exec uvicorn app.main:create_app --factory --host "$HOST" --port "$PORT"
