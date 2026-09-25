"""`cases.py` 的测试。

★ 三条最重要的断言：
  1. `unregister` **绝不删除源文件**（数据安全底线）；
  2. `view` 的 `drift` / `available` **现算**（存下来就会过期）；
  3. 索引损坏时**响亮报错**，不得静默当成空库（那会让用户以为算例全丢了）。
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from powermcp_gateway.cases import (
    MAX_HASH_BYTES,
    CaseError,
    CaseIndexError,
    CaseStore,
    allowed_root_paths,
    build_report,
    cases_root,
)
from powermcp_gateway.config import GatewayConfig


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "cases")


@pytest.fixture
def case_file(tmp_path):
    p = tmp_path / "src" / "case39.m"
    p.parent.mkdir(parents=True, exist_ok=True)
    # ★ 用 write_bytes 而非 write_text：Windows 上 write_text 会把 \n 翻成 \r\n，
    #   让"字节数"随平台变化，测试就不再是平台无关的。
    p.write_bytes(b"MPC\n")
    return p


# ---------------------------------------------------------------- 登记


def test_register_records_metadata(store, case_file):
    case, created = store.register(case_file, label="IEEE 39", tags=("ieee", "case39"))
    assert created is True
    assert case.label == "IEEE 39"
    assert case.format == "m"
    assert case.size == case_file.stat().st_size == 4
    assert len(case.sha256) == 64
    assert case.tags == ("ieee", "case39")
    assert case.registered_at.endswith("Z")
    assert len(case.id) == 12


def test_register_same_path_is_update_not_duplicate(store, case_file, monkeypatch):
    """★ 用**可控时钟**而非真实时间 —— 两次登记若落在同一秒，`_now()` 返回相同字符串，
      断言会被"时间分辨率"满足而失真（变异探针 M8 发现的测试缺陷）。
    """
    import powermcp_gateway.cases as cases_mod

    ticks = iter(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"])
    monkeypatch.setattr(cases_mod, "_now", lambda: next(ticks))

    first, created1 = store.register(case_file, label="A")
    second, created2 = store.register(case_file, label="B")

    assert created1 is True and created2 is False
    assert first.id == second.id
    assert second.label == "B"
    assert first.registered_at == "2026-01-01T00:00:00Z"
    assert second.registered_at == "2026-01-01T00:00:00Z", "原登记时间不得被覆盖"
    assert len(store.list()) == 1


def test_register_defaults_label_to_filename(store, case_file):
    case, _ = store.register(case_file)
    assert case.label == "case39.m"


def test_register_missing_path_raises(store, tmp_path):
    """★ 文件名刻意**不含**"不存在"二字 —— 否则断言会被路径本身满足而失真。

    （变异探针 M5 发现的测试缺陷：原用 `不存在.m`，删掉 exists 检查后
      `is_file()` 兜底报「必须是文件：…不存在.m」，仍含"不存在" → 假通过。）
    """
    missing = tmp_path / "ghost.m"
    assert not missing.exists()
    with pytest.raises(CaseError) as ei:
        store.register(missing)
    assert "不存在" in str(ei.value), f"应为「文件不存在」类错误，实际：{ei.value}"


def test_register_directory_raises(store, tmp_path):
    with pytest.raises(CaseError) as ei:
        store.register(tmp_path)
    assert "必须是文件" in str(ei.value)


def test_register_oversize_raises(store, case_file, monkeypatch):
    import powermcp_gateway.cases as cases_mod

    monkeypatch.setattr(cases_mod, "MAX_HASH_BYTES", 1)
    with pytest.raises(CaseError) as ei:
        store.register(case_file)
    assert "超过登记上限" in str(ei.value)


def test_case_id_is_stable_for_same_path(store, case_file):
    a, _ = store.register(case_file)
    store.unregister(a.id)
    b, _ = store.register(case_file)
    assert a.id == b.id


# ---------------------------------------------------------------- 读取


def test_get_unknown_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_list_on_missing_index_is_empty(store):
    assert store.list() == ()
    assert not store.index_path.exists()


def test_corrupt_index_is_loud_not_silent(store, case_file):
    """★ 索引损坏必须响亮 —— 静默当成空库会让用户以为算例全丢了。"""
    store.register(case_file)
    store.index_path.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.raises(CaseIndexError) as ei:
        store.list()
    assert "索引损坏" in str(ei.value)


def test_index_must_be_array(store, case_file):
    store.register(case_file)
    store.index_path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(CaseIndexError):
        store.list()


def test_index_error_is_distinct_type_from_input_error(store, tmp_path):
    """★ 两类失败必须是不同类型 —— 端点才能不靠匹配错误文本区分 400 / 500。"""
    assert issubclass(CaseIndexError, CaseError)
    with pytest.raises(CaseError) as ei:
        store.register(tmp_path / "不存在.m")
    assert not isinstance(ei.value, CaseIndexError)


def test_write_leaves_no_tmp_file(store, case_file):
    store.register(case_file)
    leftovers = list(store.root.glob("*.tmp"))
    assert leftovers == [], f"原子写入留下了临时文件：{leftovers}"


def test_index_is_human_readable_json(store, case_file):
    store.register(case_file)
    data = json.loads(store.index_path.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data[0]["format"] == "m"


# ---------------------------------------------------------------- 现状视图


def test_view_available_and_no_drift(store, case_file):
    case, _ = store.register(case_file)
    v = store.view(case, env={})
    assert v.available is True and v.drift is False
    assert v.current_size == case.size


def test_view_detects_content_drift(store, case_file):
    """★ 现算漂移：文件还在但内容变了 —— 存下来的标记会过期，必须每次比。"""
    case, _ = store.register(case_file)
    case_file.write_text("MPC CHANGED\n", encoding="utf-8")
    v = store.view(case, env={})
    assert v.available is True
    assert v.drift is True
    assert v.current_size != case.size


def test_view_detects_deleted_file(store, case_file, caplog):
    """★ 文件缺失是**常见情形**（算例被移走），不该走异常路径刷 warning ——
    故 `view()` 有 `is_file()` 快路径。变异探针 M4 发现：删掉该快路径后
    `stat()` 抛 OSError 被兜住，结果相同但**每次列清单都会刷告警**，故一并钉住。
    """
    case, _ = store.register(case_file)
    case_file.unlink()
    with caplog.at_level(logging.WARNING, logger="powermcp_gateway.cases"):
        v = store.view(case, env={})
    assert v.available is False and v.drift is False
    assert not caplog.records, (
        f"文件缺失不应产生「读取失败」告警（应由 is_file() 快路径处理）："
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_view_warns_on_real_read_failure(store, case_file, caplog, monkeypatch):
    """与上一条对照：**真正的读取失败**（文件在、但读不了）必须告警 —— 不得静默。"""
    import powermcp_gateway.cases as cases_mod

    case, _ = store.register(case_file)

    def boom(_path):
        raise OSError("模拟磁盘错误")

    monkeypatch.setattr(cases_mod, "_sha256_file", boom)
    with caplog.at_level(logging.WARNING, logger="powermcp_gateway.cases"):
        v = store.view(case, env={})
    assert v.available is False
    assert caplog.records, "真实读取失败必须告警（不得静默）"


def test_view_reports_server_readability(store, case_file):
    """★ 与 `config.server_env()` 同源 —— 否则会声称"可读"而 server 实际读不到。"""
    case, _ = store.register(case_file)
    assert store.view(case, env={}).within_allowed_roots is False
    inside = store.view(case, env={"POWERIO_MCP_ALLOWED_ROOTS": str(case_file.parent)})
    assert inside.within_allowed_roots is True


def test_allowed_root_paths_reads_same_source_as_server_env(tmp_path):
    env = {"POWERIO_MCP_ALLOWED_ROOTS": f"{tmp_path}{os.pathsep}{tmp_path / 'x'}"}
    roots = allowed_root_paths(env)
    assert roots[0] == tmp_path.resolve()
    assert len(roots) == 2


def test_allowed_root_paths_prefers_primary_over_legacy(tmp_path):
    env = {
        "POWERIO_MCP_ALLOWED_ROOTS": str(tmp_path / "primary"),
        "POWERIO_MCP_ROOT": str(tmp_path / "legacy"),
    }
    assert allowed_root_paths(env)[0] == (tmp_path / "primary").resolve()


def test_allowed_root_paths_empty_when_unset():
    assert allowed_root_paths({}) == ()


# ---------------------------------------------------------------- 注销（数据安全）


def test_unregister_never_deletes_source_file(store, case_file):
    """★ 数据安全底线：一个 HTTP 动词不该能删掉用户磁盘上的算例。"""
    case, _ = store.register(case_file)
    removed = store.unregister(case.id)
    assert removed.id == case.id
    assert case_file.is_file(), "源文件被删除了 —— 违反数据安全底线"
    assert store.list() == ()


def test_unregister_unknown_raises(store):
    with pytest.raises(KeyError):
        store.unregister("nope")


# ---------------------------------------------------------------- 根目录与报告


def test_cases_root_default_is_outside_powermcp(cfg, monkeypatch):
    """算例库必须落在 `~/.powermcp_gateway/`，**不得**混进上游的 `~/.powermcp/`。"""
    monkeypatch.delenv("POWERMCP_GATEWAY_CASES_ROOT", raising=False)
    root = cases_root(cfg)
    parts = root.parts
    assert root.name == "cases"
    assert ".powermcp_gateway" in parts
    assert ".powermcp" not in parts, "不得落在上游的 ~/.powermcp/ 下"


def test_cases_root_env_override(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path))
    assert cases_root(cfg) == tmp_path


def test_build_report_summary_and_notes(cfg, tmp_path, monkeypatch, case_file):
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    store = CaseStore(cases_root(cfg))
    store.register(case_file, label="A")

    r = build_report(cfg, env={"POWERIO_MCP_ALLOWED_ROOTS": str(case_file.parent)})
    assert r["summary"] == {
        "total": 1, "available": 1, "drifted": 0, "unreadable_by_servers": 0,
    }
    assert r["cases"][0]["within_allowed_roots"] is True
    assert any("绝不删除源文件" in n for n in r["notes"])
    assert r["index_exists"] is True


def test_build_report_counts_unreadable(cfg, tmp_path, monkeypatch, case_file):
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    CaseStore(cases_root(cfg)).register(case_file)
    r = build_report(cfg, env={})          # 未配置允许根
    assert r["summary"]["unreadable_by_servers"] == 1
    assert r["allowed_roots"] == []


def test_build_report_on_empty_store(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "空"))
    r = build_report(cfg, env={})
    assert r["summary"]["total"] == 0
    assert r["cases"] == [] and r["index_exists"] is False
    assert r["root"].endswith("空")
