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
| `GET /contracts/t0` | T0 契约报告（`summary` + `findings`），`findings` 为 `ContractFinding` 形状 |
| `POST /sessions` | 建会话。体 `{"servers": [...]}`（可省，缺省＝全部开源 server）；返回 `{id, servers, created_at}`。未知 server → 400 |
| `GET /sessions/{sid}/events` | **SSE 事件流**。`event:` 名即通道（`evidence` 不可丢 / `telemetry` 可丢），`id:` 为单调 seq。⚠️ 服务端**不解析 `Last-Event-ID`**：重连一律按历史**全量重放**（因此不丢，但会重复，客户端可按 `id` 去重）。证据通道的记录与投递已**解耦**——落后的订阅者被标记（`lagged_queues` / `lagged_deliveries`）并主动断流，重连后由历史补齐，**持久记录不因旁观者阻塞而丢** |
| `POST /sessions/{sid}/tools/call` | 代理一次工具调用。体 `{"server","tool","args"}`。契约 3 **fail-closed**：未声明参数被拒**且不转发**（返回 `ok=false` + `violations`）。400＝请求体不合法 · 404＝会话或工具不存在 · 503＝配置/清单不可用 |

## 契约 3 的事件形状

契约 3（参数契约）是**事件驱动**的 —— 它**不进 `REGISTRY`**、不参与 T0 报告，
其结论以事件形式出现在 `/sessions/{sid}/events` 上，payload **同为 `ContractFinding` 同形**
（`contract`/`state`/`reason`/`subject`/`detail`/`evidence`），因此可与其他契约的 finding
一起喂给 `summarize()` 做双轨汇总。两类：

| `kind` | `state` / `reason` | 含义 |
|---|---|---|
| `contract_violation` | `violated` / — | 参数不合法，**已拒绝转发**（fail-closed） |
| `contract_unknown` | `unknown` / `structural` | 校验器**无法判定**（如 schema 畸形）—— 放行转发，但**不静默** |

前端应按 `kind` 分派、按 `state` 汇入汇总，**两者不可混用**。

## 测试

```bash
../PowerMCP/.venv/Scripts/python.exe -m pytest -m "not integration"   # 快
../PowerMCP/.venv/Scripts/python.exe -m pytest -m integration          # 需真实拉起 server
```

> ⚠️ **沙箱下必须给 `--basetemp` 指向一个「尚不存在」的新目录**（如
> `--basetemp=./.pytest_tmp/r1`）。指向已存在且含 >50 条目的目录时，pytest 启动时的
> `rm_rf` 会被批量删除护栏拦截 → `tmp_path` 类测试在 setup 阶段 ERROR，表现为
> 「76 passed / 23 errors」，极易被误读为代码回归。
>
> ⚠️ `gateway` 以 **editable** 方式装进 `PowerMCP/.venv`（`.pth` 指向 `gateway/src`），
> 因此 `git worktree` 出来的副本跑测试时会 import 到**原目录**的代码 —— 想用副本做
> 变异/隔离验证是无效的。

## 已知范围收窄

契约 1（API 版本）**无法可靠地静态判定** —— 工具实现调用的引擎 API 其接收者多为局部变量，
AST 不做类型推断即无法确定类型（真实缺陷 `net.deepcopy()` 正是此形态）。
因此契约 1 一律返回 `unknown / structural`，**不猜测**。详见 `contracts/api_version.py`。
