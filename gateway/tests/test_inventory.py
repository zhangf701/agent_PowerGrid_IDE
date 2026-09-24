from types import SimpleNamespace

import pytest

from powermcp_gateway.inventory import (
    ServerFailure,
    ToolInventory,
    ToolRecord,
    _describe_error,
    _is_timeout,
    _timeout_error,
    build_inventory,
    install_hint_for,
)


def _fake_sdk_tool(name: str = "run_power_flow", schema: dict | None = None):
    return SimpleNamespace(
        name=name,
        description="Run a power flow.",
        input_schema=schema or {"properties": {"net": {"type": "string"}}, "required": ["net"]},
        output_schema=None,
    )


def test_from_sdk_maps_snake_case_fields():
    rec = ToolRecord.from_sdk("pandapower", _fake_sdk_tool())
    assert rec.server == "pandapower"
    assert rec.name == "run_power_flow"
    assert rec.input_schema["required"] == ["net"]
    assert rec.output_schema is None


def test_from_sdk_tolerates_missing_description():
    tool = _fake_sdk_tool()
    tool.description = None
    assert ToolRecord.from_sdk("pypsa", tool).description is None


def test_inventory_names_and_by_name():
    a = ToolRecord.from_sdk("pandapower", _fake_sdk_tool("load_network"))
    b = ToolRecord.from_sdk("pypsa", _fake_sdk_tool("load_network"))
    c = ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf"))
    inv = ToolInventory(tools=(a, b, c), failures=())

    assert inv.names("pandapower") == ("load_network",)
    assert [r.server for r in inv.by_name("load_network")] == ["pandapower", "pypsa"]
    assert inv.by_name("nope") == ()


def test_inventory_is_hashable_and_serialisable():
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf")),),
        failures=(ServerFailure("genx", "RuntimeError: no julia"),),
    )
    assert inv.names("surge") == ("compute_lodf",)
    assert inv.failures[0].server == "genx"


@pytest.mark.integration
async def test_fetch_real_server():
    from powermcp_gateway.config import GatewayConfig
    from powermcp_gateway.inventory import fetch_server_tools

    cfg = GatewayConfig.discover()
    tools = await fetch_server_tools(cfg, "pandapower")
    assert len(tools) == 8
    assert "run_power_flow" in {t.name for t in tools}


# —— 失败原因的展开（契约 8 的 detail 必须可执行）——

def test_describe_error_unwraps_exception_group():
    """anyio 把子进程错误包在 ExceptionGroup 里，必须展开。

    真实案例：opendss 的契约 8 detail 曾只剩
    "ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)"，
    而真正可执行的 "pip install powermcp[opendss]" 被吞掉 ——
    这违反方案 §4.4「⚠️/❌ 必须给出可执行修复路径」。
    """
    inner = RuntimeError(
        "ANDES: required package 'andes' is not installed.\n"
        "  Install it with:  pip install powermcp[andes]"
    )
    group = ExceptionGroup("unhandled errors in a TaskGroup", [inner])

    text = _describe_error(group)

    assert "pip install powermcp[andes]" in text   # 可执行信息必须保住
    assert "RuntimeError" in text                  # 叶子异常类型必须保住
    assert "\n" not in text                        # 折叠为单行，便于徽章渲染


def test_describe_error_handles_plain_exception():
    assert _describe_error(ValueError("boom")) == "ValueError: boom"


def test_describe_error_handles_nested_groups():
    inner = ExceptionGroup("inner", [KeyError("k")])
    outer = ExceptionGroup("outer", [inner, TimeoutError("t")])
    text = _describe_error(outer)
    assert "KeyError" in text
    assert "TimeoutError" in text


def test_describe_error_deduplicates_repeated_leaves():
    dup = RuntimeError("same")
    group = ExceptionGroup("g", [dup, RuntimeError("same")])
    assert _describe_error(group).count("same") == 1


async def test_build_inventory_surfaces_grouped_reason(monkeypatch):
    """build_inventory 归集失败时，必须把 ExceptionGroup 展开后写入 failures。"""

    async def boom(cfg, server, timeout_s=None):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [RuntimeError("Install it with:  pip install powermcp[opendss]")],
        )

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    inv = await build_inventory(cfg=None, servers=["opendss"])  # type: ignore[arg-type]

    assert len(inv.failures) == 1
    assert inv.failures[0].server == "opendss"
    assert "pip install powermcp[opendss]" in inv.failures[0].error


# —— 超时路径也必须可执行（asyncio.timeout 原生抛出的 TimeoutError 消息为空）——

def test_is_timeout_detects_plain_timeout():
    assert _is_timeout(TimeoutError()) is True


def test_is_timeout_detects_nested_timeout():
    """anyio 的清理异常可能把 TimeoutError 包在 ExceptionGroup 里。"""
    group = ExceptionGroup("g", [RuntimeError("x"), TimeoutError()])
    assert _is_timeout(group) is True


def test_is_timeout_rejects_other_errors():
    assert _is_timeout(RuntimeError("x")) is False
    assert _is_timeout(ExceptionGroup("g", [ValueError("v")])) is False


def test_timeout_error_carries_server_and_stage():
    """超时异常必须自带上文 —— 否则契约 8 的 detail 退化成 "TimeoutError:"。"""
    err = _timeout_error("opendss", 90.0)
    text = _describe_error(err)

    assert "opendss" in text                      # 哪个 server
    assert "90s" in text                          # 等了多久
    assert "握手" in text                          # 卡在哪一阶段
    assert text != "TimeoutError:"                # 不再是无信息的空消息


# —— ★ 完成标准 #5：可执行修复路径从 registry 取，且只在"依赖缺失"时才给 ——

def test_install_hint_for_known_server_with_extra():
    hint, probe = install_hint_for("andes")
    assert hint == "pip install powermcp[andes]"
    assert probe == "andes"


def test_install_hint_for_core_server_has_no_extra():
    hint, probe = install_hint_for("pandapower")
    assert hint == "pip install powermcp"      # 核心包，无 extra
    assert probe == "pandapower"


def test_install_hint_for_unknown_server_is_none():
    hint, probe = install_hint_for("no_such_server")
    assert hint is None
    assert probe is None


def test_all_servers_includes_failed_ones():
    """★ 缺陷 B：未拉起的 server 不得从求值器视野里消失。"""
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("pandapower", _fake_sdk_tool()),),
        failures=(ServerFailure("opendss", "LaunchError: ..."),),
        requested=("pandapower", "opendss"),
    )
    assert inv.servers() == ("pandapower",)
    assert inv.all_servers() == ("opendss", "pandapower")


def test_all_servers_falls_back_without_requested():
    """未显式传 requested 时，用 tools ∪ failures 兜底，失败 server 仍不丢。"""
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf")),),
        failures=(ServerFailure("genx", "boom"),),
    )
    assert inv.all_servers() == ("genx", "surge")


async def test_build_inventory_records_hint_on_dependency_failure(monkeypatch):
    """拉起失败且**看起来是依赖缺失**时，failure 必须带上可执行修复路径（方案 §4.4）。"""

    async def boom(cfg, server, timeout_s=None):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [
            RuntimeError("ANDES: required package 'andes' is not installed. "
                         "Install it with: pip install powermcp[andes]"),
        ])

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    result = await build_inventory(cfg=None, servers=["andes"])  # type: ignore[arg-type]

    assert result.requested == ("andes",)
    assert result.all_servers() == ("andes",)
    f = result.failures[0]
    assert "pip install powermcp[andes]" in f.error     # 摊平后的真实原因
    assert f.hint == "pip install powermcp[andes]"      # 结构化修复路径


async def test_timeout_failure_gets_no_install_hint(monkeypatch):
    """超时不是依赖缺失 —— 给安装提示是误导。

    方案 §4.4 要的是"**可执行**修复路径"，不是"随便给条命令"。
    """

    async def boom(cfg, server, timeout_s=None):
        raise TimeoutError("opendss 在 90s 内未完成 MCP 握手")

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    result = await build_inventory(cfg=None, servers=["opendss"])  # type: ignore[arg-type]

    assert result.failures[0].hint is None
