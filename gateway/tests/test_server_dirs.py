import pytest

from powermcp_gateway.contracts.server_dirs import SERVER_DIRS

EXPECTED = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}


def test_mapping_matches_expected():
    assert SERVER_DIRS == EXPECTED


def test_powerio_is_intentionally_absent():
    """powerio 由自己的发行版提供，仓库内没有它的目录 —— 不是遗漏。"""
    assert "powerio" not in SERVER_DIRS


def test_is_single_source_of_truth():
    """★ 既有两处必须改为**引用**本模块，不得再各自持有副本。"""
    from powermcp_gateway.contracts import api_version, doc_impl

    assert api_version.SOURCE_DIRS is SERVER_DIRS
    assert doc_impl.SERVER_DOC_DIRS is SERVER_DIRS


def test_every_dir_exists_in_the_repo():
    from powermcp_gateway.config import GatewayConfig

    root = GatewayConfig.discover().powermcp_root
    for server, dirname in SERVER_DIRS.items():
        assert (root / dirname).is_dir(), f"{server} -> {dirname} 在仓库中不存在"
