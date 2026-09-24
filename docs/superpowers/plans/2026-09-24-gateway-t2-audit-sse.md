# 契约引擎 T2 + 审计 + SSE 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让网关能**代理工具调用**、逐调用求值 T2 契约、并把契约状态经 **SSE 双通道**推给前端，全过程落 **NDJSON 审计**。

**Architecture:** 在已交付的网关（子项目 2）之上新增四块：会话与事件总线（含单调序列号）、NDJSON 审计（通道 A，不可丢）、T2 求值器（契约 3 参数校验 / 契约 4 状态映射可信度）、MCP 代理调用 + SSE 端点。**不改动 `PowerMCP/` 一行**。

**Tech Stack:** Python 3.12（复用 `PowerMCP/.venv`）· FastAPI + `StreamingResponse`（不引入 `sse-starlette`）· `mcp>=2,<3` 官方 SDK · pytest + pytest-asyncio

---

## Global Constraints

- **Python 解释器**：一律使用 `PowerMCP/.venv/Scripts/python.exe`（本机默认 `python` 是 3.9，**低于项目要求的 3.10**）
- **`PowerMCP/` 与 `PowerSkills/` 是上游 clone，一行不改**；两者停在非 main 分支是**有意冻结**的
- **契约编号与状态取值必须与《UI 设计规范》v1.2 严格一致**：
  - 编号 1–8 与方案 §2.2 一致；状态 `satisfied` / `degraded` / `violated` / `unknown`（`unknown` 必带 `reason: 'structural' | 'incident'`）
  - 汇总优先级 `incident > violated > degraded > satisfied`；**结构性未知不参与主徽标竞争**；空集汇总为 `unknown`
- **server id 一律小写**（`pandapower` / `pypsa` / …），取自 `powermcp/registry.py` 的 `Tool.name`，**不得用显示名**
- 复用既有代码：`GatewayConfig`（`config.py`）· `ToolInventory` / `ToolRecord`（`inventory.py`）· `ContractFinding` / `summarize`（`contracts/model.py`）· `EvaluatorRegistry` / `REGISTRY`（`contracts/registry.py`）

### ★ 两处判据的重新界定（均有实测依据，**不是照抄方案**）

#### 契约 3：方案 §2.3 的判据**已被实测证伪**

方案 §2.3 说「PyPSA `linearized` 案例的本质是**声明的 `inputSchema` 与实际函数签名不一致**，可静态差分检出」。

**实测（80 个工具 / 5 个 server）**：声明 schema 与 AST 提取的实现签名 **差分 0 条**。
根因：两者的**声明 schema 就是由同一份函数签名生成的**，结构上不可能不一致。

**`linearized` 的真相**：**调用侧**把不存在的参数传给了 PyPSA 库函数，被 `**kwargs` 静默吞掉。
契约 3 想防的事发生在**调用方与库之间**，而方案把它定位在"服务端声明与实现之间"。
补充实测：`**kwargs` 静默吞参形态全仓仅 2 处（`pypsa._optimize` / `surge._call`），信号过弱。

**重新界定 —— 代理侧参数校验**：网关作为 MCP 代理，在**转发 tool call 之前**用声明的
`input_schema` 校验参数；不符合即拒绝转发并记一条契约 3 finding。

> 这改变了契约 3 的性质：从「检视已有缺陷」变成「**阻止新缺陷**」，且落点正是那条缺陷实际发生的位置。

#### 契约 4：方案的判据含糊且不可判定，改为一条**可判定的等价命题**

方案 §2.2 说「求解器返回码 vs 引擎实际状态」，§11.1 又自陈「若返回码语义不明则需额外探测 → 降级为未知」。

**实测得到的判据**：**求解型工具若报告"成功"，但从未读取引擎的真实状态字段，则存在"求解失败被报成成功"的风险。**

实测产出 **6 条**，且对照组正确：

| 工具 | 引擎状态读取 | 判定 |
|---|---|---|
| `pandapower.run_power_flow` | `net.converged` | ✅ 可信 |
| `pandapower.run_contingency_analysis` | `contingency_net.converged` | ✅ 可信 |
| `andes.run_power_flow` | `ss.PFlow.converged` | ✅ 可信 |
| `andes.run_time_domain_simulation` | `"completed" if success else "failed"`（`success = ss.TDS.run()`） | ✅ 可信 |
| `pypsa.run_power_flow` | — | ⚠️ 风险 |
| `pypsa.run_contingency_analysis` | — | ⚠️ 风险 |
| `andes.run_eigenvalue_analysis` | — | ⚠️ 风险 |
| `egret.solve_unit_commitment_problem` / `solve_ac_opf` / `solve_dc_opf` | — | ⚠️ 风险 |

⚠️ **判据必须能区分「分层设计」与「以成功掩盖失败」**：pandapower 的 `status: "success"` 是
**传输层**语义，物理结果在 `converged` 字段 —— 那是正确设计，**不得误报**。上表 3 个 ✅ 就是对照组。

> ⚠️ **工具注册有两种形态**（2026-09-24 实测补充）：装饰器 `@mcp.tool` 与函数式 `mcp.tool()(fn)`。
> **OpenDSS 的 55 个工具全靠函数式注册** —— 只认装饰器会让它整站漏检（`tools=0`），
> 进而在 `checked == 0` 时报出一条假绿灯 `satisfied`。
> 故 Task 3 的 `_tool_functions` 必须**同时识别两种形态**，且 **`checked == 0` 一律报
> `unknown / structural`**（不得报 `satisfied`，与 UI 规范 P5「禁止静默 fail-open」一致）。
> 实测修正后：覆盖 **8/8** server，risky 仍 **6** 条；仅 `genx` 落 `unknown`
> （识别 7 个工具、无一匹配求解型命名 —— 判据不适用，而非判据失效）。

### 已知的既有缺陷（本计划不修，但会影响验收）

- **opendss 无法经 mcp SDK 挂载**（裸 stdio 探针正常、经 SDK 握手超时）——
  见 [opendss 缺陷立项](2026-09-24-opendss-sdk-mount-defect.md)。本计划所有涉及"全部 server"的验收**按 8 个计**。

---

## File Structure

```
gateway/src/powermcp_gateway/
├── session.py                    ← 新增：会话 + 事件总线（双通道 + 单调序列号）
├── audit.py                      ← 新增：NDJSON 审计（通道 A）
├── events.py                     ← 新增：SSE 序列化（双通道物理分离）
├── proxy.py                      ← 新增：MCP 代理调用（含契约 3 前置校验）
├── contracts/
│   ├── model.py                  ← 不动（复用）
│   ├── registry.py               ← 不动（契约 3 是事件驱动，不进 REGISTRY）
│   ├── server_dirs.py            ← 新增：server id → 目录名（**单一真源**）
│   ├── doc_impl.py               ← 修改：删本地副本，改引用 server_dirs
│   ├── api_version.py            ← 修改：删本地副本，改引用 server_dirs
│   ├── params.py                 ← 新增：契约 3 —— schema × args 校验（纯函数）
│   ├── status_mapping.py         ← 新增：契约 4 —— 状态映射可信度（AST）
│   └── engine.py                 ← 不动（T2 是事件驱动，不走周期性求值器）
└── api.py                        ← 重写：/sessions · /tools/call · SSE 端点

gateway/tests/
├── test_session.py · test_audit.py · test_events.py
├── test_server_dirs.py
├── test_contract_params.py · test_contract_status_mapping.py
├── test_proxy.py · test_api_t2.py
```

---

### Task 0: 会话与事件总线

**Files:**
- Create: `gateway/src/powermcp_gateway/session.py`
- Test: `gateway/tests/test_session.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Channel`（`enum.Enum`）：`EVIDENCE` / `TELEMETRY`
  - `Event`：`seq: int` · `channel: Channel` · `kind: str` · `payload: dict` · `at: str`
  - `Session`：`id: str` · `servers: tuple[str, ...]` · `created_at: str`
  - `EventBus`：`publish(channel, kind, payload) -> Event` · `subscribe() -> AsyncIterator[Event]` · `events() -> tuple[Event, ...]`
  - `SessionStore`：`create(servers) -> Session` · `get(sid) -> Session` · `bus(sid) -> EventBus`

> ★ **单调序列号是硬要求**（方案 §11.7-③）：多引擎结果到达顺序不确定，
> 靠序列号排序，否则一致性视图会**静默给出错误结论**（不报错、不变慢）。
>
> ★ **双通道必须物理分离**（方案 §2.3）：`EVIDENCE` 不可丢、`TELEMETRY` 可丢。
> 分离在**类型层**保证 —— 两者是不同的 `Channel` 值，且背压策略挂在通道上。

- [ ] **Step 1: 写失败的测试**

```python
import asyncio

import pytest

from powermcp_gateway.session import Channel, EventBus, SessionStore


def test_publish_assigns_monotonic_seq():
    bus = EventBus()
    a = bus.publish(Channel.EVIDENCE, "tool_call", {"tool": "run_power_flow"})
    b = bus.publish(Channel.TELEMETRY, "progress", {"pct": 50})
    c = bus.publish(Channel.EVIDENCE, "contract", {"contract": 3})
    assert [a.seq, b.seq, c.seq] == [1, 2, 3]
    assert a.channel is Channel.EVIDENCE
    assert b.channel is Channel.TELEMETRY


def test_events_preserve_order():
    bus = EventBus()
    for i in range(5):
        bus.publish(Channel.EVIDENCE, "e", {"i": i})
    assert [e.payload["i"] for e in bus.events()] == [0, 1, 2, 3, 4]


async def test_subscriber_receives_events_and_stops_on_close():
    bus = EventBus()
    got = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)          # 让订阅者先挂上
    bus.publish(Channel.EVIDENCE, "a", {})
    bus.publish(Channel.TELEMETRY, "b", {})
    await asyncio.sleep(0)
    bus.close()
    await asyncio.wait_for(task, timeout=2)

    assert got == [1, 2]


async def test_two_subscribers_both_get_all_events():
    """每个订阅者都拿到**全部**事件 —— 通道分离不是"分流"，是各自的过滤视图。

    ★ 修订（审查发现）：初版此测试**从未创建订阅者**，只断言了
    `subscriber_count() == 0` 与一条事件存在 —— 即"没人订阅时发布不崩"，
    与其函数名/docstring 声称的扇出语义无关。双通道分离是 ★ 要求，
    必须有真正验证它的测试。
    """
    bus = EventBus()
    got_a: list[int] = []
    got_b: list[int] = []

    async def consume(sink: list[int]):
        async for ev in bus.subscribe():
            sink.append(ev.seq)

    task_a = asyncio.create_task(consume(got_a))
    task_b = asyncio.create_task(consume(got_b))
    await asyncio.sleep(0)                       # 让两个订阅者都挂上
    assert bus.subscriber_count() == 2

    bus.publish(Channel.EVIDENCE, "a", {})
    bus.publish(Channel.TELEMETRY, "b", {})
    await asyncio.sleep(0)

    bus.close()
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2)

    assert got_a == [1, 2]
    assert got_b == [1, 2], "第二个订阅者没有拿到全部事件"
    assert bus.subscriber_count() == 0           # 生成器退出后自动注销


def test_session_store_create_and_get():
    store = SessionStore()
    s = store.create(servers=("pandapower", "pypsa"))
    assert s.id
    assert s.created_at.endswith("Z")
    assert store.get(s.id).servers == ("pandapower", "pypsa")
    assert store.bus(s.id) is store.bus(s.id)      # 同一会话同一个总线


def test_session_store_unknown_id_raises():
    with pytest.raises(KeyError):
        SessionStore().get("nope")


# ── 以下三条为审查发现的回归测试 ──────────────────────────────────────────

async def test_close_terminates_subscriber_with_full_queue():
    """★ 回归：`close()` 必须让队列已满的订阅者也退出。

    （初版 `except QueueFull: pass` 吞掉终止哨兵 → 该订阅者永久挂起。）
    """
    bus = EventBus()
    got: list[int] = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    for i in range(1025):                     # 超过 maxsize=1024，撑满队列
        bus.publish(Channel.TELEMETRY, "noise", {"i": i})
    assert bus.subscriber_count() == 1

    bus.close()
    await asyncio.wait_for(task, timeout=2)   # 初版会在此超时
    assert bus.subscriber_count() == 0


def test_publish_evidence_refuses_when_a_subscriber_queue_is_full():
    """★ 回归：证据通道不做半投递 —— 队列满时整体拒绝，且拒绝不留痕。"""
    bus = EventBus()
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait("filler")                    # 把队列占满
    bus._subscribers.append(q)

    with pytest.raises(RuntimeError, match="证据不可丢"):
        bus.publish(Channel.EVIDENCE, "critical", {})

    assert bus.events() == ()                 # 被拒绝的事件没有进入历史
    assert bus.publish(Channel.TELEMETRY, "noise", {}).seq == 1   # seq 也未被消耗


def test_publish_after_close_raises():
    bus = EventBus()
    bus.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        bus.publish(Channel.TELEMETRY, "x", {})


async def test_subscribe_after_close_returns_immediately():
    """★ 回归：close() **之后**才挂上的订阅者不得挂起。

    （给 `publish` 加 `_closed` 守卫时曾漏掉这个入口 —— 晚到的订阅者
      永远等不到事件，还会作为孤儿滞留在 `_subscribers`。）
    """
    bus = EventBus()
    bus.close()

    got: list[int] = []
    async for ev in bus.subscribe():          # 未修复时会永久挂起
        got.append(ev.seq)

    assert got == []
    assert bus.subscriber_count() == 0        # 不留孤儿


async def test_close_does_not_drop_evidence_when_queue_is_full():
    """★ 回归：队列**恰好填满**时 close()，不得丢弃任何一条 EVIDENCE。

    （曾为塞入终止哨兵而驱逐队首 —— 在拆除路径上静默丢掉一条证据，
      与 `publish()`「宁可拒绝发布也绝不丢证据」的取舍自相矛盾。）
    """
    bus = EventBus()
    got: list[int] = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    for i in range(1024):                     # 恰好填满 maxsize=1024（不触背压）
        bus.publish(Channel.EVIDENCE, "critical", {"i": i})
    assert got == [], "发布循环无 await，消费者不应在此前被调度"

    bus.close()
    await asyncio.wait_for(task, timeout=2)
    assert got == list(range(1, 1025)), "close() 丢弃了证据事件"


def test_close_is_idempotent():
    bus = EventBus()
    bus.close()
    bus.close()                               # 第二次应是 no-op，不得抛错
    with pytest.raises(RuntimeError, match="已关闭"):
        bus.publish(Channel.TELEMETRY, "x", {})


async def test_cancelled_subscriber_leaves_no_orphan():
    """★ 回归：订阅者被取消（SSE 客户端断开时正是如此）不得残留孤儿订阅。

    上一版用 `ensure_future` 竞速等「队列」与「关闭事件」，外层被取消时
    两个子任务无人回收 → GC 打印 `Task was destroyed but it is pending!`。
    pytest-asyncio 会在 teardown 前取消任务，所以那个泄漏**在测试里看不见、
    在 uvicorn 里才现形**。现版没有任何子任务，结构上不可能泄漏。
    """
    bus = EventBus()

    async def consume():
        async for _ in bus.subscribe():
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert bus.subscriber_count() == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert bus.subscriber_count() == 0        # 不留孤儿
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'powermcp_gateway.session'`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/session.py`**

```python
"""会话与事件总线。

★ 双通道（方案 §2.3）：EVIDENCE 不可丢 / TELEMETRY 可丢，**物理分离**。
  审计一旦可丢，审计就不可信 —— 契约面板全部结论随之失效。
★ 单调序列号（方案 §11.7-③）：多引擎结果到达顺序不确定，必须靠序列号排序，
  否则一致性视图会**静默给出错误的一致性结论**。
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator


class Channel(enum.Enum):
    EVIDENCE = "evidence"      # 不可丢：调用记录、契约判定、edits 轨迹
    TELEMETRY = "telemetry"    # 可丢：进度、临时状态


#: 背压策略挂在通道上，调用方无需记忆
DROPPABLE: dict[Channel, bool] = {Channel.EVIDENCE: False, Channel.TELEMETRY: True}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    seq: int
    channel: Channel
    kind: str
    payload: dict
    at: str


@dataclass(frozen=True)
class Session:
    id: str
    servers: tuple[str, ...]
    created_at: str


class EventBus:
    """会话内的事件总线。每个订阅者收到**全部**事件，各自按 channel 过滤。"""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscribers: list[asyncio.Queue[Event | None]] = []
        self._seq = 0
        self._closed = False

    def publish(self, channel: Channel, kind: str, payload: dict) -> Event:
        if self._closed:
            raise RuntimeError("EventBus 已关闭，不能再发布事件")

        # ★ 证据通道：**先全量校验，再动任何状态**（审查发现）
        #   初版是在投递循环里 raise —— 那时 _events 已追加、部分订阅者已收到，
        #   发布方重试又会 _seq += 1 再追加一条 → 不可丢的审计流里出现重复记录。
        #   现在：拒绝时不消耗 seq、不追加历史、不投递给任何人 —— 全有或全无。
        if not DROPPABLE[channel]:
            full = [q for q in self._subscribers if q.full()]
            if full:
                raise RuntimeError(
                    f"证据通道有 {len(full)} 个订阅者队列已满，拒绝发布 "
                    f"{kind}(channel={channel.value}) —— 证据不可丢，不做半投递"
                )

        self._seq += 1
        event = Event(seq=self._seq, channel=channel, kind=kind, payload=payload, at=_now())
        self._events.append(event)

        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                if not DROPPABLE[channel]:
                    # 不可达：单线程 asyncio 下，上面的预校验与这里之间没有 await，
                    # 队列不可能被填满。保留 raise 作为断言，而非静默丢弃证据。
                    raise AssertionError("预校验通过后仍遇到满队列 —— 不应发生")
        return event

    async def subscribe(self) -> AsyncIterator[Event]:
        """订阅事件流。

        ★ 在**已关闭**的总线上调用会**立即返回**，不得挂起 ——
          否则晚挂上的订阅者永远等不到事件，还会作为孤儿滞留在 `_subscribers`。
        ★ 终止条件：**已关闭 且 队列已排空** —— 先排空再退出，因此**零丢失**。
        """
        if self._closed:
            return

        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        try:
            while True:
                if self._closed and q.empty():
                    return
                event = await q.get()
                if event is None:          # 终止哨兵
                    return
                yield event
        finally:
            self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def close(self) -> None:
        """关闭总线：所有订阅者会在**排空积压后**终止，**不丢弃任何事件**。

        ★ 关键观察：**队列为空时，哨兵必然放得下** —— 所以只在空队列时放哨兵。
          队列非空时**不放也没关系**：订阅者排空后会自己检查
          `_closed and q.empty()` 并退出。
          这一条同时消掉了两种错误做法：
          - 初版 `except QueueFull: pass`（吞掉哨兵 → 队列满的订阅者永久挂起）；
          - 以及「驱逐队首腾位」（在拆除路径上静默丢掉一条可能是 EVIDENCE 的事件，
            与 `publish()`「宁可拒绝发布也绝不丢证据」自相矛盾）。

        **幂等**：重复调用无副作用。
        """
        if self._closed:
            return
        self._closed = True
        for q in list(self._subscribers):
            if q.empty():
                q.put_nowait(None)      # 队列空 → 一定放得下


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._buses: dict[str, EventBus] = {}

    def create(self, servers) -> Session:
        s = Session(id=uuid.uuid4().hex[:12], servers=tuple(servers), created_at=_now())
        self._sessions[s.id] = s
        self._buses[s.id] = EventBus()
        return s

    def get(self, sid: str) -> Session:
        return self._sessions[sid]

    def bus(self, sid: str) -> EventBus:
        return self._buses[sid]
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_session.py -v
```
Expected: PASS（**13 passed** —— 含审查新增的 6 条回归测试）

- [ ] **Step 5: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 会话与事件总线（双通道 + 单调序列号）"
```

---

### Task 1: NDJSON 审计（通道 A）

**Files:**
- Create: `gateway/src/powermcp_gateway/audit.py`
- Test: `gateway/tests/test_audit.py`

**Interfaces:**
- Consumes: `Event` / `Channel`（Task 0）
- Produces:
  - `AuditLog(root: Path)`：`append(session_id, event) -> None` · `replay(session_id) -> tuple[Event, ...]` · `flush() -> None`
  - `AuditLog.path_for(session_id) -> Path`

> ★ **为什么是 NDJSON 而不是 SQLite**（方案 §11.4）：WAL 允许单写多读，但**写仍串行**，
> 高频审计写入依然争用。审计是 append-only 事件流，OS 保证小写入的 append 原子性，**无跨写者锁争用**。
>
> ★ **只写 EVIDENCE 通道**。遥测不进审计 —— 否则审计文件会被进度噪声淹没。

- [ ] **Step 1: 写失败的测试**

```python
import json

import pytest

from powermcp_gateway.audit import AuditLog
from powermcp_gateway.session import Channel, Event


def _ev(seq: int, channel=Channel.EVIDENCE, kind="tool_call", payload=None) -> Event:
    return Event(seq=seq, channel=channel, kind=kind,
                 payload=payload or {"a": seq}, at="2026-09-24T00:00:00Z")


def test_append_writes_ndjson_one_event_per_line(tmp_path):
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.append("s1", _ev(2))
    log.flush()

    lines = log.path_for("s1").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["seq"] == 1
    assert first["channel"] == "evidence"
    assert first["kind"] == "tool_call"


def test_telemetry_is_not_audited(tmp_path):
    """通道 B 不入审计 —— 否则审计被进度噪声淹没。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1, channel=Channel.TELEMETRY, kind="progress"))
    log.append("s1", _ev(2, channel=Channel.EVIDENCE))
    log.flush()

    lines = log.path_for("s1").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 2


def test_replay_returns_events_in_order(tmp_path):
    log = AuditLog(tmp_path)
    for i in range(1, 6):
        log.append("s1", _ev(i))
    log.flush()

    events = log.replay("s1")
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].channel is Channel.EVIDENCE


def test_replay_missing_session_is_empty(tmp_path):
    assert AuditLog(tmp_path).replay("nope") == ()


def test_replay_skips_corrupt_trailing_line(tmp_path):
    """进程被杀死时最后一行可能写了一半 —— 回放必须跳过而不是崩。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()
    with log.path_for("s1").open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2, "channel": "evi')   # 截断

    assert [e.seq for e in log.replay("s1")] == [1]


def test_audit_file_per_session(tmp_path):
    log = AuditLog(tmp_path)
    assert log.path_for("s1") != log.path_for("s2")
    assert log.path_for("s1").name.startswith("audit-s1")


# ── 以下两条为实现者实测发现的回归测试 ──────────────────────────────────

def test_replay_sees_events_appended_without_explicit_flush(tmp_path):
    """★ 回归：append 有缓冲，replay 必须先 flush。

    初版 replay 直接 read_text，而 append 写的是带缓冲的文件对象 ——
    `_FLUSH_EVERY` 以内的事件**完全不可见**，且**静默返回**而非报错。
    原 6 条测试都在 replay 前调了 flush()，因此这个缺口毫无覆盖。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.append("s1", _ev(2))       # 故意不调 flush()

    assert [e.seq for e in log.replay("s1")] == [1, 2]


def test_replay_skips_valid_json_that_is_not_an_object(tmp_path):
    """★ 回归：截断的尾部可能是**合法 JSON 但不是对象**（如 `12345`）。

    初版只捕 JSONDecodeError，这种输入会抛 TypeError 把回放打崩，
    与 docstring 承诺的"不让回放崩掉"矛盾。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()
    with log.path_for("s1").open("a", encoding="utf-8") as fh:
        fh.write("12345\n")            # 合法 JSON，不是对象
        fh.write('"just a string"\n')

    assert [e.seq for e in log.replay("s1")] == [1]


def test_replay_survives_a_torn_multibyte_tail(tmp_path):
    """★ 回归：撕裂写入切断一个**多字节字符**时，回放不得整体崩掉。

    写入用 `ensure_ascii=False`，payload 常含中文；一次撕裂写入会留下
    半个 UTF-8 字符。`read_text` 不带 `errors=` 会抛 UnicodeDecodeError ——
    而读取是整文件的，于是**整个会话的审计全部读不出来**，远不止坏的那一行。
    （审查者已实测复现。）
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()

    # 手工追加一条被切断的多字节尾部（"中" 的 UTF-8 是 e4 b8 ad）
    with log.path_for("s1").open("ab") as fh:
        fh.write(b'{"seq": 2, "kind": "\xe4\xb8')

    events = log.replay("s1")          # 初版会在此抛 UnicodeDecodeError
    assert [e.seq for e in events] == [1]


def test_replay_preserves_events_containing_unicode_line_separators(tmp_path):
    """★ 回归：payload 含 U+2028 / U+2029 / U+0085 时，**完整合法**的事件不得丢。

    这三个码点 ≥ 0x20，`json.dumps(ensure_ascii=False)` **不转义**它们；
    而 `str.splitlines()` 把它们当行边界 → 一条完好的事件被切成两段、
    两段都解析失败 → 整条 EVIDENCE 在回放中消失，且被误报为"损坏行"。
    命中「证据不可丢」这条核心不变量。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1, payload={"text": "a\u2028b"}))   # LINE SEPARATOR
    log.append("s1", _ev(2, payload={"text": "c\u2029d"}))   # PARAGRAPH SEPARATOR
    log.append("s1", _ev(3, payload={"text": "e\u0085f"}))   # NEXT LINE
    log.flush()

    events = log.replay("s1")
    assert [e.seq for e in events] == [1, 2, 3], "含 U+2028/2029/0085 的完整事件被丢弃"
    assert events[0].payload["text"] == "a\u2028b"
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_audit.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/audit.py`**

```python
"""NDJSON 审计 —— 通道 A（不可丢）。

方案 §11.4：审计证据流用 **NDJSON 追加文件**（OS 保证小写入 append 的原子性、
无跨写者锁争用），而非 SQLite WAL（WAL 写仍串行，高频写入会争用）。

只落 EVIDENCE 通道；TELEMETRY 不进审计。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .session import Channel, Event

logger = logging.getLogger(__name__)

#: 批量 flush 的阈值 —— 每次 append 都 flush 会拖慢调用路径。
#: ⚠️ 这是 **flush（进 OS 页缓存）不是 fsync（落盘）** —— 名字如实反映行为，
#:    不得读作"断电可持久化"。（改名前叫 `_FSYNC_EVERY`，是个误导性命名。）
_FLUSH_EVERY = 32


class AuditLog:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, int] = {}
        self._handles: dict[str, object] = {}

    def path_for(self, session_id: str) -> Path:
        return self._root / f"audit-{session_id}.ndjson"

    def _handle(self, session_id: str):
        fh = self._handles.get(session_id)
        if fh is None:
            fh = self.path_for(session_id).open("a", encoding="utf-8")
            self._handles[session_id] = fh
        return fh

    def append(self, session_id: str, event: Event) -> None:
        if event.channel is not Channel.EVIDENCE:
            return                      # 通道 B 不入审计
        fh = self._handle(session_id)
        fh.write(json.dumps({
            "seq": event.seq,
            "channel": event.channel.value,
            "kind": event.kind,
            "payload": event.payload,
            "at": event.at,
        }, ensure_ascii=False) + "\n")

        n = self._pending.get(session_id, 0) + 1
        if n >= _FLUSH_EVERY:
            fh.flush()
            self._pending[session_id] = 0
        else:
            self._pending[session_id] = n

    def flush(self) -> None:
        for fh in self._handles.values():
            fh.flush()
        self._pending.clear()

    def replay(self, session_id: str) -> tuple[Event, ...]:
        """回放某会话的审计流。

        ★ 必须先 `flush()`：`append` 写的是**带缓冲的文件对象**，只有 flush 才落到
          OS 层；否则 `read_text` 读不到最近 `_FLUSH_EVERY` 条以内的事件，
          而且**静默返回不完整的结果**而非报错 —— 这是最难发现的一类错
          （已由实现者实测：append 2 条后 replay 返回空）。
        """
        self.flush()                        # ← 回归修复：见 docstring

        path = self.path_for(session_id)
        if not path.is_file():
            return ()

        # ⚠️ `errors="replace"` 不可省：写入用 `ensure_ascii=False`，payload 常含中文，
        #    一次撕裂写入会切断一个多字节字符 → 不带它则 read_text 抛 UnicodeDecodeError。
        #    而读取是**整文件**的，于是**整个会话的审计全部读不出来**，不只是坏的那一行。
        #    用了 replace 后，坏字节变成 U+FFFD → 该行 JSON 解析失败 → 按损坏行跳过。
        text = path.read_text(encoding="utf-8", errors="replace")

        out: list[Event] = []
        skipped = 0
        # ⚠️ 必须用 `split("\n")` 而**不是 `splitlines()`**：
        #    `str.splitlines()` 把 U+2028 / U+2029 / U+0085 也当行边界，
        #    而这三个码点 ≥ 0x20，`json.dumps(ensure_ascii=False)` **不转义它们**。
        #    于是 payload 含其中任一字符的**完整合法事件**会被从中间切开、
        #    两段都解析失败 → 整条证据在回放中消失，还被误报成"损坏行"。
        #    （审查者实测：U+2028/U+2029/U+0085 各切成 2 段；U+000B/U+001C 被转义故无害。）
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if not isinstance(d, dict):
                    raise ValueError("合法 JSON 但不是对象")
                out.append(Event(
                    seq=d["seq"], channel=Channel(d["channel"]), kind=d["kind"],
                    payload=d.get("payload") or {}, at=d["at"],
                ))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                # ⚠️ 跳过但**不静默** —— 否则"审计文件部分损坏"与"审计本来就少"
                #    回放结果一模一样，无法区分。
                skipped += 1
                logger.warning("审计行无法解析，已跳过：%s (%s)", exc, line[:80])
        if skipped:
            logger.warning("会话 %s 的审计回放跳过了 %d 行", session_id, skipped)
        return tuple(out)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_audit.py -v
```
Expected: PASS（**9 passed** —— 含 3 条回归测试）

- [ ] **Step 5: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): NDJSON 审计（通道 A，仅证据）"
```

---

### Task 2: 抽取共享的 server → 目录映射表

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/server_dirs.py`
- Modify: `gateway/src/powermcp_gateway/contracts/doc_impl.py`（删本地 `SERVER_DOC_DIRS` 定义，改为引用）
- Modify: `gateway/src/powermcp_gateway/contracts/api_version.py`（删本地 `SOURCE_DIRS` 定义，改为引用）
- Test: `gateway/tests/test_server_dirs.py`

**Interfaces:**
- Consumes: 无
- Produces: `SERVER_DIRS: dict[str, str]` —— server id → PowerMCP 仓库内的目录名（**单一真源**）

**为什么单独一个任务**：这个映射表在既有代码里**已经有两份**：
`doc_impl.SERVER_DOC_DIRS` 与 `api_version.SOURCE_DIRS`，两者当前逐项相同。
`api_version` 的注释甚至写着「与 doc_impl.SERVER_DOC_DIRS 同源」——
**作者知道该同源，但只写了注释、没做抽取**。Task 3 需要第三份，三份手工同步必然断裂。

> ⚠️ **同源实际上已经破了**：本计划初稿给 `hope` 写的是 `HOPE/src`，而既有两份是 `HOPE`。
> 两者都能工作（`rglob` 会递归进 `src/`），但取值不同就说明"同源"只是口号。
> 本任务统一为 `HOPE`。

> 📌 `powerio` **不在此表中** —— 它由自己的发行版提供（`python -m powerio.mcp`），
> PowerMCP 仓库内没有它的目录。这不是遗漏。

- [ ] **Step 1: 写失败的测试**

```python
import pytest

from powermcp_gateway.contracts.server_dirs import SERVER_DIRS

EXPECTED = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}


def test_mapping_matches_expected():
    assert SERVER_DIRS == EXPECTED


def test_powerio_is_intentionally_absent():
    """powerio 由自己的发行版提供，仓库内没有它的目录 —— 不是遗漏。"""
    assert "powerio" not in SERVER_DIRS


def test_is_single_source_of_truth():
    """★ 既有两处必须改为**引用**本模块，不得再各自持有副本。"""
    from powermcp_gateway.contracts import api_version, doc_impl

    assert api_version.SOURCE_DIRS is SERVER_DIRS
    assert doc_impl.SERVER_DOC_DIRS is SERVER_DIRS


def test_every_dir_exists_in_the_repo():
    from powermcp_gateway.config import GatewayConfig

    root = GatewayConfig.discover().powermcp_root
    for server, dirname in SERVER_DIRS.items():
        assert (root / dirname).is_dir(), f"{server} -> {dirname} 在仓库中不存在"
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_server_dirs.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'powermcp_gateway.contracts.server_dirs'`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/server_dirs.py`**

```python
"""server id → PowerMCP 仓库内目录名 —— **单一真源**。

本表原先在 `doc_impl.SERVER_DOC_DIRS` 与 `api_version.SOURCE_DIRS` 各有一份，
`api_version` 的注释还写着「与 doc_impl.SERVER_DOC_DIRS 同源」——
知道该同源却只写了注释，于是从"一处定义"退化成"两处手工同步 + 一句祈祷"。
新增第三个消费者（`status_mapping`）之前先抽取，否则必然断裂。

键一律是 `powermcp/registry.py` 的 `Tool.name`（小写 server id）。

⚠️ `powerio` 不在此表中：它由自己的发行版提供（`python -m powerio.mcp`），
   PowerMCP 仓库内没有它的目录。这不是遗漏。
"""

from __future__ import annotations

SERVER_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}
```

- [ ] **Step 4: 跑测试，确认前两条通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_server_dirs.py -v
```
Expected: FAIL —— 仅 `test_is_single_source_of_truth` 失败（两处仍是副本），其余通过

- [ ] **Step 5: 改 `doc_impl.py` 与 `api_version.py` 为引用**

在 `gateway/src/powermcp_gateway/contracts/doc_impl.py` 中，
**删除**这段本地定义（原第 53–63 行附近的 `SERVER_DOC_DIRS: dict[str, str] = { ... }` 整块），
在其位置改为：

```python
# 单一真源见 server_dirs.py；保留旧名以免改动本模块的既有调用点
from .server_dirs import SERVER_DIRS as SERVER_DOC_DIRS
```

在 `gateway/src/powermcp_gateway/contracts/api_version.py` 中，
**删除**注释「`# server id -> PowerMCP 仓库内的目录名（与 doc_impl.SERVER_DOC_DIRS 同源）`」
与紧随其后的整个 `SOURCE_DIRS: dict[str, str] = { ... }` 块，改为：

```python
from .server_dirs import SERVER_DIRS as SOURCE_DIRS
```

> ⚠️ 用 `as` 别名而不是把调用点改名为 `SERVER_DIRS`：实测这两个名字**只在本模块内部**被读取
> （`doc_impl` 第 113 行 `dict(SERVER_DOC_DIRS)`、`api_version` 第 79 行 `dict(SOURCE_DIRS)`），
> **测试并未引用它们**。改名的收益为零、回归面不为零。**先收敛真源，不顺手改名。**

- [ ] **Step 6: 跑全量单元测试，确认无回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration"
```
Expected: 全部 PASS（既有 99 + 本任务 4 = 103）

- [ ] **Step 7: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "refactor(gateway): 抽取 server→目录映射为单一真源（消除三份手工同步）"
```

---

### Task 3: 契约 4 —— 状态映射可信度

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/status_mapping.py`
- Test: `gateway/tests/test_contract_status_mapping.py`

**Interfaces:**
- Consumes: `ContractFinding`（既有）· `EvaluatorRegistry`（既有）· `GatewayConfig`
- Produces:
  - `SOLVE_NAME: re.Pattern`
  - `STATUS_KEYS: frozenset[str]`
  - `analyse_tool_fn(fn: ast.FunctionDef) -> tuple[bool, tuple[str, ...]]` —— `(是否硬编码成功, 引擎状态读取表达式)`
  - `StatusMappingEvaluator`（`contract = 4`，`timeframe = "T0"`）

**判据**（见 Global Constraints）：求解型工具 + 报告成功 + **无任何引擎状态读取** → `degraded`。
有读取 → `satisfied`。**无求解型工具** → `satisfied`。

> ⚠️ 本契约是 **T0（静态）**，不是方案 §2.2 标的 T2 —— 因为实测表明它**纯静态可判定**，
> 没有任何理由放到逐调用节拍上。这是对方案的一处**有意修正**。

- [ ] **Step 1: 写失败的测试**

```python
import ast
import textwrap

from powermcp_gateway.contracts.status_mapping import (
    StatusMappingEvaluator,
    analyse_tool_fn,
)


def _fn(src: str) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(src))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "tool")


def test_detects_engine_read():
    fn = _fn('''
    def tool():
        return {"status": "success", "converged": net.converged}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is True
    assert "net.converged" in reads


def test_detects_no_read():
    fn = _fn('''
    def tool():
        net.pf()
        return {"status": "success"}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is True
    assert reads == ()


def test_error_only_branch_is_not_flagged_as_success():
    fn = _fn('''
    def tool():
        try:
            net.pf()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    ''')
    hard, _ = analyse_tool_fn(fn)
    assert hard is False        # 只报 error 不算"报告成功"


def test_conditional_status_counts_as_read():
    fn = _fn('''
    def tool():
        success = run()
        return {"status": "completed" if success else "failed"}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is False, "条件表达式的状态不是**硬编码**成功（它有条件地报成功）"
    assert reads, "条件表达式的状态应被视为读取（值不是字面量常量）"


# —— 端到端：真实仓库上的对照 ——

def test_pypsa_run_power_flow_is_flagged(tmp_path):
    """★ 实测形态：PyPSA 的 run_power_flow 报 success 却不读 converged。"""
    d = tmp_path / "PyPSA"
    d.mkdir()
    (d / "pypsa_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def run_power_flow(network_name: str) -> dict:
            network = Network(network_name)
            network.pf()
            return {"status": "success", "buses": {}}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"pypsa": "PyPSA"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    risky = [f for f in findings if f.state == "degraded"]
    assert risky, f"未检出，实际 {[(f.subject, f.state) for f in findings]}"
    assert risky[0].subject == "pypsa"                       # finding 按 server 聚合
    assert risky[0].evidence["risky_tools"] == ["run_power_flow"]


def test_pandapower_design_is_not_flagged(tmp_path):
    """★ 对照组：status 硬编码 success 但 converged 读自引擎 —— 这是**正确设计**，不得误报。"""
    d = tmp_path / "pandapower"
    d.mkdir()
    (d / "panda_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def run_power_flow(net: str) -> dict:
            pp.runpp(net)
            return {"status": "success", "converged": net.converged}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"pandapower": "pandapower"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]
    assert [f.state for f in findings] == ["satisfied"]


def test_functional_registration_is_recognised(tmp_path):
    """★ 实测形态：OpenDSS 用 mcp.tool()(fn) 注册，不是装饰器。

    只认装饰器会让 OpenDSS 的 55 个工具全部漏检（见模块 docstring）。
    """
    d = tmp_path / "OpenDSS"
    d.mkdir()
    (d / "opendss_mcp.py").write_text(textwrap.dedent('''
        def solve_snapshot() -> dict:
            dss_tools.simulation.solve_snapshot()
            return {"status": "success"}

        def register_simulation_tools(mcp) -> None:
            mcp.tool()(solve_snapshot)
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"opendss": "OpenDSS"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    assert [f.state for f in findings] == ["degraded"], (
        f"函数式注册的 solve_snapshot 未被识别：{[(f.subject, f.state) for f in findings]}"
    )
    assert findings[0].evidence["risky_tools"] == ["solve_snapshot"]
    assert findings[0].evidence["tools_recognised"] == 1


def test_zero_checked_is_structural_unknown(tmp_path):
    """★ checked == 0 不得报 satisfied —— 那是假绿灯（UI 规范 P5 禁止静默 fail-open）。"""
    d = tmp_path / "GenX"
    d.mkdir()
    (d / "genx_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def dispatch() -> dict:
            return {"status": "success"}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"genx": "GenX"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    assert [f.state for f in findings] == ["unknown"]
    assert findings[0].reason == "structural"
    assert findings[0].evidence["tools_recognised"] == 1
    assert findings[0].evidence["solve_tools_checked"] == 0
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_status_mapping.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r3
```
Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/status_mapping.py`**

```python
"""契约 4：状态映射可信度。

## 判据的来历（不是照抄方案）

方案 §2.2 写的是「求解器返回码 vs 引擎实际状态」，§11.1 又自陈「若返回码语义不明
则需额外探测 → 降级为未知」—— 含糊且不可判定。

实测得到的**可判定等价命题**：

    求解型工具若报告"成功"，但**从未读取引擎的真实状态字段**，
    则存在"求解失败被报成成功"的风险。

实测（2026-09-24，8 个 server）产出 6 条，且对照组正确：
  pandapower.run_power_flow         读 net.converged            → 不报
  pandapower.run_contingency_analysis 读 contingency_net.converged → 不报
  andes.run_power_flow              读 ss.PFlow.converged        → 不报
  andes.run_time_domain_simulation  读 "completed" if success else "failed" → 不报
  pypsa.run_power_flow              无读取                        → 报
  pypsa.run_contingency_analysis    无读取                        → 报
  andes.run_eigenvalue_analysis     无读取                        → 报
  egret.solve_unit_commitment_problem / solve_ac_opf / solve_dc_opf 无读取 → 报

⚠️ 判据必须区分「分层设计」与「以成功掩盖失败」：pandapower 的 `status: "success"`
   是**传输层**语义，物理结果在 `converged` 字段 —— 那是正确设计，不得误报。

## 工具注册有两种形态，只认一种会漏掉整个 server

实测发现 `PowerMCP/` 里 MCP 工具的注册**不只有装饰器**：

| 形态 | 写法 | 使用者 |
|---|---|---|
| (a) 装饰器 | `@mcp.tool()` / `@mcp.tool` | pandapower / pypsa / surge / andes / egret / hope / genx |
| (b) 函数式 | `mcp.tool()(fn)`，包在 `register_*_tools(mcp)` 里 | **OpenDSS（55 个工具全靠这种）** |

只认 (a) 时 OpenDSS 的 55 个工具**全部漏检**（`tools=0`），于是 `checked == 0`，
在旧口径下报 `satisfied`，理由是「0 个求解型工具均读取了引擎状态字段」——
这是一条**假绿灯**：网关根本没看到 OpenDSS 的任何工具。其中 `solve_snapshot`
名字含 `solve`，本应被本契约检查。

修正后实测：OpenDSS 识别出 55 个工具、`solve_checked=1`，其余 7 个 server 的
工具数**逐个不变**（无新误报），risky 总数仍为 6。

## `checked == 0` 不得报 satisfied

`checked == 0` 有两种成因，旧口径无法区分却一律报 satisfied：

1. 该 server 确无求解型工具（判据不适用）—— 报 satisfied 尚可接受
2. **工具定义形态未被识别**（判据失效）—— 报 satisfied 是假绿灯

与 UI 规范 P5「禁止静默 fail-open」一致的处理：**`checked == 0` → `unknown / structural`**，
并在 detail 里带上已识别的工具总数，让"看不到"与"确实没有"可诊断。

修正后实测：仅 `genx` 落在此分支（识别 7 个工具、无一匹配求解型命名）。

## 为什么是 T0 而不是 T2

本判据**纯静态可判定**，无需逐调用求值。方案把它标为 T2 是过度设计 ——
本计划有意修正为 T0。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding
# 目录映射取自单一真源（Task 2）—— 本模块**不再自带副本**
from .server_dirs import SERVER_DIRS

#: 求解型工具的命名特征
SOLVE_NAME = re.compile(
    r"solve|run_|opf|optim|contingency|power_flow|sced|scuc|simulation|eigenvalue",
    re.IGNORECASE,
)

#: 表达"结果状态"的字段名
STATUS_KEYS = frozenset({"status", "converged", "success", "succeeded", "ok"})

#: 视为"报告成功"的字面量
_SUCCESS_LITERALS = ("success", "completed", True)


def analyse_tool_fn(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, tuple[str, ...]]:
    """返回 (是否报告成功, 引擎状态读取的表达式文本)。

    「报告成功」= 返回的 dict 里有状态类字段被赋成成功字面量。
    「引擎状态读取」= 同一 dict 里状态类字段的值是属性访问或条件表达式
    （即值不是编译期常量 —— 它来自运行时，也就是引擎）。
    """
    reports_success = False
    reads: list[str] = []

    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value.lower() not in STATUS_KEYS:
                continue

            if isinstance(value, ast.Constant):
                if value.value in _SUCCESS_LITERALS:
                    reports_success = True
            elif isinstance(value, ast.Attribute):
                reads.append(ast.unparse(value))
            elif isinstance(value, ast.IfExp):
                reads.append(ast.unparse(value)[:80])

    return reports_success, tuple(dict.fromkeys(reads))


def _tool_functions(tree: ast.Module):
    """产出被注册为 MCP 工具的函数定义 —— 识别两种形态。

    (a) 装饰器：``@mcp.tool()`` / ``@mcp.tool``
    (b) 函数式：``mcp.tool()(fn)`` —— OpenDSS 的 55 个工具全靠这种

    只认 (a) 会让 OpenDSS 整站漏检，见模块 docstring。
    """
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)

    seen: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(f, ast.Attribute) and f.attr == "tool":
                if id(node) not in seen:
                    seen.add(id(node))
                    yield node
                break

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        inner = call.func
        if not isinstance(inner, ast.Call):
            continue
        inner_f = inner.func
        if not (isinstance(inner_f, ast.Attribute) and inner_f.attr == "tool"):
            continue
        for arg in call.args:
            if isinstance(arg, ast.Name) and arg.id in funcs:
                target = funcs[arg.id]
                if id(target) not in seen:
                    seen.add(id(target))
                    yield target


class StatusMappingEvaluator:
    contract = 4
    name = "状态映射契约"
    timeframe = "T0"

    def __init__(self, source_dirs: dict[str, str] | None = None) -> None:
        self._dirs = dict(source_dirs) if source_dirs is not None else dict(SERVER_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for server, dirname in sorted(self._dirs.items()):
            server_dir = cfg.powermcp_root / dirname
            if not server_dir.is_dir():
                findings.append(ContractFinding(
                    contract=4, state="unknown", reason="structural", subject=server,
                    detail=f"未找到 {server} 的源码目录 {server_dir}，无法扫描状态映射。",
                    evidence={"server": server, "dir": str(server_dir)},
                ))
                continue

            risky: list[str] = []
            checked = 0
            recognised = 0
            unparseable: list[str] = []
            for py in sorted(server_dir.rglob("*.py")):
                try:
                    tree = ast.parse(py.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    unparseable.append(str(py.relative_to(server_dir)))
                    continue
                for fn in _tool_functions(tree):
                    recognised += 1
                    if not SOLVE_NAME.search(fn.name):
                        continue
                    checked += 1
                    hard_success, reads = analyse_tool_fn(fn)
                    if hard_success and not reads:
                        risky.append(fn.name)

            base_evidence = {
                "server": server,
                "tools_recognised": recognised,
                "solve_tools_checked": checked,
                "unparseable": unparseable,
                "method": "static-ast",
            }

            if risky:
                findings.append(ContractFinding(
                    contract=4, state="degraded", reason=None, subject=server,
                    detail=(
                        f"{len(risky)} 个求解型工具报告成功但**从不读取引擎状态**："
                        f"{'、'.join(risky)}。求解失败可能被报成成功。"
                    ),
                    evidence={**base_evidence, "risky_tools": risky},
                ))
            elif checked == 0:
                findings.append(ContractFinding(
                    contract=4, state="unknown", reason="structural", subject=server,
                    detail=(
                        f"已识别 {recognised} 个工具，但无一匹配求解型命名 —— 本判据对该 server "
                        f"无适用对象。**不报 satisfied**：无法区分「确无求解型工具」与"
                        f"「工具定义形态未被识别」。"
                    ),
                    evidence=base_evidence,
                ))
            else:
                findings.append(ContractFinding(
                    contract=4, state="satisfied", reason=None, subject=server,
                    detail=f"求解型工具均读取了引擎状态字段（共 {checked} 个）。",
                    evidence=base_evidence,
                ))

        return findings
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_status_mapping.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r3
```
Expected: PASS（8 passed）

- [ ] **Step 5: 在真实仓库上跑一次，核对与手工实测一致**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe - <<'PY'
import asyncio
from pathlib import Path
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.contracts.status_mapping import StatusMappingEvaluator
cfg = GatewayConfig.discover()
for f in StatusMappingEvaluator().evaluate(None, cfg):
    print(f"{f.subject:<12} {f.state:<10} {f.detail[:88]}")
PY
```
Expected: `pypsa` / `andes` / `egret` 报 `degraded`；`pandapower` / `surge` / `hope` / `opendss` 报 `satisfied`；**`genx` 报 `unknown`（structural，因 `checked == 0`）**。

- [ ] **Step 6: 注册并提交**

在 `contracts/__init__.py` 末尾追加：

```python
from .status_mapping import StatusMappingEvaluator

REGISTRY.register(StatusMappingEvaluator())
__all__ += ["StatusMappingEvaluator"]
```

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" -p no:cacheprovider --basetemp=./.pytest_tmp/r3
```

Expected: 全部 PASS（既有 103 + 本任务 8 = 111）

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 4 状态映射可信度（判据经实测重新界定）"
```

---

### Task 4: 契约 3 —— 参数校验（纯函数）

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/params.py`
- Test: `gateway/tests/test_contract_params.py`

**Interfaces:**
- Consumes: 无（纯函数，不依赖 SDK）
- Produces:
  - `ArgViolation`：`kind: str` · `arg: str` · `detail: str` —— `kind ∈ {"unknown_arg", "missing_required", "wrong_type"}`
  - `validate_args(schema: dict, args: dict) -> tuple[ArgViolation, ...]`
  - **本模块不定义 Evaluator**（见文件末尾说明）

> ★ 本任务只做**纯函数**校验，不做代理（代理在 Task 5）。
> 为了可测，校验与调用严格分离。
>
> ★ **契约 3 不走 `REGISTRY`**：它是事件驱动的（finding 在代理层产生并以
> `contract_violation` 事件落审计），不是周期性求值。因此本任务**不改 `registry.py`**。
>
> ★ 类型校验**只做 JSON Schema 的基础类型**（`string`/`number`/`integer`/`boolean`/`object`/`array`），
> 不做 `$ref` / `oneOf` / 嵌套校验 —— YAGNI，且过度严格会挡住合法调用。

- [ ] **Step 1: 写失败的测试**

```python
from powermcp_gateway.contracts.params import validate_args

SCHEMA = {
    "type": "object",
    "properties": {
        "network_name": {"type": "string"},
        "solver_name": {"type": "string"},
        "linear": {"type": "boolean"},
        "max_iter": {"type": "integer"},
    },
    "required": ["network_name"],
}


def test_valid_args_produce_no_violations():
    assert validate_args(SCHEMA, {"network_name": "n", "linear": True}) == ()


def test_unknown_arg_is_flagged():
    """★ 这就是 linearized 那类缺陷 —— 传了声明里没有的参数，会被引擎静默忽略。"""
    v = validate_args(SCHEMA, {"network_name": "n", "linearized": True})
    assert len(v) == 1
    assert v[0].kind == "unknown_arg"
    assert v[0].arg == "linearized"


def test_missing_required_is_flagged():
    v = validate_args(SCHEMA, {})
    assert [x.kind for x in v] == ["missing_required"]
    assert v[0].arg == "network_name"


def test_wrong_type_is_flagged():
    v = validate_args(SCHEMA, {"network_name": 123})
    assert v[0].kind == "wrong_type"
    assert v[0].arg == "network_name"


def test_bool_is_not_accepted_as_integer():
    """Python 里 bool 是 int 的子类 —— 必须显式排除，否则 True 会被当成合法整数。"""
    v = validate_args(SCHEMA, {"network_name": "n", "max_iter": True})
    assert [x.kind for x in v] == ["wrong_type"]


def test_schema_without_properties_accepts_anything():
    assert validate_args({}, {"anything": 1}) == ()
    assert validate_args({"type": "object"}, {"anything": 1}) == ()


def test_anyof_with_null_accepts_none():
    """真实 schema 形态：solver_options 是 anyOf:[object, null]。"""
    schema = {"properties": {"opts": {"anyOf": [{"type": "object"}, {"type": "null"}]}}}
    assert validate_args(schema, {"opts": None}) == ()


def test_violations_are_sorted_and_deduped():
    v = validate_args(SCHEMA, {"network_name": "n", "zzz": 1, "aaa": 2})
    assert [x.arg for x in v] == ["aaa", "zzz"]
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_params.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r4
```
Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/params.py`**

```python
"""契约 3：参数契约 —— 代理侧参数校验。

## 判据的来历（方案 §2.3 的原判据已被实测证伪）

方案 §2.3 说「PyPSA `linearized` 案例的本质是**声明的 `inputSchema` 与实际函数签名
不一致**，可静态差分检出」。实测（80 个工具 / 5 个 server）：**差分 0 条** ——
因为 server 的声明 schema 就是由同一份函数签名生成的，结构上不可能不一致。

`linearized` 的真相是：**调用侧**把不存在的参数传给了库函数，被 `**kwargs` 静默吞掉。
契约 3 想防的事发生在**调用方与库之间**。

因此本模块的定位是 **代理侧参数校验**：网关转发 tool call 之前，
用声明的 `input_schema` 校验参数；不符合即**拒绝转发**并记一条 finding。

这改变了契约 3 的性质：从「检视已有缺陷」变成「**阻止新缺陷**」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_JSON_TO_PY: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


@dataclass(frozen=True)
class ArgViolation:
    kind: str          # unknown_arg | missing_required | wrong_type
    arg: str
    detail: str


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "integer":
        # ⚠️ Python 里 bool 是 int 的子类；True 不应被当作合法整数
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    types = _JSON_TO_PY.get(expected)
    return True if types is None else isinstance(value, types)


def _accepted_types(prop: dict) -> tuple[str, ...]:
    if "type" in prop:
        t = prop["type"]
        return (t,) if isinstance(t, str) else tuple(t)
    if "anyOf" in prop:
        return tuple(x["type"] for x in prop["anyOf"] if isinstance(x, dict) and "type" in x)
    return ()


def validate_args(schema: dict, args: dict) -> tuple[ArgViolation, ...]:
    """按 JSON Schema 校验一次调用的入参。

    schema 无 `properties` 时返回空 —— 无从判定，不制造假警报。
    """
    props: dict = schema.get("properties") or {}
    if not props:
        return ()

    out: list[ArgViolation] = []

    for name in sorted(set(args) - set(props)):
        out.append(ArgViolation(
            kind="unknown_arg", arg=name,
            detail=f"参数 `{name}` 不在工具声明的 input_schema 中 —— 引擎可能静默忽略它",
        ))

    for name in schema.get("required") or []:
        if name not in args:
            out.append(ArgViolation(
                kind="missing_required", arg=name,
                detail=f"缺少必填参数 `{name}`",
            ))

    for name, value in sorted(args.items()):
        prop = props.get(name)
        if not isinstance(prop, dict):
            continue
        accepted = _accepted_types(prop)
        if accepted and not any(_type_ok(t, value) for t in accepted):
            out.append(ArgViolation(
                kind="wrong_type", arg=name,
                detail=f"参数 `{name}` 期望 {'|'.join(accepted)}，实际 {type(value).__name__}",
            ))

    return tuple(out)


# ───────────────────────────────────────────────────────────────────────────
# 契约 3 没有"周期性求值器"。
#
# 与契约 1/2/4/5/6/7 不同，契约 3 是**事件驱动**的：它的 finding 产生在
# `proxy.call_tool()` 转发校验那一刻，以 `contract_violation` 事件的形式
# 进入会话总线（通道 A）与 NDJSON 审计。
#
# 因此本模块**不定义 Evaluator、不注册进 REGISTRY** —— 那是刻意的：
# 一个 `evaluate() -> []` 的求值器只会是死代码，还会误导人以为契约 3 是周期求值的。
# 前端契约面板消费的是事件流里的 `contract_violation`，不是 T0 报告。
# ───────────────────────────────────────────────────────────────────────────
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_params.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r4
```
Expected: PASS（8 passed）

- [ ] **Step 5: 跑全量单元测试，确认无回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" -p no:cacheprovider --basetemp=./.pytest_tmp/r4
```
Expected: 全部 PASS（既有 111 + 本任务 8 = 119）

- [ ] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 3 参数校验纯函数（判据改为代理侧）"
```

---

### Task 5: 代理调用（契约 3 的落地点）

**Files:**
- Create: `gateway/src/powermcp_gateway/proxy.py`
- Test: `gateway/tests/test_proxy.py`

**Interfaces:**
- Consumes: `ToolInventory` / `ToolRecord`（既有）· `validate_args` / `ArgViolation`（Task 4）· `EventBus` / `Channel`（Task 0）· `AuditLog`（Task 1）
- Produces:
  - `CallOutcome`：`ok: bool` · `server: str` · `tool: str` · `result: dict | None` · `violations: tuple[ArgViolation, ...]` · `error: str | None`
  - `async def call_tool(cfg, server, tool, args, *, schema, bus=None, audit=None, session_id=None) -> CallOutcome`

**硬规则**：校验不通过 → **不转发、不调用引擎**、返回 `ok=False` 与违规明细。
（fail-closed：宁可拒绝，也不让一个会被静默忽略的调用跑过去。）

- [ ] **Step 1: 写失败的测试**

```python
import asyncio

from powermcp_gateway.proxy import call_tool

SCHEMA = {
    "type": "object",
    "properties": {"network_name": {"type": "string"}},
    "required": ["network_name"],
}


def test_invalid_args_are_rejected_without_touching_the_engine(monkeypatch):
    """★ 核心：参数非法时**根本不应发起调用**。"""
    import powermcp_gateway.proxy as proxy

    called = []

    async def fake_dispatch(cfg, server, tool, args):
        called.append((server, tool, args))
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n", "linearized": True}, schema=SCHEMA,
    ))

    assert outcome.ok is False
    assert called == [], "非法参数被转发给了引擎"
    assert [v.kind for v in outcome.violations] == ["unknown_arg"]
    assert "linearized" in outcome.error


def test_valid_args_are_forwarded(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "value": 42}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is True
    assert outcome.result["value"] == 42
    assert outcome.violations == ()


def test_engine_error_is_surfaced_not_swallowed(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def boom(cfg, server, tool, args):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(proxy, "_dispatch", boom)

    outcome = asyncio.run(call_tool(
        cfg=None, server="surge", tool="run_power_flow",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "engine exploded" in outcome.error


def test_violation_is_published_to_evidence_channel(monkeypatch):
    """契约 3 的违规必须进审计（通道 A），不得只留在返回值里。"""
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"nope": 1}, schema=SCHEMA,
        bus=bus, session_id="s1",
    ))

    kinds = [(e.channel, e.kind) for e in bus.events()]
    assert (Channel.EVIDENCE, "contract_violation") in kinds


def test_successful_call_publishes_tool_call_event(monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    kinds = [e.kind for e in bus.events()]
    assert "tool_call" in kinds


def test_closed_bus_does_not_lose_the_outcome(monkeypatch):
    """★ 回归：总线已关闭时，结果 / 违规明细**仍必须**交回调用者。

    `EventBus.publish` 在 closed 时 raise RuntimeError。若 `_emit` 不处理，
    `call_tool` 会抛异常 —— 契约 3「返回 ok=False 与违规明细」的承诺被击穿，
    成功路径上更会**丢失一个已经执行完的调用结果**。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()
    bus.close()

    ok_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert ok_outcome.ok is True
    assert ok_outcome.result == {"status": "success"}

    bad_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n", "nope": 1},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert bad_outcome.ok is False
    assert [v.kind for v in bad_outcome.violations] == ["unknown_arg"]


def test_tool_is_error_is_not_reported_as_success(monkeypatch):
    """★ MCP 工具失败的标准形态：**不抛异常**，以 `is_error=True` 返回。

    只取 `content` 会把它报成 `ok=True` —— 正是契约 3 要防的
    「看起来成功、实际没生效」形态的镜像。
    """
    import powermcp_gateway.proxy as proxy

    async def failing_dispatch(cfg, server, tool, args):
        return {"is_error": True, "content": [{"type": "text", "text": "solver diverged"}]}

    monkeypatch.setattr(proxy, "_dispatch", failing_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="run_power_flow", args={"network_name": "n"},
        schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "is_error" in outcome.error
    assert outcome.result["content"][0]["text"] == "solver diverged"
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_proxy.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r5
```
Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/proxy.py`**

```python
"""MCP 代理调用 —— 契约 3 的落地点。

★ 这里是唯一能"阻止"参数契约缺陷的位置：在把调用转发给引擎**之前**校验参数。
  校验不通过 → 不转发。fail-closed。
  理由：一个会被引擎静默忽略的调用，跑过去比不跑更危险 —— 它会产出一个
  "看起来成功、实际没生效"的结果，而那正是 original 缺陷（linearized）的形态。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .audit import AuditLog
from .config import GatewayConfig
from .contracts.params import ArgViolation, validate_args
from .session import Channel, EventBus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallOutcome:
    ok: bool
    server: str
    tool: str
    result: dict | None = None
    violations: tuple[ArgViolation, ...] = ()
    error: str | None = None


def _is_timeout(exc: BaseException) -> bool:
    """判断异常（含 ExceptionGroup 嵌套）是否由超时引起。

    与 `inventory._is_timeout` 逻辑相同 —— **有意重复而非跨模块 import**：
    那是 inventory 的私有实现细节，proxy 依赖它会形成脆弱耦合。
    若出现第三处消费者，再提取共享模块。
    """
    if isinstance(exc, TimeoutError):
        return True
    for sub in getattr(exc, "exceptions", ()) or ():
        if _is_timeout(sub):
            return True
    return False


async def _dispatch(cfg: GatewayConfig, server: str, tool: str, args: dict) -> dict:
    """真正转发给 MCP server。单测里会被 monkeypatch 掉。

    ⚠️ **必须有超时**（与 `inventory.fetch_server_tools` 一致，复用同一个 `cfg.server_timeout_s`）：
      已知 opendss 的失效形态正是「裸 stdio 探针正常、经 SDK 握手挂起」——
      没有超时会让整个网关请求**永久挂住**，且调用方无从判断是慢还是死。

    ⚠️ **必须回传 `is_error`**：MCP 工具失败时**不抛异常**，而是以 `isError=True` 返回
      （MCP 的标准错误形态）。只取 `content` 会把引擎侧失败报成成功 ——
      那正是契约 3 要防的「看起来成功、实际没生效」形态的**镜像**。

    ⚠️ 超时异常**必须补上下文**：`asyncio.timeout` 抛出的 `TimeoutError` **消息为空**，
      不补的话 `CallOutcome.error` 会退化成 `"TimeoutError: "` —— 与
      `inventory._timeout_error` 的既有做法不一致（方案 §4.4 要求给出可执行修复路径）。
    """
    params = StdioServerParameters(
        command=str(cfg.python),
        args=["-m", "powermcp.cli", "run", server],
        cwd=str(cfg.powermcp_root),
    )
    try:
        async with asyncio.timeout(cfg.server_timeout_s):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments=args)
                    return {
                        "is_error": bool(result.is_error),
                        "content": [c.model_dump() for c in result.content],
                    }
    except Exception as exc:
        if _is_timeout(exc):
            raise TimeoutError(
                f"{server} 在 {cfg.server_timeout_s:g}s 内未完成工具调用 `{tool}` —— "
                f"进程可能已启动但不响应，需单独排查该 server 的 stdio 管道"
            ) from exc
        raise


def _emit(bus: EventBus | None, audit: AuditLog | None, session_id: str | None,
          kind: str, payload: dict) -> None:
    """把事件发到会话总线并落审计 —— **尽力而为，失败不得吞掉调用结果**。

    ⚠️ `EventBus.publish` 在总线已关闭时会 raise RuntimeError；`audit.append` 也可能因
      磁盘/权限失败。这两者**都不允许**让 `call_tool` 抛异常：
        - 成功路径上调用**已经执行**，结果必须交回调用者；
        - 违规路径上必须交出 fail-closed 的违规明细。
      否则契约 3「校验不通过 → 返回 ok=False 与违规明细」的承诺会被一次发布失败击穿。
      失败本身记 warning（**不静默**，可诊断）。
    """
    if bus is None or session_id is None:
        return
    try:
        event = bus.publish(Channel.EVIDENCE, kind, payload)
        if audit is not None:
            audit.append(session_id, event)
    except Exception:
        logger.warning(
            "事件发布/审计失败（kind=%s, session=%s）—— 调用结果仍会返回",
            kind, session_id, exc_info=True,
        )


async def call_tool(
    cfg: GatewayConfig,
    server: str,
    tool: str,
    args: dict[str, Any],
    *,
    schema: dict,
    bus: EventBus | None = None,
    audit: AuditLog | None = None,
    session_id: str | None = None,
) -> CallOutcome:
    violations = validate_args(schema, args)

    if violations:
        _emit(bus, audit, session_id, "contract_violation", {
            "contract": 3, "server": server, "tool": tool,
            "violations": [v.__dict__ for v in violations],
        })
        return CallOutcome(
            ok=False, server=server, tool=tool, violations=violations,
            error="; ".join(v.detail for v in violations),
        )

    try:
        result = await _dispatch(cfg, server, tool, args)
    except Exception as exc:  # 引擎失败要如实暴露，不吞
        _emit(bus, audit, session_id, "tool_error", {
            "server": server, "tool": tool, "error": f"{type(exc).__name__}: {exc}"[:300],
        })
        return CallOutcome(ok=False, server=server, tool=tool,
                           error=f"{type(exc).__name__}: {exc}"[:300])

    if result.get("is_error"):
        # MCP 工具失败的标准形态：**不抛异常**，以 is_error=True 返回。
        # 不检查它就会把引擎侧失败报成 ok=True —— 正是契约 3 要防的形态。
        _emit(bus, audit, session_id, "tool_error", {
            "server": server, "tool": tool,
            "error": "工具以 is_error=True 返回（MCP 标准错误形态，非异常）",
        })
        return CallOutcome(
            ok=False, server=server, tool=tool, result=result,
            error="工具以 is_error=True 返回（MCP 标准错误形态，非异常）",
        )

    _emit(bus, audit, session_id, "tool_call", {
        "server": server, "tool": tool, "args": args,
    })
    return CallOutcome(ok=True, server=server, tool=tool, result=result)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_proxy.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r5
```
Expected: PASS（7 passed）

- [ ] **Step 5: 跑全量单元测试，确认无回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" -p no:cacheprovider --basetemp=./.pytest_tmp/r5
```
Expected: 全部 PASS（既有 119 + 本任务 7 = 126）

- [ ] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): MCP 代理调用 + 契约 3 fail-closed 校验"
```

---

### Task 6: SSE 序列化与端点

> ⚠️ **来自 Task 0 审查的设计后果（必须知悉）**：`EventBus.publish()` 对 EVIDENCE 通道是
> **全有或全无** —— 只要**任一**订阅者的队列满，就整体拒绝发布。因此
> **一个卡住/慢消费的 SSE 客户端会阻塞整个会话的审计发布**（跨通道队头阻塞）。
>
> 这是计划有意的取舍（"宁可拒绝发布也绝不丢证据"），本任务**不改变它**。
> 但实现时必须让这种卡住**可诊断而不是神秘**：
> - `session_events` 生成器必须在客户端断开时**及时退出**（`request.is_disconnected()` 轮询已写在这段代码里），
>   否则一个已挂掉的浏览器标签页会永久占住订阅者名额；
> - 订阅者的队列上限（1024）被打满时，应有日志/事件可循，而不是只看到后续调用莫名失败。
>
> 若实现中发现这与 `StreamingResponse` 的背压语义冲突（它自己不施加背压），
> **停下来报告，不要擅自改 `publish()` 的全有或全无语义**。

**Files:**
- Create: `gateway/src/powermcp_gateway/events.py`
- Modify: `gateway/src/powermcp_gateway/api.py`
- Test: `gateway/tests/test_events.py`, `gateway/tests/test_api_t2.py`

**Interfaces:**
- Consumes: `Event` / `Channel` / `SessionStore`（Task 0）
- Produces:
  - `format_sse(event: Event) -> str` —— 返回完整的 SSE 帧（含 `event:` / `id:` / `data:`）
  - `sse_stream(bus) -> AsyncIterator[str]`
  - API：`POST /sessions` → `{id, servers}` · `GET /sessions/{sid}/events`（SSE）· `POST /sessions/{sid}/tools/call`

> ★ **双通道用两个 SSE `event:` 名区分**（`evidence` / `telemetry`），
> 前端按 event 名分别处理，无需解析 payload 判断优先级。

- [ ] **Step 1: 写失败的测试**

```python
import json

from powermcp_gateway.events import format_sse
from powermcp_gateway.session import Channel, Event


def test_format_sse_includes_id_and_event_name():
    ev = Event(seq=7, channel=Channel.EVIDENCE, kind="contract",
               payload={"contract": 3}, at="2026-09-24T00:00:00Z")
    frame = format_sse(ev)

    assert frame.endswith("\n\n")
    lines = dict(
        (l.split(": ", 1) for l in frame.strip().splitlines() if ": " in l)
    )
    assert lines["id"] == "7"                       # 序列号即 id —— 断线重连可续
    assert lines["event"] == "evidence"             # ★ 通道即事件名
    assert json.loads(lines["data"])["payload"]["contract"] == 3


def test_format_sse_telemetry_uses_its_own_event_name():
    ev = Event(seq=8, channel=Channel.TELEMETRY, kind="progress", payload={},
               at="2026-09-24T00:00:00Z")
    assert "event: telemetry" in format_sse(ev)
```

**另外，在 `gateway/tests/test_session.py` 末尾追加 2 个测试**（覆盖本次给 `EventBus` 新增的同步注册 API）：

```python
def test_subscribe_queue_registers_synchronously():
    """★ 注册必须**同步**生效 —— 否则「先订阅再补历史」之间会有丢失窗口。"""
    bus = EventBus()
    bus.publish(Channel.EVIDENCE, "before", {})
    q = bus.subscribe_queue()
    assert bus.subscriber_count() == 1          # 无需 await 即已注册
    bus.publish(Channel.EVIDENCE, "after", {})
    assert q.get_nowait().kind == "after"       # 注册之后的事件进队列
    bus.unsubscribe(q)
    assert bus.subscriber_count() == 0


def test_unsubscribe_is_idempotent():
    bus = EventBus()
    q = bus.subscribe_queue()
    bus.unsubscribe(q)
    bus.unsubscribe(q)                          # 重复注销不得抛
    assert bus.subscriber_count() == 0
```

> `test_session.py` 既有 13 个测试已在用 `EventBus` / `Channel`，import 应已齐备；
> 若确实缺，按该文件既有的 import 风格补上。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_events.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [ ] **Step 3: 写 `gateway/src/powermcp_gateway/events.py`**

```python
"""SSE 序列化 —— 双通道物理分离。

通道即 SSE 的 `event:` 名（`evidence` / `telemetry`），前端按名分派，
不需要解析 payload 才知道该不该丢。

`id:` 用事件的单调序列号 —— 断线重连时前端可用 `Last-Event-ID` 续传，
且**乱序到达时可按 id 排序**（方案 §11.7-③）。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from .session import Channel, Event, EventBus


def format_sse(event: Event) -> str:
    data = json.dumps({
        "seq": event.seq,
        "kind": event.kind,
        "payload": event.payload,
        "at": event.at,
    }, ensure_ascii=False)
    return (
        f"id: {event.seq}\n"
        f"event: {event.channel.value}\n"
        f"data: {data}\n\n"
    )


async def sse_stream(bus: EventBus) -> AsyncIterator[str]:
    """把总线上的事件转成 SSE 帧（**不含历史补发**）。

    ⚠️ 与 `EventBus.subscribe_queue()` 的区别：本生成器是 async generator，
      订阅者要到**第一次迭代**才注册 —— 所以**不能**用它实现"先订阅、再补发历史"，
      两步之间会有丢失窗口。需要历史补发的场景（HTTP SSE 端点）请用
      `subscribe_queue()`。本函数适合"只要实时流、不要历史"的消费者。
    """
    async for event in bus.subscribe():
        yield format_sse(event)
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_events.py -v
```
Expected: PASS（2 passed）

- [ ] **Step 5: 给 `EventBus` 加同步注册 API（改 Task 0 已交付的 `session.py`）**

> ★ **为什么需要**：`subscribe()` 是 async generator —— 订阅者要到第一次 `__anext__()`
> 才真正注册。SSE 端点必须「先订阅、再补发历史」，否则两步之间 `yield` 让出的窗口里
> 发布的事件会**既不在历史快照里、也不在订阅队列里**，静默丢失
> （EVIDENCE 通道的设计前提是"不可丢"）。同步注册方法让「注册」与「取快照」之间**无 await 窗口**。
>
> ⚠️ 这是本任务对 Task 0 已交付代码的**唯一**改动，**只加方法、不改既有行为**。

在 `gateway/src/powermcp_gateway/session.py` 的 `EventBus` 类中，
**在 `subscriber_count()` 之前**（即 `subscribe()` 方法之后）插入：

```python
    def subscribe_queue(self) -> asyncio.Queue[Event | None]:
        """**同步**注册一个订阅者并返回其队列 —— 立即生效，无 await 窗口。

        与 `subscribe()` 的区别：后者是 async generator，订阅者要到第一次
        `__anext__()` 才真正注册。调用方若需要「注册订阅者」与「取历史快照」
        原子（例如 SSE 端点要先订阅、再补发历史），必须用本方法 ——
        否则两步之间 `yield` 让出的窗口里发布的事件会既不在快照里、
        也不在订阅队列里，**静默丢失**。

        调用方负责在结束时调用 `unsubscribe(q)`。
        """
        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event | None]) -> None:
        """注销 `subscribe_queue()` 返回的队列。**幂等**。"""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass
```

- [ ] **Step 6: 跑 `test_session.py`，确认通过（含新增 2 个）**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_session.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r6b
```
Expected: PASS（既有 13 + 新增 2 = 15 passed）

- [ ] **Step 7: 写失败的 API 测试 `gateway/tests/test_api_t2.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app


@pytest.fixture
def app():
    return create_app()


async def test_create_session(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["pandapower", "pypsa"]})
    assert r.status_code == 200
    body = r.json()
    assert body["id"]
    assert body["servers"] == ["pandapower", "pypsa"]


async def test_create_session_rejects_unknown_server(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["powerworld"]})
    assert r.status_code == 400        # 商业引擎已被方案 v3 移除


async def test_session_events_returns_streaming_response(app):
    """★ `ASGITransport` **无法**测无限流式响应 —— 实测会挂死。

    它会等 ASGI 应用整体结束，而 SSE 永不结束，所以
    `async with c.stream(...)` **连响应头都拿不到**。故直接调用端点函数检查返回对象。

    验证「路由已注册 + 返回 `StreamingResponse` + `media_type` 为 `text/event-stream`」。
    真实 HTTP 下的响应头与断开清理留给 Task 7 的端到端验收；流的序列化由
    `test_events.py` 的 `format_sse` 单测覆盖。
    """
    from fastapi.responses import StreamingResponse
    from starlette.requests import Request

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/sessions/{sid}/events")
    request = Request({"type": "http", "method": "GET", "path": "/x",
                       "headers": [], "query_string": b""})
    resp = await route.endpoint(sid, request)

    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"


async def test_unknown_session_events_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/sessions/nope/events")
    assert r.status_code == 404
```

- [ ] **Step 8: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api_t2.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r6c
```
Expected: FAIL —— 404 / 405（端点尚未存在）

- [ ] **Step 9: 重写 `gateway/src/powermcp_gateway/api.py`**

**为什么整体重写而不是插入**：新端点必须与既有端点共享**同一个** `SessionStore` / `AuditLog`
实例（测试要能拿到它们），所以把状态与路由注册提到**模块级**，不再塞在 `create_app` 的闭包里。
顺带把 `_cfg()` 也提到模块级，`create_app` 因此变薄。

把 `gateway/src/powermcp_gateway/api.py` 的**全部内容**替换为：

```python
"""网关 HTTP API。

状态（会话 / 审计 / 配置 / T0 缓存）全部在**模块级** —— 端点与测试共享同一实例。
路由注册拆成 `register_session_routes()`，`create_app()` 只负责组装。
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .audit import AuditLog
from .config import GatewayConfig
from .contracts.engine import T0Cache, evaluate_t0
from .events import format_sse
from .inventory import build_inventory
from .proxy import CallOutcome, call_tool
from .session import SessionStore

# P1 只挂开源引擎（方案 v3 已移除全部商业引擎）
OPEN_SOURCE_SERVERS: tuple[str, ...] = (
    "pandapower", "pypsa", "surge", "andes",
    "egret", "opendss", "hope", "genx", "powerio",
)

#: SSE 空闲时的断开轮询间隔（秒）。**空闲连接也必须能检测到断开** ——
#: 否则一个已挂掉的浏览器标签页会**永久占住订阅者名额**，最终让整个会话的
#: EVIDENCE 发布失败（见 Task 0 审查的队头阻塞后果）。
_DISCONNECT_POLL_S = 1.0

_cache = T0Cache()
_STORE = SessionStore()
_AUDIT = AuditLog(Path.home() / ".powermcp" / "audit")
_CONFIG: GatewayConfig | None = None


def _cfg() -> GatewayConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = GatewayConfig.discover()
    return _CONFIG


async def call_with_contracts(
    sid: str,
    server: str,
    tool: str,
    args: dict,
    *,
    get_schema: Callable[[str, str], dict],
) -> CallOutcome:
    """代理调用 + T2 契约求值的单一入口。

    契约 3 的判定在 `call_tool` 内完成（转发前校验，fail-closed）；
    本函数负责接上会话总线与审计，并把结果的 schema 取自 `get_schema`。
    """
    return await call_tool(
        _cfg(), server, tool, args,
        schema=get_schema(server, tool),
        bus=_STORE.bus(sid), audit=_AUDIT, session_id=sid,
    )


def register_session_routes(app: FastAPI) -> None:
    """注册会话 / SSE / 代理端点。"""

    @app.post("/sessions")
    async def create_session(payload: dict):
        requested = tuple(payload.get("servers") or OPEN_SOURCE_SERVERS)
        unknown = [s for s in requested if s not in OPEN_SOURCE_SERVERS]
        if unknown:
            return JSONResponse(
                status_code=400,
                content={"detail": f"未知或已移除的 server：{unknown}"},
            )
        session = _STORE.create(requested)
        return {"id": session.id, "servers": list(session.servers),
                "created_at": session.created_at}

    @app.get("/sessions/{sid}/events")
    async def session_events(sid: str, request: Request):
        try:
            bus = _STORE.bus(sid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "会话不存在"})

        async def gen():
            # ★ 先**同步**注册订阅者，再取历史快照 —— 两步之间无 await 窗口。
            #   若先取快照再订阅，中间每次 yield 让出的窗口里发布的事件会
            #   既不在快照、也不在队列里 —— **静默丢失**（EVIDENCE 不可丢）。
            q = bus.subscribe_queue()
            try:
                last_seq = 0
                for event in bus.events():      # 补发历史：晚订阅 / 断线重连不丢
                    yield format_sse(event)
                    last_seq = event.seq

                while True:
                    try:
                        event = await asyncio.wait_for(
                            q.get(), timeout=_DISCONNECT_POLL_S
                        )
                    except asyncio.TimeoutError:
                        # ★ 空闲时也必须轮询断开 —— 否则一个已挂掉的标签页会
                        #   永久占住订阅者名额，最终让整个会话的 EVIDENCE 发布失败。
                        if await request.is_disconnected():
                            return
                        continue

                    if event is None:           # 总线关闭的终止哨兵
                        return
                    if event.seq <= last_seq:   # 已在历史里补发过
                        continue
                    last_seq = event.seq

                    if await request.is_disconnected():
                        return
                    yield format_sse(event)
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/sessions/{sid}/tools/call")
    async def tools_call(sid: str, payload: dict):
        try:
            _STORE.get(sid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "会话不存在"})

        server = payload["server"]
        tool = payload["tool"]
        args = payload.get("args") or {}

        inv = await build_inventory(_cfg(), [server])
        recs = [t for t in inv.tools if t.server == server and t.name == tool]
        if not recs:
            return JSONResponse(
                status_code=404,
                content={"detail": f"{server}.{tool} 不存在或该 server 未拉起"},
            )

        outcome = await call_with_contracts(
            sid, server, tool, args,
            get_schema=lambda _s, _t: recs[0].input_schema,
        )
        return dataclasses.asdict(outcome)


def create_app(cfg: GatewayConfig | None = None) -> FastAPI:
    app = FastAPI(title="PowerMCP Gateway", version="0.1.0")
    if cfg is not None:
        global _CONFIG
        _CONFIG = cfg

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/servers")
    async def servers() -> dict[str, list[str]]:
        return {"servers": list(OPEN_SOURCE_SERVERS)}

    @app.get("/contracts/t0")
    async def contracts_t0() -> dict:
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        inv = await build_inventory(c, OPEN_SOURCE_SERVERS)
        report = await evaluate_t0(inv, c, cache=_cache)
        return {
            "cache_key": report.cache_key,
            "evaluated_at": report.evaluated_at,
            "summary": dataclasses.asdict(report.summary),
            "findings": [dataclasses.asdict(f) for f in report.findings],
        }

    register_session_routes(app)
    return app
```

- [ ] **Step 10: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api_t2.py tests/test_api.py -v -p no:cacheprovider --basetemp=./.pytest_tmp/r6d
```
Expected: PASS（6 passed —— 含既有 2 个，确认无回归）

- [ ] **Step 11: 跑全量单元测试，确认无回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" -p no:cacheprovider --basetemp=./.pytest_tmp/r6e
```
Expected: 全部 PASS（既有 126 + 本任务 8 = 134）

- [ ] **Step 12: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): SSE 双通道 + 会话/代理端点"
```

---

### Task 7: T2 节拍打通 + 端到端验收

**Files:**
- Test: `gateway/tests/test_api_t2.py`（追加）
- **不改任何实现文件** —— T2 入口在 Task 6 Step 7 已随 `api.py` 重写完成

**Interfaces:**
- Consumes: `call_with_contracts` / `_STORE` / `_AUDIT`（Task 6 Step 7 已全部提供）· `call_tool`（Task 5）
- Produces: 无新符号 —— 本任务只补**测试与端到端验收**

> ★ 这是**把 T2 契约接到代理层**的那一步。契约 3 的违规由 `call_tool` 直接产生，
> 这里负责把它包装成规范要求的 `ContractFinding` 形状并推送 —— 前端契约面板消费的正是这个形状。

- [ ] **Step 1: 写失败的测试（追加到 `test_api_t2.py`）**

```python
async def test_call_with_valid_args_streams_tool_call_event(app, monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"net": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    assert outcome.ok is True
    assert "tool_call" in [e.kind for e in api_mod._STORE.bus(sid).events()]


async def test_contract_violation_is_reported_as_finding(app, monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow",
        {"nets": "x"},                                   # ← 拼错的参数名
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}},
                                 "required": ["net"]},
    )

    assert outcome.ok is False
    viol = [e for e in api_mod._STORE.bus(sid).events() if e.kind == "contract_violation"]
    assert viol
    assert viol[0].payload["contract"] == 3


async def test_audit_file_records_the_violation(tmp_path, monkeypatch):
    """★ 契约 3 的违规必须落进 NDJSON 审计 —— 只有事件不落盘等于没法事后追。

    注入 tmp_path 的 AuditLog，避免测试往真实 ~/.powermcp/audit 里写文件。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)

    app = api_mod.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"nets": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    scratch.flush()

    kinds = [e.kind for e in scratch.replay(sid)]
    assert "contract_violation" in kinds
    assert scratch.path_for(sid).is_file()
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api_t2.py -v
```
Expected: FAIL —— `AttributeError: module 'powermcp_gateway.api' has no attribute 'call_with_contracts'`

- [ ] **Step 3: 确认无需改动实现**

`call_with_contracts` / `_STORE` / `_AUDIT` 已在 **Task 6 Step 7 的重写**中引入
（签名 `call_with_contracts(sid, server, tool, args, *, get_schema)`）。
本任务**只加测试与端到端验收**，不新增实现代码。

若 Step 2 的失败信息不是 `AttributeError: ... has no attribute 'call_with_contracts'`，
说明 Task 6 Step 7 没做完 —— 回到那里补齐，**不要在本任务里另写一份**。

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api_t2.py -v
```
Expected: PASS（6 passed）

- [ ] **Step 5: 全量回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration"
```
Expected: 全部 PASS（既有 76 + 本计划新增约 40）

- [ ] **Step 6: 真实端到端手工验收**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app --factory --port 8766 &
sleep 5
SID=$(curl -s -X POST localhost:8766/sessions -H 'content-type: application/json' \
      -d '{"servers":["pypsa"]}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "会话: $SID"
timeout 20 curl -sN "localhost:8766/sessions/$SID/events" &
sleep 1
# ★ 故意传一个不存在的参数：期望被拒，且事件流出现 contract_violation
curl -s -X POST "localhost:8766/sessions/$SID/tools/call" -H 'content-type: application/json' \
  -d '{"server":"pypsa","tool":"get_network_info","args":{"network_name":"x","linearized":true}}'
```

Expected：
1. 返回体 `ok=false`，`violations[0].kind == "unknown_arg"`，`arg == "linearized"`
2. SSE 流里出现 `event: evidence` + `"kind": "contract_violation"`、`"contract": 3`
3. `~/.powermcp/audit/audit-<sid>.ndjson` 里有对应行

- [ ] **Step 7: 提交并回填执行记录**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): T2 契约接入代理层 + 端到端验收"
```

在计划文件末尾追加「执行记录」，格式对齐 [子项目 2 计划](2026-09-24-gateway-contract-engine-t0.md) 的同名章节（状态表 / 完成标准实测 / 与规格的偏差 / 遗留）。

---

## 完成标准

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -v -m "not integration"
```

全部通过，且满足：

1. **契约 4** 在真实仓库上产出 7 条 `degraded`（`pypsa`×2 / `andes`×2 / `egret`×3 所在的 server），
   而 `pandapower` / `surge` 为 `satisfied` —— **对照组不得误报**
2. **契约 3**：传 `linearized` 这类未声明参数时**被拒绝且未转发**（`ok=false`，事件流有 `contract_violation`）
3. **SSE 双通道**：`event: evidence` 与 `event: telemetry` 分别出现；`id:` 单调递增
4. **审计**：`~/.powermcp/audit/audit-<sid>.ndjson` 只含 `evidence` 行；`replay()` 能还原
5. **无回归**：子项目 2 的 76 个测试仍全过

---

## 后续计划（不在本计划范围）

- **子项目 4**：进程监管（心跳 / 退避重启 / 熔断 / 引擎状态端点）—— 方案 §八 列为 P1 必做
- **子项目 1**：设计系统落地（tokens → CSS 变量 / Tailwind / 5 个签名组件 / Zod 边界）
- **子项目 5**：前端视图（聊天面板 + 契约面板），消费本计划的 `/sessions/{sid}/events`
- **opendss 挂载缺陷**：[立项文档](2026-09-24-opendss-sdk-mount-defect.md)
