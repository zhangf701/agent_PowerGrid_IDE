@echo off
setlocal
rem ============================================================
rem PowerMCP gateway launcher (self-use, 2026-09-25).
rem - POWERIO_MCP_ALLOWED_ROOTS: lets the powerio server read
rem   cases under the project (examples/data + GridData).
rem - POWERMCP_SESSION_POOL=1: persistent per-session server
rem   connections (stateful workflows, T6-M5 fix).
rem - LLM key is auto-mapped from DEEPSEEK_API_KEY if present.
rem   Keys are never printed or written to disk.
rem NOTE: keep this file ASCII + CRLF (cmd.exe parses UTF-8/LF badly).
rem ============================================================
setlocal
for %%i in ("%~dp0..") do set "POWERMCP_ROOT=%%~fi"
set "POWERIO_MCP_ALLOWED_ROOTS=%POWERMCP_ROOT%"
set "POWERMCP_SESSION_POOL=1"
if not defined POWERMCP_LLM_BASE_URL set "POWERMCP_LLM_BASE_URL=https://api.deepseek.com"
if not defined POWERMCP_LLM_MODEL set "POWERMCP_LLM_MODEL=deepseek-chat"
if not defined POWERMCP_LLM_API_KEY if defined DEEPSEEK_API_KEY set "POWERMCP_LLM_API_KEY=%DEEPSEEK_API_KEY%"
if not defined POWERMCP_LLM_API_KEY echo [WARN] POWERMCP_LLM_API_KEY not set - /chat will be unavailable
echo [run_gateway] root  = %POWERMCP_ROOT%
echo [run_gateway] fence = %POWERIO_MCP_ALLOWED_ROOTS%
echo [run_gateway] llm   = %POWERMCP_LLM_BASE_URL% (model: %POWERMCP_LLM_MODEL%)
echo.
"%POWERMCP_ROOT%\PowerMCP\.venv\Scripts\python.exe" -m uvicorn powermcp_gateway.api:create_app --factory --host 127.0.0.1 --port 8765
echo.
echo [run_gateway] gateway exited (code %errorlevel%). Press any key to close...
pause >nul
