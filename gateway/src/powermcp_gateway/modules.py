"""选题模块的清单解析、装配与脚手架（方案 v4 §六 / 模块化架构）。

★ 为什么需要：v4 的定位是「通用研究工作台」，**一个选题 = 一个可插拔模块**。
  内核必须稳定、且**不含任何领域知识**；模块通过声明式清单接入。

★★ **本模块的自证条件**：**禁用全部模块后内核仍可用**。
  若禁用模块内核就不可用，说明内核被领域知识污染了 ——
  这是把「内核稳定」从口号变成**可检验判据**的方式（见 `tests/test_modules.py`
  与 `tests/test_api_modules.py` 的自证测试）。

★ 校验的**两条不同尺度**（有意区分，不混为一谈）：

  | 对象 | 尺度 | 理由 |
  |---|---|---|
  | 清单**自己指向**的文件（schema / prompt / template） | **装配失败** | 清单说了它存在，不存在就是清单错 |
  | **外部系统**里的名字（server / skill id） | **警告** | 外部可能后补；且我们无权替上游断言 |

★ fail-loud：单个模块装配失败**只标记它自己**，不影响其他模块与内核。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import GatewayConfig

logger = logging.getLogger(__name__)

#: 覆盖模块根目录（与 `environment.ENV_MODULES_ROOT` 同名同义）
ENV_MODULES_ROOT = "POWERMCP_MODULES_ROOT"

MANIFEST_NAME = "module.yaml"

#: 网关自身版本 —— `requires.core` 与它比较
CORE_VERSION = "0.1.0"

KIND_RESEARCH = "research"
KIND_ENGINEERING = "engineering"
KINDS = (KIND_RESEARCH, KIND_ENGINEERING)

MATURITY_LEVELS = ("L0", "L1", "L2")

#: 清单中「指向本项目内文件」的字段 → 该文件必须存在
_FILE_REF_FIELDS = ("schema", "columns", "file", "template")

_VERSION_RE = re.compile(r"^\s*(>=|==|<=|>|<)?\s*(\d+(?:\.\d+)*)\s*$")


class ModuleError(RuntimeError):
    """清单非法 —— 该模块装配失败（映射到 `ModuleFailure`，不外抛）。"""


@dataclass(frozen=True)
class Declaration:
    """一条声明（entity / result_table / prompt / check / export / slot）。"""

    id: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    version: str
    kind: str
    maturity: str
    enabled: bool
    path: str                          # 相对模块根的 POSIX 路径
    servers: tuple[str, ...] = ()
    solvers: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    entities: tuple[Declaration, ...] = ()
    result_tables: tuple[Declaration, ...] = ()
    prompts: tuple[Declaration, ...] = ()
    checks: tuple[Declaration, ...] = ()
    exports: tuple[Declaration, ...] = ()
    slots: tuple[Declaration, ...] = ()

    @property
    def declarations(self) -> tuple[Declaration, ...]:
        return (self.entities + self.result_tables + self.prompts
                + self.checks + self.exports + self.slots)


@dataclass(frozen=True)
class ModuleFailure:
    module_id: str
    path: str
    error: str


@dataclass(frozen=True)
class AssemblyReport:
    root: str
    root_exists: bool
    modules: tuple[Module, ...]
    failures: tuple[ModuleFailure, ...]
    notes: tuple[str, ...]
    effective: dict[str, list[str]]


def modules_root(cfg: GatewayConfig) -> Path:
    """模块根目录（默认 `PowerMCP` 的兄弟目录 `modules/`）。"""
    override = os.environ.get(ENV_MODULES_ROOT)
    if override:
        return Path(override)
    return cfg.powermcp_root.parent / "modules"


# ---------------------------------------------------------------- 版本比较


def _parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in str(text).split(".") if p != "")


def satisfies(version: str, spec: str | None) -> bool:
    """极简版本判定：支持 `>=` / `==` / `<=` / `>` / `<`，缺省视为 `>=`。

    ★ 刻意**不引入 packaging**：清单里的 `requires.core` 只需要表达
      "不早于某个版本"，为此加一个依赖不划算。无法解析的 spec 一律视为**不满足**
      （fail-loud，而不是默认放行）。
    """
    if spec is None or str(spec).strip() == "":
        return True
    m = _VERSION_RE.match(str(spec))
    if m is None:
        return False
    op, want = m.group(1) or ">=", _parse_version(m.group(2))
    have = _parse_version(version)
    n = max(len(have), len(want))
    have += (0,) * (n - len(have))
    want += (0,) * (n - len(want))
    return {
        ">=": have >= want, "==": have == want, "<=": have <= want,
        ">": have > want, "<": have < want,
    }[op]


# ---------------------------------------------------------------- 清单解析


def _as_str_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        # 单值写法容错：`tools: surge.run_power_flow`
        return (value,)
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ModuleError(f"`{where}` 必须是字符串或字符串数组")


def _declarations(value: Any, where: str) -> tuple[Declaration, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ModuleError(f"`{where}` 必须是数组")
    out: list[Declaration] = []
    seen: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ModuleError(f"`{where}[{i}]` 必须是对象")
        did = item.get("id")
        if not isinstance(did, str) or not did.strip():
            raise ModuleError(f"`{where}[{i}]` 缺少非空 `id`")
        did = did.strip()
        if did in seen:
            raise ModuleError(f"`{where}` 中 id 重复：{did}")
        seen.add(did)
        out.append(Declaration(id=did, detail={k: v for k, v in item.items() if k != "id"}))
    return tuple(out)


def _check_file_refs(base: Path, declarations: tuple[Declaration, ...],
                     where: str) -> list[str]:
    """清单指向的文件必须存在（**装配失败**尺度）。返回缺失的相对路径列表。"""
    missing: list[str] = []
    for decl in declarations:
        for fname in _FILE_REF_FIELDS:
            ref = decl.detail.get(fname)
            if not isinstance(ref, str) or not ref.strip():
                continue
            target = (base / ref).resolve()
            if not target.is_file():
                missing.append(f"{where}.{decl.id}.{fname} → {ref}")
    return missing


def parse_manifest(path: Path, *, core_version: str = CORE_VERSION) -> Module:
    """解析单个 `module.yaml`。

    Raises:
        ModuleError: 清单非法（含清单指向的文件不存在）。
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModuleError(f"清单无法解析：{exc}") from exc
    if not isinstance(raw, dict):
        raise ModuleError("清单根必须是映射（key: value）")

    mid = raw.get("id")
    if not isinstance(mid, str) or not mid.strip():
        # ★ 提示 YAML 的坑：`on` / `off` / `yes` / `no` 会被解析成**布尔值**，
        #   于是 `id: on` 拿到的是 `True` —— 报"缺少 id"而不说原因会让人查半天。
        raise ModuleError(
            f"缺少非空 `id`（实际拿到 {type(mid).__name__}: {mid!r}）—— "
            "注意 YAML 会把 `on` / `off` / `yes` / `no` 解析成布尔值，"
            "模块 id 请改用普通单词"
        )
    mid = mid.strip()
    if mid != path.parent.name:
        raise ModuleError(
            f"`id`（{mid}）必须与目录名（{path.parent.name}）一致 —— "
            "否则按 id 引用会与按路径引用产生歧义"
        )

    kind = raw.get("kind", KIND_RESEARCH)
    if kind not in KINDS:
        raise ModuleError(f"`kind` 必须是 {list(KINDS)} 之一，收到 {kind!r}")

    maturity = raw.get("maturity", "L0")
    if maturity not in MATURITY_LEVELS:
        raise ModuleError(f"`maturity` 必须是 {list(MATURITY_LEVELS)} 之一，收到 {maturity!r}")

    requires = raw.get("requires") or {}
    if not isinstance(requires, dict):
        raise ModuleError("`requires` 必须是映射")
    core_spec = requires.get("core")
    if core_spec is not None and not satisfies(core_version, str(core_spec)):
        raise ModuleError(
            f"要求 core {core_spec}，当前网关内核版本为 {core_version}"
        )

    entities = _declarations(raw.get("entities"), "entities")
    result_tables = _declarations(raw.get("result_tables"), "result_tables")
    prompts = _declarations(raw.get("prompts"), "prompts")
    checks = _declarations(raw.get("checks"), "checks")
    exports = _declarations(raw.get("exports"), "exports")
    slots = _declarations(raw.get("slots"), "slots")

    missing: list[str] = []
    for where, decls in (("entities", entities), ("result_tables", result_tables),
                         ("prompts", prompts), ("checks", checks), ("exports", exports)):
        missing += _check_file_refs(path.parent, decls, where)
    if missing:
        raise ModuleError("清单指向的文件不存在：" + "；".join(missing))

    return Module(
        id=mid,
        name=str(raw.get("name") or mid),
        version=str(raw.get("version") or "0.0.0"),
        kind=kind,
        maturity=maturity,
        enabled=bool(raw.get("enabled", True)),
        path=path.parent.name,
        servers=_as_str_list(requires.get("servers"), "requires.servers"),
        solvers=_as_str_list(requires.get("solvers"), "requires.solvers"),
        tools=_as_str_list(raw.get("tools"), "tools"),
        skills=_as_str_list(raw.get("skills"), "skills"),
        entities=entities,
        result_tables=result_tables,
        prompts=prompts,
        checks=checks,
        exports=exports,
        slots=slots,
    )


# ---------------------------------------------------------------- 装配


def load_modules(root: Path, *, known_servers: tuple[str, ...] = (),
                 known_skills: tuple[str, ...] = (),
                 core_version: str = CORE_VERSION) -> AssemblyReport:
    """扫描并装配全部模块。

    ★ **单个模块失败不影响其他模块与内核** —— 失败收进 `failures`，如实上报。
    ★ **跨模块声明同名 → 保留先出现的，后者记为失败**（不静默覆盖）。
    """
    notes: list[str] = []
    if not root.is_dir():
        return AssemblyReport(
            root=str(root), root_exists=False, modules=(), failures=(),
            notes=(
                f"模块根目录不存在：{root} —— 内核**不依赖任何模块**，此为正常状态"
                "（禁用全部模块后内核仍可用，是本架构的自证条件）。",
            ),
            effective={"tools": [], "skills": [], "servers": [], "solvers": []},
        )

    modules: list[Module] = []
    failures: list[ModuleFailure] = []
    claimed: dict[str, str] = {}          # 声明 id → 先占用的模块 id
    seen_ids: set[str] = set()

    for manifest in sorted(root.glob(f"*/{MANIFEST_NAME}")):
        rel = manifest.parent.name
        try:
            mod = parse_manifest(manifest, core_version=core_version)
        except ModuleError as exc:
            logger.warning("模块装配失败：%s（%s）", rel, exc)
            failures.append(ModuleFailure(module_id=rel, path=rel, error=str(exc)))
            continue

        if mod.id in seen_ids:
            msg = f"模块 id 重复：{mod.id}"
            failures.append(ModuleFailure(module_id=mod.id, path=rel, error=msg))
            continue
        seen_ids.add(mod.id)

        # 跨模块声明同名 → 禁止（不静默覆盖）
        clash = [d.id for d in mod.declarations if d.id in claimed]
        if clash:
            owner = claimed[clash[0]]
            msg = (
                f"声明 id 与模块 `{owner}` 冲突：{clash} —— "
                "同名声明会让按 id 引用产生歧义，故拒绝装配（不静默覆盖）"
            )
            failures.append(ModuleFailure(module_id=mod.id, path=rel, error=msg))
            continue
        for d in mod.declarations:
            claimed[d.id] = mod.id

        # 外部系统的名字只**警告**（不替上游断言）
        if known_servers:
            unknown = [s for s in mod.servers if s not in known_servers]
            if unknown:
                notes.append(f"模块 `{mod.id}` 声明的 server 不在已知清单中：{unknown}")
        if known_skills:
            unknown_sk = [s for s in mod.skills if s not in known_skills]
            if unknown_sk:
                notes.append(f"模块 `{mod.id}` 声明的 skill 不存在：{unknown_sk}")

        modules.append(mod)

    active = [m for m in modules if m.enabled]
    effective = {
        "tools": sorted({t for m in active for t in m.tools}),
        "skills": sorted({s for m in active for s in m.skills}),
        "servers": sorted({s for m in active for s in m.servers}),
        "solvers": sorted({s for m in active for s in m.solvers}),
    }
    if len(modules) > len(active):
        notes.append(
            f"{len(modules) - len(active)} 个模块被显式禁用（`enabled: false`）—— "
            "禁用是**正常状态**，内核不依赖任何模块。"
        )
    notes.append(
        "模块的 `tools` 是**软收窄**（该选题的推荐工具集），**不是硬白名单** —— "
        "硬限制会让「通用工作台」退化成「一次只能用一个选题」。"
    )

    return AssemblyReport(
        root=str(root), root_exists=True, modules=tuple(modules),
        failures=tuple(failures), notes=tuple(notes), effective=effective,
    )


def build_report(cfg: GatewayConfig, *, known_servers: tuple[str, ...] = (),
                 known_skills: tuple[str, ...] = ()) -> dict:
    """`GET /modules` 的响应体。"""
    rep = load_modules(modules_root(cfg), known_servers=known_servers,
                       known_skills=known_skills)
    return {
        "root": rep.root,
        "root_exists": rep.root_exists,
        "core_version": CORE_VERSION,
        "summary": {
            "total": len(rep.modules),
            "enabled": sum(1 for m in rep.modules if m.enabled),
            "disabled": sum(1 for m in rep.modules if not m.enabled),
            "failed": len(rep.failures),
            "by_maturity": _count_by(rep.modules, "maturity"),
            "by_kind": _count_by(rep.modules, "kind"),
        },
        "effective": rep.effective,
        "modules": [asdict(m) for m in rep.modules],
        "failures": [asdict(f) for f in rep.failures],
        "notes": list(rep.notes),
    }


def _count_by(modules: tuple[Module, ...], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in modules:
        key = getattr(m, attr)
        out[key] = out.get(key, 0) + 1
    return out


# ---------------------------------------------------------------- 脚手架

_TEMPLATE_MANIFEST = """\
# 选题模块清单（方案 v4 §六 / 模块化架构）
#
# ★ 默认从 **L0 声明式** 起步 —— 多数选题只需声明，无需写 UI 代码。
#   需要数据表时升到 L1（填 entities / result_tables 并给出 schema 文件），
#   只有需要自定义面板时才升到 L2。
id: {mid}                      # 必须与目录名一致
name: {name}
version: 0.1.0
kind: {kind}                   # research | engineering
maturity: L0                   # L0 声明式 | L1 数据式 | L2 组件式
enabled: true

requires:
  core: ">=0.1"
  # servers: [surge]           # 本选题用到的 server
  # solvers: [HiGHS]           # 允许的求解器（Gurobi 已被网关显式排除）

# 本选题的工具白名单（**软收窄**：作为该选题会话的推荐工具集，不是硬限制）
tools: []
#   - surge.run_n1_branch_contingency

# 本选题关心的技能（用于聚焦「技能手册」视图）
skills: []
#   - contingency-mitigation

# —— 以下为 L1+ 才需要填；填了就必须给出对应文件（否则装配失败）——
# entities:
#   - id: my_entity
#     schema: ./schema/my_entity.json
# result_tables:
#   - id: my_results
#     columns: ./schema/my_columns.json
#     metrics: [count]

# prompts:
#   - id: my-prompt
#     file: ./prompts/my_prompt.md
# checks:
#   - id: my-check
#     file: ./checks/my_check.py
# exports:
#   - id: my-report
#     template: ./templates/my_report.md

# L2 才用：槽位注入（nav.extra / case.detail.tabs / chat.result.after /
#                    experiment.result.columns / verification.extra）
slots: []
"""

_README = """\
# {mid}

{name}

由 `create_module` 脚手架生成，**默认 L0 声明式** —— 只需编辑 `module.yaml` 即可开工。

> ⚠️ **填完 `module.yaml` 后请更新本文件** —— 上面这句话在模块升到 L1/L2 后就不准了。
> （本次两个真实模块 `n1-ranking` / `cross-engine-consistency` 都停在 L1，
> 它们的 README 已按实际内容重写；脚手架产物只是起点，不是最终状态。）

| 目录 | 用途 | 何时需要 |
|---|---|---|
| `prompts/` | 选题专属提示词 | L0（可选） |
| `schema/` | 实体与结果表的结构定义 | L1 |
| `checks/` | 领域自检规则（区别于 8 类**接口**契约） | L0（可选） |
| `templates/` | 报告模板 | L0（可选） |
| `ui/` | React 组件 | **L2 才需要** |

## 三层成熟度

- **L0 声明式**：仅 `module.yaml` —— 多数选题到此为止。
- **L1 数据式**：加 `entities` / `result_tables` + schema 文件，内核自动渲染成表与图。
- **L2 组件式**：加 `ui/` 下的 React 组件，经槽位注入。

## 硬约束

- ❌ 不得访问 `PowerMCP/`
- ❌ 不得绕过网关直连 MCP server
- ❌ 不得写 `~/.powermcp/`
- ❌ 不得 import 内核内部模块
"""


def scaffold_module(root: Path, module_id: str, *, name: str | None = None,
                    kind: str = KIND_RESEARCH, force: bool = False) -> Path:
    """生成一个 L0 模块骨架。

    ★ **默认生成 L0**：强制「先声明、后写码」的顺序，避免一上来就写组件。

    Raises:
        ModuleError: id 非法 / kind 非法 / 目标已存在（且未 `force`）。
    """
    if not re.fullmatch(r"[a-z][a-z0-9-]*", module_id or ""):
        raise ModuleError(
            "模块 id 只能含小写字母、数字与连字符，且**必须以字母开头**"
            f"（收到 {module_id!r}）"
        )
    if kind not in KINDS:
        raise ModuleError(f"`kind` 必须是 {list(KINDS)} 之一，收到 {kind!r}")

    target = root / module_id
    if target.exists():
        if not force:
            raise ModuleError(f"目标已存在：{target}（用 force=True 覆盖）")
        shutil.rmtree(target)

    (target / "prompts").mkdir(parents=True)
    (target / "schema").mkdir()
    (target / "checks").mkdir()
    (target / "templates").mkdir()
    (target / "ui").mkdir()

    (target / MANIFEST_NAME).write_text(
        _TEMPLATE_MANIFEST.format(mid=module_id, name=name or module_id, kind=kind),
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        _README.format(mid=module_id, name=name or module_id), encoding="utf-8"
    )
    return target
