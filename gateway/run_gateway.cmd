@echo off
rem ============================================================
 rem 网关启动脚本（自用，2026-09-25）
rem ★ 路径围笼：POWERIO_MCP_ALLOWED_ROOTS 允许 powerio server 读项目内算例
rem   （examples/data/ 与 GridData/MatpowerData/）。
rem   实测证据：.superpowers/sdd/m20-allowed-roots.py
rem     - 允许根=项目根 → case30.m 解析成功（51215 字符）
rem     - 允许根不含算例 → is_error=True（围笼确实在拦）
rem   注意：MCP SDK 只继承白名单环境变量，此变量必须**显式设置**才会传给子进程。
rem
rem LLM 配置：密钥不进代码 —— 请在系统环境变量里设 POWERMCP_LLM_API_KEY，
rem 或运行前 set POWERMCP_LLM_API_KEY=sk-xxx（本脚本不会打印任何密钥）。
rem ============================================================
setlocal
for %%i in ("%~dp0..") do set "POWERMCP_ROOT=%%~fi"
set "POWERIO_MCP_ALLOWED_ROOTS=%POWERMCP_ROOT%"

if not defined POWERMCP_LLM_BASE_URL set "POWERMCP_LLM_BASE_URL=https://api.deepseek.com"
if not defined POWERMCP_LLM_MODEL set "POWERMCP_LLM_MODEL=deepseek-chat"
if not defined POWERMCP_LLM_API_KEY echo [WARN] POWERMCP_LLM_API_KEY not set — /chat will be unavailable

echo [run_gateway] root   = %POWERMCP_ROOT%
echo [run_gateway] fence  = %POWERIO_MCP_ALLOWED_ROOTS%
echo [run_gateway] llm    = %POWERMCP_LLM_BASE_URL% (model: %POWERMCP_LLM_MODEL%)
echo.
"%POWERMCP_ROOT%\PowerMCP\.venv\Scripts\python.exe" -m uvicorn powermcp_gateway.api:create_app --factory --host 127.0.0.1 --port 8765
