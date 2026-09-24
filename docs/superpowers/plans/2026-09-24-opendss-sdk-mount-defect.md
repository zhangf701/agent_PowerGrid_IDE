# OpenDSS 无法经 mcp SDK 挂载 —— 缺陷立项与排查计划

> **性质**：**独立缺陷立项**（不是实施计划）。本文只做"现象固化 + 已排除项 + 待查假设 + 判定标准"，
> 不含修复步骤 —— 根因未定，任何修复方案都是猜测。
>
> | 项 | 值 |
> |---|---|
> | 日期 | 2026-09-24 |
> | 状态 | **未解决**（opendss 未进入 gateway 的 inventory） |
> | 影响面 | 契约 2（文档-实现）· 契约 8（运行时依赖）· 能力矩阵 §4.4 的 OpenDSS 行 · 方案 §1.1「OpenDSS 工具面不可核实」 |
> | 上游 | `docs/superpowers/plans/2026-09-24-gateway-contract-engine-t0.md` Task 9 Step 5 |
> | 关联 | `gateway/src/powermcp_gateway/inventory.py`（`fetch_server_tools`） |
> | 边界 | **不改 `PowerMCP/` 一行**（zero source mutation）· **不改 `mcp` SDK**（上游） |

---

## 一、现象

`fetch_server_tools(cfg, "opendss")` 抛 `TimeoutError`（90s / 180s 均超时），
导致 opendss 不在 `ToolInventory` 中：

```
拉取失败: [('opendss', 'TimeoutError: ')]
已挂载 server: andes, egret, genx, hope, pandapower, powerio, pypsa, surge   ← 8 个，缺 opendss
```

**关键悖论**：同一个 opendss 进程，用**裸 stdio 探针**能正确响应，用 **mcp SDK 的
`stdio_client` + `ClientSession`** 却握手超时。

---

## 二、已排除项（每条都有实测证据，不是推断）

| # | 假设 | 结论 | 证据 |
|---:|---|:--:|---|
| 1 | 缺依赖 | ❌ 排除 | `py_dss_toolkit` 0.20.0 + `py-dss-interface` 2.3.0 已装；`probe_installed("py_dss_toolkit")` 通过 |
| 2 | 启动慢 / 超时值不够 | ❌ 排除 | 裸探针**响应延迟 1.86s**，与 andes（1.87s）完全同速；180s 上限仍超时 |
| 3 | MCP 协议不兼容 | ❌ 排除 | 用 **SDK 的原样报文**（`protocolVersion:"2025-11-25"`、`_meta:{}`、`clientInfo.name="mcp"`）重跑裸探针，opendss / andes / egret **三者响应逐字节同构**，唯一差异是 `serverInfo.name`（`PyDSS-MCP` vs `ANDES MCP Server` vs `Egret Power System Analy…`） |
| 4 | 入口方式差异 | ❌ 排除 | `python OpenDSS/opendss_mcp.py`（cwd=OpenDSS）与 `python -m powermcp.cli run opendss`（cwd=仓库根）**两条路径同样超时** |
| 5 | SDK 写侧不工作 | ❌ 排除 | 让 SDK 连一个"只 `read(200)` 并落盘的哑进程"，日志收到完整报文：`{"jsonrpc":"2.0","id":1,"method":"initialize",…,"_meta":{}}\n` → **SDK 确实写出了 initialize** |

### 附：三引擎响应逐字节对比（同一 SDK 报文）

```
andes   : {"jsonrpc":"2.0","id":1,"result":{"capabilities":{…},"protocolVersion":"2025-11-25","serverInfo":{"name":"ANDES MCP Server","version":""}}}
egret   : {"jsonrpc":"2.0","id":1,"result":{"capabilities":{…},"protocolVersion":"2025-11-25","serverInfo":{"name":"Egret Power System Analy…"}}}
opendss : {"jsonrpc":"2.0","id":1,"result":{"capabilities":{…},"protocolVersion":"2025-11-25","serverInfo":{"name":"PyDSS-MCP","version":""}}}
```

`capabilities` 完全一致（`experimental/prompts/resources/tools` 四项，`listChanged:false`）。

---

## 三、一次**未定论**的实验（记录在案，勿当结论）

用中间代理进程逐字节转发（`SDK → proxy → opendss`）并落盘日志，结果为
**`UP:` 字节全部出现、`DOWN:` 一条都没有**。

⚠️ **该实验有 confounder，结论不成立**：代理的 `up()` 用 `sys.stdin.buffer.read(1)`
逐字节转发，日志末尾**恰好缺最后一个 `\n`** —— 若该字节确实没送到，opendss 就是在
等一个不完整的行，自然不响应。因此这次实验**不能**证明"opendss 没回包"。

**重做要求**：改用块转发（`read(4096)`）+ 完整十六进制日志 + 转发后立即 `flush`，
并在子进程侧独立记录其 stdin 收到的字节数。

---

## 四、待查假设（按判别力排序）

### H1 ★ 最高优先级：initialize 报文是否被 opendss 提前消费

opendss 的依赖链里含 `ipython` / `ipywidgets` / `jupyterlab-widgets`（`py_dss_toolkit` 的依赖），
且其 `core/server.py` 会 `import core.engine` 触发 DSS 引擎初始化。
**若其中任何一步读取了 `sys.stdin`**，就会把 SDK 发来的 initialize 吃掉，
服务端则永远在等一个已经过去的请求 —— 这与"裸探针正常、SDK 超时"的现象**高度吻合**
（裸探针在 1.0s 后才写入，恰好躲过了启动期的读取窗口；SDK 是立即写入）。

**验证方法（决定性）**：写一个包装脚本，在 `from core.server import create_mcp` 之后、
`mcp.run()` 之前，把 `sys.stdin` 换成 tee 包装器，记录所有被读取的字节。
若启动期日志非空 → H1 成立，根因即"启动期消费 stdin"。

### H2：把 server 简化到最小 MCP server，二分定位

用一个只注册 1 个 tool、不 import 任何 opendss 代码的 `MCPServer` 脚本，
让 SDK 去连：
- 若**也超时** → 与 opendss 内容无关，问题在 spawn / 管道层（转 H4）
- 若**正常** → 与 opendss 的 import 副作用有关（转 H1）

### H3：重做代理实验（见 §三）

块转发 + 完整日志，确认 opendss 到底有没有回包。

### H4：stdout 句柄与缓冲

`py_dss_interface` 会加载 OpenDSS DLL。若该 DLL（或其宿主）复制 / 重定向了
stdout 句柄，SDK 的读端可能收不到。
**验证方法**：在 `mcp.run()` 前后打印 `os.fstat(1)`、`sys.stdout.isatty()`、
并用 `PYTHONUNBUFFERED=1` 复测。

---

## 五、判定标准（什么算"解决"）

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -c "
import asyncio
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.inventory import fetch_server_tools
cfg = GatewayConfig.discover()
tools = asyncio.run(fetch_server_tools(cfg, 'opendss'))
print(len(tools), [t.name for t in tools][:5])
"
```

必须返回工具清单而非 `TimeoutError`；且 `GET /contracts/t0` 的
`summary.incident_unknown` 由 1 降为 **0**，opendss 进入 inventory 后
契约 2 / 契约 8 对其给出真实判定。

**同时必须确认**：README 声明的 **55 个工具名**（v2 口径实测）与运行时工具面的差异 ——
这是方案 §1.1 所称"OpenDSS 声明的 6 个工具名全部不存在"的**唯一原始证据来源**，
此前因挂载失败从未被真正检验过。

---

## 六、若结论为"上游缺陷"时的处置

不改上游。在网关侧新增**「已知不兼容引擎」登记表**（`gateway/src/powermcp_gateway/compat.py`），
把 opendss 记为 `unknown / structural` 并在 `detail` 中指向本文档，
使契约面板能如实显示"该引擎无法挂载，原因见立项文档"，而不是一个无信息的 `TimeoutError`。

> 这一处置与契约 8 的语义一致：**能力声明 vs 实际可用**的错配必须可读，
> 而 `TimeoutError: ` 这种空消息恰恰是不可读的（参见 2026-09-24 记录中
> `build_inventory` 吞掉 anyio `ExceptionGroup` 内层信息的问题 —— 两者同源）。
