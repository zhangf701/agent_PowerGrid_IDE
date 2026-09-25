"""`modules.py` 的测试。

★ 两条最重要的：
  1. **脚手架产物必须能被装配**（round-trip）—— 否则新选题一开工就是坏的；
  2. **内核自证条件**：无模块 / 模块根不存在 / 模块全失败时，装配结果仍是"成功且干净"的，
     因为内核**不依赖任何模块**。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.modules import (
    CORE_VERSION,
    ENV_MODULES_ROOT,
    KIND_ENGINEERING,
    PROMPT_SUPPLEMENT_LIMIT,
    ModuleError,
    build_prompt_supplement,
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
               _MINIMAL.replace("maturity: L0", "maturity: L1")
               + "\nentities:\n  - id: a\n    schema: ./schema/a.json\n")
    (tmp_path / "demo" / "schema").mkdir()
    (tmp_path / "demo" / "schema" / "a.json").write_text("{}", encoding="utf-8")
    assert parse_manifest(p).entities[0].id == "a"


def test_single_string_accepted_for_tools(tmp_path):
    """容错：`tools: x` 与 `tools: [x]` 等价。"""
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nrequires:\n  servers: [surge]\ntools: surge.run_power_flow\n")
    assert parse_manifest(p).tools == ("surge.run_power_flow",)


def test_tools_without_servers_declaration_is_warned(tmp_path):
    """G-7 的软化另一半：有 tools 但没声明 servers —— 不是矛盾，但提示补声明。"""
    _write(tmp_path, "demo", _MINIMAL + "\ntools: [surge.run_dc_power_flow]\n")
    rep = load_modules(tmp_path)
    assert rep.failures == ()
    assert any("未声明 `requires.servers`" in n for n in rep.notes)


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
           + "\ntools: [surge.1]\nskills: [s1]\n"
             "requires:\n  servers: [surge]\n  solvers: [HiGHS]\n")
    _write(tmp_path, "b", _MINIMAL.replace("id: demo", "id: b")
           + "\ntools: [pypsa.2]\nskills: [s2]\nrequires:\n  servers: [pypsa]\n")
    eff = load_modules(tmp_path).effective
    assert eff["tools"] == ["pypsa.2", "surge.1"]
    assert eff["skills"] == ["s1", "s2"]
    assert eff["servers"] == ["pypsa", "surge"]
    assert eff["solvers"] == ["HiGHS"]


def test_cross_module_declaration_clash_is_refused(tmp_path):
    """★ 同名声明**禁止**（不静默覆盖）—— 否则按 id 引用会产生歧义。"""
    for mid in ("a", "b"):
        _write(tmp_path, mid, _MINIMAL.replace("id: demo", f"id: {mid}")
               .replace("maturity: L0", "maturity: L1")
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


# ---------------------------------------------------------------- 校验补强 G-7 / G-8
# 来源：两个真实模块的验证过程（`.superpowers/sdd/m15-module-gaps.py` 实测确认原先拦不住）

def test_g7_tools_must_be_covered_by_requires_servers(tmp_path):
    """★ G-7：`servers: [surge]` 却列了 `pypsa.*` —— 清单自相矛盾，必须装配失败。"""
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nrequires:\n  servers: [surge]\ntools: [pypsa.optimize_network]\n")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    msg = str(ei.value)
    assert "自相矛盾" in msg and "pypsa" in msg


def test_g7_passes_when_servers_cover_tools(tmp_path):
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nrequires:\n  servers: [surge, pypsa]\n"
                          "tools: [surge.run_dc_power_flow, pypsa.optimize_network]\n")
    m = parse_manifest(p)
    assert set(m.servers) == {"surge", "pypsa"} and len(m.tools) == 2


def test_g7_ignores_tools_without_dot(tmp_path):
    """没有点的工具名（畸形）不参与前缀判定 —— 那是另一类问题，不在这里误报。"""
    p = _write(tmp_path, "demo", _MINIMAL + "\ntools: [没有点的名字]\n")
    assert parse_manifest(p).tools == ("没有点的名字",)


def test_g8_l0_with_l1_content_is_refused(tmp_path):
    """★ G-8：`maturity: L0`（仅声明式）却填了 entities —— 声明与实际不符。"""
    p = _write(tmp_path, "demo",
               _MINIMAL + "\nentities:\n  - id: e\n    schema: ./schema/s.json\n")
    (tmp_path / "demo" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "demo" / "schema" / "s.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "声明与实际不符" in str(ei.value) or "L0" in str(ei.value)


def test_g8_l2_without_slots_is_refused(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL.replace("maturity: L0", "maturity: L2"))
    with pytest.raises(ModuleError) as ei:
        parse_manifest(p)
    assert "L2" in str(ei.value)


def test_g8_l1_with_entities_passes(tmp_path):
    p = _write(tmp_path, "demo",
               _MINIMAL.replace("maturity: L0", "maturity: L1")
               + "\nentities:\n  - id: e\n    schema: ./schema/s.json\n")
    (tmp_path / "demo" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "demo" / "schema" / "s.json").write_text("{}", encoding="utf-8")
    assert parse_manifest(p).maturity == "L1"


def test_g8_l1_without_entities_passes(tmp_path):
    """L1 但没填 entities 只是「声明得比实际高」，无害 —— 不拒绝。"""
    p = _write(tmp_path, "demo", _MINIMAL.replace("maturity: L0", "maturity: L1"))
    assert parse_manifest(p).maturity == "L1"


# ---------------------------------------------------------------- 校验补强 G-9 / G-10
# 这两条是**外部名字**尺度 → 只警告不拒绝（与 requires.servers / skills 的既有尺度一致）

def test_g9_unknown_server_prefix_in_tools_is_warned(tmp_path):
    """★ G-9：原先只校验 `requires.servers` 的已知性，tools 里写错 server 毫无提示。"""
    _write(tmp_path, "demo",
           _MINIMAL + "\nrequires:\n  servers: [不存在的server]\n"
                      "tools: [不存在的server.某工具]\n")
    rep = load_modules(tmp_path, known_servers=("surge",))
    assert rep.failures == (), "外部名字只警告，不装配失败"
    joined = " ".join(rep.notes)
    assert "tools` 引用了未知 server" in joined


def test_g9_known_servers_produce_no_warning(tmp_path):
    _write(tmp_path, "demo",
           _MINIMAL + "\nrequires:\n  servers: [surge]\ntools: [surge.run_dc_power_flow]\n")
    rep = load_modules(tmp_path, known_servers=("surge",))
    assert not any("未知 server" in n for n in rep.notes)


def test_g10_unknown_slot_is_warned_not_refused(tmp_path):
    """★ G-10：拼错的槽位名会静默失效；但**槽位清单尚未冻结**，故只警告。"""
    _write(tmp_path, "demo",
           _MINIMAL.replace("maturity: L0", "maturity: L2")
           + "\nslots:\n  - id: 拼错的槽位\n")
    rep = load_modules(tmp_path)
    assert rep.failures == ()
    assert any("未知槽位" in n and "尚未冻结" in n for n in rep.notes)


def test_g10_known_slot_produces_no_warning(tmp_path):
    _write(tmp_path, "demo",
           _MINIMAL.replace("maturity: L0", "maturity: L2")
           + "\nslots:\n  - id: nav.extra\n")
    rep = load_modules(tmp_path)
    assert rep.failures == ()
    assert not any("未知槽位" in n for n in rep.notes)


def test_slot_names_are_the_five_from_the_spec(tmp_path):
    """槽位清单与 UI 规范 §4.7.6 / 方案 v4 §3.3 保持一致。"""
    from powermcp_gateway.modules import SLOT_NAMES
    assert set(SLOT_NAMES) == {
        "nav.extra", "case.detail.tabs", "chat.result.after",
        "experiment.result.columns", "verification.extra",
    }


# ---------------------------------------------------------------- 真实模块仍合规

def test_real_modules_pass_the_new_rules():
    """★ 四条新规则不得把已有的两个真实模块判死 —— 否则是规则过严而非模块有错。"""
    rep = load_modules(modules_root(GatewayConfig.discover()),
                       known_servers=("surge", "pandapower", "pypsa", "powerio",
                                      "andes", "egret", "opendss", "hope", "genx"))
    assert rep.failures == (), f"真实模块被新规则判死：{rep.failures}"
    assert len(rep.modules) == 2
    assert not any("未知 server" in n or "未知槽位" in n for n in rep.notes)


# ---------------------------------------------------------------- G-1 / G-2 / G-5 清单补口（2026-09-25 裁决）

def test_g1_sample_cases_are_parsed(tmp_path):
    """★ G-1：默认算例字段 —— 指向算例库 id 或路径，运行时数据，不做存在性校验。"""
    p = _write(tmp_path, "demo", _MINIMAL + "\nsample_cases:\n  - examples/data/case39.m\n  - case39\n")
    assert parse_manifest(p).sample_cases == ("examples/data/case39.m", "case39")


def test_g1_sample_cases_single_string_is_accepted(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL + "\nsample_cases: examples/data/case39.m\n")
    assert parse_manifest(p).sample_cases == ("examples/data/case39.m",)


def test_g1_sample_cases_bad_type_is_error(tmp_path):
    p = _write(tmp_path, "demo", _MINIMAL + "\nsample_cases: 123\n")
    with pytest.raises(ModuleError, match="sample_cases"):
        parse_manifest(p)


def _module_with_result_table(tmp_path, extra: str = "") -> Path:
    """L1 模块：一个 result_table + 可选的 checks / columns_source 片段。"""
    (tmp_path / "demo" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "demo" / "schema" / "cols.json").write_text("[]", encoding="utf-8")
    body = (
        _MINIMAL.replace("maturity: L0", "maturity: L1")
        + "\nresult_tables:\n  - id: rt1\n    columns: ./schema/cols.json\n" + extra
    )
    return _write(tmp_path, "demo", body)


def test_g2_columns_source_is_kept_in_detail(tmp_path):
    """★ G-2：columns_source 声明「列由数据决定」，值 = 展开维度列名；渲染在内核。"""
    p = _module_with_result_table(tmp_path, "    columns_source: engine\n")
    rt = parse_manifest(p).result_tables[0]
    assert rt.detail["columns_source"] == "engine"


def test_g2_columns_source_must_be_nonempty_string(tmp_path):
    for bad in ("123", '""', "true"):
        p = _module_with_result_table(tmp_path, f"    columns_source: {bad}\n")
        with pytest.raises(ModuleError, match="columns_source"):
            parse_manifest(p)


def _check_file(tmp_path, name: str = "my_check.py", body: str | None = None) -> None:
    d = tmp_path / "demo" / "checks"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body or "", encoding="utf-8")


def test_g5_check_result_table_must_reference_declared_table(tmp_path):
    """★ G-5：`checks[].result_table` 引用未声明的 result_table → 装配失败（清单内部一致性）。"""
    _check_file(tmp_path)
    extra = (
        "checks:\n  - id: c1\n    file: ./checks/my_check.py\n    result_table: 不存在的表\n"
    )
    p = _module_with_result_table(tmp_path, extra)
    with pytest.raises(ModuleError, match="不是本模块已声明的 result_table"):
        parse_manifest(p)


def test_g5_check_result_table_declared_table_passes(tmp_path):
    _check_file(tmp_path)
    extra = "checks:\n  - id: c1\n    file: ./checks/my_check.py\n    result_table: rt1\n"
    p = _module_with_result_table(tmp_path, extra)
    ck = parse_manifest(p).checks[0]
    assert ck.detail["result_table"] == "rt1"


def test_g5_check_without_result_table_is_allowed(tmp_path):
    """未绑定 check 允许声明（引擎会跳过并如实上报，见 test_checks.py）。"""
    _check_file(tmp_path)
    extra = "checks:\n  - id: c1\n    file: ./checks/my_check.py\n"
    p = _module_with_result_table(tmp_path, extra)
    assert parse_manifest(p).checks[0].detail.get("result_table") is None


def test_g5_bare_on_key_is_boolean_trapped_so_we_use_result_table(tmp_path):
    """★ 为什么绑定键不叫 `on`：YAML 1.1 把裸键 `on` 解析成 True —— 绑定会静默失效。"""
    _check_file(tmp_path)
    extra = "checks:\n  - id: c1\n    file: ./checks/my_check.py\n    on: rt1\n"
    p = _module_with_result_table(tmp_path, extra)
    ck = parse_manifest(p).checks[0]
    assert True in ck.detail and "on" not in ck.detail   # `on` 已被 YAML 吃掉


# ---------------------------------------------------------------- G-4：prompts 接线


def _write_prompt_module(root, mid: str, *, enabled: bool = True,
                         text: str = "请始终检查单位。") -> None:
    d = root / mid
    (d / "prompts").mkdir(parents=True, exist_ok=True)
    (d / "prompts" / "p.md").write_text(text, encoding="utf-8")
    enabled_line = "enabled: true" if enabled else "enabled: false"
    (d / "module.yaml").write_text(
        _MINIMAL + f"{enabled_line}\nprompts:\n  - id: p1\n    file: ./prompts/p.md\n",
        encoding="utf-8",
    )


def test_prompt_supplement_collects_enabled_module_prompts(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _write_prompt_module(tmp_path, "demo")
    out = build_prompt_supplement(cfg)
    assert "demo" in out and "请始终检查单位。" in out


def test_prompt_supplement_empty_when_no_modules(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path / "不存在"))
    assert build_prompt_supplement(cfg) == ""


def test_prompt_supplement_excludes_disabled_modules(tmp_path, monkeypatch, cfg):
    """★ 全部禁用 → 空串：内核行为与无模块时一致（自证条件不被提示词破坏）。"""
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _write_prompt_module(tmp_path, "demo", enabled=False)
    assert build_prompt_supplement(cfg) == ""


def test_prompt_supplement_skips_unreadable_file(tmp_path, monkeypatch, cfg):
    """装配后被删的提示词 → 跳过并 warning，不让一个坏文件打断补充。"""
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _write_prompt_module(tmp_path, "demo")
    (tmp_path / "demo" / "prompts" / "p.md").unlink()
    assert build_prompt_supplement(cfg) == ""


def test_prompt_supplement_truncates_overlong_input(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _write_prompt_module(tmp_path, "demo", text="长" * (PROMPT_SUPPLEMENT_LIMIT + 100))
    out = build_prompt_supplement(cfg)
    assert len(out) <= PROMPT_SUPPLEMENT_LIMIT + 100   # 正文截断 + 截断说明
    assert "截断" in out
