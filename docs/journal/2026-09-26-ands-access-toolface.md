---
date: 2026-09-26
type: journal
keywords: [ANDES, 接入, 工具面, inventory复用, 会话server清单, T6-M5残留, 变异m32]
git_branch: master
previous: 2026-09-25-serverpool-t6m5.md
note: 补记 6f5d454：张老师重测称「没有任何 ANDES 工具」→ 根因 MVP 建会话硬编码 servers=['surge','powerio']。inventory 复用池连接 + 会话 server 扩齐。测试 498 → 501；变异 m32 3/3 全红。
---

# ANDES 接入工具面（inventory 复用池连接 + 会话 server 清单扩齐）

## 一、动因（张老师重测）

模型称「没有任何 ANDES 工具」。实测 `andes 2.0.0` 可挂载（**6 工具**）；根因是 MVP 建会话**硬编码 `servers=['surge','powerio']`**，把 andes / pandapower / pypsa 全漏了。

## 二、设计

- **serverpool 泛化请求通道**：`call` 与 `list_tools` 走同一条持久连接；`ServerPool.list_tools` 断裂重连语义与 `call` 一致。
- **inventory 复用池连接**（`fetch_server_tools` / `build_inventory` 支持 `sid + pool`）：列工具不再每轮重新挂载全部 server —— 这是 T6-M5 在 inventory 侧的残留；**池未开启时保持原签名调用**，既有 monkeypatch 测试不受影响。
- **MVP 会话 server 扩为** `surge / powerio / pandapower / pypsa / andes`（见 `frontend/mvp.html`）。

## 三、验证

| 项 | 结果 |
|---|---|
| 单元 | `test_serverpool.py` +24、`test_pool_integration.py` +2 |
| 全量 | **498 → 501 passed**（无回归） |
| 变异探针 | **m32 3/3 全红**（复用 / 重连 / LRU） |
| 上游 | `PowerMCP/` · `PowerSkills/` 0 行改动 ✓ |

## 四、显式不做 / 后续

- ANDES 输出根在 `%USERPROFILE%\.powermcp`，需路径围笼放行（见 `2026-09-26-gateway-startup-hardening.md` 的**未提交补丁**——这是 `6f5d454` 的连带修复，待提交）。
- 接口冻结仍暂缓。
