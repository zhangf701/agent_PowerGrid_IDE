"""MCP 代理调用 —— 契约 3 的落地点。

★ 这里是唯一能"阻止"参数契约缺陷的位置：在把调用转发给引擎**之前**校验参数。
  校验不通过 → 不转发。fail-closed。
  理由：一个会被引擎静默忽略的调用，跑过去比不跑更危险 —— 它会产出一个
  "看起来成功、实际没生效"的结果，而那正是 original 缺陷（linearized）的形态。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .audit import AuditLog
from .config import GatewayConfig
from .contracts.model import ContractFinding
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


def _emit_finding(
    bus: EventBus | None,
    audit: AuditLog | None,
    session_id: str | None,
    kind: str,
    finding: ContractFinding,
) -> None:
    """把一个 `ContractFinding` 以事件 payload 形式发出。

    ★ payload 必须与 `/contracts/t0` 的 finding **同形**（`dataclasses.asdict`）：
      前端契约面板按同一套形状解析；且 `ContractFinding.state` 是 `summarize()`
      的输入 —— 缺了 `state` 的裸字典无法参与双轨汇总，主徽标永远不会因它变红
      （又是静默 fail-open）。

    ★ 用 `ContractFinding(...)` **构造**而非手拼字典，形状与不变式由模型保证：
      `__post_init__` 会校验契约编号、`unknown ⇔ reason` 的配对，畸形 payload
      在构造期就炸，不会流进事件流。
    """
    _emit(bus, audit, session_id, kind, asdict(finding))


def _error_text_from_content(content: object) -> str:
    """从 MCP 结果的 `content` 提取纯文本（`[{"type": "text", "text": ...}, ...]`）。

    ★ 工具的**真实错误消息**（如 `"solver diverged"`）只存在于 `content` 里，
      而 `is_error` 路径的 `error` 才是诊断时人最先看到的东西 —— 不提取就等于
      把最有信息量的部分藏起来（T5-M2）。

    ★ 对非 list/tuple、非 dict 元素、缺失/非 str 的 `text` **一律安全跳过**，
      不抛异常（隔离坏输入）。无可用文本时返回空串，由调用方退回固定文案。
    """
    if not isinstance(content, (list, tuple)):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return " | ".join(parts)


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
    """转发一次工具调用，并在转发**之前**用声明的 schema 校验参数（契约 3）。

    ★ 校验失效时的取舍（**显式设计决定**）：`validate_args` 自身若因 schema 畸形
      而抛异常，**不 fail-closed 拒发** —— 畸形 schema 不是"这次调用有问题"的证据，
      拒发会打断一个本来合法的调用。但也绝不静默：发一条
      `state="unknown" / reason="structural"` 的 finding，把"看不到"如实报出来，
      与契约 4 的 `checked == 0 → unknown/structural` 同一口径（UI 规范 P5 禁止
      静默 fail-open）。校验层是唯一能阻止坏调用的地方，不该对坏输入裸奔。
    """
    try:
        violations = validate_args(schema, args)
    except Exception as exc:
        logger.warning("参数校验器无法判定（schema 畸形？）", exc_info=True)
        # 注意 kind：**无法判定 ≠ 存在违规** —— 用独立的 `contract_unknown`，
        # 与真违规的 `contract_violation` 区分。理由：任何按 kind 过滤的消费者
        # （前端按 kind 分派、完成标准按 kind 验收）若把 unknown 当违规，就是**假警报**；
        # 靠消费者记得读 state 才不出错，正是本项目反复否掉的"静默兜底"。
        _emit_finding(bus, audit, session_id, "contract_unknown", ContractFinding(
            contract=3, state="unknown", reason="structural", subject=server,
            detail=f"参数校验器无法判定：{type(exc).__name__}: {exc}"[:200],
            evidence={"server": server, "tool": tool, "method": "proxy-validate"},
        ))
        violations = ()

    if violations:
        _emit_finding(bus, audit, session_id, "contract_violation", ContractFinding(
            contract=3, state="violated", reason=None, subject=server,
            detail="; ".join(v.detail for v in violations),
            evidence={
                "server": server,
                "tool": tool,
                "violations": [asdict(v) for v in violations],
                "method": "proxy-validate",
            },
        ))
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
        # ★ error 必须带上工具的**真实输出**：工具的失败消息（如 "solver diverged"）
        #   只在 result["content"] 里，而 error 才是诊断时人最先看到的东西（T5-M2）。
        #   提取不到文本时退回固定文案（绝不产生空消息）。
        message = "工具以 is_error=True 返回（MCP 标准错误形态，非异常）"
        detail = _error_text_from_content(result.get("content"))
        if detail:
            message = f"{message}：{detail}"[:300]      # 与既有 [:300] 截断风格一致
        _emit(bus, audit, session_id, "tool_error", {
            "server": server, "tool": tool, "error": message,
        })
        return CallOutcome(
            ok=False, server=server, tool=tool, result=result, error=message,
        )

    _emit(bus, audit, session_id, "tool_call", {
        "server": server, "tool": tool, "args": args,
    })
    return CallOutcome(ok=True, server=server, tool=tool, result=result)
