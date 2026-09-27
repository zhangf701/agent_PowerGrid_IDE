"""§11.2 并发隔离 —— 网关侧的租约与命名空间（方案 §11.2 / §2.7）。

★ **为什么需要它**（§11.2 原文）：实验矩阵的批量参数扫描**必然并发**，而全仓
  **无任何锁机制**；`runs_dir(tool)` 是 **per-tool 共享**（非 per-session / per-case），
  共享进程会放大文件冲突面。

★ **为什么网关能解决、且不必改上游**（`PowerMCP/` 是上游 clone，一行不改）：
  `powermcp/paths.py::runs_dir(tool)` = `powermcp_home()/runs/<tool>`，
  而 `powermcp_home()` = `os.environ["POWERMCP_HOME"] or ~/.powermcp`。
  ⇒ 网关**给每个会话的子进程注入不同的 `POWERMCP_HOME`**，就得到
    `~/.powermcp/sessions/<sid>/runs/<tool>` —— 即 §11.2 措施 1 的目标命名空间。
  （方案写作 `runs/<session_id>/<tool>/<case_hash>/`；**会话维度是关键**，
   case 维度由「一格一个会话 + 每格各自 `load_network`」天然满足。）

★ **五项措施的落地边界（诚实清单，不夸大）**：

  | # | 措施 | 状态 |
  |---:|---|---|
  | 1 | 命名空间加 session 维度 | ✅ `session_home()` + `config.session_env()` |
  | 2 | 租约锁 | ⚠️ **进程内**（`LeaseRegistry`）；**跨进程 / 跨机文件租约未做** |
  | 3 | 工作流级事务 | ✅ 网关自身状态（临时文件 + `os.replace` + 写锁）；⚠️ 引擎产物属上游 |
  | 4 | 引擎实例串行化 | ✅ `(sid, server)` 租约；且每会话各自一个 server 进程 |
  | 5 | 统一写入方式 | ❌ **上游所有**（`ANDES/andes_mcp.py` 按名字拼路径），由措施 1 缓解 |

★ **残余风险**（§11.2 原文已自陈，不宣称消除）：
  `ALLOWED_ROOTS` 检查**无法阻止另一进程在验证后替换路径**；
  本模块的租约是**进程内**的，多网关进程同时跑同一算例仍可能争用 —— 故
  **不得对外宣称"并发已完全安全"**，只能宣称"单进程内已隔离，跨进程未覆盖"。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "LeaseRegistry",
    "LeaseTimeout",
    "LEASES",
    "session_home",
    "session_env",
    "powermcp_home_base",
    "case_key_of",
    "file_write_lock",
    "reset_leases",
]


class LeaseTimeout(RuntimeError):
    """在超时内没拿到租约 —— **响亮失败**，由调用方映射成可执行的错误。

    ★ 为什么不无限等待：并发场景下无界等待会把请求**挂死**（用户看不到任何进展），
      而"另一个持有者卡住了"这件事必须被说出来，不能被静默吸收。
    """


@dataclass
class _LeaseState:
    """一把租约的运行期状态（仅供 `stats()` 与超时诊断）。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: **正在排队**的协程数（不含持有者）。只在"锁已被占"时才增加。
    waiting: int = 0
    #: 累计持有次数
    acquisitions: int = 0


@dataclass
class _Counters:
    acquired: int = 0
    waited: int = 0
    timed_out: int = 0
    max_waiters: int = 0
    keys: int = 0


class LeaseRegistry:
    """按 key 的**进程内**异步互斥租约（§11.2 措施 2 / 4 的落点）。

    ★ 语义是**互斥**：同一 key 同时只允许一个持有者。这与 §11.2 的
      「每 `(engine, case_hash)` 一把锁」一致 —— 锁保护的是**共享的可写状态**
      （`runs/<tool>/` 下的产物、引擎进程内的已加载网络）。
    ★ 为什么是注册表而不是给对象挂 `asyncio.Lock`：key 是**运行时派生**的
      （会话 × 引擎、引擎 × 算例），数量无上界；注册表按需创建，并把
      「谁在等、等了多少」变成**可观测**的量（方案 §4.4 要求进度可观测）。
    ★ 等待**有超时**：超时抛 `LeaseTimeout`（响亮失败），绝不静默继续。
    """

    def __init__(self, *, default_timeout_s: float = 120.0) -> None:
        self._states: dict[str, _LeaseState] = {}
        self._counters = _Counters()
        self._default_timeout_s = default_timeout_s

    # ---------------------------------------------------------------- 内部

    def _state(self, key: str) -> _LeaseState:
        st = self._states.get(key)
        if st is None:
            st = _LeaseState()
            self._states[key] = st
            self._counters.keys = len(self._states)
        return st

    # ---------------------------------------------------------------- 公开

    @asynccontextmanager
    async def hold(self, key: str, *, timeout_s: float | None = None) -> AsyncIterator[None]:
        """持有 `key` 的租约；退出时释放。

        Raises:
            LeaseTimeout: 在 `timeout_s` 内没拿到（**不静默继续**）。
        """
        st = self._state(key)
        limit = self._default_timeout_s if timeout_s is None else timeout_s
        # ★ 判"是否需要排队"必须看**锁是否已被占**，不能看 `waiting > 0`：
        #   锁空闲时 `await acquire()` **不会让出事件循环**，前一个持有者会在
        #   下一个 await 点之前就把 `waiting` 减回去 —— 用 `waiting` 判会漏计
        #   （实测：两个协程争一把锁，`waited` 却是 0）。
        queued = st.lock.locked()
        if queued:
            st.waiting += 1
            self._counters.waited += 1
            self._counters.max_waiters = max(self._counters.max_waiters, st.waiting + 1)
            logger.debug("等待租约 key=%s（%d 个排队者）", key, st.waiting)
        try:
            try:
                await asyncio.wait_for(st.lock.acquire(), timeout=limit)
            except asyncio.TimeoutError as exc:
                self._counters.timed_out += 1
                raise LeaseTimeout(
                    f"等待租约 {key!r} 超过 {limit:g}s —— 另一个持有者可能卡住了。"
                    "这不是「没结果」，而是「还没轮到」：请稍后重试，"
                    "或检查该引擎是否无响应。"
                ) from exc
        finally:
            if queued:
                st.waiting -= 1
        st.acquisitions += 1
        self._counters.acquired += 1
        try:
            yield
        finally:
            st.lock.release()

    def stats(self) -> dict[str, Any]:
        """租约运行期统计 —— 挂在 `/health` 上，让"有没有在排队"可观测。"""
        active = [k for k, s in self._states.items() if s.lock.locked()]
        return {
            "keys": len(self._states),
            "active": len(active),
            "acquired": self._counters.acquired,
            "waited": self._counters.waited,
            "timed_out": self._counters.timed_out,
            "max_waiters": self._counters.max_waiters,
            # ⚠️ 只暴露**正在争用**的 key（正常运行时为空），便于排查"谁卡住了"
            "contended_keys": sorted(active)[:8],
            "default_timeout_s": self._default_timeout_s,
            "scope": "process-local",
        }

    def reset(self) -> None:
        """清空统计与租约表（**仅供测试**；运行期调用会丢掉正在排队的租约）。"""
        self._states.clear()
        self._counters = _Counters()


#: 进程级默认租约表。所有工具调用与实验执行共用它 —— 这正是"进程内隔离"的范围。
LEASES = LeaseRegistry()


def reset_leases() -> None:
    """重置进程级租约表（供测试隔离用）。"""
    LEASES.reset()


# ------------------------------------------------------------------ 写锁（措施 2/3）


#: 进程内**按路径**的写锁表。保护 JSON 索引的「读-改-写」。
_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def file_write_lock(path: Path) -> threading.Lock:
    """取某路径的**进程内**写锁（不存在则创建）。

    ★ 为什么是 `threading.Lock` 而不是 `asyncio.Lock`：`CaseStore` / `ExperimentStore`
      的方法是**同步的**，在事件循环里被直接调用。改用 `asyncio.Lock` 要把整条
      调用链（含所有端点与测试）改成 async —— 改动面大、且容易漏一处就**静默失效**。
      临界区只有「读 JSON → 改 → 原子替换」三步，是本地的毫秒级 IO，持锁极短，
      用线程锁的代价可接受（且不会把事件循环卡住太久）。
    ★ 为什么按**路径**而不是全局一把锁：不同索引文件之间没有共享状态，
      全局锁会把无关的写串起来（无谓争用）。
    ⚠️ **仅进程内**：多网关进程同时写同一索引仍会互相覆盖 —— 这是本模块
      docstring 里写明的残余风险，**不宣称已消除**。
    """
    key = os.path.normcase(str(path))
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


# ------------------------------------------------------------------ 命名空间


def session_home(base: Path, sid: str) -> Path:
    """会话级 `POWERMCP_HOME` —— §11.2 措施 1 的目标命名空间。

    注入后上游的 `runs_dir(tool)` 会落到
    `<base>/sessions/<sid>/runs/<tool>`，即"per-session"隔离。

    ★ `sid` 会**规范化**（只留安全字符）后才拼进路径：会话 id 来自 HTTP 路径/请求体，
      直接拼路径等于把路径穿越的口子交给调用方。
    """
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    if not safe:
        raise ValueError("会话 id 规范化后为空 —— 拒绝用它构造路径")
    return base / "sessions" / safe


#: 看起来像**算例文件路径**的参数名（用于从工具参数派生 case 键）。
#: ⚠️ 不追求穷举：派不出 case 键时**回落到参数哈希**（见 `case_key_of`），
#:   宁可退化成"按参数互斥"，也不假装认得出所有形态。
_PATH_ARG_HINTS = ("file_path", "path", "case_path", "source_path", "filename", "file")


def powermcp_home_base(env: Mapping[str, str] | None = None) -> Path:
    """上游 `powermcp_home()` 的**基目录**（认 `POWERMCP_HOME`，与上游同口径）。"""
    e = os.environ if env is None else env
    raw = e.get("POWERMCP_HOME")
    return Path(raw) if raw else (Path.home() / ".powermcp")


def session_env(sid: str, *,
                env: Mapping[str, str] | None = None) -> tuple[dict[str, str], str | None]:
    """会话级环境覆盖 —— §11.2 措施 1 的落点。

    Returns:
        `(overrides, note)`。`note` 非空表示**没有**重定向，并给出原因与修复路径。

    ★ 为什么**围笼校验不通过就不重定向**（而不是照做）：
      `runs_dir` 的产物要过 `powerio.mcp.sandbox` 的 `checked_path`。把
      `POWERMCP_HOME` 指到围笼**外面**，等于让 ANDES/Egret 的每一次写都被拒
      —— 那是**把引擎弄坏**，比"共享命名空间"严重得多。
      故这里的取舍是：**宁可退化成共享命名空间（并响亮说明），也不静默弄坏引擎**。
    ★ 围笼**未配置**时同样不重定向：上游会回落到"导入时的 cwd"，我们无从判断
      会话目录是否可写 —— 不猜。
    """
    from .cases import allowed_root_paths, is_within_roots

    home = session_home(powermcp_home_base(env), sid)
    roots = allowed_root_paths(env)
    if not roots:
        return {}, (
            "未配置 `POWERIO_MCP_ALLOWED_ROOTS` —— 无法判断会话命名空间是否可写，"
            "故**不重定向** `POWERMCP_HOME`（保持共享命名空间）。"
            "要启用会话级隔离，请设置该变量并包含 `"
            f"{powermcp_home_base(env)}`（见 run_gateway 脚本）。"
        )
    if not is_within_roots(home, roots):
        return {}, (
            f"会话命名空间 `{home}` 不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 —— **不重定向**"
            "（否则 server 子进程写 `runs/` 会被围笼拦下，表现为引擎报 PathNotAllowed）。"
            f"请把 `{powermcp_home_base(env)}` 加进允许根后重启网关。"
        )
    return {"POWERMCP_HOME": str(home)}, None


def case_key_of(args: Mapping[str, Any]) -> str:
    """从工具参数派生**稳定的算例键**（§11.2 措施 2 的 `case_hash` 位）。

    ★ 用**解析后的路径**而不是文件内容哈希：内容哈希要把 74 MB 的算例读一遍，
      而这一步在**每次调用**的路径上；路径同一性已足以发现"两次调用碰同一个算例"。
      （算例的**内容**哈希由算例库负责，两者用途不同，不要混。）
    ★ 认不出路径参数时**回落到规范化参数哈希** —— 退化成"按参数互斥"，
      比"假装没有冲突"安全（宁可多锁一点，不可漏锁）。
    """
    paths: list[str] = []
    for name, value in args.items():
        if not isinstance(value, str) or not value:
            continue
        looks_like_path = (
            name.lower() in _PATH_ARG_HINTS
            or "/" in value
            or "\\" in value
            or Path(value).suffix.lower() in {".m", ".raw", ".json", ".dss", ".nc", ".xiidm"}
        )
        if looks_like_path:
            try:
                paths.append(os.path.normcase(str(Path(value).expanduser().resolve(strict=False))))
            except (OSError, ValueError):
                paths.append(value)
    if paths:
        blob = "|".join(sorted(paths))
    else:
        blob = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
