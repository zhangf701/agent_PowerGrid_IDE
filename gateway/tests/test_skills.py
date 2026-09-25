"""`skills.py` 的测试。

分两层：
  - **单元层**（tmp_path 构造假技能）：解析逻辑的边界与容错；
  - **真实数据层**：对仓库内真实 PowerSkills 断言**结构不变式**
    （总数 / 分类计数 / 无悬空引用 / 无孤儿手册）。
    ⚠️ 刻意**不**硬编码"ltspice 缺 escalation"这类**已知待修**的具体状态 ——
    它一旦被修好，测试应表现为"该断言过时"而不是"代码回归"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.skills import (
    ENV_SKILLS_ROOT,
    KIND_ENGINEERING,
    KIND_META,
    KIND_TOOL,
    build_report,
    evaluate_health,
    index_skills,
    skills_root,
)

TOOL_SKILL = """\
---
name: demo-tool
description: Progressive-disclosure workflow. Use whenever the user asks: "run it".
---

# demo-tool

## Escalation triggers

| Observation | Escalate to |
|---|---|
| `loading_percent` > 100 | `thermal-overload-mitigation` |
| solver diverges | `convergence-failure-mitigation` |

## Next section
| not | a table |
"""


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------- frontmatter


def test_frontmatter_splits_on_first_colon_only():
    """`description` 内含冒号（真实技能里就有）—— 必须按第一个冒号切。"""
    from powermcp_gateway.skills import _parse_frontmatter

    meta = _parse_frontmatter(TOOL_SKILL)
    assert meta["name"] == "demo-tool"
    assert meta["description"].endswith('"run it".')


def test_frontmatter_absent_returns_empty():
    from powermcp_gateway.skills import _parse_frontmatter

    assert _parse_frontmatter("# 没有 frontmatter\n") == {}
    assert _parse_frontmatter("") == {}


# ---------------------------------------------------------------- escalation 解析


def test_triggers_parsed_and_section_ends_at_next_heading():
    from powermcp_gateway.skills import _parse_triggers

    got = _parse_triggers(TOOL_SKILL)
    assert [t.escalate_to for t in got] == [
        "thermal-overload-mitigation", "convergence-failure-mitigation",
    ]
    assert got[0].observation == "`loading_percent` > 100"
    # 下一个标题之后的表格不得被吞进来
    assert all("not" != t.observation for t in got)


def test_triggers_survive_a_subheading_inside_the_section():
    """★ 节内的 `###` 子标题**不得**让整节被跳过。

    否则该技能会被误报为「缺 escalation 表」—— 一条假健康警报。
    （本条由变异探针 M3 逼出来：原来的"任意标题即结束"分支不可达，
      因为空行检查先命中；真正会踩到它的是子标题场景。）
    """
    from powermcp_gateway.skills import _parse_triggers

    text = (
        "## Escalation triggers\n\n"
        "### How to escalate\n\n"
        "| Observation | Escalate to |\n"
        "|---|---|\n"
        "| a | b |\n"
    )
    assert [t.escalate_to for t in _parse_triggers(text)] == ["b"]


def test_triggers_absent_returns_empty():
    from powermcp_gateway.skills import _parse_triggers

    assert _parse_triggers("# 无关内容\n\n## Working rules\n- x\n") == ()


def test_triggers_strip_code_marks_and_quotes():
    from powermcp_gateway.skills import _parse_triggers

    text = "## Escalation triggers\n\n| Observation | Escalate to |\n|---|---|\n| a | \"b\" |\n"
    assert _parse_triggers(text)[0].escalate_to == "b"


def test_trigger_with_empty_cell_is_skipped():
    from powermcp_gateway.skills import _parse_triggers

    text = "## Escalation triggers\n\n| Observation | Escalate to |\n|---|---|\n| a |  |\n| b | c |\n"
    assert [t.escalate_to for t in _parse_triggers(text)] == ["c"]


# ---------------------------------------------------------------- kind 判定


@pytest.mark.parametrize("rel,expected", [
    ("powerskills-tool/skills/surge/SKILL.md", KIND_TOOL),
    ("powerskills-engineering/skills/x-mitigation/SKILL.md", KIND_ENGINEERING),
    ("skill-creator/SKILL.md", KIND_META),
])
def test_kind_is_derived_from_path(rel, expected):
    from powermcp_gateway.skills import _kind_for

    assert _kind_for(rel) == expected


# ---------------------------------------------------------------- 索引


def test_index_finds_nested_and_falls_back_to_dir_name(tmp_path):
    _write(tmp_path, "powerskills-tool/skills/alpha/SKILL.md",
           "---\nname: alpha\ndescription: d\n---\n")
    # 无 frontmatter → 用目录名
    _write(tmp_path, "powerskills-engineering/skills/beta-mitigation/SKILL.md", "# beta\n")

    skills = index_skills(tmp_path)
    assert [s.id for s in skills] == ["alpha", "beta-mitigation"]
    assert skills[1].description == ""
    assert skills[1].kind == KIND_ENGINEERING


def test_missing_root_returns_empty_not_error(tmp_path):
    """PowerSkills 可以不在场（两个仓库可分开 clone）—— 不得抛异常。"""
    assert index_skills(tmp_path / "不存在") == ()


def test_duplicate_id_keeps_one_deterministically(tmp_path):
    """重复 id 必须去重，且结果**确定**（不依赖文件系统枚举顺序）。

    ⚠️ 刻意不断言"保留的是哪一个" —— 那取决于路径排序，是平台细节；
      重要的是「只有一个」且「两次调用一致」。
    """
    _write(tmp_path, "powerskills-tool/skills/a/SKILL.md", "---\nname: dup\n---\n")
    _write(tmp_path, "powerskills-engineering/skills/b/SKILL.md", "---\nname: dup\n---\n")

    first = index_skills(tmp_path)
    assert len(first) == 1
    assert first[0].id == "dup"
    assert [s.path for s in index_skills(tmp_path)] == [first[0].path]


def test_unreadable_file_is_skipped(tmp_path, monkeypatch):
    """单个技能读不了不得让整次索引失败（隔离坏输入）。"""
    good = _write(tmp_path, "powerskills-tool/skills/good/SKILL.md", "---\nname: good\n---\n")
    bad = _write(tmp_path, "powerskills-tool/skills/bad/SKILL.md", "---\nname: bad\n---\n")
    real_read = Path.read_text

    def flaky(self, *a, **kw):
        if self == bad:
            raise OSError("模拟读取失败")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert [s.id for s in index_skills(tmp_path)] == ["good"]
    assert good.exists()


# ---------------------------------------------------------------- 健康信号


def _skill(sid, kind, triggers=()):
    from powermcp_gateway.skills import Skill

    return Skill(id=sid, name=sid, kind=kind, description="", path=f"{sid}/SKILL.md",
                 triggers=tuple(triggers))


def test_health_flags_missing_escalation_only_for_tool_skills():
    """缓解手册本身是终点，不该要求它有 escalation 表。"""
    from powermcp_gateway.skills import SkillTrigger

    skills = (
        _skill("t1", KIND_TOOL),
        _skill("t2", KIND_TOOL, [SkillTrigger("obs", "t1")]),
        _skill("p1", KIND_ENGINEERING),
        _skill("m1", KIND_META),
    )
    sig = evaluate_health(skills).signals
    assert sig["escalation_missing"] == ["t1"]
    assert sig["orphan_playbooks"] == ["p1"]


def test_health_flags_dangling_escalation():
    from powermcp_gateway.skills import SkillTrigger

    skills = (
        _skill("t1", KIND_TOOL, [SkillTrigger("obs", "不存在的技能")]),
    )
    assert evaluate_health(skills).signals["dangling_escalation"] == ["t1 → 不存在的技能"]


def test_health_level_is_unknown_by_design():
    """★ 不得把人工审计结论硬编码成 level —— 必须如实标 unknown（P5 未知态可见）。"""
    h = evaluate_health((_skill("t", KIND_TOOL),))
    assert h.level == "unknown"
    assert "unknown" in h.source


# ---------------------------------------------------------------- 报告形状


def test_build_report_shape(tmp_path, monkeypatch):
    _write(tmp_path, "powerskills-tool/skills/surge/SKILL.md", TOOL_SKILL)
    monkeypatch.setenv(ENV_SKILLS_ROOT, str(tmp_path))
    r = build_report(GatewayConfig.discover())

    assert r["root_exists"] is True
    assert r["summary"] == {"total": 1, "by_kind": {KIND_TOOL: 1}, "with_escalation": 1}
    assert set(r["health"]) == {"level", "signals", "source"}
    assert r["skills"][0]["escalation"][0]["escalate_to"] == "thermal-overload-mitigation"


def test_skills_root_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_SKILLS_ROOT, str(tmp_path))
    assert skills_root(GatewayConfig.discover()) == tmp_path


def test_skills_root_defaults_to_sibling_of_powermcp(monkeypatch):
    monkeypatch.delenv(ENV_SKILLS_ROOT, raising=False)
    cfg = GatewayConfig.discover()
    assert skills_root(cfg) == cfg.powermcp_root.parent / "PowerSkills"


# ---------------------------------------------------------------- 真实数据不变式


def test_real_powerskills_invariants():
    """对仓库内真实 PowerSkills 断言结构不变式（不硬编码"已知待修"的具体状态）。"""
    cfg = GatewayConfig.discover()
    root = skills_root(cfg)
    if not root.is_dir():
        pytest.skip(f"PowerSkills 不在场：{root}")

    r = build_report(cfg)
    assert r["summary"]["total"] == 22, "11 tool + 10 engineering + 1 meta"
    assert r["summary"]["by_kind"][KIND_TOOL] == 11
    assert r["summary"]["by_kind"][KIND_ENGINEERING] == 10
    assert r["summary"]["by_kind"][KIND_META] == 1

    sig = r["health"]["signals"]
    assert sig["dangling_escalation"] == [], "escalation 引用必须无悬空"
    assert sig["orphan_playbooks"] == [], "不得有从未被引用的缓解手册"
    assert all(s["description"] for s in r["skills"]), "每个技能都应有 description"
