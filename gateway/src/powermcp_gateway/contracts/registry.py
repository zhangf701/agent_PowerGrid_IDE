"""契约求值器的协议与注册表。"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import CONTRACT_NAMES, ContractFinding


@runtime_checkable
class ContractEvaluator(Protocol):
    """一个契约的求值器。求值器必须是纯函数式：给定同样的输入，给出同样的输出。"""

    contract: int
    name: str
    timeframe: Literal["T0"]

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        ...


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._by_contract: dict[int, ContractEvaluator] = {}

    def register(self, evaluator: ContractEvaluator) -> None:
        n = evaluator.contract
        if n not in CONTRACT_NAMES:
            raise ValueError(f"契约编号必须是 1–8，收到 {n}")
        if n in self._by_contract:
            raise ValueError(
                f"契约 {n} 已注册（{self._by_contract[n].name}），不能重复注册 {evaluator.name}"
            )
        self._by_contract[n] = evaluator

    def all(self) -> tuple[ContractEvaluator, ...]:
        return tuple(self._by_contract[k] for k in sorted(self._by_contract))

    def get(self, contract: int) -> ContractEvaluator:
        return self._by_contract[contract]


REGISTRY = EvaluatorRegistry()
