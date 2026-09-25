#!/usr/bin/env bash
# ============================================================
# 网关启动脚本（自用，2026-09-25）
# ★ 路径围笼：POWERIO_MCP_ALLOWED_ROOTS 允许 powerio server 读项目内算例
#   （examples/data/ 与 GridData/MatpowerData/）。
#   实测证据：.superpowers/sdd/m20-allowed-roots.py
#     - 允许根=项目根 → case30.m 解析成功（51215 字符）
#     - 允许根不含算例 → is_error=True（围笼确实在拦）
#   注意：MCP SDK 只继承白名单环境变量，此变量必须**显式设置**才会传给子进程。
#
# LLM 配置：密钥不进代码 —— 请在 shell 配置文件里 export POWERMCP_LLM_API_KEY，
# 或运行前临时设置。本脚本不会打印任何密钥。
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export POWERIO_MCP_ALLOWED_ROOTS="$ROOT"
# ★ 子项目 4：会话级持久 server 连接池（有状态工作流的前提，T6-M5 根治）
export POWERMCP_SESSION_POOL=1

: "${POWERMCP_LLM_BASE_URL:=https://api.deepseek.com}"
: "${POWERMCP_LLM_MODEL:=deepseek-chat}"
# 密钥回退映射：环境里已有 DEEPSEEK_API_KEY 时自动接上（值不打印、不落盘）
if [ -z "$POWERMCP_LLM_API_KEY" ] && [ -n "$DEEPSEEK_API_KEY" ]; then
  export POWERMCP_LLM_API_KEY="$DEEPSEEK_API_KEY"
fi
export POWERMCP_LLM_BASE_URL POWERMCP_LLM_MODEL
if [ -z "$POWERMCP_LLM_API_KEY" ]; then
  echo "[WARN] POWERMCP_LLM_API_KEY not set — /chat 不可用"
fi

echo "[run_gateway] root  = $ROOT"
echo "[run_gateway] fence = $POWERIO_MCP_ALLOWED_ROOTS"
echo "[run_gateway] llm   = $POWERMCP_LLM_BASE_URL (model: $POWERMCP_LLM_MODEL)"
echo
exec "$ROOT/PowerMCP/.venv/Scripts/python.exe" -m uvicorn \
  powermcp_gateway.api:create_app --factory --host 127.0.0.1 --port 8765
