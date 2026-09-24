# PowerMCP Gateway

本地网关：拉起 9 个开源 MCP server，求值 T0 静态契约，通过 HTTP 暴露契约状态。

## 运行

```bash
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app --factory --port 8765
```

## 端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 存活检查 |
| `GET /servers` | 已挂载的 9 个开源 server |
| `GET /contracts/t0` | T0 契约报告（`summary` + `findings`） |

## 测试

```bash
../PowerMCP/.venv/Scripts/python.exe -m pytest -m "not integration"   # 快
../PowerMCP/.venv/Scripts/python.exe -m pytest -m integration          # 需真实拉起 server
```

## 已知范围收窄

契约 1（API 版本）**无法可靠地静态判定** —— 工具实现调用的引擎 API 其接收者多为局部变量，
AST 不做类型推断即无法确定类型（真实缺陷 `net.deepcopy()` 正是此形态）。
因此契约 1 一律返回 `unknown / structural`，**不猜测**。详见 `contracts/api_version.py`。
