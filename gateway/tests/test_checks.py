"""`checks.py`（G-5 契约 + 执行引擎）的测试。

★ 最重要的三条：
  1. **未绑定的 check 必须被跳过并如实上报** —— 引擎绝不拿空行跑出虚假的"通过"
     （UI 规范 §7.4「关闭必须彻底」在 check 侧的对应物）；
  2. **单个 check 崩溃 ≠ 通过** —— 记 error 级 Finding，其它 check 不受影响；
  3. 契约校验 fail-loud：缺 RULE_ID / SEVERITY 非法 / check 不可调用都要报清楚。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.modules import ENV_MODULES_ROOT, ModuleError, parse_manifest
from powermcp_gateway.checks import (
    CheckContext,
    CheckError,
    load_check_module,
    run_checks,
    run_module_checks,
)

_MANIFEST = """\
id: demo
name: 演示模块
version: 0.1.0
kind: research
maturity: L1
enabled: {enabled}
result_tables:
  - id: rt1
    columns: ./schema/cols.json
checks:
  - id: c_ok
    file: ./checks/ok_check.py
    result_table: rt1
{extra}
"""


def _setup(tmp_path: Path, *, enabled: bool = True, extra: str = "",
           ok_body: str | None = None) -> Path:
    (tmp_path / "demo" / "schema").mkdir(parents=True)
    (tmp_path / "demo" / "schema" / "cols.json").write_text("[]", encoding="utf-8")
    (tmp_path / "demo" / "checks").mkdir(parents=True)
    (tmp_path / "demo" / "checks" / "ok_check.py").write_text(
        ok_body if ok_body is not None else (
            'RULE_ID = "demo-rule"\n'
            'SEVERITY = "warning"\n'
            "def check(ctx):\n"
            "    return [f\"第 {i} 行有问题\" for i, r in enumerate(ctx.rows) if r.get('bad')]\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "demo" / "module.yaml").write_text(
        _MANIFEST.format(enabled=str(enabled).lower(), extra=extra), encoding="utf-8",
    )
    return tmp_path / "demo" / "module.yaml"


def _ctx(rows, table="rt1", mid="demo") -> CheckContext:
    return CheckContext(rows=rows, result_table=table, module_id=mid)


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


# ---------------------------------------------------------------- 契约校验


def test_missing_rule_id_is_loud(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("SEVERITY = 'warning'\ndef check(ctx):\n    return []\n", encoding="utf-8")
    with pytest.raises(CheckError, match="RULE_ID"):
        load_check_module(p)


def test_bad_severity_is_loud(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("RULE_ID = 'r'\nSEVERITY = '致命'\ndef check(ctx):\n    return []\n",
                 encoding="utf-8")
    with pytest.raises(CheckError, match="SEVERITY"):
        load_check_module(p)


def test_non_callable_check_is_loud(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("RULE_ID = 'r'\nSEVERITY = 'info'\ncheck = 42\n", encoding="utf-8")
    with pytest.raises(CheckError, match="check"):
        load_check_module(p)


def test_syntax_error_is_loud_not_a_crash(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def check(ctx)\n", encoding="utf-8")
    with pytest.raises(CheckError, match="执行失败"):
        load_check_module(p)


# ---------------------------------------------------------------- 执行与归一


def test_legacy_list_of_str_uses_module_severity(tmp_path):
    p = _setup(tmp_path)
    mod = parse_manifest(p)
    outcomes, skipped = run_module_checks(
        mod, tmp_path, rows_by_table={"rt1": [{"bad": True}]},
    )
    assert not skipped and len(outcomes) == 1
    f = outcomes[0].findings[0]
    assert (f.severity, f.rule_id, f.result_table) == ("warning", "demo-rule", "rt1")
    assert "第 0 行" in f.message


def test_empty_rows_and_clean_data_produce_no_findings(tmp_path):
    p = _setup(tmp_path)
    mod = parse_manifest(p)
    outcomes, _ = run_module_checks(mod, tmp_path, rows_by_table={"rt1": [{"bad": False}]})
    assert outcomes[0].findings == ()


def test_dict_findings_allow_severity_override(tmp_path):
    body = (
        'RULE_ID = "r"\nSEVERITY = "info"\n'
        "def check(ctx):\n"
        "    return [{'message': '严重问题', 'severity': 'error'}, {'message': '普通提示'}]\n"
    )
    p = _setup(tmp_path, ok_body=body)
    mod = parse_manifest(p)
    outcomes, _ = run_module_checks(mod, tmp_path, rows_by_table={"rt1": []})
    severities = [f.severity for f in outcomes[0].findings]
    assert severities == ["error", "info"]


def test_dict_finding_without_message_becomes_error(tmp_path):
    body = (
        'RULE_ID = "r"\nSEVERITY = "info"\n'
        "def check(ctx):\n"
        "    return [{'severity': 'warning'}]\n"
    )
    p = _setup(tmp_path, ok_body=body)
    mod = parse_manifest(p)
    outcomes, _ = run_module_checks(mod, tmp_path, rows_by_table={"rt1": []})
    f = outcomes[0].findings[0]
    assert f.severity == "error" and "message" in f.message


def test_non_list_return_is_an_error_not_silence(tmp_path):
    body = 'RULE_ID = "r"\nSEVERITY = "info"\ndef check(ctx):\n    return "没问题"\n'
    p = _setup(tmp_path, ok_body=body)
    mod = parse_manifest(p)
    outcomes, _ = run_module_checks(mod, tmp_path, rows_by_table={"rt1": []})
    assert outcomes[0].error and "str" in outcomes[0].error


def test_crashing_check_becomes_error_finding_and_does_not_block_others(tmp_path):
    """★ 单个 check 崩溃 ≠ 通过 —— error 级 Finding，同模块其它 check 照跑。"""
    p = _setup(
        tmp_path,
        extra="  - id: c_boom\n    file: ./checks/boom.py\n    result_table: rt1\n",
    )
    (tmp_path / "demo" / "checks" / "boom.py").write_text(
        'RULE_ID = "boom"\nSEVERITY = "info"\n'
        "def check(ctx):\n    raise ValueError('炸了')\n",
        encoding="utf-8",
    )
    mod = parse_manifest(p)
    assert len(mod.checks) == 2
    outcomes, _ = run_module_checks(mod, tmp_path, rows_by_table={"rt1": []})
    by_id = {o.check_id: o for o in outcomes}
    assert by_id["c_boom"].findings[0].severity == "error"
    assert "炸了" in by_id["c_boom"].findings[0].message
    assert by_id["c_ok"].error == ""                      # 另一个 check 不受影响


def test_unbound_check_is_skipped_not_run_on_empty_rows(tmp_path):
    """★ 未绑定 result_table → 跳过并如实上报 —— 绝不拿空行跑出虚假的"通过"。"""
    p = _setup(tmp_path, extra="  - id: c_free\n    file: ./checks/ok_check.py\n")
    mod = parse_manifest(p)
    outcomes, skipped = run_module_checks(mod, tmp_path, rows_by_table={"rt1": []})
    assert len(outcomes) == 1 and outcomes[0].check_id == "c_ok"
    assert len(skipped) == 1 and skipped[0]["check_id"] == "c_free"
    assert "result_table" in skipped[0]["reason"]


def test_missing_rows_for_bound_table_is_skipped(tmp_path):
    p = _setup(tmp_path)
    mod = parse_manifest(p)
    _, skipped = run_module_checks(mod, tmp_path, rows_by_table={})  # 没给 rt1 的行
    assert len(skipped) == 1 and "rt1" in skipped[0]["reason"]


# ---------------------------------------------------------------- 端点实现体


def test_run_checks_unknown_module_is_keyerror(tmp_path, monkeypatch, cfg: GatewayConfig):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    with pytest.raises(KeyError, match="不存在"):
        run_checks(cfg, module_id="ghost", rows_by_table={})


def test_run_checks_disabled_module_is_runtime_error(tmp_path, monkeypatch, cfg: GatewayConfig):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _setup(tmp_path, enabled=False)
    with pytest.raises(RuntimeError, match="禁用"):
        run_checks(cfg, module_id="demo", rows_by_table={"rt1": []})


def test_run_checks_summary_and_findings(tmp_path, monkeypatch, cfg: GatewayConfig):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    _setup(tmp_path)
    rep = run_checks(cfg, module_id="demo", rows_by_table={"rt1": [{"bad": True}]})
    assert rep["summary"]["checks_run"] == 1
    assert rep["summary"]["by_severity"]["warning"] == 1
    assert rep["results"][0]["rule_id"] == "demo-rule"
    assert rep["skipped"] == []


def test_run_checks_translates_assembly_failure(tmp_path, monkeypatch, cfg: GatewayConfig):
    """模块**装配失败**（如 checks 文件缺失）时如实转述，而不是笼统的"不存在"。"""
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    (tmp_path / "broken" / "checks").mkdir(parents=True)
    (tmp_path / "broken" / "module.yaml").write_text(
        "id: broken\nname: b\nversion: 0.1.0\n"
        "checks:\n  - id: c1\n    file: ./checks/缺失.py\n    result_table: x\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="装配失败"):
        run_checks(cfg, module_id="broken", rows_by_table={})
