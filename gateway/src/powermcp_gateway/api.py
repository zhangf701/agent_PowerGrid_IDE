"""网关 HTTP API。"""

from __future__ import annotations

import dataclasses

from fastapi import FastAPI, HTTPException

from .config import GatewayConfig
from .contracts.engine import T0Cache, evaluate_t0
from .inventory import build_inventory

# P1 只挂开源引擎（方案 v3 已移除全部商业引擎）
OPEN_SOURCE_SERVERS: tuple[str, ...] = (
    "pandapower", "pypsa", "surge", "andes",
    "egret", "opendss", "hope", "genx", "powerio",
)

_cache = T0Cache()


def create_app(cfg: GatewayConfig | None = None) -> FastAPI:
    app = FastAPI(title="PowerMCP Gateway", version="0.1.0")
    config = cfg

    def _cfg() -> GatewayConfig:
        nonlocal config
        if config is None:
            config = GatewayConfig.discover()
        return config

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/servers")
    async def servers() -> dict[str, list[str]]:
        return {"servers": list(OPEN_SOURCE_SERVERS)}

    @app.get("/contracts/t0")
    async def contracts_t0() -> dict:
        try:
            c = _cfg()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        inv = await build_inventory(c, OPEN_SOURCE_SERVERS)
        report = await evaluate_t0(inv, c, cache=_cache)
        return {
            "cache_key": report.cache_key,
            "evaluated_at": report.evaluated_at,
            "summary": dataclasses.asdict(report.summary),
            "findings": [dataclasses.asdict(f) for f in report.findings],
        }

    return app
