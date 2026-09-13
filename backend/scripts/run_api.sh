#!/usr/bin/env bash
# 啟動新後端（caseapi），並且一定會載入專案根目錄的 .env。
#
# 為什麼需要這個腳本：`caseapi/config.py` 只讀 `os.environ`（12-factor 的作法，
# 也是測試能預期行為的前提），本身不會去讀 .env。直接跑
# `uvicorn caseapi.main:app` 的話，.env 裡的 `CASEAPI_MODEL_PROVIDER=agentcore`
# 不會生效，後端會默默用固定假模型啟動——「問 AI」就只會回佔位字串，看起來
# 像壞掉。這裡用 uvicorn 內建的 `--env-file` 把它載進來，並在啟動時把實際會用
# 的 provider 印出來，讓降級一定看得見。
#
# 用法：
#   backend/scripts/run_api.sh              # 預設 127.0.0.1:8001
#   PORT=8002 backend/scripts/run_api.sh    # 換埠

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/backend"
ENV_FILE="$ROOT/.env"
PYTHON="$BACKEND/.venv/bin/python"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"

if [ ! -x "$PYTHON" ]; then
  echo "找不到 $PYTHON；請先建立 backend/.venv（不要另建新的 venv）。" >&2
  exit 1
fi

args=(-m uvicorn caseapi.main:app --host "$HOST" --port "$PORT")

if [ -f "$ENV_FILE" ]; then
  args+=(--env-file "$ENV_FILE")
  provider="$(grep -E '^CASEAPI_MODEL_PROVIDER=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)"
  provider="${provider:-fixed}"
  echo "載入 $ENV_FILE，model provider = ${provider}"
  if [ "$provider" = "agentcore" ]; then
    echo "注意：agentcore 會把選取的案件內容送到 AWS Bedrock AgentCore Runtime。"
  fi
else
  echo "找不到 $ENV_FILE：將以固定假模型（fixed）啟動，「問 AI」只會回佔位字串。" >&2
fi

cd "$BACKEND"
exec "$PYTHON" "${args[@]}"
