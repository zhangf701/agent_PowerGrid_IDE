"""算例库端点（`/cases`）的测试。

★ 最重要的一条：`DELETE /cases/{id}` **不得删除源文件** —— 数据安全底线。
★ 错误映射：缺字段 400 · 路径不存在 400 · 未知 id 404 · 索引损坏 500 · 配置失败 503。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
from powermcp_gateway.api import create_app
from powermcp_gateway.config import ConfigError, GatewayConfig


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def cases_env(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(root))
    return root


@pytest.fixture
def app(cfg, cases_env):
    return create_app(cfg=cfg)


@pytest.fixture
def case_file(tmp_path):
    p = tmp_path / "data" / "case39.m"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MPC\n")
    return p


async def _req(app, method: str, path: str, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


async def test_routes_are_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/cases", "/cases/{cid}"} <= paths
    methods = {
        (getattr(r, "path", ""), m)
        for r in app.routes for m in getattr(r, "methods", set())
    }
    assert ("/cases", "GET") in methods and ("/cases", "POST") in methods
    assert ("/cases/{cid}", "GET") in methods and ("/cases/{cid}", "DELETE") in methods


# ---------------------------------------------------------------- 登记


async def test_list_empty(app):
    r = await _req(app, "GET", "/cases")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total"] == 0
    assert body["cases"] == []
    assert body["index_exists"] is False


async def test_register_creates_and_returns_201(app, case_file):
    r = await _req(app, "POST", "/cases",
                   json={"path": str(case_file), "label": "IEEE 39", "tags": ["ieee"]})
    assert r.status_code == 201
    body = r.json()
    assert body["created"] is True
    assert body["case"]["label"] == "IEEE 39"
    assert body["case"]["tags"] == ["ieee"]
    assert body["case"]["drift"] is False
    assert body["case"]["available"] is True


async def test_register_same_path_returns_200_not_201(app, case_file):
    await _req(app, "POST", "/cases", json={"path": str(case_file), "label": "A"})
    r = await _req(app, "POST", "/cases", json={"path": str(case_file), "label": "B"})
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert (await _req(app, "GET", "/cases")).json()["summary"]["total"] == 1


async def test_register_missing_path_field_is_400(app):
    for payload in ({}, {"path": ""}, {"path": "   "}, {"path": 123}):
        r = await _req(app, "POST", "/cases", json=payload)
        assert r.status_code == 400, payload
        assert "path" in r.json()["detail"]


async def test_register_bad_types_are_400(app, case_file):
    for payload in (
        {"path": str(case_file), "label": 5},
        {"path": str(case_file), "notes": []},
        {"path": str(case_file), "tags": "ieee"},
        {"path": str(case_file), "tags": [1, 2]},
    ):
        r = await _req(app, "POST", "/cases", json=payload)
        assert r.status_code == 400, payload


async def test_register_nonexistent_file_is_400(app, tmp_path):
    r = await _req(app, "POST", "/cases", json={"path": str(tmp_path / "没有.m")})
    assert r.status_code == 400
    assert "不存在" in r.json()["detail"]


async def test_register_directory_is_400(app, tmp_path):
    r = await _req(app, "POST", "/cases", json={"path": str(tmp_path)})
    assert r.status_code == 400
    assert "必须是文件" in r.json()["detail"]


# ---------------------------------------------------------------- 详情


async def test_get_case_detail(app, case_file):
    cid = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()["case"]["id"]
    r = await _req(app, "GET", f"/cases/{cid}")
    assert r.status_code == 200
    assert r.json()["id"] == cid


async def test_get_unknown_case_is_404(app):
    r = await _req(app, "GET", "/cases/nope")
    assert r.status_code == 404


async def test_drift_is_reported_on_read(app, case_file):
    """★ 漂移必须**现算**：文件改了，列表里就该看到。"""
    cid = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()["case"]["id"]
    case_file.write_bytes(b"MPC CHANGED\n")
    assert (await _req(app, "GET", f"/cases/{cid}")).json()["drift"] is True
    assert (await _req(app, "GET", "/cases")).json()["summary"]["drifted"] == 1


async def test_unreadable_by_servers_is_reported(app, case_file, monkeypatch):
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOTS", raising=False)
    cid = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()["case"]["id"]
    assert (await _req(app, "GET", f"/cases/{cid}")).json()["within_allowed_roots"] is False
    assert (await _req(app, "GET", "/cases")).json()["summary"]["unreadable_by_servers"] == 1

    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    assert (await _req(app, "GET", f"/cases/{cid}")).json()["within_allowed_roots"] is True


# ---------------------------------------------------------------- 注销（数据安全）


async def test_delete_unregisters_but_keeps_source_file(app, case_file):
    """★ 数据安全底线：DELETE 只注销登记，源文件必须原封不动。"""
    cid = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()["case"]["id"]

    r = await _req(app, "DELETE", f"/cases/{cid}")
    assert r.status_code == 200
    assert r.json()["unregistered"] == cid
    assert r.json()["source_file_kept"] is True

    assert case_file.is_file(), "源文件被删除了 —— 违反数据安全底线"
    assert case_file.read_bytes() == b"MPC\n"
    assert (await _req(app, "GET", "/cases")).json()["summary"]["total"] == 0


async def test_delete_unknown_is_404(app):
    assert (await _req(app, "DELETE", "/cases/nope")).status_code == 404


# ---------------------------------------------------------------- 失败映射


async def test_corrupt_index_is_500(app, cases_env, case_file):
    """索引损坏是**服务端数据问题** → 500，不是 400（不能怪客户端）。"""
    await _req(app, "POST", "/cases", json={"path": str(case_file)})
    (cases_env / "cases.json").write_text("{ 坏掉的 JSON", encoding="utf-8")
    r = await _req(app, "GET", "/cases")
    assert r.status_code == 500
    assert "索引损坏" in r.json()["detail"]


async def test_cases_is_503_when_config_unresolvable(app, monkeypatch):
    def boom():
        raise ConfigError("未找到 PowerMCP 仓库根")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    assert (await _req(app, "GET", "/cases")).status_code == 503


async def test_delete_on_corrupt_index_is_500(app, cases_env, case_file):
    cid = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()["case"]["id"]
    (cases_env / "cases.json").write_text("[]not json", encoding="utf-8")
    assert (await _req(app, "DELETE", f"/cases/{cid}")).status_code == 500


# ---------------------------------------------------------------- 报告形状


async def test_report_carries_notes_and_allowed_roots(app, case_file, monkeypatch):
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    await _req(app, "POST", "/cases", json={"path": str(case_file)})
    body = (await _req(app, "GET", "/cases")).json()

    assert body["allowed_roots"] == [str(case_file.parent)]
    assert any("绝不删除源文件" in n for n in body["notes"])
    assert any("within_allowed_roots" in n for n in body["notes"])
    assert json.dumps(body, ensure_ascii=False)  # 可序列化


# ---------------------------------------------------------------- 输入规范化（#6）


async def test_register_quoted_path_succeeds_and_reports_normalization(app, case_file):
    """★ #6 的回归：带引号的**已存在**文件必须登记成功，且**如实**报出归一化。"""
    r = await _req(app, "POST", "/cases", json={"path": '"%s"' % case_file})
    assert r.status_code == 201
    body = r.json()
    assert body["case"]["available"] is True
    assert "剥离首尾引号" in body["path_normalized"]
    assert body["path_used"] == str(case_file)


async def test_register_zero_width_path_succeeds(app, case_file):
    r = await _req(app, "POST", "/cases", json={"path": "\u200b" + str(case_file)})
    assert r.status_code == 201
    assert "剔除零宽字符" in r.json()["path_normalized"]


async def test_register_clean_path_reports_no_normalization(app, case_file):
    """★ 反向断言：干净路径**不得**出现 `path_normalized` ——
    否则字段恒真，等于给"已归一化"发假证书。"""
    body = (await _req(app, "POST", "/cases", json={"path": str(case_file)})).json()
    assert "path_normalized" not in body
    assert "path_used" not in body


async def test_register_dirty_nonexistent_path_400_is_actionable(app, tmp_path):
    """★ #6 的核心诉求：400 必须给出**可操作**线索，而不是只说"不存在"。"""
    ghost = tmp_path / "nope.m"
    r = await _req(app, "POST", "/cases", json={"path": '"%s"' % ghost})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "算例文件不存在" in detail
    assert "可疑字符" in detail and "引号" in detail
    assert "已自动归一化" in detail
    assert str(ghost) in detail          # 报出**实际检查**的是哪条路径


async def test_register_clean_nonexistent_path_400_has_no_false_hint(app, tmp_path):
    """★ 反向断言：干净路径的 400 **不得**出现可疑字符提示（防误报）。"""
    r = await _req(app, "POST", "/cases", json={"path": str(tmp_path / "nope.m")})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "算例文件不存在" in detail
    assert "可疑字符" not in detail
    assert "已自动归一化" not in detail

