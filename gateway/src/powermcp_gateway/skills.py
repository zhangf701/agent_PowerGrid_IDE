"""PowerSkills 技能索引。

★ 为什么需要（方案 v4 §4.5）：PowerSkills 的 21 个技能在 v3 中**零覆盖** ——
  `skill` 在《UI 设计规范》出现 **0 次**、在《前端设计方案》**1 次**（且仅作契约比对对象）。
  而它承载了「研究方法」最直接的载体：**Escalation triggers**
  （观测值 → 缓解手册的数字驱动映射，审计结论为 10/10 引用完整、无悬空）。

★ 健康度**只报可计算信号**，不转录审计报告里的人工结论：
  审计报告（🔴 阻断 3 / 🟠 事实不符 4 / 🟡 引用错误 1）是**人工阅读**得出的，
  尚未机器可读。把它的数字硬编码进来会立刻过期，且无法复核。
  因此本模块只算三类**可验证**的信号，并把整体健康度如实标为 `unknown`
  （方案 v4 的 P5「未知态必须可见」）：
    1. `escalation_missing`  —— tool skill 缺 escalation 表（审计实测 ltspice 如此）
    2. `dangling_escalation` —— escalate_to 指向不存在的技能（悬空引用）
    3. `orphan_playbooks`    —— 缓解手册从未被任何 tool skill 引用
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import GatewayConfig

logger = logging.getLogger(__name__)

#: 覆盖 PowerSkills 根目录（默认取 PowerMCP 的兄弟目录）
ENV_SKILLS_ROOT = "POWERMCP_SKILLS_ROOT"

#: 技能类别
KIND_TOOL = "tool"
KIND_ENGINEERING = "engineering"
KIND_META = "meta"

#: 应有 escalation 表的类别 —— 只有 tool skill 被设计成要给出升级路径。
#: 缓解手册本身是终点，元技能（skill-creator）不属于任一插件。
_KINDS_NEEDING_ESCALATION = frozenset({KIND_TOOL})

#: markdown 标题：捕获 `#` 的个数（层级）与标题文本
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class SkillTrigger:
    """一条 escalation 规则：观测到什么 → 升级到哪本手册。"""

    observation: str
    escalate_to: str


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    kind: str
    description: str
    path: str                                   # 相对技能根的 POSIX 路径
    triggers: tuple[SkillTrigger, ...] = ()

    @property
    def has_escalation(self) -> bool:
        return bool(self.triggers)


@dataclass(frozen=True)
class SkillHealth:
    """健康度的**可计算**信号。

    ⚠️ `level` 恒为 `unknown`：本模块不转录人工审计结论（见模块 docstring）。
    `signals` 里的是**可复核**的机器判定；`source` 说明为何整体仍是 unknown。
    """

    level: str
    signals: dict
    source: str


def skills_root(cfg: GatewayConfig) -> Path:
    """定位 PowerSkills 根目录。

    路径推演：PowerSkills 与 PowerMCP 是**兄弟目录**（同属项目根）。
    允许用 `POWERMCP_SKILLS_ROOT` 覆盖 —— 两个仓库可以分开 clone。
    """
    override = os.environ.get(ENV_SKILLS_ROOT)
    if override:
        return Path(override)
    return cfg.powermcp_root.parent / "PowerSkills"


def _parse_frontmatter(text: str) -> dict[str, str]:
    """解析文件顶部的 YAML frontmatter（**只做简单行解析**）。

    ★ 刻意不引入 PyYAML：本模块只需要 `name` / `description` 两个标量字段，
      而 `description` 里含冒号（"…studies. Use whenever…: …"），
      按**第一个**冒号切分即可正确还原。为两个标量加一个依赖不划算。
    ⚠️ 不支持多行标量（`|` / `>`）与引号包裹 —— 若将来技能改用这些写法，
      本函数会给出带引号的原文，需同步升级。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _strip_code_marks(value: str) -> str:
    """去掉 markdown 行内代码标记与包裹的引号。"""
    v = value.strip().strip("`").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def _parse_triggers(text: str) -> tuple[SkillTrigger, ...]:
    """解析 `## Escalation triggers` 下的 markdown 表。

    容错取向：**宁可少解析，不可误解析** ——
    表头行、分隔行（`|---|---|`）、非表格行都不会变成一条规则。

    ★ 结束条件按**标题层级**判定：只有**同级或更高级**的标题才结束本节。
      若简单地在任意标题处结束，节内一个 `### 子标题` 就会让整节被跳过，
      该技能随即被误报为「缺 escalation 表」—— 一条**假健康警报**
      （由变异探针 M3 发现：该分支原本不可达，因为空行检查先命中了）。
    """
    lines = text.splitlines()
    start: int | None = None
    level = 2
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m and "escalation" in m.group(2).lower():
            start = i + 1
            level = len(m.group(1))
            break
    if start is None:
        return ()

    out: list[SkillTrigger] = []
    for line in lines[start:]:
        stripped = line.strip()
        m = _HEADING_RE.match(stripped)
        if m and len(m.group(1)) <= level:
            break                           # 同级或更高级标题 → 本节结束
        if not stripped.startswith("|"):
            if out:                         # 表已开始又遇到非表格行 → 表结束
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= set("-: "):     # 分隔行
            continue
        if cells[0].lower() in ("observation", "观测", "触发条件"):
            continue
        obs = cells[0]
        target = _strip_code_marks(cells[1])
        if not obs or not target:
            continue
        out.append(SkillTrigger(observation=obs, escalate_to=target))
    return tuple(out)


def _kind_for(rel: str) -> str:
    parts = Path(rel).parts
    if "powerskills-tool" in parts:
        return KIND_TOOL
    if "powerskills-engineering" in parts:
        return KIND_ENGINEERING
    return KIND_META


def index_skills(root: Path) -> tuple[Skill, ...]:
    """扫描 `root` 下全部 `SKILL.md`，按 id 排序返回。

    ⚠️ 目录不存在时返回**空元组**而非抛异常：PowerSkills 可以不在场
      （两个仓库可分开 clone），此时环境视图应显示"未找到"而不是 500。
    """
    if not root.is_dir():
        logger.warning("未找到 PowerSkills 根目录：%s（技能面板将为空）", root)
        return ()

    skills: list[Skill] = []
    for path in sorted(root.rglob("SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # 单个技能读不了不得让整次索引失败（隔离坏输入）
            logger.warning("技能文件不可读，已跳过：%s（%s）", path, exc)
            continue
        rel = path.relative_to(root).as_posix()
        meta = _parse_frontmatter(text)
        skill_id = meta.get("name") or path.parent.name
        skills.append(Skill(
            id=skill_id,
            name=skill_id,
            kind=_kind_for(rel),
            description=meta.get("description", ""),
            path=rel,
            triggers=_parse_triggers(text),
        ))

    # 同一 id 出现两次会让"按 id 引用"变得歧义 —— 保留**路径序在前**的那个
    # （`rglob` 结果先排序，故该选择是确定的；仅重复 id 时才可见）。
    seen: set[str] = set()
    unique: list[Skill] = []
    for s in skills:
        if s.id in seen:
            logger.warning("技能 id 重复，已跳过后者：%s（%s）", s.id, s.path)
            continue
        seen.add(s.id)
        unique.append(s)
    # 按 id 排序输出：id 是技能之间相互引用的键（escalation 的 escalate_to），
    # 按它排序才能让"引用目标"与"被引用者"在列表里易于对照。
    return tuple(sorted(unique, key=lambda s: s.id))


def evaluate_health(skills: tuple[Skill, ...]) -> SkillHealth:
    """计算三类**可复核**的健康信号（见模块 docstring）。"""
    ids = {s.id for s in skills}

    missing = sorted(
        s.id for s in skills
        if s.kind in _KINDS_NEEDING_ESCALATION and not s.has_escalation
    )
    dangling = sorted({
        f"{s.id} → {t.escalate_to}"
        for s in skills
        for t in s.triggers
        if t.escalate_to not in ids
    })
    referenced = {t.escalate_to for s in skills for t in s.triggers}
    orphans = sorted(
        s.id for s in skills
        if s.kind == KIND_ENGINEERING and s.id not in referenced
    )

    return SkillHealth(
        level="unknown",
        signals={
            "escalation_missing": missing,
            "dangling_escalation": dangling,
            "orphan_playbooks": orphans,
        },
        source=(
            "本模块只报**可计算**信号（缺 escalation 表 / 悬空引用 / 孤儿手册）。"
            "人工审计结论（🔴 阻断 3 · 🟠 事实不符 4 · 🟡 引用错误 1 · 🔵 规范 5）"
            "尚未机器可读，故整体健康度如实标为 unknown —— "
            "界面必须显示该未知态，不得让用户以为 21 个技能都可靠"
            "（典型：pypsa 的 `Network.status` 会**误报失败**，比崩溃更隐蔽）。"
        ),
    )


def build_report(cfg: GatewayConfig) -> dict:
    """`GET /skills` 的响应体。"""
    root = skills_root(cfg)
    skills = index_skills(root)
    health = evaluate_health(skills)

    by_kind: dict[str, int] = {}
    for s in skills:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + 1

    return {
        "root": str(root),
        "root_exists": root.is_dir(),
        "summary": {
            "total": len(skills),
            "by_kind": by_kind,
            "with_escalation": sum(1 for s in skills if s.has_escalation),
        },
        "health": {
            "level": health.level,
            "signals": health.signals,
            "source": health.source,
        },
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "description": s.description,
                "path": s.path,
                "escalation": [
                    {"observation": t.observation, "escalate_to": t.escalate_to}
                    for t in s.triggers
                ],
            }
            for s in skills
        ],
    }
