"""实验矩阵 —— `experiment` 这一级实体（方案 v4 §4.4）。

★ 为什么它是判据 #2 / #3 的落点（方案 §12）：
  - #2「能组织研究」= 同一算例的多组实验挂在同一个 case 下、结果可对比；
  - #3「能批量跑」  = 网格（算例 × 因子）一次提交并拿到结果表。
  两条都要求「实验」是**一等对象**，而不是会话里一串散落的 `tool_call`。

★ 本步（P2-①a）的**明确范围**：只做**定义与登记**。
    实验 = 算例集合 × 因子网格 × **一条工具步骤序列**（每步 server / tool / args 模板）；
    展开出的每一格（cell）只算到「要跑什么」（每步的 `args` + `cache_key`），**不执行**。
  执行（逐格 `proxy.call_tool` + 逐格状态与失败可见）是 P2-①b。
  ⇒ 为什么先切这一刀：执行器必须先回答「模板参数是否真的被该引擎接受」，
    而定义层不需要回答它。分开做，定义层能用真实网格先验证，
    执行层则可以只用契约 3 的 fail-closed 兜底。

★ **为什么是步骤序列而非单步**（P2-①b 核实的硬事实）：
  引擎是**有状态**的 —— `surge.run_n1_branch_contingency` 只接 `monitored_branches`、
  **没有 `file_path`**，它跑的是进程内已加载的网络。故一次 N-1 分析 =
  `load_network(case)` → `run_n1_branch_contingency()` 两步，且两步须在同一 server 会话。
  单步模型表达不了它。⚠️ 但仍是**显式声明**：不替引擎自动注入前置步。

★ 三个关键设计决定（都可复核）：

  1. **一格 = 一条显式声明的步骤序列**（每步 `server` + `tool` + `args` 模板），
     **因子只是标签维度**（用于结果表分列与分组），不隐含任何物理语义。
     ★ 为什么不做「负荷水平」这类**语义因子**：那要求某个引擎真的能按因子缩放负荷，
       而**这一点本步未核实**（未逐参数核对 server 工具面）。
       把「负荷水平怎么施加」编码进网关 = 替引擎声称一个未验证的能力 ——
       正是契约层反复否掉的「静默假声明」。
       声明式模板把选择权交回声明者；参数对不对由**契约 3 在调用前 fail-closed** 兜住。

  2. **`cache_key` 只由可确证的量构成**（对齐方案 §4.4 的口径，并如实缩水）：
       `H(算例当前 sha256 + steps 规范化序列 + core_version)`
     ⚠️ 方案原文还含「引擎版本」与「IR 版本」—— 网关当前**没有可靠来源**取得
        引擎版本（inventory 只给工具面，不给引擎版本号），IR 也没有版本字段。
        ⇒ **不假装有**：缺的量不进 key，而在响应的 `notes` 里写明
        「`cache_key` 不含引擎版本 / IR 版本」。
        （宁可让 key 保守失效，也不能让它冒充可复现性 —— 后者是假绿灯。）

  3. **索引用 JSON + 原子替换**，与 `CaseStore` 同构（v4 §11.4 已作废 SQLite）：
     本地单用户、量级几十到几百条；JSON 可读、可 diff、可手工核对。
     量级真上来时再换存储，`ExperimentStore` 的接口不变。

★ 存储位置：`~/.powermcp_gateway/experiments/`（与算例库同级，**不在** `~/.powermcp/`）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .cases import CaseStore, cases_root
from .concurrency import LEASES, case_key_of, file_write_lock
from .modules import CORE_VERSION

logger = logging.getLogger(__name__)

#: 覆盖实验库根目录
ENV_EXPERIMENTS_ROOT = "POWERMCP_GATEWAY_EXPERIMENTS_ROOT"

#: 索引文件名
INDEX_NAME = "experiments.json"

#: 单个实验允许展开的**格数上限**。
#: 一个 HTTP 请求不该为了展开 10^6 格而挂住 —— 超限即 400 并报出实际格数。
MAX_CELLS = 2000

#: args 模板里**内置**可用的占位符。因子名不得与它们同列（否则会静默覆盖）。
BUILTIN_PLACEHOLDERS: tuple[str, ...] = ("case_path", "case_id")

#: 因子名合法形态（与 Python 标识符同规，便于模板里 `{name}` 直接可用）
_FACTOR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 整串占位符（用于**保类型**替换：`"{load_level}"` → 1.1 而不是 "1.1"）
_WHOLE_PLACEHOLDER_RE = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")

#: 任意位置的占位符（用于统计某因子是否被引用）
_ANY_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ExperimentError(RuntimeError):
    """实验定义非法（模板 / 因子 / 算例引用问题）—— **客户端输入问题**，映射 400。"""


class ExperimentIndexError(ExperimentError):
    """实验索引损坏 —— **服务端数据问题**，映射 500（不是客户端的错）。

    ★ 与 `CaseIndexError` 同理：单列类型是为了让端点**不靠匹配错误文本**区分两类失败。
    """


class ExperimentCaseStateError(ExperimentError):
    """算例**当前状态**不允许建实验（源文件不可读 / 不在路径围笼内）—— 映射 409。

    ★ 为什么与「算例未登记」分开（后者是 400）：
      - 未登记 = 请求体引用了不存在的东西 → 客户端输入问题，**改请求**即可；
      - 不可读 / 不在围笼 = 东西存在但环境状态不允许 → **改环境**即可（可修复）。
      与 `POST /cases/{id}/parse` 对同一情形返回 409 保持同口径。

    ★ 为什么不用文本区分：文案会变、会被翻译，类型不会。
    """


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def experiments_root(cfg: Any) -> Path:
    """实验库根目录（**不放在** `~/.powermcp/` 下 —— 那是上游目录）。"""
    override = os.environ.get(ENV_EXPERIMENTS_ROOT)
    if override:
        return Path(override)
    return Path.home() / ".powermcp_gateway" / "experiments"


# ------------------------------------------------------------------ 数据模型


@dataclass(frozen=True)
class Factor:
    """一个因子维度 —— **只有名字与取值，不含物理语义**。

    `values` 必须是 JSON 标量（str / int / float / bool，非 bool 的子类也算）。
    ★ 为什么拒绝容器值：因子要参与 `cache_key` 与结果表分组，
      容器会让「两格是否相同」变得依赖字典序与浮点表示，容易出错。
    """

    name: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class Step:
    """实验里的**一步**：一次显式声明的工具调用（`server` + `tool` + `args` 模板）。

    ★ 为什么是**序列**而不是单步（P2-①b 核实的硬事实，见 `PowerMCP/surge/surge_mcp.py`）：
      `run_n1_branch_contingency(monitored_branches)` **只接这一个参数**，没有 `file_path`
      —— 它跑的是 server 进程内**已加载**的网络（函数体首行 `_require_network()`）。
      ⇒ 一次 N-1 分析 = `load_network(case)` → `run_n1_branch_contingency()` **两步**，
        且两步必须落在**同一 server 会话**（网关仅传 `sid + pool` 时复用进程）。
      单步模型表达不了它，故定义层升级为显式步骤序列。
      `pandapower.run_power_flow` 同理（也无 `file_path`）。

    ★ 仍然**只有显式声明**：不替引擎自动注入 `load_network` 之类的前置步 ——
      那等于替引擎声称一个未核实的行为，正是契约层反复否掉的「静默假声明」。
    """

    server: str
    tool: str
    args_template: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Cell:
    """网格里的一格 —— 一条**已绑定参数**的步骤序列。

    - `bindings`：该格的因子取值（结果表分列用）
    - `steps`：每一步渲染后的**实际参数**（形如 `{"server", "tool", "args"}`，
      将按序交给 `proxy.call_tool`）
    - `case_sha256`：**登记时现算**的算例哈希 —— 源文件一改，旧格即为陈旧
    - `cache_key`：内容寻址键（见模块 docstring 第 2 点）
    - `status`：定义层只有 `pending`（执行是 ①b，不预先声称进度）
    """

    index: int
    case_id: str
    case_sha256: str
    bindings: dict[str, Any] = field(default_factory=dict)
    steps: tuple[dict[str, Any], ...] = ()
    cache_key: str = ""
    status: str = "pending"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Experiment:
    id: str
    label: str
    created_at: str
    case_ids: tuple[str, ...]
    factors: tuple[Factor, ...]
    steps: tuple[Step, ...]
    notes: str = ""

    @property
    def server(self) -> str:
        """本实验的 server —— **登记期已强制全部步骤同 server**（见 `_parse_steps`）。"""
        return self.steps[0].server if self.steps else ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["factors"] = [{"name": f.name, "values": list(f.values)} for f in self.factors]
        return d


# ------------------------------------------------------------------ 模板渲染


def _render_value(value: Any, ctx: dict[str, Any], *, path: str) -> Any:
    """递归渲染 args 模板里的占位符（`path` 只用于错误信息定位）。"""
    if isinstance(value, str):
        return _render_str(value, ctx, path=path)
    if isinstance(value, dict):
        return {k: _render_value(v, ctx, path=f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, ctx, path=f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def _render_str(text: str, ctx: dict[str, Any], *, path: str) -> Any:
    """渲染一个字符串值。

    ★ **整串占位符保类型**：`"{load_level}"` → `1.1`（float），不是 `"1.1"`。
      理由：工具参数大多是数值型；若一律转成字符串，契约 3 会把 `1.1` 判成
      类型不符而拒发 —— 那不是参数错，是渲染层把类型弄丢了。

    ★ **未知占位符必须报错**（不静默留下 `{xxx}`）：
      留在参数里的 `{xxx}` 会被当成字面量发给引擎，
      得到一个"跑成功了但根本没生效"的结果 —— 正是契约 3 要防的形态。
    """
    whole = _WHOLE_PLACEHOLDER_RE.match(text)
    if whole is not None:
        name = whole.group(1)
        if name not in ctx:
            raise ExperimentError(
                f"`args` 模板的 `{path}` 引用了未定义的占位符 `{{{name}}}` —— "
                f"可用：{sorted(ctx)}（因子名 + 内置 {list(BUILTIN_PLACEHOLDERS)}）"
            )
        return ctx[name]

    if "{" not in text:
        return text
    try:
        return text.format_map(ctx)
    except KeyError as exc:
        raise ExperimentError(
            f"`args` 模板的 `{path}` 引用了未定义的占位符 `{{{exc.args[0]}}}` —— "
            f"可用：{sorted(ctx)}"
        ) from exc
    except (ValueError, IndexError) as exc:
        raise ExperimentError(
            f"`args` 模板的 `{path}` 含不合法的占位符写法（{text!r}）：{exc}。"
            "单个 `{` 需写成 `{{`，位置参数（`{}`）不受支持。"
        ) from exc


def render_args(template: dict[str, Any], bindings: dict[str, Any],
                *, case_path: str, case_id: str) -> dict[str, Any]:
    """把 args 模板 + 因子绑定 渲染成**实际参数**。"""
    ctx: dict[str, Any] = {"case_path": case_path, "case_id": case_id}
    ctx.update(bindings)
    rendered = _render_value(template, ctx, path="args")
    if not isinstance(rendered, dict):
        # 模板顶层被渲染成了非 dict（例如整串占位符指向一个 dict 值）
        raise ExperimentError(
            f"`args_template` 必须是对象，渲染后得到 {type(rendered).__name__}"
        )
    return rendered


# ------------------------------------------------------------------ cache_key


def cell_cache_key(*, case_sha256: str, steps: tuple[dict[str, Any], ...],
                   core_version: str = CORE_VERSION) -> str:
    """内容寻址键 —— `H(算例 sha256 + steps 规范化序列 + core_version)`。

    ★ `sort_keys=True` 让**键序**不参与身份：两次提交参数相同、键序不同，
      必须视为同一格（否则重跑会得到"新结果"，复现性无从谈起）。
    ★ 但**步骤顺序参与身份**：`[load, run]` 与 `[run, load]` 是不同实验
      （前者能跑通，后者会因"未加载网络"失败），必须算出不同的 key。
    ⚠️ 不含引擎版本 / IR 版本（模块 docstring 第 2 点：无可靠来源，不假装有）。
    """
    blob = json.dumps(
        {
            "case_sha256": case_sha256,
            "steps": list(steps),
            "core_version": core_version,
        },
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


# ------------------------------------------------------------------ 网格展开


def _product(values: tuple[tuple[Any, ...], ...]) -> list[tuple[Any, ...]]:
    """显式实现的笛卡尔积 —— 不引 `itertools` 是为了让**顺序**在代码里一眼可见。

    ★ 顺序必须稳定：结果表行序 = 网格序，重跑必须得到同样的行序（可复现）。
    """
    combos: list[tuple[Any, ...]] = [()]
    for axis in values:
        combos = [c + (v,) for c in combos for v in axis]
    return combos


def expand(exp: Experiment, *, sha_by_case: dict[str, str],
           path_by_case: dict[str, str]) -> tuple[Cell, ...]:
    """把实验展开为格子序列（**算例在外、因子按声明序**）。"""
    names = tuple(f.name for f in exp.factors)
    axes = tuple(f.values for f in exp.factors)
    cells: list[Cell] = []
    idx = 0
    for case_id in exp.case_ids:
        case_sha = sha_by_case.get(case_id, "")
        case_path = path_by_case.get(case_id, "")
        for combo in _product(axes):
            bindings = dict(zip(names, combo))
            rendered = tuple(
                {
                    "server": s.server,
                    "tool": s.tool,
                    "args": render_args(s.args_template, bindings,
                                        case_path=case_path, case_id=case_id),
                }
                for s in exp.steps
            )
            cells.append(Cell(
                index=idx,
                case_id=case_id,
                case_sha256=case_sha,
                bindings=bindings,
                steps=rendered,
                cache_key=cell_cache_key(case_sha256=case_sha, steps=rendered),
            ))
            idx += 1
    return tuple(cells)


def grid_size(exp: Experiment) -> int:
    """网格格数（**不渲染参数** —— 用于超限检查，避免为超限请求白跑一遍渲染）。"""
    total = len(exp.case_ids)
    for f in exp.factors:
        total *= len(f.values)
    return total


def unreferenced_factors(exp: Experiment) -> tuple[str, ...]:
    """找出**未被任何步骤的 `args_template` 引用**的因子名。

    ★ 为什么值得报出来（真实网关 e2e 实测）：因子不参与渲染 ⇒ 各格 `args` 相同
      ⇒ **`cache_key` 相同** ⇒ 网格里出现**内容完全相同的重复格**。
      实测：`factors=[lv=1.0,1.1]` 而模板里没写 `{lv}` → 两格 `cache_key` 逐位相同，
      "2 格都成功"看起来正常，**实际只有一种实验条件被跑过**。
      ⇒ 不报就是静默的重复劳动 + 误导性的"格数"。
    """
    used: set[str] = set()
    for step in exp.steps:
        blob = json.dumps(step.args_template, ensure_ascii=False, default=str)
        used.update(_ANY_PLACEHOLDER_RE.findall(blob))
    return tuple(f.name for f in exp.factors if f.name not in used)


# ------------------------------------------------------------------ 存储


class ExperimentStore:
    """实验索引的读写。

    ⚠️ **非并发安全**：单进程本地使用（与 `CaseStore` 同一口径）。
      写用「临时文件 + `os.replace`」保证不会留下半截 JSON，但不处理多进程同时写。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    @property
    def index_path(self) -> Path:
        return self._root / INDEX_NAME

    def _load(self) -> list[dict]:
        path = self.index_path
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentIndexError(
                f"实验索引损坏，无法解析 {path}：{exc}"
            ) from exc
        if not isinstance(data, list):
            raise ExperimentIndexError(f"实验索引格式错误（应为数组）：{path}")
        return [d for d in data if isinstance(d, dict)]

    def _write(self, rows: list[dict]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.index_path)

    def list(self) -> tuple[Experiment, ...]:
        return tuple(_to_experiment(r) for r in self._load())

    def get(self, exp_id: str) -> Experiment:
        for row in self._load():
            if row.get("id") == exp_id:
                return _to_experiment(row)
        raise KeyError(exp_id)

    def cells(self, exp: Experiment, *, cfg: Any) -> tuple[Cell, ...]:
        """按**当前**算例状态重算格子。

        ★ **不读存下来的 args**：网格是定义的**函数**，不是快照。
          存 args 会让"改了模板但没重跑"的旧格子继续冒充当前定义 —— 静默错配。
        ⚠️ 算例哈希**现算**：源文件改了，同一格会算出新的 `cache_key`
          （旧结果即成为陈旧，这正是要的效果）。
        """
        store = CaseStore(cases_root(cfg))
        sha_by_case: dict[str, str] = {}
        path_by_case: dict[str, str] = {}
        for cid in exp.case_ids:
            case = store.get(cid)
            view = store.view(case)
            sha_by_case[cid] = view.current_sha256 or case.sha256
            path_by_case[cid] = case.source_path
        return expand(exp, sha_by_case=sha_by_case, path_by_case=path_by_case)

    def create(self, exp: Experiment) -> Experiment:
        """登记一个实验（**只存定义，不存格子** —— 见 `cells()` 的说明）。"""
        # ★ §11.2 措施 2/3：读-改-写整体在锁内（只锁 `_write` 挡不住丢更新）。
        with file_write_lock(self.index_path):
            rows = self._load()
            if any(r.get("id") == exp.id for r in rows):
                raise ExperimentError(f"实验 id 已存在：{exp.id}")
            rows.append(exp.to_dict())
            self._write(rows)
        return exp

    def delete(self, exp_id: str) -> Experiment:
        """删除实验定义并返回被删除的实验；结果文件由 API 层一并清理。"""
        with file_write_lock(self.index_path):
            rows = self._load()
            for index, row in enumerate(rows):
                if row.get("id") == exp_id:
                    deleted = _to_experiment(row)
                    del rows[index]
                    self._write(rows)
                    return deleted
        raise KeyError(exp_id)


# ------------------------------------------------------------------ 执行（P2-①b）


#: 执行记录文件名。按 `cache_key` 索引，**不按格子序号**。
RESULTS_NAME = "results.json"


@dataclass(frozen=True)
class StepOutcome:
    """一步的执行结果 —— 由调用方注入，让执行循环能脱离 HTTP / MCP 单测。"""

    ok: bool
    error: str | None = None
    remounted: bool = False
    result_excerpt: Any = None


def results_root(cfg: Any, exp_id: str) -> Path:
    """某个实验的结果目录（与实验索引同级，**不在** `~/.powermcp/` 下）。"""
    return experiments_root(cfg) / exp_id


class ResultsStore:
    """按 `cache_key` 索引的执行结果。

    ★ **为什么键是 `cache_key` 而不是格子序号**：算例或模板一改，同一序号对应的
      已经不是同一个实验条件了。绑 `cache_key` 才能让旧结果**自动失配** ——
      而不是继续冒充当前条件的结果（静默错配，正是本项目最防的形态）。
    ⚠️ 与 `ExperimentStore` 同一口径：**非并发安全**，单进程本地使用。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._root / RESULTS_NAME

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExperimentIndexError(
                f"实验结果文件损坏，无法解析 {self.path}：{exc}"
            ) from exc
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def merge(self, records: tuple[dict, ...]) -> None:
        """把本轮执行记录并入结果库（**只覆盖本轮跑到的 `cache_key`**）。"""
        # ★ §11.2 措施 2/3：读-改-写整体在锁内 —— 否则两个并发 run 会互相覆盖
        #   （各自读到旧 data，后写的把先写的整片抹掉）。
        with file_write_lock(self.path):
            data = self._load()
            for rec in records:
                key = rec.get("cache_key")
                if isinstance(key, str) and key:
                    data[key] = rec
            self._write(data)

    def get(self, cache_key: str) -> dict | None:
        rec = self._load().get(cache_key)
        return rec if isinstance(rec, dict) else None

    def all(self) -> dict:
        return self._load()


async def execute_cells(
    cells: tuple[Cell, ...],
    *,
    new_session: Callable[[], str],
    run_step: Callable[[str, str, str, dict], Awaitable[StepOutcome]],
    ran_at: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[dict, ...]:
    """**串行**执行全部格子，返回逐格执行记录（落盘由调用方决定）。

    ★ **串行**（方案 §4.4 裁决：先串行跑通，再评估并发）。

    ★ **一格一个会话**：会话是引擎状态的边界。若跨格复用会话，某格 `load_network`
      失败后，下一格的 `run_*` 可能跑在**上一格残留的网络**上 —— 得到"跑成功、但结果
      是别家的"这种最危险的假绿灯。隔离的代价是每格重新挂载 server（秒级），
      对批量实验可接受：**宁可慢，不可错**。

    ★ **失败即停本格后续步骤**（但继续跑其他格）：后续步骤依赖前序步骤建立的引擎状态，
      继续跑只会产出无意义的结果，还会把"没加载网络"的失败伪装成业务失败。

    ★ **`remounted=True` 一律判该格失败**：重连意味着该 server 进程此前已死，
      **会话状态（如已加载的网络）无法担保**。宁可保守报失败，也不让
      "可能是空网络跑出来的结果"冒充成功（假绿灯）。

    ★ **§11.2 措施 2（租约锁）**：每步按 `(server, 算例键)` 取租约后才执行 ——
      保护的是"同一引擎上的同一算例"这份共享可变状态。当前**串行**执行下不会争用，
      它是**并发化时**才生效的接线（`proxy.call_tool` 另有 `(会话, server)` 租约，
      保护引擎实例；两者 key 不同、按固定顺序嵌套，不会死锁）。
    """
    started = ran_at or _now()
    records: list[dict] = []
    for cell in cells:
        if should_cancel is not None and should_cancel():
            records.append({
                "index": cell.index,
                "case_id": cell.case_id,
                "case_sha256": cell.case_sha256,
                "bindings": cell.bindings,
                "cache_key": cell.cache_key,
                "status": "cancelled",
                "steps": [],
                "ran_at": started,
            })
            continue
        sid = new_session()
        steps_out: list[dict] = []
        status = "ok"
        for i, step in enumerate(cell.steps):
            lease_key = f"case::{step['server']}::{case_key_of(step['args'])}"
            async with LEASES.hold(lease_key):
                outcome = await run_step(sid, step["server"], step["tool"], step["args"])
            rec: dict[str, Any] = {
                "index": i,
                "server": step["server"],
                "tool": step["tool"],
                "ok": bool(outcome.ok),
                "error": outcome.error,
                "remounted": bool(outcome.remounted),
            }
            if outcome.result_excerpt is not None:
                rec["result_excerpt"] = outcome.result_excerpt
            steps_out.append(rec)
            if not outcome.ok:
                status = "failed"
                break
            if outcome.remounted:
                status = "failed"
                rec["error"] = (
                    "连接断裂后重连执行（remounted）—— 该 server 进程此前已死，"
                    "会话状态（如已加载的网络）无法担保，故判本格失败；"
                    "请重跑本实验（若反复出现，需排查该 server 的稳定性）"
                )
                break
        records.append({
            "index": cell.index,
            "case_id": cell.case_id,
            "case_sha256": cell.case_sha256,
            "bindings": cell.bindings,
            "cache_key": cell.cache_key,
            "status": status,
            "steps": steps_out,
            "ran_at": started,
        })
    return tuple(records)


def status_counts(records: tuple[dict, ...]) -> dict[str, int]:
    """按 `status` 计数（空集返回 `{}` —— 空集 ≠ 全部正常）。"""
    out: dict[str, int] = {}
    for rec in records:
        key = str(rec.get("status", "unknown"))
        out[key] = out.get(key, 0) + 1
    return out


# ------------------------------------------------------------------ 结果表（P2-①c）

#: 指标扁平化时单个字符串值的长度上限（超长文本不是"可比指标"，只会撑爆表格）。
_METRIC_STR_MAX = 80

#: 单个格子的指标数量上限（防止引擎返回大对象时表格列爆炸）。
_METRIC_MAX_KEYS = 64

#: 指标键的命名空间前缀。
#: ★ **必须有**（真实网关 e2e 暴露）：引擎结果的内层 JSON 顶层就有 `status`
#:   （值 `"success"`），与结果表的保留列 `status`（格子执行状态）**撞名** ——
#:   实测列定义里出现了两个 `status`，前端/CSV 消费者按 key 取值必然取错一个。
#:   统一加前缀后，指标键与保留列（index/case_id/status/ran_at）**不可能再撞**。
_METRIC_PREFIX = "metric"


def extract_metrics(excerpt: Any, *, max_keys: int = _METRIC_MAX_KEYS) -> dict[str, Any]:
    """从结果摘要里抽出**可比较的标量指标**（扁平化，键用点号路径）。

    ★ 只取标量与**列表长度**：
      - 标量（数值 / 布尔 / 短字符串）可直接跨格比较；
      - 列表长度（如 `violations.count`）是**真实可核对**的量，不是派生猜测。
    ⚠️ **不发明派生量**（如"最大负载率"）—— 那是模块的语义，内核不该替它猜
      （与 ①a「不做语义因子」同一口径）。
    ⚠️ 超长字符串、非 JSON 形状、截断摘要一律**跳过**，并在调用方以 `notes` 说明。
    """
    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str) -> None:
        if len(out) >= max_keys:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(node, list):
            if prefix:
                out[f"{prefix}.count"] = len(node)
        elif isinstance(node, bool) or isinstance(node, (int, float)):
            if prefix:
                out[prefix] = node
        elif isinstance(node, str):
            if prefix and len(node) <= _METRIC_STR_MAX:
                out[prefix] = node

    if isinstance(excerpt, dict):
        if "__truncated__" in excerpt:
            return {}                      # 摘要被截断 → 不给半截指标（宁可空）
        if "__unserializable__" in excerpt:
            return {}
        inner = excerpt.get("inner", excerpt.get("raw", excerpt))
        walk(inner, _METRIC_PREFIX)        # ★ 加命名空间，避免与保留列撞名
    return out


def _metrics_from_record(rec: dict) -> tuple[dict[str, Any], bool]:
    """取某格执行记录里**最后一步**的结果摘要 → 指标。

    Returns:
        `(metrics, truncated)` —— 摘要被截断时 `metrics` 为空、`truncated=True`。
    """
    steps = rec.get("steps")
    if not isinstance(steps, list) or not steps:
        return {}, False
    last = steps[-1]
    if not isinstance(last, dict) or not last.get("ok"):
        return {}, False
    excerpt = last.get("result_excerpt")
    if not isinstance(excerpt, dict):
        return {}, False
    if "__truncated__" in excerpt:
        return {}, True
    return extract_metrics(excerpt), False


def _metric_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def build_results_report(exp: Experiment, cells: tuple[Cell, ...],
                         stored: dict[str, dict]) -> dict:
    """`GET /experiments/{eid}/results` 的响应体。

    ★ 结果**按 `cache_key` 与当前格子对齐**：算例或模板一改，格子会算出新 key，
      于是该格显示 `never_run`，而**旧 key 的记录成为 `orphaned`** ——
      这正是"陈旧结果不会冒充当前条件"的可观测形态（不静默、也不丢弃）。
    ★ 列由**各格指标的并集**决定（按名排序），保证跨格可比较且顺序稳定。
    """
    current = {c.cache_key for c in cells}
    orphaned = sorted(k for k in stored if k not in current)

    rows: list[dict] = []
    col_seen: dict[str, str] = {}
    truncated_cells: list[int] = []
    for cell in cells:
        rec = stored.get(cell.cache_key)
        metrics: dict[str, Any] = {}
        if isinstance(rec, dict):
            metrics, truncated = _metrics_from_record(rec)
            if truncated:
                truncated_cells.append(cell.index)
        for key, value in metrics.items():
            col_seen.setdefault(key, _metric_type(value))
        rows.append({
            "index": cell.index,
            "case_id": cell.case_id,
            "bindings": cell.bindings,
            "cache_key": cell.cache_key,
            "status": (rec.get("status") if isinstance(rec, dict) else "never_run"),
            "ran_at": (rec.get("ran_at") if isinstance(rec, dict) else None),
            "steps": (rec.get("steps") if isinstance(rec, dict) else None),
            "metrics": metrics,
        })

    columns = [
        {"key": "index", "title": "格", "type": "number"},
        {"key": "case_id", "title": "算例", "type": "text"},
        {"key": "status", "title": "状态", "type": "state"},
        {"key": "ran_at", "title": "执行时间", "type": "text"},
    ]
    columns += [{"key": k, "title": k, "type": col_seen[k]} for k in sorted(col_seen)]

    by_status: dict[str, int] = {}
    for row in rows:
        by_status[str(row["status"])] = by_status.get(str(row["status"]), 0) + 1

    notes = [
        "结果按 `cache_key` 与当前格子对齐：算例/模板一改，该格即显示 `never_run`，"
        "旧记录进入 `orphaned`（**不冒充当前条件**，也不被丢弃）。",
        "指标由各格**最后一步**的结果摘要扁平化而来（点号路径），只含标量与列表长度；"
        "**不发明派生量**（如「最大负载率」是模块语义，内核不猜）。",
        "⚠️ 本表是**格级对比**。越限明细级的 `result_tables` 透视（模块清单的列定义 / G-2 pivot）"
        "属 P3 面，本步未实现 —— 不给「看起来像有、实际没映射」的假表。",
    ]
    if truncated_cells:
        notes.append(
            f"⚠️ 格 {truncated_cells} 的结果摘要超限被截断，故**未给出指标**"
            "（宁可空，也不给半截数据）。"
        )
    if orphaned:
        notes.append(
            f"⚠️ 有 {len(orphaned)} 条结果记录不对应任何当前格子（`orphaned`）—— "
            "通常是算例或模板改过；它们属于旧条件，不可与当前结果并列比较。"
        )

    return {
        "experiment": exp.to_dict(),
        "columns": columns,
        "rows": rows,
        "summary": {
            "cells": len(rows),
            "by_status": by_status,
            "orphaned": len(orphaned),
        },
        "orphaned_keys": orphaned,
        "notes": notes,
    }


#: 导出格式 → (媒体类型, 扩展名)
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "md": ("text/markdown; charset=utf-8", "md"),
}


def export_table(report: dict, fmt: str) -> str:
    """把 `build_results_report` 的表导成 CSV / Markdown。

    ★ 只做**文本格式**：PDF 需走 HTML + Chrome headless（本项目禁用 pandoc），
      不在网关进程里做（那是渲染层的事）。
    """
    if fmt not in EXPORT_FORMATS:
        raise ExperimentError(
            f"不支持的导出格式 {fmt!r} —— 可用：{sorted(EXPORT_FORMATS)}"
        )

    columns = report["columns"]
    metric_cols = [c["key"] for c in columns if c["key"] not in
                   ("index", "case_id", "status", "ran_at")]
    header = ["index", "case_id", "status", "ran_at", "cache_key"] + metric_cols
    body: list[list[str]] = []
    for row in report["rows"]:
        bindings = row.get("bindings") or {}
        # 因子绑定列在 CSV 里单列出来（结果表要能按因子分组）
        line = [
            str(row["index"]),
            str(row["case_id"]),
            str(row["status"]),
            str(row["ran_at"] or ""),
            str(row["cache_key"]),
        ]
        metrics = row.get("metrics") or {}
        line += [_cell_text(metrics.get(k)) for k in metric_cols]
        body.append(line)
    binding_cols = sorted({k for row in report["rows"] for k in (row.get("bindings") or {})})

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(header + [f"factor.{k}" for k in binding_cols])
        for row, line in zip(report["rows"], body):
            bindings = row.get("bindings") or {}
            writer.writerow(line + [_cell_text(bindings.get(k)) for k in binding_cols])
        return buf.getvalue()

    # Markdown
    md_header = header + [f"factor.{k}" for k in binding_cols]
    lines = ["| " + " | ".join(md_header) + " |",
             "| " + " | ".join("---" for _ in md_header) + " |"]
    for row, line in zip(report["rows"], body):
        bindings = row.get("bindings") or {}
        cells_txt = line + [_cell_text(bindings.get(k)) for k in binding_cols]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells_txt) + " |")
    return "\n".join(lines) + "\n"


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ------------------------------------------------------------------ 请求解析


def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) and not isinstance(v, type(None))


def _parse_factors(raw: Any) -> tuple[tuple[Factor, ...], str | None]:
    if raw is None:
        return (), None
    if not isinstance(raw, list):
        return (), "`factors` 必须是数组（每项形如 {\"name\": ..., \"values\": [...]}）"

    seen: set[str] = set()
    factors: list[Factor] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return (), f"`factors[{i}]` 必须是对象"
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            return (), f"`factors[{i}].name` 必须是非空字符串"
        name = name.strip()
        if not _FACTOR_NAME_RE.match(name):
            return (), (
                f"`factors[{i}].name` = {name!r} 不是合法标识符 —— "
                "模板里要写成 `{name}`，须以字母或下划线开头且只含字母/数字/下划线"
            )
        if name in BUILTIN_PLACEHOLDERS:
            return (), (
                f"`factors[{i}].name` = {name!r} 是内置占位符 —— "
                f"内置名为 {list(BUILTIN_PLACEHOLDERS)}，因子不得与之同名"
                "（同名会静默覆盖内置值）"
            )
        if name in seen:
            return (), f"`factors[{i}].name` = {name!r} 重复（同一实验内因子名须唯一）"
        seen.add(name)

        values = item.get("values")
        if not isinstance(values, list) or not values:
            return (), f"`factors[{i}].values` 必须是非空数组"
        bad = [v for v in values if not _is_scalar(v)]
        if bad:
            return (), (
                f"`factors[{i}].values` 只能是标量（str/int/float/bool）—— "
                f"发现 {len(bad)} 个非标量值；因子要参与 cache_key 与结果表分组，不接受容器"
            )
        if len(set(map(str, values))) != len(values):
            return (), (
                f"`factors[{i}].values` 含重复取值 —— 会产生重复格子（{values}）"
            )
        factors.append(Factor(name=name, values=tuple(values)))
    return tuple(factors), None


def _parse_steps(raw: Any, *, known_servers: tuple[str, ...]) -> tuple[tuple[Step, ...], str | None]:
    """解析并校验 `steps` 数组（**至少一步**）。

    ★ 强制**全部步骤同 server**：一次实验的执行发生在**一个 server 会话**里
      （有状态序列的前提：`load_network` 装进的那个进程，必须就是下一步跑分析的那个）。
      跨 server 的步骤需要多个会话，且语义不成立 —— 上一步的引擎状态对另一个 server
      没有意义。⇒ 直接拒，不静默接受。
    """
    if raw is None:
        return (), (
            "缺少 `steps`（形如 "
            "[{\"server\": ..., \"tool\": ..., \"args_template\": {...}}, ...]，至少一步）"
        )
    if not isinstance(raw, list) or not raw:
        return (), "`steps` 必须是**非空**数组（至少一步；每步 `server` / `tool` 必填）"

    steps: list[Step] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return (), f"`steps[{i}]` 必须是对象"
        server = item.get("server")
        if not isinstance(server, str) or not server.strip():
            return (), f"缺少非空 `steps[{i}].server`"
        server = server.strip().lower()
        if server not in known_servers:
            return (), (
                f"`steps[{i}].server` = {server!r} 不是本网关会挂载的 server —— "
                f"可用：{list(known_servers)}"
            )
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            return (), f"缺少非空 `steps[{i}].tool`"
        template = item.get("args_template", {})
        if not isinstance(template, dict):
            return (), f"`steps[{i}].args_template` 必须是对象"
        steps.append(Step(server=server, tool=tool.strip(), args_template=template))

    servers = sorted({s.server for s in steps})
    if len(servers) > 1:
        return (), (
            f"`steps` 的全部步骤必须属于**同一个 server**（本实验跨了 {servers}）—— "
            "一次实验在**一个 server 会话**内按序执行（有状态序列的前提："
            "`load_network` 装进的进程必须就是下一步跑分析的那个）。"
            "需要跨引擎请拆成多个实验。"
        )
    return tuple(steps), None


def parse_experiment_request(payload: Any, *, known_servers: tuple[str, ...],
                             store: "ExperimentStore | None" = None,
                             cfg: Any = None,
                             exp_id: str | None = None) -> tuple[Experiment | None, str | None]:
    """校验并构造一个 `Experiment`。

    Returns:
        `(experiment, error)` —— 出错时前者为 `None`，`error` 是**可执行**的 400 文案。

    Raises:
        ExperimentCaseStateError: 算例已登记但**当前状态**不允许建实验
            （源文件不可读 / 不在路径围笼内）—— 端点须映射 409（可修复），不是 400。
        ExperimentIndexError: 算例索引损坏 —— 端点须映射 500。

    ★ 为什么在这里就把「算例存在且可读」查掉：实验的主语是算例，
      算例不存在时登记出来的实验**永远跑不了**，而错误会推迟到执行期才暴露 ——
      那时用户看到的是几百格里每一格都失败，而不是一句"这个算例没登记"。
    """
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"

    raw_ids = payload.get("case_ids")
    if raw_ids is None:
        one = payload.get("case_id")
        raw_ids = [one] if one is not None else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, "缺少非空 `case_ids`（字符串数组；也接受单个 `case_id`）"
    if not all(isinstance(c, str) and c.strip() for c in raw_ids):
        return None, "`case_ids` 必须是非空字符串的数组"
    case_ids = tuple(dict.fromkeys(c.strip() for c in raw_ids))

    label = payload.get("label")
    if label is not None and not isinstance(label, str):
        return None, "`label` 必须是字符串或 null"
    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        return None, "`notes` 必须是字符串"

    steps, err = _parse_steps(payload.get("steps"), known_servers=known_servers)
    if err:
        return None, err

    factors, err = _parse_factors(payload.get("factors"))
    if err:
        return None, err

    exp = Experiment(
        id=exp_id or "",
        label=(label or "").strip() or f"{steps[0].server}." + "+".join(s.tool for s in steps),
        created_at=_now(),
        case_ids=case_ids,
        factors=factors,
        steps=steps,
        notes=notes,
    )

    # 算例必须已登记且**可读**（不可读 → 实验永远跑不了，错误不该推迟到执行期）
    if store is not None and cfg is not None:
        case_store = CaseStore(cases_root(cfg))
        for cid in case_ids:
            try:
                case = case_store.get(cid)
            except KeyError:
                return None, (
                    f"`case_ids` 里的 {cid!r} 未登记 —— 先 `POST /cases` 登记该算例"
                    "（算例是实验的主语，不登记的实验永远无法执行）"
                )
            view = case_store.view(case)
            if not view.available:
                raise ExperimentCaseStateError(
                    f"算例 {cid}（{case.source_path}）当前不可读 —— "
                    "先恢复该文件，或重新登记后再建实验"
                )
            if not view.within_allowed_roots:
                raise ExperimentCaseStateError(
                    f"算例 {cid} 不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 —— server 子进程读不到它，"
                    f"请把 `{Path(case.source_path).parent}` 加入该变量后重启网关"
                    "（见 `GET /environment` 的 `server_env` 段）"
                )

    size = grid_size(exp)
    if size > MAX_CELLS:
        return None, (
            f"网格展开为 {size} 格，超过上限 {MAX_CELLS} —— "
            "请缩小 `case_ids` 或某个因子的取值个数"
            f"（当前：{len(case_ids)} 算例 × "
            + " × ".join(str(len(f.values)) for f in factors)
            + "）"
        )
    if size == 0:
        return None, "网格展开为 0 格（检查 `case_ids` 与 `factors`）"

    # ★ 渲染一遍全部格子再落盘：模板错误必须在**登记时**暴露，
    #   而不是等到执行期让每一格各报一次同样的错。
    try:
        _ = expand(exp, sha_by_case={c: "" for c in case_ids},
                   path_by_case={c: "" for c in case_ids})
    except ExperimentError as exc:
        return None, str(exc)

    return exp, None


def derive_experiment_id(exp: Experiment) -> str:
    """由**定义内容**派生稳定 id —— 同一定义重复提交即为同一实验。"""
    blob = json.dumps(
        {
            "case_ids": sorted(exp.case_ids),
            "factors": [{"name": f.name, "values": list(f.values)} for f in exp.factors],
            "steps": [s.to_dict() for s in exp.steps],
        },
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _to_experiment(row: dict) -> Experiment:
    """把索引行转成 `Experiment`。**容忍缺字段**，但不静默丢 id / steps。"""
    factors: list[Factor] = []
    for item in row.get("factors") or ():
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            values = item.get("values") or ()
            factors.append(Factor(
                name=name,
                values=tuple(values) if isinstance(values, (list, tuple)) else (),
            ))
    steps: list[Step] = []
    for item in row.get("steps") or ():
        if isinstance(item, dict):
            steps.append(Step(
                server=str(item.get("server", "")),
                tool=str(item.get("tool", "")),
                args_template=(
                    item.get("args_template")
                    if isinstance(item.get("args_template"), dict) else {}
                ),
            ))
    return Experiment(
        id=str(row.get("id", "")),
        label=str(row.get("label", "")),
        created_at=str(row.get("created_at", "")),
        case_ids=tuple(str(c) for c in (row.get("case_ids") or ())),
        factors=tuple(factors),
        steps=tuple(steps),
        notes=str(row.get("notes", "")),
    )


def build_report(cfg: Any, store: ExperimentStore) -> dict:
    """`GET /experiments` 的响应体。"""
    exps = store.list()
    total_cells = 0
    items = []
    for exp in exps:
        try:
            cells = store.cells(exp, cfg=cfg)
        except KeyError:
            # 引用的算例已被注销 —— **不静默跳过**，如实报出
            cells = ()
            items.append({
                **exp.to_dict(),
                "cell_count": 0,
                "error": "引用的算例已被注销，无法展开网格",
            })
            continue
        total_cells += len(cells)
        items.append({**exp.to_dict(), "cell_count": len(cells)})
    return {
        "root": str(store.root),
        "index_exists": store.index_path.is_file(),
        "summary": {
            "total": len(exps),
            "cells": total_cells,
        },
        "experiments": items,
        "notes": [
            "本端点只做**定义与登记**（展开成「要跑什么」+ `cache_key`）；"
            "执行是 `POST /experiments/{eid}/run`，结果表是 `GET /experiments/{eid}/results`。",
            "`cache_key` = H(算例当前 sha256 + steps 规范化序列 + core_version)；"
            "**不含引擎版本与 IR 版本**（网关当前无可靠来源，不假装有）。"
            "算例源文件一改，同一格会算出新的 key —— 旧结果即为陈旧。",
            f"网格上限 {MAX_CELLS} 格/实验。",
            "⚠️ 登记时**不校验** `steps[].tool` 是否真的存在于该 server —— 校验需真实拉起"
            " server 子进程（秒级），与「一个登记请求应当廉价」冲突。"
            "错误会在执行期由**契约 3 的 fail-closed** 逐格报出，而不是静默放行。",
        ],
    }
