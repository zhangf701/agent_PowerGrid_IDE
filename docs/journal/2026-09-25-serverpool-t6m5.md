---
date: 2026-09-25
type: journal
keywords: [子项目 4, T6-M5, 连接池, 会话持久, 进程监管, 状态丢失, serverpool, 有状态工作流]
git_branch: master
previous: 2026-09-25-opendss-rootcause-pending.md
note: T6-M5 根治 —— 会话级持久 server 连接池。有状态工作流（载入→分析）从「不可能」到「可用」。测试 487 → 498。
---

# 子项目 4：会话级持久 server 连接池（T6-M5 根治）

## 一、动因（张老师首轮真实测试）

张老师在 MVP 里跑「载入算例 → 逐步分析」，LLM 的工具轨迹显示：`load_builtin_case`
成功后，下一次 `get_network_info` 报**没有已载入的网络**。代码层坐实：
`proxy._dispatch` 每次调用**新起 server 子进程、用完即关**。台账 T6-M5 原判
「慢」，实测是**功能阻断**——有状态工作流在旧架构下根本不可能。

## 二、设计（`gateway/src/powermcp_gateway/serverpool.py`）

- **一个 `(session_id, server)` 一条持久连接**：专属 asyncio task 持有
  `stdio_client + ClientSession` 上下文，经队列串行接活。
  ★ 上下文必须在**同一个 task** 进出（anyio cancel scope 是 task 绑定的）——
  这正是不能"把 session 存字典"的原因。
- **懒挂载**：首次用到才起进程。
- **断裂自愈**：传输断裂（进程崩溃/管道关闭，递归识别 anyio 的
  ClosedResourceError/BrokenResourceError/EndOfStream）→ 丢弃旧连接、重连一次、
  **重跑同一调用**，`remounted=True` 如实上报；`run_turn` 产出 `notice`：
  「进程已重连——此前装载的算例/网络状态已丢失」。
- **超时即弃**：调用超时（含**首次挂载**超时）→ 连接整体丢弃，宁可重挂也不复用可疑连接。
- **每会话 LRU 上限**（默认 6）：防长会话撑爆进程数。
- **连接器可注入**：测试用有状态假会话（`FakeSession` 计数器跨调用递增即证明复用）。
- **门控**：`POWERMCP_SESSION_POOL=1`（run_gateway 已设）或 `create_app(pool=…)`；
  **默认关闭** = 旧语义，既有 monkeypatch `_dispatch` 的测试全部不受影响。
- 观测面：`/health` 新增 `server_pool`：`{mounted, calls, remounts, evictions, max_per_session}`。

## 三、验证

| 项 | 结果 |
|---|---|
| 单元 + 集成 | `test_serverpool.py`（9）+ `test_pool_integration.py`（2）：复用 / 断裂重连 / 引擎失败不重连 / 超时弃连 / LRU / 会话清理 / HTTP 层状态持久 |
| 全量 | **498 passed, 2 deselected**（487 → 498，+11），无回归 |
| 变异探针 | **3/3 全红**（`m32-pool-mutation.py`：复用 / 重连 / LRU） |
| **真进程实测** | 网关（池开启）+ 真 surge：`load_builtin_case case14` → `get_network_info` 返回 `"name": "case14", 14 母线, 20 支路, 5 机组` —— **正是张老师失败的场景，状态跨调用存活**；池 `mounted=1, calls=2, remounts=0` |
| 上游 | `PowerMCP/` · `PowerSkills/` 0 行改动 ✓ |

## 四、显式不做 / 后续

- server 重连后**不假装恢复状态**——如实上报丢失（fail-loud 于用户体验）。
- `inventory.fetch_server_tools` 保持逐次挂载（列工具无状态）。
- 会话删除端点尚不存在；池的会话清理挂 lifespan + LRU，将来加 `DELETE /sessions/{sid}` 时接上。
