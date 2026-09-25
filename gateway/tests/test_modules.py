"""`modules.py` 的测试。

★ 两条最重要的：
  1. **脚手架产物必须能被装配**（round-trip）—— 否则新选题一开工就是坏的；
  2. **内核自证条件**：无模块 / 模块根不存在 / 模块全失败时，装配结果仍是"成功且干净"的，
     因为内核**不依赖任何模块**。
"""

from __future__ import annotations

import pytest
import yaml

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.modules import (
    CORE_VERSION,
    ENV_MODULES_ROOT,
    KIND_ENGINEERING,
    ModuleError,
    build_report,
    load_modules,
    modules_root,
    parse_manifest,
    satisfies,
    scaffold_module,
)

_MINIMAL = """\
id: demo
name: 演示模块
version: 0.1.0
kind: research
maturity: L0
"""


def _write(root, mid: str, body: str, *, manifest: str = "module.yaml"):
    p = root / mid / manifest
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


# ---------------------------------------------------------------- 版本判定


@pytest.mark.parametrize("version,spec,expected", [
    ("0.1.0", ">=0.1", True),
    ("0.1.0", ">=0.2", False),
    ("0.1.0", "==0.1.0", True),
    ("0.1.0", "==0.2.0", False),
    ("0.1.0", "<=0.1", True),
    ("0.1.0", ">0.1", False),
    ("0.1.0", "<0.2", True),
    ("0.1.0", "0.1", True),          # 缺省视为 >=
    ("0.1.0", "", True),
    ("0.1.0", None, True),
    ("0.1.0", "乱写", False),        # 无法解析 → 不满足（fail-loud）
    ("1.10.0", ">=1.9", True),       # 按数值而非字典序比较
])
def test_satisfies(version, spec, expected):
    assert satisfies(version, spec) is expected


# ---------------------------------------------------------------- 清单解析


def test_parse_minimal_manifest(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL)
    m = parse_manifest(p)
    assert (m.id, m.kind, m.maturity, m.enabled) == ("demo", "research", "L0", True)
    assert m.name == "演示模块"
    assert m.tools == () and m.declarations == ()


def test_id_must_match_directory_name(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL.replace("id: demo", "id: 别的"))
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "必须与目录名" in str(ei.value)
    assert "别的" in str(ei.value) and "demo" in str(ei.value)


def test_missing_id_is_error(tmp_path):
    p = _write(tmp_path, "demo", "name: x\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "id" in str(ei.value)


@pytest.mark.parametrize("body", [
    _MINIMAL.replace("kind: research", "kind: 别的"),
    _MINIMAL.replace("maturity: L0", "maturity: L9"),
])
def test_bad_kind_and_maturity(tmp_path, body):
    p = _write(tmp_path, "demo", body)
    with pytest.raises(ModuleError):
        parse_manifest(p)


def test_requires_core_unsatisfied(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL + "\nrequires:\n  core: \">=9.0\"\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "core" in str(ei.value) and CORE_VERSION in str(ei.value)


def test_root_must_be_mapping(tmp_path):
    p = _write(tmp_path, "demo", "- 这是个数组\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "映射" in str(ei.value)


def test_broken_yaml_is_error(tmp_path):
    p = _write(tmp_path, "demo", "id: demo\n  bad: [\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "无法解析" in str(ei.value)


def test_declarations_reject_duplicate_id(tmp_path):
    body = _MINIMAL + (
        "\nentities:\n  - id: a\n    schema: ./schema/a.json\n"
        "  - id: a\n    schema: ./schema/a.json\n"
    )
    p = _write(tmp_path, "demo", body)
    (tmp_path / "demo" / "schema").mkdir()
    (tmp_path / "demo" / "schema" / "a.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "id 重复" in str(ei.value)


def test_declaration_missing_id_is_error(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL + "\nentities:\n  - schema: ./s.json\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "缺少非空 `id`" in str(ei.value)


def test_manifest_referenced_file_must_exist(tmp_path):
    """★ 清单**自己指向**的文件不存在 → 装配失败（清单说了它存在，就是清单错）。"""
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nentities:\n  - id: a\n    schema: ./schema/缺.json\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "指向的文件不存在" in str(ei.value)
    assert "缺.json" in str(ei.value)


def test_declaration_file_present_is_ok(tmp_path):
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nentities:\n  - id: a\n    schema: ./schema/a.json\n")
    (tmp_path / "demo" / "schema").mkdir()
    (tmp_path / "demo" / "schema" / "a.json").write_text("{}", encoding="utf-8")
    assert parse_manifest(p).entities[0].id == "a"


def test_single_string_accepted_for_tools(tmp_path):
    """容错：`tools: x` 与 `tools: [x]` 等价。"""
    p = _write(tmp_path, "demo", _MINIMAL + "\ntools: surge.run_power_flow\n")
    assert parse_manifest(p).tools == ("surge.run_power_flow",)


def test_bad_tools_type_is_error(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL + "\ntools: 123\n")
    with pytest.raises(ModuleError):
        parse_manifest(p)


# ---------------------------------------------------------------- 装配


def test_missing_root_is_not_an_error(tmp_path):
    """★ 内核自证条件：模块根不存在是**正常状态**，内核不依赖任何模块。"""
    rep = load_modules(tmp_path / "不存在")
    assert rep.root_exists is False
    assert rep.modules == () and rep.failures == ()
    assert rep.effective == {"tools": [], "skills": [], "servers": [], "solvers": []}
    assert any("内核**不依赖任何模块**" in n for n in rep.notes)


def test_empty_root_is_clean(tmp_path):
    rep = load_modules(tmp_path)
    assert rep.root_exists is True
    assert rep.modules == () and rep.failures == ()


def test_broken_module_does_not_affect_others(tmp_path):
    """★ fail-loud：单个模块失败**只标记它自己**，其他模块照常装配。"""
    _write(tmp_path, "good", _MINIMAL.replace("id: demo", "id: good"))
    _write(tmp_path, "bad", "id: bad\nkind: 不存在\n")
    rep = load_modules(tmp_path)
    assert [m.id for m in rep.modules] == ["good"]
    assert [f.module_id for f in rep.failures] == ["bad"]
    assert "kind" in rep.failures[0].error


def test_disabled_module_is_listed_but_not_effective(tmp_path):
    _write(tmp_path, "alpha", _MINIMAL.replace("id: demo", "id: alpha")
           + "\ntools: [a.b]\n")
    _write(tmp_path, "beta", _MINIMAL.replace("id: demo", "id: beta")
           + "\nenabled: false\ntools: [c.d]\n")
    rep = load_modules(tmp_path)
    assert len(rep.modules) == 2
    assert rep.effective["tools"] == ["a.b"], "被禁用模块不得进入生效集"
    assert any("被显式禁用" in n for n in rep.notes)


def test_yaml_boolean_id_is_rejected_with_helpful_message(tmp_path):
    """★ YAML 会把 `on` / `off` / `yes` / `no` 解析成布尔值 —— 诊断必须点出这一点。

    否则 `id: on` 会以"缺少 id"报出来，让人查半天（本条即由这个坑逼出来）。
    """
    p = _write(tmp_path, "on", _MINIMAL.replace("id: demo", "id: on"))
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    msg = str(ei.value)
    assert "布尔值" in msg, f"诊断未点明 YAML 布尔陷阱：{msg}"


def test_effective_is_union_of_enabled_modules(tmp_path):
    _write(tmp_path, "a", _MINIMAL.replace("id: demo", "id: a")
           + "\ntools: [x.1]\nskills: [s1]\nrequires:\n  servers: [surge]\n  solvers: [HiGHS]\n")
    _write(tmp_path, "b", _MINIMAL.replace("id: demo", "id: b")
           + "\ntools: [x.2]\nskills: [s2]\nrequires:\n  servers: [pypsa]\n")
    eff = load_modules(tmp_path).effective
    assert eff["tools"] == ["x.1", "x.2"]
    assert eff["skills"] == ["s1", "s2"]
    assert eff["servers"] == ["pypsa", "surge"]
    assert eff["solvers"] == ["HiGHS"]


def test_cross_module_declaration_clash_is_refused(tmp_path):
    """★ 同名声明**禁止**（不静默覆盖）—— 否则按 id 引用会产生歧义。"""
    for mid in ("a", "b"):
        _write(tmp_path, mid, _MINIMAL.replace("id: demo", f"id: {mid}")
               + "\nentities:\n  - id: same\n    schema: ./schema/s.json\n")
        (tmp_path / mid / "schema").mkdir(parents=True, exist_ok=True)
        (tmp_path / mid / "schema" / "s.json").write_text("{}", encoding="utf-8")

    rep = load_modules(tmp_path)
    assert len(rep.modules) == 1, "先出现的保留"
    assert len(rep.failures) == 1
    assert "冲突" in rep.failures[0].error
    assert rep.failures[0].module_id == "b", "后出现的被拒绝"


def test_unknown_server_and_skill_are_warnings_not_failures(tmp_path):
    """★ 外部系统的名字只**警告** —— 我们不替上游断言。"""
    _write(tmp_path, "demo", _MINIMAL
           + "\nrequires:\n  servers: [不存在的server]\nskills: [不存在的skill]\n")
    rep = load_modules(tmp_path, known_servers=("surge",), known_skills=("pandapower",))
    assert rep.failures == ()
    assert len(rep.modules) == 1
    joined = " ".join(rep.notes)
    assert "不存在的server" in joined and "不存在的skill" in joined


def test_notes_state_tools_are_soft_not_hard(tmp_path):
    """★ 「软收窄」这一取舍必须在响应里写明，避免被当成硬白名单。"""
    _write(tmp_path, "demo", _MINIMAL)
    rep = load_modules(tmp_path)
    assert any("软收窄" in n and "不是硬白名单" in n for n in rep.notes)


# ---------------------------------------------------------------- 报告


def test_build_report_shape(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _write(tmp_path, "a", _MINIMAL.replace("id: demo", "id: a"))
    _write(tmp_path, "b", _MINIMAL.replace("id: demo", "id: b")
           + "\nmaturity: L1\nkind: engineering\nenabled: false\n")

    r = build_report(cfg)
    assert r["root"] == str(tmp_path)
    assert r["root_exists"] is True
    assert r["core_version"] == CORE_VERSION
    assert r["summary"] == {
        "total": 2, "enabled": 1, "disabled": 1, "failed": 0,
        "by_maturity": {"L0": 1, "L1": 1},
        "by_kind": {"research": 1, "engineering": 1},
    }
    assert len(r["modules"]) == 2 and r["failures"] == []


def test_build_report_on_missing_root(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path / "无"))
    r = build_report(cfg)
    assert r["root_exists"] is False
    assert r["summary"]["total"] == 0


def test_modules_root_env_override(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    assert modules_root(cfg) == tmp_path


# ---------------------------------------------------------------- 脚手架


def test_scaffold_creates_l0_layout(tmp_path):
    p = scaffold_module(tmp_path, "n1-ranking", name="N-1 排序研究")
    assert p.is_dir()
    for sub in ("prompts", "schema", "checks", "templates", "ui"):
        assert (p / sub).is_dir(), sub
    assert (p / "module.yaml").is_file()
    assert (p / "README.md").is_file()


def test_scaffold_defaults_to_l0(tmp_path):
    """★ 默认 L0 —— 强制「先声明、后写码」。"""
    p = scaffold_module(tmp_path, "x")
    manifest = yaml.safe_load((p / "module.yaml").read_text(encoding="utf-8"))
    assert manifest["maturity"] == "L0"
    assert manifest["kind"] == "research"
    assert manifest["tools"] == [] and manifest["slots"] == []


def test_scaffold_output_loads_cleanly(tmp_path):
    """★ round-trip：脚手架产物**必须能装配** —— 否则新选题一开工就是坏的。"""
    scaffold_module(tmp_path, "n1-ranking", name="N-1 排序研究")
    rep = load_modules(tmp_path)
    assert rep.failures == (), f"脚手架产物装配失败：{rep.failures}"
    assert [m.id for m in rep.modules] == ["n1-ranking"]
    assert rep.modules[0].maturity == "L0"


@pytest.mark.parametrize("bad", ["", "N1", "n1_ranking", "1", "-x", "有中文"])
def test_scaffold_rejects_bad_id(tmp_path, bad):
    with pytest.raises(ModuleError):
        scaffold_module(tmp_path, bad)


def test_scaffold_rejects_bad_kind(tmp_path):
    with pytest.raises(ModuleError):
        scaffold_module(tmp_path, "x", kind="别的")


def test_scaffold_refuses_existing_without_force(tmp_path):
    scaffold_module(tmp_path, "x")
    with pytest.raises(ModuleError) as ei:
        scaffold_module(tmp_path, "x")
    assert "已存在" in str(ei.value)


def test_scaffold_force_overwrites(tmp_path):
    p = scaffold_module(tmp_path, "x")
    (p / "marker.txt").write_text("旧", encoding="utf-8")
    scaffold_module(tmp_path, "x", force=True)
    assert not (p / "marker.txt").exists()


def test_scaffold_engineering_kind(tmp_path):
    p = scaffold_module(tmp_path, "eng", kind=KIND_ENGINEERING)
    manifest = yaml.safe_load((p / "module.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == KIND_ENGINEERING
