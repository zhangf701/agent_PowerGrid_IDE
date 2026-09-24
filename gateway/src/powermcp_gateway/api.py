"""网关 HTTP API。

状态（会话 / 审计 / 配置 / T0 缓存）全部在**模块级** —— 端点与测试共享同一实例。
路由注册拆成 `register_session_routes()`，`create_app()` 只负责组装。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from contextlib import asynccontextmanager
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """应用生命周期：**关闭时必须 flush 审计**。

    ★ `AuditLog` 是**批量写入**（每 32 条 flush 一次）。没有这一步，进程退出时
      缓冲区里的 EVIDENCE 事件会**直接丢失** —— 而审计通道的设计前提是"不可丢"。
      实测（2026-09-24 端到端验收）：单条契约违规后进程被杀，
      `audit-<sid>.ndjson` 仍是 **0 字节**，违规记录彻底丢失。
    """
    yield
    try:
        _AUDIT.flush()
    except Exception:
        logger.warning("退出时 flush 审计失败 —— 缓冲区内的证据事件可能丢失", exc_info=True)

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
    app = FastAPI(title="PowerMCP Gateway", version="0.1.0", lifespan=_lifespan)
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