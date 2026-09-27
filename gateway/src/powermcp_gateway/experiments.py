"""实验矩阵 —— `experiment` 这一级实体（方案 v4 §4.4）。

★ 为什么它是判据 #2 / #3 的落点（方案 §12）：
  - #2「能组织研究」= 同一算例的多组实验挂在同一个 case 下、结果可对比；
  - #3「能批量跑」  = 网格（算例 × 因子）一次提交并拿到结果表。
  两条都要求「实验」是**一等对象**，而不是会话里一串散落的 `tool_call`。

★ 本步（P2-①a）的**明确范围**：只做**定义与登记**。
    实验 = 算例集合 × 因子网格 × 一个工具步骤（server / tool / args 模板）；
    展开出的每一格（cell）只算到「要跑什么」（`args` + `cache_key`），**不执行**。
  执行（逐格 `proxy.call_tool` + 逐格状态与失败可见）是 P2-①b。
  ⇒ 为什么先切这一刀：执行器必须先回答「模板参数是否真的被该引擎接受」，
    而定义层不需要回答它。分开做，定义层能用真实网格先验证，
    执行层则可以只用契约 3 的 fail-closed 兜底。

★ 三个关键设计决定（都可复核）：

  1. **一格 = 一次显式声明的工具调用**（`server` + `tool` + `args` 模板），
     **因子只是标签维度**（用于结果表分列与分组），不隐含任何物理语义。
     ★ 为什么不做「负荷水平」这类**语义因子**：那要求某个引擎真的能按因子缩放负荷，
       而**这一点本步未核实**（未逐参数核对 server 工具面）。
       把「负荷水平怎么施加」编码进网关 = 替引擎声称一个未验证的能力 ——
       正是契约层反复否掉的「静默假声明」。
       声明式模板把选择权交回声明者；参数对不对由**契约 3 在调用前 fail-closed** 兜住。

  2. **`cache_key` 只由可确证的量构成**（对齐方案 §4.4 的口径，并如实缩水）：
       `H(算例当前 sha256 + server + tool + 规范化 args + core_version)`
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

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import CaseStore, cases_root
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
class Cell:
    """网格里的一格 —— 一次**已绑定参数**的工具调用。

    - `bindings`：该格的因子取值（结果表分列用）
    - `args`：模板渲染后的**实际参数**（将原样交给 `proxy.call_tool`）
    - `case_sha256`：**登记时现算**的算例哈希 —— 源文件一改，旧格即为陈旧
    - `cache_key`：内容寻址键（见模块 docstring 第 2 点）
    - `status`：本步只有 `pending`（执行是 ①b，不预先声称进度）
    """

    index: int
    case_id: str
    case_sha256: str
    bindings: dict[str, Any] = field(default_factory=dict)
    args: dict[str, Any] = field(default_factory=dict)
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
    server: str
    tool: str
    args_template: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

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


def cell_cache_key(*, case_sha256: str, server: str, tool: str,
                   args: dict[str, Any], core_version: str = CORE_VERSION) -> str:
    """内容寻址键 —— `H(算例 sha256 + server + tool + 规范化 args + core_version)`。

    ★ `sort_keys=True` 让**键序**不参与身份：两次提交参数相同、键序不同，
      必须视为同一格（否则重跑会得到"新结果"，复现性无从谈起）。
    ⚠️ 不含引擎版本 / IR 版本（模块 docstring 第 2 点：无可靠来源，不假装有）。
    """
    blob = json.dumps(
        {
            "case_sha256": case_sha256,
            "server": server,
            "tool": tool,
            "args": args,
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
            args = render_args(exp.args_template, bindings,
                               case_path=case_path, case_id=case_id)
            cells.append(Cell(
                index=idx,
                case_id=case_id,
                case_sha256=case_sha,
                bindings=bindings,
                args=args,
                cache_key=cell_cache_key(
                    case_sha256=case_sha, server=exp.server,
                    tool=exp.tool, args=args,
                ),
            ))
            idx += 1
    return tuple(cells)


def grid_size(exp: Experiment) -> int:
    """网格格数（**不渲染参数** —— 用于超限检查，避免为超限请求白跑一遍渲染）。"""
    total = len(exp.case_ids)
    for f in exp.factors:
        total *= len(f.values)
    return total


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
        rows = self._load()
        if any(r.get("id") == exp.id for r in rows):
            raise ExperimentError(f"实验 id 已存在：{exp.id}")
        rows.append(exp.to_dict())
        self._write(rows)
        return exp


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

    step = payload.get("step")
    if not isinstance(step, dict):
        return None, "缺少 `step`（形如 {\"server\": ..., \"tool\": ..., \"args_template\": {...}}）"
    server = step.get("server")
    if not isinstance(server, str) or not server.strip():
        return None, "缺少非空 `step.server`"
    server = server.strip().lower()
    if server not in known_servers:
        return None, (
            f"`step.server` = {server!r} 不是本网关会挂载的 server —— "
            f"可用：{list(known_servers)}"
        )
    tool = step.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return None, "缺少非空 `step.tool`"
    template = step.get("args_template", {})
    if not isinstance(template, dict):
        return None, "`step.args_template` 必须是对象"
    tool = tool.strip()

    factors, err = _parse_factors(payload.get("factors"))
    if err:
        return None, err

    exp = Experiment(
        id=exp_id or "",
        label=(label or "").strip() or f"{server}.{tool}",
        created_at=_now(),
        case_ids=case_ids,
        factors=factors,
        server=server,
        tool=tool,
        args_template=template,
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
            "server": exp.server,
            "tool": exp.tool,
            "args_template": exp.args_template,
        },
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _to_experiment(row: dict) -> Experiment:
    """把索引行转成 `Experiment`。**容忍缺字段**，但不静默丢 id / server / tool。"""
    factors: list[Factor] = []
    for item in row.get("factors") or ():
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            values = item.get("values") or ()
            factors.append(Factor(
                name=name,
                values=tuple(values) if isinstance(values, (list, tuple)) else (),
            ))
    return Experiment(
        id=str(row.get("id", "")),
        label=str(row.get("label", "")),
        created_at=str(row.get("created_at", "")),
        case_ids=tuple(str(c) for c in (row.get("case_ids") or ())),
        factors=tuple(factors),
        server=str(row.get("server", "")),
        tool=str(row.get("tool", "")),
        args_template=row.get("args_template") if isinstance(row.get("args_template"), dict) else {},
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
            "本步（P2-①a）只做**定义与登记**：端点返回的是「要跑什么」，**尚不执行**；"
            "执行与逐格状态是 P2-①b。",
            "`cache_key` = H(算例当前 sha256 + server + tool + 规范化 args + core_version)；"
            "**不含引擎版本与 IR 版本**（网关当前无可靠来源，不假装有）。"
            "算例源文件一改，同一格会算出新的 key —— 旧结果即为陈旧。",
            f"网格上限 {MAX_CELLS} 格/实验。",
            "⚠️ 登记时**不校验** `step.tool` 是否真的存在于该 server —— 校验需真实拉起"
            " server 子进程（秒级），与「一个登记请求应当廉价」冲突。"
            "错误会在执行期由**契约 3 的 fail-closed** 逐格报出，而不是静默放行。",
        ],
    }
