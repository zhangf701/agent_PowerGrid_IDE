"""网关 HTTP API。

状态（会话 / 审计 / 配置 / T0 缓存）全部在**模块级** —— 端点与测试共享同一实例。
路由注册拆成 `register_session_routes()`，`create_app()` 只负责组装。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import DEFAULT_MAX_ROUNDS, AgentEvent, run_turn
from .audit import AuditLog
from .cases import (
    CaseError,
    CaseIndexError,
    CaseStore,
    allowed_root_paths,
    cases_root,
)
from .cases import build_report as build_cases_report
from .case_ir import (
    ARTIFACT_NAME,
    CaseIrError,
    artifact_to_payload,
    load_artifact,
    parse_case,
    run_diagnostics,
    save_artifact,
)
from .config import GatewayConfig
from .checks import run_checks as run_module_checks_engine
from .contracts.engine import T0Cache, evaluate_t0
from .environment import build_report as build_environment_report
from .events import format_sse
from .inventory import build_inventory
from .llm import ChatMessage, LlmConfig, LlmConfigError, OpenAICompatProvider
from .modules import build_prompt_supplement
from .modules import build_report as build_modules_report
from .proxy import CallOutcome, call_tool
from .serverpool import ServerPool
from .session import Channel, SessionStore
from .skills import build_report as build_skills_report

# P1 只挂开源引擎（方案 v3 已移除全部商业引擎）
OPEN_SOURCE_SERVERS: tuple[str, ...] = (
    "pandapower", "pypsa", "surge", "andes",
    "egret", "opendss", "hope", "genx", "powerio",
)

#: SSE 空闲时的断开轮询间隔（秒）。**空闲连接也必须能检测到断开** ——
#: 否则一个已挂掉的浏览器标签页会**永久占住订阅者名额**，其队列被填满后成为
#: **滞后订阅者**（见 `EventBus.stats()` 的 `lagged_queues` / `lagged_deliveries`）。
#: ⚠️ 自 I-2 起，满队列**不再**让整个会话的 EVIDENCE 发布失败 —— 持久记录永远先于
#:    扇出、不依赖任何订阅者；此处轮询只是为了让订阅者名额被**及时回收**。
_DISCONNECT_POLL_S = 1.0

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """应用生命周期：**关闭时必须 flush 并 close 审计**。

    ★ `AuditLog` 是**批量写入**（每 32 条 flush 一次）。没有 flush，进程退出时
      缓冲区里的 EVIDENCE 事件会**直接丢失** —— 而审计通道的设计前提是"不可丢"。
      实测（2026-09-24 端到端验收）：单条契约违规后进程被杀，
      `audit-<sid>.ndjson` 仍是 **0 字节**，违规记录彻底丢失。
    ★ 没有 close，则每个新会话泄漏一个文件句柄（`audit.py` 只 `open("a")` 从不关闭），
      Windows 上还会持续占住文件（T1-M7）。

    ⚠️ flush/close 失败**不得阻塞进程退出、不得外抛** —— 只记 warning（保持既有语义）。
    """
    yield
    try:
        _AUDIT.flush()
        _AUDIT.close()
    except Exception:
        logger.warning("退出时 flush/close 审计失败 —— 缓冲区内的证据事件可能丢失", exc_info=True)
    if _POOL is not None:
        try:
            await _POOL.aclose()
        except Exception:
            logger.warning("退出时关闭 server 连接池失败 —— 子进程可能残留", exc_info=True)

_cache = T0Cache()
_STORE = SessionStore()
_AUDIT = AuditLog(Path.home() / ".powermcp" / "audit")
_CONFIG: GatewayConfig | None = None
_PROVIDER: OpenAICompatProvider | None = None
#: 会话级持久 server 连接池（子项目 4 / T6-M5 根治）。
#: ★ **默认关闭**（None = 每次调用临时挂载的旧语义），由 `POWERMCP_SESSION_POOL=1`
#:   或 `create_app(pool=…)` 显式开启 —— 既有测试 monkeypatch `_dispatch` 的语义不变。
_POOL: "ServerPool | None" = None


def _cfg() -> GatewayConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = GatewayConfig.discover()
    return _CONFIG


def _provider() -> OpenAICompatProvider:
    """惰性创建 LLM 适配器。

    ★ **不在这里捕获 `LlmConfigError`** —— 配置缺失必须由端点显式映射为 HTTP 503
      （与 `/contracts/t0` 的配置失败语义一致），而不是退化成一个通用 500。
    """
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = OpenAICompatProvider(LlmConfig.from_env())
    return _PROVIDER


#: 对话流里允许的 SSE 事件名（与 `agent.AgentEvent.kind` 一一对应）。
#: 白名单而非直通 —— 防止将来 agent 新增 kind 时把未定义事件名泄漏给前端。
_CHAT_EVENT_KINDS = frozenset({"text", "notice", "tool_call", "tool_error", "final", "error"})


def _chat_sse(kind: str, payload: dict) -> str:
    """对话流的 SSE 帧。

    ⚠️ 与 `events.format_sse` **有意不同**：后者序列化的是**总线事件**
    （带 `seq` / `channel`，供断线重连全量重放）；本流是**本轮对话**的
    瞬时视图，不带 seq、不可重放 —— 可重放的部分（工具调用、最终回答）
    由 `_publish_evidence` 单独写进总线与审计。
    """
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _event_payload(ev: AgentEvent) -> dict:
    """`AgentEvent` → SSE payload。只带该 kind 有意义的字段，避免噪声。"""
    if ev.kind == "text" or ev.kind == "final":
        return {"text": ev.text}
    if ev.kind == "tool_call":
        return {"server": ev.server, "tool": ev.tool, "args": ev.args}
    if ev.kind == "tool_error":
        return {"server": ev.server, "tool": ev.tool, "detail": ev.detail}
    return {"detail": ev.detail}


def _case_store() -> CaseStore:
    """会话无关的算例索引（与 `register_case_routes` 内的 `_store()` 同源同义）。"""
    return CaseStore(cases_root(_cfg()))


def build_case_context() -> str:
    """算例库现状 → 并入对话 system 消息（v4 §4.3「对话分析」的数据源接线）。

    ★ 为什么必须有：张老师首轮实测——用户在界面登记并解析了算例，但模型
      **完全不知道**，只能瞎猜内置算例名（`__invalid__`）。模型需要的不是 IR
      本体（51KB），而是三件事：**有哪些算例、路径在哪、是否已解析**。

    - 只读索引 + 现状视图（available / drift / within_allowed_roots 现算），
      **不拉起任何 server**（廉价，同 /environment 的口径）；
    - 已解析与否看产物文件是否存在（`<cid>/parse.json`）；
    - 算例库为空 → 空串（不注入）；读取失败 → 空串 + warning（不阻断对话）。
    """
    try:
        store = _case_store()
        cfg = _cfg()
        cases = store.list()
    except Exception:
        logger.warning("算例库现状读取失败，本轮对话不注入算例上下文", exc_info=True)
        return ""
    if not cases:
        return ""
    root = cases_root(cfg)
    lines: list[str] = []
    for case in cases:
        try:
            v = store.view(case)
        except Exception:
            logger.warning("算例现状计算失败：%s", case.id, exc_info=True)
            continue
        parsed = (root / case.id / ARTIFACT_NAME).is_file()
        flags = []
        if not v.available:
            flags.append("文件已不在")
        if v.drift:
            flags.append("内容已变（重新解析前结果不可信）")
        if not v.within_allowed_roots:
            flags.append("server 子进程读不到")
        flag_s = ("（⚠ " + "；".join(flags) + "）") if flags else ""
        lines.append(
            f"- {case.label}（id={case.id}，{case.format}）路径：`{case.source_path}`"
            f" · 已解析：{'是' if parsed else '否'}{flag_s}"
        )
    if not lines:
        return ""
    return (
        "以下是算例库当前登记的全部算例。用户在界面上「登记 / 解析」的"
        "就是它们 —— 当用户说『已解析』『已载入』时，指的就是下列算例："
        "直接用其路径载入分析，**不要**向用户索要路径，也**不要**用猜测的"
        "内置算例名替代。\n" + "\n".join(lines)
    )


def _publish_evidence(bus, session_id: str, kind: str, payload: dict) -> None:
    """把一条事件写进总线 + 审计（**尽力而为，失败不得打断对话流**）。

    与 `proxy._emit` 同一取舍：`publish` 在总线已关闭时抛 `RuntimeError`，
    `audit.append` 失败时返回 False —— 两者都**不许**让正在进行的对话流断掉。
    """
    try:
        event = bus.publish(Channel.EVIDENCE, kind, payload)
    except Exception:
        logger.warning("对话事件发布失败（kind=%s, session=%s）", kind, session_id, exc_info=True)
        return
    if not _AUDIT.append(session_id, event):
        logger.warning(
            "对话事件未持久化（kind=%s, session=%s）—— 仅在内存历史中；"
            "详见 GET /health 的 audit.append_failures", kind, session_id,
        )


def _parse_chat_request(payload: dict) -> tuple[list[ChatMessage], str | None]:
    """解析对话请求体。

    接受两种形式：
      - `{"message": "..."}` —— 便捷形式，等价于单条 user 消息；
      - `{"messages": [{"role": ..., "content": ...}, ...]}` —— 完整历史。

    ★ **服务端不持久化对话历史**：会话（`Session`）只承载 server 组合与事件总线。
      客户端传完整历史是 LLM API 的通行做法，也让"刷新后恢复"这件事
      明确地落在**会话持久化**这个独立单元里，而不是藏在端点里做半套。
    ★ 只接受 `system` / `user` / `assistant` 三种角色 —— `tool` 与
      `assistant.tool_calls` 由服务端在**本轮内**自行管理，客户端不得注入，
      否则可以伪造工具结果污染审计。
    """
    raw = payload.get("messages")
    if raw is None:
        single = payload.get("message")
        if not isinstance(single, str) or not single.strip():
            return [], "请求体需提供 `message`（非空字符串）或 `messages`（消息数组）"
        raw = [{"role": "user", "content": single}]
    if not isinstance(raw, list) or not raw:
        return [], "`messages` 必须是非空数组"

    out: list[ChatMessage] = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            return [], f"messages[{i}] 必须是对象"
        role = m.get("role")
        if role not in ("system", "user", "assistant"):
            return [], f"messages[{i}].role 必须是 system / user / assistant"
        content = m.get("content")
        if not isinstance(content, str):
            return [], f"messages[{i}].content 必须是字符串"
        out.append(ChatMessage(role=role, content=content))

    if out[-1].role != "user":
        return [], "最后一条消息必须是 user"
    return out, None


def _parse_max_rounds(payload: dict) -> tuple[int, str | None]:
    """解析 `max_rounds`（可选）。上界 32 —— 防止客户端把单轮请求变成长时间占用。"""
    raw = payload.get("max_rounds")
    if raw is None:
        return DEFAULT_MAX_ROUNDS, None
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0, "`max_rounds` 必须是整数"
    if not 1 <= raw <= 32:
        return 0, "`max_rounds` 必须在 1–32 之间"
    return raw, None


def _parse_servers(payload: dict, session_servers: tuple[str, ...]) -> tuple[list[str], str | None]:
    """解析可选的 `servers`（本轮要挂载的 server 子集）。

    ★ 为什么要这个字段：`build_inventory` 会**真实拉起**每个 server 进程
      （秒级/个，见 T6-M5）。允许按轮收窄子集，是当前唯一不需要引入
      清单缓存的实用优化 —— 也正是"选题模块声明工具白名单"的雏形。
    """
    raw = payload.get("servers")
    if raw is None:
        return list(session_servers), None
    if not isinstance(raw, list) or not raw:
        return [], "`servers` 必须是非空数组"
    unknown = [s for s in raw if s not in session_servers]
    if unknown:
        return [], f"`servers` 含会话未启用的项：{unknown}（本会话：{list(session_servers)}）"
    return list(dict.fromkeys(raw)), None


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
        pool=_POOL,
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
                    # ★ 尽力而为的滞后检查（I-2）：若本订阅者队列已被标记滞后
                    #   （不可丢通道满 → 总线跳过投递），主动结束本响应，
                    #   让浏览器重连并按历史全量重放 —— 而不是继续半速跟随。
                    #   注意：gen() 可能挂起在 yield 上，所以这只是尽力而为；
                    #   核心不变式（持久记录先于扇出、不丢）不依赖这一步。
                    if bus.is_lagged(q):
                        logger.warning(
                            "SSE 订阅者已滞后，主动结束连接以触发重连全量重放 (sid=%s)", sid
                        )
                        return
                    try:
                        event = await asyncio.wait_for(
                            q.get(), timeout=_DISCONNECT_POLL_S
                        )
                    except asyncio.TimeoutError:
                        # ★ 空闲时也必须轮询断开 —— 否则一个已挂掉的标签页会
                        #   永久占住订阅者名额（它只会让**自己**滞后，不再影响持久
                        #   记录；见 EventBus 的背压不变式）。
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

        # ★ 请求体缺字段是**客户端错误**（400），不是 500。
        #   原先 `payload["server"]` 直接下标，缺键即 `KeyError` → HTTP 500 ——
        #   把一个可诊断的坏请求报成了服务端故障（M-2）。
        server = payload.get("server")
        tool = payload.get("tool")
        if not isinstance(server, str) or not server:
            return JSONResponse(
                status_code=400,
                content={"detail": "请求体缺少 `server`（需为非空字符串）"},
            )
        if not isinstance(tool, str) or not tool:
            return JSONResponse(
                status_code=400,
                content={"detail": "请求体缺少 `tool`（需为非空字符串）"},
            )
        args = payload.get("args") or {}

        # ★ 与 `/contracts/t0` 保持**同一错误语义**：配置/清单系统性失败 → 503（M-3）。
        #   注意 `build_inventory` 会把**单个** server 的失败收进 `inv.failures` 而不抛；
        #   这里捕获到异常意味着系统性失败（如 `_cfg()` 无法解析配置）—— 503 恰当。
        #   单 server 失败仍走既有路径：`recs` 为空 → 404。
        try:
            inv = await build_inventory(_cfg(), [server])
        except Exception as exc:  # noqa: BLE001 —— 统一映射为 503，不外泄为 500
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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

    @app.post("/sessions/{sid}/chat")
    async def chat(sid: str, payload: dict):
        """一轮对话：自然语言 → 多轮工具调用 → 回答（SSE 流）。

        ★ Agent 循环在**网关侧**（2026-09-25 张老师裁决）：工具执行经
          `call_with_contracts` → `proxy.call_tool`，因此契约 3 的 fail-closed 校验、
          契约 finding 的 EVIDENCE 发布、NDJSON 审计**全部天然在环内**。

        流的形态（`event:` 名即事件 kind）：
          - `text`       文本增量
          - `notice`     非致命降级（如部分 server 未拉起 → 本轮工具面不完整）
          - `tool_call`  一次工具调用已成功执行
          - `tool_error` 工具失败 / 参数非法 / 工具不存在
          - `final`      本轮最终回答
          - `error`      本轮整体失败（LLM 错误 / 轮次超限）

        ★ **可重放的部分**（用户消息、工具调用、最终回答、本轮失败）**同时**
          写进会话总线与 NDJSON 审计；`text` 增量**只**在本流里（瞬时视图），
          断线重连靠总线历史拿到完整回答，而不是逐 token 重放。

        ⚠️ **HTTP 状态码只覆盖"请求能不能开始"**：配置缺失 503、会话不存在 404、
          请求体非法 400。**开始之后的失败一律走 `error` 事件** ——
          `StreamingResponse` 一旦发出响应头，状态码就不可能再改。
        """
        try:
            session = _STORE.get(sid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "会话不存在"})

        messages, err = _parse_chat_request(payload)
        if err:
            return JSONResponse(status_code=400, content={"detail": err})

        max_rounds, err = _parse_max_rounds(payload)
        if err:
            return JSONResponse(status_code=400, content={"detail": err})

        servers, err = _parse_servers(payload, session.servers)
        if err:
            return JSONResponse(status_code=400, content={"detail": err})

        try:
            provider = _provider()
        except LlmConfigError as exc:
            # 配置缺失是**系统性失败** —— 与 `/contracts/t0` 一致映射为 503，不是 500。
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        async def gen():
            bus = _STORE.bus(sid)
            _publish_evidence(bus, sid, "user_message", {
                "content": messages[-1].content, "servers": servers,
            })

            # ★ 清单在**流内**构建：`build_inventory` 会真实拉起 server 进程
            #   （秒级/个，见 T6-M5）。放在流外会把 TTFT 拖到秒级且无法提前结束；
            #   失败则以 `error` 事件如实报出，而不是静默退化。
            try:
                inv = await build_inventory(_cfg(), servers)
            except Exception as exc:
                yield _chat_sse("error", {"detail": f"工具清单构建失败：{exc}"})
                _publish_evidence(bus, sid, "turn_error",
                                  {"detail": f"工具清单构建失败：{exc}"})
                return

            # ★ 部分 server 拉不起来**必须说出来**（方案 §4.1「装得上 ≠ 跑得动」）：
            #   否则用户会以为"这个工具不存在"，而事实是"这个 server 没起来"。
            if inv.failures:
                _publish_evidence(bus, sid, "inventory_degraded", {
                    "servers": servers,
                    "failures": [dataclasses.asdict(f) for f in inv.failures],
                })
                detail = "；".join(f"{f.server}: {f.error}" for f in inv.failures)
                yield _chat_sse("notice", {
                    "detail": (
                        f"{len(inv.failures)} 个 server 未拉起，本轮工具面不完整：{detail}"
                    )[:400],
                })

            schema_by = {(t.server, t.name): t.input_schema for t in inv.tools}

            async def execute(server: str, tool: str, args: dict) -> CallOutcome:
                return await call_with_contracts(
                    sid, server, tool, args,
                    get_schema=lambda s, t: schema_by.get((s, t), {}),
                )

            # ★ G-4（prompts 接线，2026-09-25）：把**启用模块**的提示词并入 system 消息 ——
            #   此前「模块声明了 prompts 但 LLM 不读」，装配成功 ≠ 能干活。
            #   全部模块禁用 → 空串 → 不注入，内核行为与无模块时一致（自证条件不被破坏）。
            # ★ 算例库接线（v4 §4.3）：把**已登记算例**的现状并入 system 消息 ——
            #   张老师首轮实测：用户「已解析」了算例，模型却不知道，只能瞎猜内置算例名。
            #   两者合并进**同一条** system 消息（客户端历史仍是它自己的，不混入内核内容）。
            convo = list(messages)
            sys_parts: list[str] = []
            try:
                supplement = build_prompt_supplement(_cfg())
            except Exception as exc:
                # 提示词收集失败**不阻断对话**（fail-loud 到 notice），但必须说出来
                supplement = ""
                yield _chat_sse("notice", {
                    "detail": f"模块提示词收集失败，本轮未注入：{exc}"[:400],
                })
            if supplement:
                sys_parts.append(
                    "以下是当前启用的选题模块提供的领域提示词"
                    "（来自模块 prompts，非内核内置）：\n\n" + supplement
                )
            try:
                case_ctx = build_case_context()
            except Exception as exc:
                case_ctx = ""
                yield _chat_sse("notice", {
                    "detail": f"算例库现状读取失败，本轮未注入：{exc}"[:400],
                })
            if case_ctx:
                sys_parts.append(case_ctx)
            if sys_parts:
                convo.insert(0, ChatMessage(role="system", content="\n\n".join(sys_parts)))

            async for ev in run_turn(
                provider, convo, specs=inv.tools,
                execute=execute, max_rounds=max_rounds,
            ):
                if ev.kind == "final":
                    _publish_evidence(bus, sid, "assistant_message",
                                      {"content": ev.text, "servers": servers})
                elif ev.kind == "error":
                    # 本轮失败也要留痕 —— 否则审计里只有"问了"，看不出"为什么没答"
                    _publish_evidence(bus, sid, "turn_error", {"detail": ev.detail})
                if ev.kind in _CHAT_EVENT_KINDS:
                    yield _chat_sse(ev.kind, _event_payload(ev))

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def _parse_case_request(payload: dict) -> tuple[dict, str | None]:
    """解析算例登记请求体。

    ★ `path` 必填且非空；`label` / `tags` / `notes` 可选。
      类型错误一律 400 并指明字段 —— 不把畸形请求送进文件系统。
    """
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return {}, "请求体需提供 `path`（算例文件路径，非空字符串）"

    label = payload.get("label")
    if label is not None and not isinstance(label, str):
        return {}, "`label` 必须是字符串"

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        return {}, "`notes` 必须是字符串"

    tags_raw = payload.get("tags")
    if tags_raw is None:
        tags: list[str] = []
    elif isinstance(tags_raw, list) and all(isinstance(t, str) for t in tags_raw):
        tags = tags_raw
    else:
        return {}, "`tags` 必须是字符串数组"

    return {
        "path": raw.strip(),
        "label": (label or "").strip() or None,
        "tags": tags,
        "notes": notes or "",
    }, None


def register_case_routes(app: FastAPI) -> None:
    """注册算例库端点（方案 v4 §4.2）。

    ★ 算例是 v4 引入的**新一级实体**：v3 只有 session 粒度，研究无法「组织」。
    ★ 端点本身**不碰文件内容** —— 只登记路径与哈希；解析为 PowerIO IR
      是后续单元（P0-2b-2，需要真实拉起 server）。
    """

    def _store() -> CaseStore:
        return CaseStore(cases_root(_cfg()))

    @app.get("/cases")
    async def list_cases() -> dict:
        """列出全部算例，含**现算**的可用性 / 漂移 / server 可读性。"""
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            return build_cases_report(c)
        except CaseIndexError as exc:
            # 索引损坏是**服务端数据问题** → 500（不是客户端的错）
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/cases")
    async def register_case(payload: dict):
        """登记一个算例（同一路径重复登记 = 更新，返回 200 而非 201）。"""
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        parsed, err = _parse_case_request(payload)
        if err:
            return JSONResponse(status_code=400, content={"detail": err})

        store = _store()
        try:
            case, created = store.register(
                parsed["path"], label=parsed["label"],
                tags=tuple(parsed["tags"]), notes=parsed["notes"],
            )
            view = store.view(case)
        except CaseIndexError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except CaseError as exc:
            # 路径不存在 / 是目录 / 超限 —— 都是**客户端输入问题**
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        return JSONResponse(
            status_code=201 if created else 200,
            content={"created": created, "case": view.to_dict()},
        )

    @app.get("/cases/{cid}")
    async def get_case(cid: str):
        store = _store()
        try:
            case = store.get(cid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "算例不存在"})
        except CaseIndexError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return store.view(case).to_dict()

    @app.delete("/cases/{cid}")
    async def delete_case(cid: str):
        """**注销登记** —— 只删索引条目，**绝不删除源文件**。

        ★ 数据安全底线：一个 HTTP 动词不该能删掉用户磁盘上的算例。
          若要真正删除文件，那是文件系统的事，不由本端点代劳。
        """
        store = _store()
        try:
            removed = store.unregister(cid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "算例不存在"})
        except CaseIndexError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "unregistered": removed.id,
            "label": removed.label,
            "source_path": removed.source_path,
            "source_file_kept": True,
        }

    def _require_case(cfg, cid: str):
        """取算例并校验「可解析」的前置条件。

        Returns:
            `(case, view, error_response)` —— 出错时前两者为 `None`。

        ★ **前置条件必须显式检查并给出可执行指引**，而不是把请求放过去让 server 报一个
          看不懂的沙箱错误。这正是本会话实测到的坑：`POWERIO_MCP_ALLOWED_ROOTS`
          若不透传，server 只认默认根，表现为"读不到文件"。
        """
        store = _store()
        try:
            case = store.get(cid)
        except KeyError:
            return None, None, JSONResponse(status_code=404, content={"detail": "算例不存在"})
        except CaseIndexError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        view = store.view(case)
        if not view.available:
            # 409：当前状态不允许该操作（源文件没了），但**可修复**
            return case, view, JSONResponse(status_code=409, content={
                "detail": f"算例源文件不存在或不可读：{case.source_path}",
            })
        if not view.within_allowed_roots:
            roots = [str(r) for r in allowed_root_paths()]
            return case, view, JSONResponse(status_code=409, content={
                "detail": (
                    "算例所在目录不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 —— server 子进程读不到它。"
                    f"请把 `{Path(case.source_path).parent}` 加入该变量后重启网关"
                    f"（当前允许根：{roots}；见 `GET /environment` 的 `server_env` 段）。"
                ),
            })
        return case, view, None

    def _load_artifact_or_409(cfg, cid: str):
        art = load_artifact(cases_root(cfg), cid)
        if art is None:
            return None, JSONResponse(status_code=409, content={
                "detail": "该算例尚未解析 —— 先 `POST /cases/{id}/parse`",
            })
        return art, None

    @app.post("/cases/{cid}/parse")
    async def parse_case_route(cid: str):
        """把算例解析为 PowerIO IR 并落盘。

        ⚠️ **会真实拉起 powerio 进程**（秒级），属显式动作，故为 POST。
        ⚠️ 每次 POST **都重新解析**（不复用产物）—— 想要已有产物请用 `GET /cases/{id}/ir`。
        ★ 响应**不返回 IR 本身**（约 60KB），只返回元数据；IR 走 `GET /cases/{id}/ir`。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        case, _view, err = _require_case(c, cid)
        if err is not None:
            return err

        try:
            artifact = await parse_case(c, case)
        except CaseIrError as exc:
            # 502：**上游（引擎）失败**，不是本网关或客户端的错
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        payload = artifact_to_payload(artifact)
        path = save_artifact(cases_root(c), payload)
        payload.pop("ir", None)
        payload["artifact"] = str(path)
        payload["has_ir"] = True
        return payload

    @app.get("/cases/{cid}/ir")
    async def get_case_ir(cid: str):
        """取已解析的 PowerIO IR（供 IR 检查器视图用）。"""
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        store = _store()
        try:
            case = store.get(cid)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": "算例不存在"})
        except CaseIndexError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        art, err = _load_artifact_or_409(c, cid)
        if err is not None:
            return err

        raw = art.get("ir", "")
        parsed: object = raw
        ir_parsed = False
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                ir_parsed = True
            except json.JSONDecodeError:
                parsed = raw      # 解析不了就原样给（不假装成功）

        return {
            "case_id": cid,
            "value_type": art.get("value_type"),
            "parsed_at": art.get("parsed_at"),
            "source_path": art.get("source_path"),
            "ir_parsed": ir_parsed,
            "ir_bytes": art.get("ir_bytes"),
            "ir": parsed,
        }

    @app.get("/cases/{cid}/diagnostics")
    async def case_diagnostics(cid: str):
        """用已解析的 IR 跑 `powerio.diagnostics`。

        ★ **陈旧检测**：产物记录了**解析时**的源文件哈希；若源文件此后变了，
          `stale=true` —— 诊断结论来自旧数据。存下来的"最新"标记会过期，
          故每次现算比对。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        case, view, err = _require_case(c, cid)
        if err is not None:
            return err

        art, err = _load_artifact_or_409(c, cid)
        if err is not None:
            return err

        ir = art.get("ir")
        if not isinstance(ir, str) or not ir:
            raise HTTPException(status_code=500, detail="算例产物缺少 `ir` 字段，请重新解析")

        stale = (
            view.current_sha256 is not None
            and art.get("source_sha256") != view.current_sha256
        )
        try:
            result = await run_diagnostics(c, ir)
        except CaseIrError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "case_id": cid,
            "value_type": art.get("value_type"),
            "parsed_at": art.get("parsed_at"),
            "stale": stale,
            "result": result,
        }


def register_check_routes(app: FastAPI) -> None:
    """模块 checks 执行端点（G-4 最小闭环 + G-5 契约，见 `checks.py` 模块 docstring）。"""

    @app.post("/checks/run")
    async def checks_run(payload: dict):
        """跑一个模块的全部 checks（G-5：`check(ctx) -> list[str|dict]`）。

        请求体：
          - `module_id`（必填，str）
          - `rows`（必填，`{result_table_id: [行, ...]}`）—— 结果表存储尚未建成，
            行由**调用方**提供（如对话工具结果的落表、将来的实验引擎）；
          - `case` / `case_id`（可选）—— 原样进 ctx，供 check 做算例级判定。

        错误映射：400 请求体非法 / 404 模块不存在或装配失败 / 409 模块已禁用 / 503 配置失败。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not isinstance(payload, dict):
            return JSONResponse(status_code=400, content={"detail": "请求体必须是 JSON 对象"})
        module_id = payload.get("module_id")
        if not isinstance(module_id, str) or not module_id.strip():
            return JSONResponse(status_code=400, content={"detail": "缺少非空 `module_id`"})
        rows_by_table = payload.get("rows")
        if not isinstance(rows_by_table, dict) or not all(
            isinstance(k, str) and isinstance(v, list) for k, v in rows_by_table.items()
        ):
            return JSONResponse(status_code=400, content={
                "detail": "`rows` 必须是 `{result_table_id: [行, ...]}`（键为表 id，值为行数组）",
            })
        case = payload.get("case")
        if case is not None and not isinstance(case, dict):
            return JSONResponse(status_code=400, content={"detail": "`case` 必须是对象或 null"})
        case_id = payload.get("case_id")
        if case_id is not None and not isinstance(case_id, str):
            return JSONResponse(status_code=400, content={"detail": "`case_id` 必须是字符串或 null"})

        try:
            return run_module_checks_engine(
                c, module_id=module_id.strip(), rows_by_table=rows_by_table,
                case=case, case_id=case_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def create_app(cfg: GatewayConfig | None = None, *,
               provider: OpenAICompatProvider | None = None,
               pool: "ServerPool | None" = None) -> FastAPI:
    app = FastAPI(title="PowerMCP Gateway", version="0.1.0", lifespan=_lifespan)
    if cfg is not None:
        global _CONFIG
        _CONFIG = cfg
    if provider is not None:
        global _PROVIDER
        _PROVIDER = provider
    # ★ 子项目 4：会话级持久 server 连接池。默认关闭（旧语义：逐调用挂载）；
    #   `POWERMCP_SESSION_POOL=1`（run_gateway 启动脚本已设）或显式传 `pool=` 开启。
    global _POOL
    if pool is not None:
        _POOL = pool
    elif os.environ.get("POWERMCP_SESSION_POOL") == "1":
        _POOL = ServerPool(_cfg())
    else:
        _POOL = None

    @app.get("/health")
    async def health() -> dict:
        """存活检查 + **审计持久化降级**的观测面（C-2）。

        ★ 为什么把审计计数放在健康面上：审计写失败（磁盘满/权限）时，事件**已在内存
          历史中、但未持久化到 NDJSON** —— 这是 I-2 之后**唯一残留的静默降级路径**。
          让它在这里可读，就不必翻日志才发现"证据流已在悄悄掉数据"。
          `audit.append_failures` 是**累计量**（丢失量级），`audit.handles` 是现状量。
        """
        return {"status": "ok", "audit": _AUDIT.stats(),
                "server_pool": (_POOL.stats() if _POOL is not None
                                else {"enabled": False})}

    @app.get("/servers")
    async def servers() -> dict[str, list[str]]:
        return {"servers": list(OPEN_SOURCE_SERVERS)}

    @app.get("/environment")
    async def environment() -> dict:
        """环境就绪报告（方案 v4 §4.1）。

        ★ **廉价**：不拉起任何 MCP server —— server 挂载状态见 `GET /contracts/t0`。
          这一分工写在响应体的 `notes` 里，避免前端以为是漏了。
        ★ **绝不回显凭据**：`llm.endpoint` 只给 `scheme://host`，密钥只报"是否设置"。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return build_environment_report(c)

    @app.get("/skills")
    async def skills() -> dict:
        """PowerSkills 技能索引 + Escalation triggers（方案 v4 §4.5）。

        ★ 这是 v4 相对 v3 的**最重要新增**：21 个技能在 v3 中零覆盖，
          而 escalation triggers（观测值 → 缓解手册）是「研究方法」最直接的载体。
        ★ 健康度只报**可计算**信号（缺 escalation 表 / 悬空引用 / 孤儿手册），
          整体标 `unknown` —— 不转录人工审计结论，也不让用户以为技能都可靠。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return build_skills_report(c)

    @app.get("/modules")
    async def modules() -> dict:
        """选题模块清单与装配状态（方案 v4 §六）。

        ★★ **内核不依赖任何模块** —— 模块根不存在、为空、或全部禁用时，
          本端点照常 200 且 `failures` 为空。这正是本架构的**自证条件**：
          若禁用模块内核就不可用，说明内核被领域知识污染了。
        ★ **fail-loud**：单个模块装配失败只标记它自己（`failures`），
          不影响其他模块，也不影响内核。
        """
        try:
            c = _cfg()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        skills = build_skills_report(c)
        return build_modules_report(
            c,
            known_servers=OPEN_SOURCE_SERVERS,
            known_skills=tuple(s["id"] for s in skills["skills"]),
        )

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
    register_case_routes(app)
    register_check_routes(app)
    _mount_ui(app)
    return app


def _mount_ui(app: FastAPI) -> None:
    """把前端静态产物挂在 `/ui`（方案 v4 §九：静态文件由 FastAPI 单进程 serve）。

    ★ **为什么必须同源**：前端若用 `file://` 打开，调 `http://127.0.0.1:...` 属**跨源**请求，
      浏览器会直接拦掉 —— 表现为"界面打开了但什么都加载不出来"。
      挂在同一进程下就绕开了 CORS，也不需要给网关加 CORS 中间件（少一个安全面）。

    ⚠️ 目录不存在时**静默跳过** —— 网关要能独立使用，不能因为前端没构建就起不来。
    """
    try:
        ui_dir = _cfg().powermcp_root.parent / "frontend"
    except Exception:  # 配置无法解析时不影响 app 组装（端点自己会报 503）
        return
    if ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")