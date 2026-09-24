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
    """提取 prop 声明的可接受 JSON 类型名；**对畸形输入安全退化为 `()`**。

    与 `validate_args` 对「非 dict 的 prop」的 fail-open 立场一致（第 84-87 行）：
    校验器只做它看得懂的事，看不懂就不下结论，**绝不因 schema 畸形而抛异常**。

    取舍（显式记录）：
      - `type` 是 str          → `(t,)`
      - `type` 是 list/tuple   → 只保留其中**是 str** 的元素（丢弃非 str 项）
      - `type` 其它类型（int/dict/None…）→ `()`
      - `anyOf` 是 list/tuple  → 取其中 dict 元素且 `type` 为 str 的项的 type
      - `anyOf` 其它类型       → `()`
      - 二者都缺失            → 维持既有语义 `()`

    原实现对 `type=5`、`anyOf=5` 会 `TypeError: 'int' object is not iterable`
    （`tuple(5)`），异常会逃出 `proxy.call_tool` 变成 HTTP 500。
    """
    if "type" in prop:
        t = prop["type"]
        if isinstance(t, str):
            return (t,)
        if isinstance(t, (list, tuple)):
            return tuple(x for x in t if isinstance(x, str))
        return ()
    if "anyOf" in prop:
        a = prop["anyOf"]
        if isinstance(a, (list, tuple)):
            return tuple(
                x["type"] for x in a
                if isinstance(x, dict) and isinstance(x.get("type"), str)
            )
        return ()
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
# `proxy.call_tool()` 转发校验那一刻，以事件的形式进入会话总线（通道 A）
# 与 NDJSON 审计。
#
# ★ 事件流上契约 3 有**两个 kind**（都是 `ContractFinding` 同形 payload —— 见 I-1）：
#     - `contract_violation`：**判定为违规**（`state="violated"`）—— 校验器据声明
#       schema 判定这次调用确实有问题（如 `linearized` 未知参数），调用被拒发。
#     - `contract_unknown`：**无法判定**（`state="unknown"` / `reason="structural"`）
#       —— 校验器自身对畸形 schema 无法下结论，调用**照常转发**，但如实报告"看不到"。
#   前端按 `kind` 分派、按 `state` 汇入双轨汇总（§UI 规范 v1.2 的 unknown 两分）。
#   两者**不可混用**：把"无法判定"塞进 `contract_violation` 会让按 kind 过滤的消费者
#   产生**假警报** —— 与"假绿灯"是同一枚硬币的另一面。
#
# 因此本模块**不定义 Evaluator、不注册进 REGISTRY** —— 那是刻意的：
# 一个 `evaluate() -> []` 的求值器只会是死代码，还会误导人以为契约 3 是周期求值的。
# 前端契约面板消费的是事件流里的这两个 kind，不是 T0 报告。
# ───────────────────────────────────────────────────────────────────────────
