"""V2 提案 -> 校验 -> commit -> 查询 API 验收。"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app
from powermcp_gateway.cases import CaseStore, cases_root
from powermcp_gateway.config import GatewayConfig


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    monkeypatch.setenv("POWERMCP_GATEWAY_EXPERIMENTS_ROOT", str(tmp_path / "exp"))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(tmp_path))
    return tmp_path


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def app(cfg, roots):
    return create_app(cfg=cfg)


@pytest.fixture
def case_id(cfg, roots):
    path = roots / "data" / "case39.m"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MPC\n")
    case, _ = CaseStore(cases_root(cfg)).register(path, label="IEEE 39")
    return case.id


async def _req(app, method: str, path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.request(method, path, **kwargs)


def _proposal(case_id: str) -> dict:
    return {
        "title": "V2 load scan",
        "research_question": {"id": "rq-1", "statement": "How does load change?"},
        "hypothesis": {"id": "hyp-1", "statement": "Loading increases."},
        "design": {"cases": [case_id], "factors": [{"name": "scale", "type": "number", "values": [1.0, 1.1]}]},
        "execution": {"steps": [{"server": "surge", "tool": "run_ac_power_flow", "args_template": {"file_path": "{case_path}", "scale": "{scale}"}}]},
        "observables": {"metrics": ["loading"]},
        "analysis": {"methods": ["summary", "extreme_cases"]},
    }


@pytest.mark.asyncio
async def test_proposal_validate_commit_and_frozen_detail(app, case_id):
    created = await _req(app, "POST", "/experiment-proposals", json=_proposal(case_id))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "needs_confirmation"
    assert body["validation"]["valid"] is True
    assert body["resource_estimate"]["cells"] == 2
    proposal_id = body["proposal"]["proposal_id"]

    validated = await _req(app, "POST", f"/experiment-proposals/{proposal_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["preview"]["cell_count"] == 2

    committed = await _req(app, "POST", f"/experiment-proposals/{proposal_id}/commit")
    assert committed.status_code == 201, committed.text
    experiment = committed.json()["experiment"]
    eid = experiment["eid"]
    assert experiment["schema_version"] == "2.0"
    assert len(experiment["cells"]) == 2
    assert all(cell["cell_id"] for cell in experiment["cells"])

    detail = await _req(app, "GET", f"/experiments/{eid}")
    assert detail.status_code == 200
    assert detail.json()["experiment"]["eid"] == eid
    assert detail.json()["summary"]["by_status"] == {"pending": 2}

    design = await _req(app, "GET", f"/experiments/{eid}/design")
    assert design.status_code == 200
    assert design.json()["resource_estimate"]["cells"] == 2


@pytest.mark.asyncio
async def test_invalid_proposal_is_rejected_before_storage(app, case_id):
    payload = _proposal(case_id)
    payload["execution"]["steps"][0]["args_template"] = {"x": "{unknown}"}
    response = await _req(app, "POST", "/experiment-proposals", json=payload)
    assert response.status_code == 400
    assert "unknown" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_v2_experiment_is_404(app):
    response = await _req(app, "GET", "/experiments/exp-does-not-exist/summary")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_v2_run_writes_observation_store(app, case_id, monkeypatch):
    import json
    import powermcp_gateway.api as api_mod
    from powermcp_gateway.inventory import ToolInventory, ToolRecord
    from powermcp_gateway.proxy import CallOutcome

    def record():
        return ToolRecord("surge", "run_ac_power_flow", None,
                          {"type": "object", "properties": {"file_path": {"type": "string"}}}, None)

    async def fake_inventory(*args, **kwargs):
        return ToolInventory(tools=(record(),), failures=(), requested=("surge",))

    async def fake_call(sid, server, tool, args, *, get_schema):
        return CallOutcome(ok=True, server=server, tool=tool, result={
            "content": [{"type": "text", "text": json.dumps({"loading": 99})}],
        })

    monkeypatch.setattr(api_mod, "build_inventory", fake_inventory)
    monkeypatch.setattr(api_mod, "call_with_contracts", fake_call)
    created = await _req(app, "POST", "/experiment-proposals", json=_proposal(case_id))
    proposal_id = created.json()["proposal"]["proposal_id"]
    committed = await _req(app, "POST", f"/experiment-proposals/{proposal_id}/commit")
    eid = committed.json()["experiment"]["eid"]
    run = await _req(app, "POST", f"/experiments/{eid}/run")
    assert run.status_code == 200, run.text
    assert run.json()["summary"]["completed"] == 2
    observations = await _req(app, "GET", f"/experiments/{eid}/observations")
    assert observations.status_code == 200
    assert len(observations.json()["observations"]) == 2
    results = await _req(app, "GET", f"/experiments/{eid}/results")
    assert results.status_code == 200
    assert results.json()["rows"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_v2_experiment_is_listed(app, case_id):
    """★ 回归 F-V2-1：V2 实验必须能出现在 `GET /experiments` 列表里。

    此前该端点 **500** —— `_v2_compat_experiment` 把 `steps[].args_template` 原样取自
    冻结的 `execution`（`MappingProxyType`），而 `list_experiments() -> dict` 会触发
    pydantic **严格**序列化 → `Unable to serialize unknown type: <class 'mappingproxy'>`。
    同一份数据在 `/experiments/{eid}`（无返回注解 → 宽松编码）却能 200，故此前无用例钉住。
    """
    created = await _req(app, "POST", "/experiment-proposals", json=_proposal(case_id))
    proposal_id = created.json()["proposal"]["proposal_id"]
    committed = await _req(app, "POST", f"/experiment-proposals/{proposal_id}/commit")
    eid = committed.json()["experiment"]["eid"]

    listing = await _req(app, "GET", "/experiments")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    ids = [item["id"] for item in body["experiments"]]
    assert eid in ids
    item = next(item for item in body["experiments"] if item["id"] == eid)
    # ★ 关键：args_template 必须是普通 dict（不是 mappingproxy），否则序列化会炸
    assert item["steps"][0]["args_template"] == {"file_path": "{case_path}", "scale": "{scale}"}


@pytest.mark.asyncio
async def test_proposals_commit_to_independent_experiments(app, case_id):
    """★ 回归（2026-09-28 张老师裁决）：每个提案 = 一个独立实验配置。

    同一执行定义 + 不同措辞的两个提案 → **两个不同 eid 的独立实验**（各自 201）；
    同一提案重复 commit → 复用（200 + `reused:true`，幂等不重跑）。
    （旧口径「同执行定义折叠成同一实验」已废弃 —— 用户视角里提案就是实验。）
    """
    first = await _req(app, "POST", "/experiment-proposals", json=_proposal(case_id))
    pid1 = first.json()["proposal"]["proposal_id"]
    committed1 = await _req(app, "POST", f"/experiment-proposals/{pid1}/commit")
    assert committed1.status_code == 201, committed1.text
    assert committed1.json()["reused"] is False
    eid1 = committed1.json()["experiment"]["eid"]

    other = _proposal(case_id)
    other["title"] = "另一个标题"
    other["research_question"] = {"id": "rq-2", "statement": "另一个研究问题？"}
    other["hypothesis"] = {"id": "hyp-2", "statement": "另一个假设。"}
    second = await _req(app, "POST", "/experiment-proposals", json=other)
    pid2 = second.json()["proposal"]["proposal_id"]
    assert pid2 != pid1, "不同措辞应派生出不同 proposal_id"

    committed2 = await _req(app, "POST", f"/experiment-proposals/{pid2}/commit")
    assert committed2.status_code == 201, committed2.text
    assert committed2.json()["reused"] is False
    eid2 = committed2.json()["experiment"]["eid"]
    assert eid2 != eid1, "不同提案必须得到独立实验（即使执行定义相同）"

    # 同一提案重复 commit → 幂等复用（200），eid 不变
    recommitted = await _req(app, "POST", f"/experiment-proposals/{pid2}/commit")
    assert recommitted.status_code == 200, recommitted.text
    assert recommitted.json()["reused"] is True
    assert recommitted.json()["experiment"]["eid"] == eid2


@pytest.mark.asyncio
async def test_proposals_can_accumulate_and_be_deleted(app, case_id):
    """★ 回归 F-V2-6：提案必须能**累积多个**、逐个提交/删除。

    此前只有「建一个 → 看一个 → 提交」的单值路径，且**没有列表/删除端点** ⇒
    用户无法新增第二个提案，体验上「只能新建一个，要建新的得先删旧的」。
    （`ProposalStore` 本来就支持多提案，缺的只是读出口与删除出口。）
    """
    for title in ("A", "B"):
        payload = _proposal(case_id)
        payload["title"] = title
        created = await _req(app, "POST", "/experiment-proposals", json=payload)
        assert created.status_code == 201, created.text

    listing = await _req(app, "GET", "/experiment-proposals")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 2
    assert {item["title"] for item in body["proposals"]} == {"A", "B"}
    assert all(item["committed_eid"] is None for item in body["proposals"])

    # 提交其中一个 → 列表里该提案带上对应 eid
    target = next(item for item in body["proposals"] if item["title"] == "A")
    committed = await _req(app, "POST", f"/experiment-proposals/{target['proposal_id']}/commit")
    assert committed.status_code == 201, committed.text
    eid = committed.json()["experiment"]["eid"]

    after_commit = await _req(app, "GET", "/experiment-proposals")
    refreshed = next(i for i in after_commit.json()["proposals"] if i["proposal_id"] == target["proposal_id"])
    assert refreshed["committed_eid"] == eid

    # 删掉另一个 → 总数减 1
    other = next(i for i in after_commit.json()["proposals"] if i["title"] == "B")
    removed = await _req(app, "DELETE", f"/experiment-proposals/{other['proposal_id']}")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True

    assert (await _req(app, "GET", "/experiment-proposals")).json()["total"] == 1

    # 删不存在的提案 → 404
    missing = await _req(app, "DELETE", "/experiment-proposals/proposal-nope")
    assert missing.status_code == 404

    # ★ 删**已 commit** 的提案：实验本身必须保留（不可变性不因删提案而破坏）
    kept = await _req(app, "DELETE", f"/experiment-proposals/{target['proposal_id']}")
    assert kept.status_code == 200
    assert kept.json()["experiment_kept"] == eid
    assert (await _req(app, "GET", f"/experiments/{eid}/design")).status_code == 200
