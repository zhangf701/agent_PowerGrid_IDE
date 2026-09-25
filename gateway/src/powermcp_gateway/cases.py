"""算例库 —— `case` 这一级实体。

★ 为什么需要（方案 v4 §4.2）：v3 只有 **session** 粒度，研究无法「组织」——
  你没法说"这是 case39 那组实验"。算例库是实验矩阵（§4.4）的**主语**。

★ 三个关键设计决定（都可复核）：

  1. **按路径引用，不复制文件**。
     张老师指着他自己的算例，算例就是那个文件。复制会在他的数据旁边悄悄多出一份，
     且他改了原文件、库里的却还是旧的 —— 那是**静默的数据不一致**。
     代价是"可复现性依赖源文件仍在原位"，故**记录 sha256 并在读取时检测漂移**
     （`drift` 字段），把不确定性显式化而不是掩盖。

  2. **索引用 JSON + 原子替换，不用 SQLite**。
     方案 §11.4 原写"算例元数据 → SQLite WAL"，此处**有意偏离并说明**：
     本地单用户、量级为几十到几百条，JSON 可读、可 diff、可手工核对，
     而 SQLite 会引入连接/迁移/锁的开销与不可读的二进制。
     等到量级或并发真的需要时再换 —— 届时 `CaseStore` 的接口不变。
     （已同步更新 v4 §11.4，避免文档与实现不一致。）

  3. **`DELETE` 只注销登记，绝不删除源文件**。
     这是数据安全底线 —— 一个 HTTP 动词不该能删掉用户磁盘上的算例。

★ 存储位置：`~/.powermcp_gateway/cases/`（**独立于** `~/.powermcp/`，后者是上游目录）。
  这回答了提案 §十四-4 的实测问题：**不需要改动 `PowerMCP/` 一行** ——
  网关只是把 `POWERIO_MCP_ALLOWED_ROOTS` 透传给子进程（见 `config.server_env`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import GatewayConfig, server_env

logger = logging.getLogger(__name__)

#: 覆盖算例库根目录
ENV_CASES_ROOT = "POWERMCP_GATEWAY_CASES_ROOT"

#: 索引文件名
INDEX_NAME = "cases.json"

#: 单文件哈希上限。超过即拒绝注册 —— 一个 HTTP 请求不该为了哈希几十 GB 而挂住。
#: （真需要大算例时，调高它或改成登记时不算哈希，届时再定。）
MAX_HASH_BYTES = 256 * 1024 * 1024

_HASH_CHUNK = 1024 * 1024


class CaseError(RuntimeError):
    """算例登记失败（路径不存在 / 超限 / 不是文件）—— **客户端输入问题**，映射 400。"""


class CaseIndexError(CaseError):
    """算例索引本身损坏 —— **服务端数据问题**，映射 500（不是客户端的错）。

    ★ 单列一个类型是为了让端点**不必靠匹配错误文本**来区分两类失败 ——
      文本会变，类型不会。
    """


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cases_root(cfg: GatewayConfig) -> Path:
    """算例库根目录（**不放在** `~/.powermcp/` 下 —— 那是上游的目录）。"""
    override = os.environ.get(ENV_CASES_ROOT)
    if override:
        return Path(override)
    return Path.home() / ".powermcp_gateway" / "cases"


@dataclass(frozen=True)
class Case:
    id: str
    label: str
    source_path: str
    format: str
    size: int
    sha256: str
    registered_at: str
    tags: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class CaseView:
    """读取时的**计算视图** —— 带"现在还在不在 / 有没有变"。

    ★ 这两个字段**必须现算**，不能存进索引：存下来就会过期，
      而过期的"文件还在"比不报更危险（用户会以为一切正常）。
    """

    case: Case
    available: bool
    drift: bool                     # 文件仍在，但内容与登记时不同
    within_allowed_roots: bool      # server 子进程能否读到它
    current_size: int | None = None
    current_sha256: str | None = None   # 现算哈希 —— 用于判断已解析产物是否**陈旧**

    def to_dict(self) -> dict:
        d = asdict(self.case)
        d.update(
            available=self.available,
            drift=self.drift,
            within_allowed_roots=self.within_allowed_roots,
            current_size=self.current_size,
            current_sha256=self.current_sha256,
        )
        return d


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _case_id(source: Path) -> str:
    """由**规范化绝对路径**派生稳定 id —— 同一路径重复登记即为「更新」而非「新增」。"""
    key = os.path.normcase(str(source.resolve())).encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:12]


def allowed_root_paths(env: dict[str, str] | None = None) -> tuple[Path, ...]:
    """当前**实际会透传给 server** 的允许根。

    ★ 必须与 `config.server_env()` 取同一来源 —— 否则算例库会声称"可读"、
      而 server 实际读不到（本会话实测过的正是这类"设了不生效"的坑）。
    """
    passed = server_env(env)
    raw = ""
    for name in ("POWERIO_MCP_ALLOWED_ROOTS", "POWERIO_MCP_ROOT", "POWERIO_MCP_ALLOWED_ROOT"):
        if passed.get(name):
            raw = passed[name]
            break
    if not raw:
        # 未配置 → 上游回落到"导入时的 cwd"，即 PowerMCP 仓库根。
        return ()
    return tuple(
        Path(p.strip()).expanduser().resolve(strict=False)
        for p in raw.split(os.pathsep) if p.strip()
    )


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    if not roots:
        return False
    target = path.resolve(strict=False)
    for root in roots:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


class CaseStore:
    """算例索引的读写。

    ⚠️ **非并发安全**：单进程本地使用。写用「临时文件 + `os.replace`」保证
      不会写出半截 JSON，但不处理多进程同时写。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    @property
    def index_path(self) -> Path:
        return self._root / INDEX_NAME

    # ------------------------------------------------------------ 读

    def _load(self) -> list[dict]:
        path = self.index_path
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # ★ 索引损坏必须**响亮** —— 静默当成空库会让用户以为算例全丢了
            raise CaseIndexError(f"算例索引损坏，无法解析 {path}：{exc}") from exc
        if not isinstance(data, list):
            raise CaseIndexError(f"算例索引格式错误（应为数组）：{path}")
        return [d for d in data if isinstance(d, dict)]

    def _write(self, rows: list[dict]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.index_path)      # 原子替换：不会留下半截文件

    def list(self) -> tuple[Case, ...]:
        return tuple(_to_case(r) for r in self._load())

    def get(self, case_id: str) -> Case:
        for row in self._load():
            if row.get("id") == case_id:
                return _to_case(row)
        raise KeyError(case_id)

    def view(self, case: Case, env: dict[str, str] | None = None) -> CaseView:
        """计算某个算例的现状（存在性 / 漂移 / server 可读性）。"""
        source = Path(case.source_path)
        roots = allowed_root_paths(env)
        if not source.is_file():
            return CaseView(case, available=False, drift=False,
                            within_allowed_roots=_is_within(source, roots))
        try:
            size = source.stat().st_size
            digest = _sha256_file(source)
        except OSError as exc:
            logger.warning("读取算例失败：%s（%s）", source, exc)
            return CaseView(case, available=False, drift=False,
                            within_allowed_roots=_is_within(source, roots))
        return CaseView(
            case,
            available=True,
            drift=digest != case.sha256,
            within_allowed_roots=_is_within(source, roots),
            current_size=size,
            current_sha256=digest,
        )

    # ------------------------------------------------------------ 写

    def register(self, source: Path, *, label: str | None = None,
                 tags: tuple[str, ...] = (), notes: str = "") -> tuple[Case, bool]:
        """登记一个算例。

        Returns:
            `(case, created)` —— `created=False` 表示该路径**已登记过**，本次是更新。

        Raises:
            CaseError: 路径不存在 / 不是文件 / 超过哈希上限。
        """
        src = Path(source).expanduser()
        if not src.exists():
            raise CaseError(f"算例文件不存在：{src}")
        if not src.is_file():
            raise CaseError(f"算例必须是文件（不支持目录）：{src}")

        size = src.stat().st_size
        if size > MAX_HASH_BYTES:
            raise CaseError(
                f"算例 {src.name} 为 {size} 字节，超过登记上限 "
                f"{MAX_HASH_BYTES} 字节 —— 调高 MAX_HASH_BYTES 或改为不算哈希再登记"
            )

        resolved = src.resolve()
        case = Case(
            id=_case_id(resolved),
            label=label or resolved.name,
            source_path=str(resolved),
            format=resolved.suffix.lstrip(".").lower() or "unknown",
            size=size,
            sha256=_sha256_file(resolved),
            registered_at=_now(),
            tags=tuple(tags),
            notes=notes,
        )

        rows = self._load()
        created = True
        for i, row in enumerate(rows):
            if row.get("id") == case.id:
                created = False
                # 保留原登记时间（它是"这个算例什么时候进入研究"的记录，不该被覆盖）
                case = Case(**{**asdict(case), "registered_at": row.get(
                    "registered_at", case.registered_at)})
                rows[i] = asdict(case)
                break
        else:
            rows.append(asdict(case))
        self._write(rows)
        return case, created

    def unregister(self, case_id: str) -> Case:
        """注销登记 —— **只删索引条目，绝不删除源文件**。"""
        rows = self._load()
        for i, row in enumerate(rows):
            if row.get("id") == case_id:
                removed = _to_case(row)
                del rows[i]
                self._write(rows)
                return removed
        raise KeyError(case_id)


def _to_case(row: dict) -> Case:
    """把索引行转成 `Case`。**容忍缺字段**（旧索引 / 手工编辑），但不静默丢 id。"""
    tags = row.get("tags") or ()
    return Case(
        id=str(row.get("id", "")),
        label=str(row.get("label", "")),
        source_path=str(row.get("source_path", "")),
        format=str(row.get("format", "unknown")),
        size=int(row.get("size", 0) or 0),
        sha256=str(row.get("sha256", "")),
        registered_at=str(row.get("registered_at", "")),
        tags=tuple(str(t) for t in tags) if isinstance(tags, (list, tuple)) else (),
        notes=str(row.get("notes", "")),
    )


def build_report(cfg: GatewayConfig, env: dict[str, str] | None = None) -> dict:
    """`GET /cases` 的响应体。"""
    store = CaseStore(cases_root(cfg))
    roots = allowed_root_paths(env)
    cases = store.list()
    views = [store.view(c, env) for c in cases]
    return {
        "root": str(store.root),
        "index_exists": store.index_path.is_file(),
        "allowed_roots": [str(r) for r in roots],
        "summary": {
            "total": len(views),
            "available": sum(1 for v in views if v.available),
            "drifted": sum(1 for v in views if v.drift),
            "unreadable_by_servers": sum(1 for v in views if not v.within_allowed_roots),
        },
        "cases": [v.to_dict() for v in views],
        "notes": [
            "算例按**路径引用**，不复制文件；`drift=true` 表示源文件内容已与登记时不同。"
            "（登记时记录 sha256，读取时现算比对。）",
            "`DELETE /cases/{id}` **只注销登记，绝不删除源文件**。",
            "`within_allowed_roots=false` 的算例，**server 子进程读不到** —— "
            "需把它所在目录加进 `POWERIO_MCP_ALLOWED_ROOTS`（见 `GET /environment` 的 `server_env`）。",
        ],
    }
