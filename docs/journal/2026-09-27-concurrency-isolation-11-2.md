# 2026-09-27 — §11.2 并发隔离（会话命名空间 · 租约 · 写串行化）

> 状态：✅ 已交付（网关侧）。网关 **613 → 635 passed**（+22）；变异探针 m41 **11/11 红**；
> 真实网关 e2e 三条全部拿到磁盘/统计级证据。
> 前置：方案 `PowerMCP_前端设计方案.md` §2.7 / §11.2 · [handoff_2026-09-27_p2-experiments-complete.md](handoff_2026-09-27_p2-experiments-complete.md)

## 一、§11.2 原文要求（五项措施）

| # | 措施 | 原文 |
|---:|---|---|
| 1 | 命名空间加 session 维度 | `runs_dir` 升级为 `~/.powermcp/runs/<session_id>/<tool>/<case_hash>/` |
| 2 | 租约锁 | 每 `(engine, case_hash)` 一把；本地 `fcntl` / `portalocker`，跨机文件租约 |
| 3 | 工作流级事务 | 产物写 staging；整体成功才 `os.replace` 提交；失败丢弃 staging |
| 4 | 引擎实例串行化 | 单实例 + 请求队列；跨机每容器一实例 + 负载均衡 |
| 5 | 统一写入方式 | 把 ANDES 等按名字拼路径的写法统一到 `mkstemp` / `staged_*_write` |

## 二、★ 关键可行性发现：措施 1 **不必改上游**

`PowerMCP/` 是上游 clone（**一行不改**），而措施 1/5 原文都指向上游源码。核实后发现出路：

```
powermcp/paths.py:  runs_dir(tool) = powermcp_home() / "runs" / tool
powermcp/config.py: powermcp_home() = os.environ["POWERMCP_HOME"] or ~/.powermcp
```

⇒ **网关给每个会话的子进程注入不同的 `POWERMCP_HOME`**，上游的 `runs_dir` 就自动落到
`~/.powermcp/sessions/<sid>/runs/<tool>` —— 正是措施 1 的目标命名空间。**未改上游一行。**

## 三、交付内容

| 文件 | 内容 |
|---|---|
| `concurrency.py`（新） | `LeaseRegistry`（异步键控租约 + 超时 + 统计）· `session_home` / `session_env` · `case_key_of` · `file_write_lock` |
| `proxy.py` | `session_server_env()`（**唯一**的会话 env 实现）· `call_tool` 持 `(会话, 引擎)` 租约 · `_CURRENT_SID` |
| `serverpool.py` | `_server_env(sid)` —— 池按 `(sid, server)` 分桶，天然每会话一套命名空间 |
| `inventory.py` | legacy 路径同样走 `session_server_env`（同一实现，防漂移） |
| `config.py` | `server_env(overrides=…)` |
| `cases.py` | `register` / `unregister` 的读-改-写进锁 · 公开 `is_within_roots`（围笼判定只有一份） |
| `experiments.py` | `ExperimentStore.create` / `ResultsStore.merge` 进锁 · 每步 `(server, 算例键)` 租约 |
| `api.py` | 修 `_RUNNING` 竞态 · `/health` 暴露 `leases` 统计 |

### 五项措施的落地边界（诚实清单，不夸大）

| # | 措施 | 状态 |
|---:|---|---|
| 1 | 命名空间加 session 维度 | ✅ 实现并**磁盘级验证**（见 §五） |
| 2 | 租约锁 | ⚠️ **进程内**（`LeaseRegistry`）；**跨进程 / 跨机文件租约未做** |
| 3 | 工作流级事务 | ✅ 网关自身状态（读-改-写整体进锁 + 临时文件 + `os.replace`）；⚠️ 引擎产物属上游 |
| 4 | 引擎实例串行化 | ✅ `(会话, 引擎)` 租约；且**连接池本身即"队列串行接活"**（核实所得） |
| 5 | 统一写入方式 | ❌ **上游所有**（`ANDES/andes_mcp.py` 按名字拼路径）；由措施 1 缓解 |

★ **措施 4 的一个事实修正**：核实 `serverpool._Conn._run` 后确认，连接池**本来就是队列串行**
（"专属 task 持有上下文，队列串行接活"）⇒ 池开启时引擎实例串行化**已由池保证**。
本步的 `(会话, 引擎)` 租约真正起作用的是**无池路径**（那里每次调用各起一个进程，
却共享同一 `runs/` 目录）—— 实测见 §五。

## 四、开发中修掉的 3 个真实缺陷

1. **`_RUNNING` 竞态（本会话 ①b-2 引入的）**：原顺序是「检查 → `await` 取清单 → `add`」，
   两个并发 `POST /run` 会**都通过检查**（此时谁都还没 add）⇒ 防护形同虚设。
   改为「检查 + **立即占位** → try/finally 释放」。现在用**真并发**测试钉住。
2. **三处 JSON 索引的丢更新**：`CaseStore.register` / `ExperimentStore.create` /
   `ResultsStore.merge` 都是 `_load()` → 改 → `_write()`，**只锁 `_write` 挡不住**
   （两个请求各自读到旧 rows，后写的覆盖先写的）。改为读-改-写**整体**进锁，
   并用"8 线程并发登记一个不少"的测试证明。
3. **`waited` 统计的漏计**：初版按 `waiting > 0` 判"是否需要排队"，而锁空闲时
   `await acquire()` **不会让出事件循环** ⇒ 前一个持有者在下一个 await 点前就把
   `waiting` 减回去了 ⇒ 实测两个协程争一把锁，`waited` 却是 0。
   改为按 **`lock.locked()`** 判（用真实并发测试发现，不是靠读代码）。

## 五、真实网关 e2e（三条证据）

| 证据 | 结果 |
|---|---|
| **① 命名空间落盘**（8767 无池，ANDES 真实跑潮流） | 会话 `624e9dbec6ae` 下出现 `~/.powermcp/sessions/624e9dbec6ae/runs/andes/pf_case39/case39.m` 与 `mcp_server.log` —— 产物落在**该会话自己的**命名空间，不是共享的 `~/.powermcp/runs/andes/`。同时证明**围笼覆盖了会话目录**（否则 `checked_path(for_write=True)` 会拒写） |
| **② 租约真的排队**（8767 无池，同会话并发两次 `load_network`） | 两次都 `ok`；`/health` 的 `leases` = `acquired=2, waited=1, max_waiters=2` —— 第二个**确实排队了** |
| **③ 并发 run 被拒**（8766 有池，并发两个 `POST /run`） | `req1 HTTP=200` / `req2 HTTP=409`（"该实验正在执行中"） |
| 附：上游路径验证 | 注入 env 后子进程里 `runs_dir('andes')` = `~/.powermcp/sessions/e2e-sess-1/runs/andes`，且**目录被真实创建** |

## 六、验证

- 网关 pytest **613 → 635 passed**（新增 `tests/test_concurrency.py` 20 条 + API 层 2 条）。
- 变异探针 **m41 11/11 全红**（新建）：L1–L4 租约 · S1–S3 命名空间 · W1–W2 写锁 ·
  C1 引擎串行化 · R1 `_RUNNING` 竞态。
- ⚠️ **探针自检机制补强**（本步实测踩到，已修）：
  - **锚点唯一性**：`count(anchor) == 1` 先校验 —— 实测 W2 锚点命中 2 次（会静默打空）。
  - **写入回读校验**：沙箱 fs shim 下 `write_text` 实测会不生效 ⇒ 写后回读比对，
    不一致即**响亮退出**（否则"测试没变红"会被误读成"测试没区分力"）。
  - **单条超时保护**：变异若让测试**挂死**（而非报错），单条 120s 超时兜住，
    否则整个探针卡住、源码停在变异态。
  - **恢复不依赖备份文件**：实测一次异常退出后源码**留在变异态**，而它是新文件、
    `git diff` 看不见 —— 改为直接写回原文 + 恢复后逐一比对。

## 七、诚实边界（**不得**被读成"并发已完全安全"）

1. **租约是进程内**的。多网关进程同时跑同一算例仍可能争用 —— 措施 2 的
   "跨机文件租约"部分**未做**。
2. **措施 5 属上游**（ANDES 按名字拼路径），本步**未改**上游；由措施 1 缓解。
3. `ALLOWED_ROOTS` 检查**无法阻止另一进程在验证后替换路径**（上游源码已自陈）——
   租约 + 事务提交可缓解，**不可宣称消除**。
4. 实验执行仍是**串行**的（方案 §4.4 裁决）；本步只是把**并发化的前置条件**补齐，
   **没有**打开并发开关。
