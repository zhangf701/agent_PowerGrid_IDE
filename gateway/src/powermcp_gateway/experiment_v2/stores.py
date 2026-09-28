"""V2 提案索引和观察结果存储。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from .models import ExperimentProposal, Observation


class StoreError(RuntimeError):
    pass


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))


class ProposalStore:
    """本地 JSON 提案索引；写入采用临时文件替换。"""

    filename = "proposals.json"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def path(self) -> Path:
        return self.root / self.filename

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"提案索引损坏：{self.path}") from exc
        if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
            raise StoreError("提案索引必须是 JSON 对象数组")
        return data

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(_dump(rows), encoding="utf-8")
        os.replace(tmp, self.path)

    def create(self, proposal: ExperimentProposal | Mapping[str, Any]) -> ExperimentProposal:
        proposal = proposal if isinstance(proposal, ExperimentProposal) else ExperimentProposal.from_dict(proposal)
        rows = self._load()
        if any(row.get("proposal_id") == proposal.proposal_id for row in rows):
            raise StoreError(f"proposal_id 已存在：{proposal.proposal_id}")
        rows.append(proposal.to_dict())
        self._write(rows)
        return proposal

    save = create

    def get(self, proposal_id: str) -> ExperimentProposal:
        for row in self._load():
            if row.get("proposal_id") == proposal_id:
                return ExperimentProposal.from_dict(row)
        raise KeyError(proposal_id)

    def list(self) -> tuple[ExperimentProposal, ...]:
        return tuple(ExperimentProposal.from_dict(row) for row in self._load())

    def delete(self, proposal_id: str) -> ExperimentProposal:
        rows = self._load()
        for index, row in enumerate(rows):
            if row.get("proposal_id") == proposal_id:
                removed = ExperimentProposal.from_dict(row)
                del rows[index]
                self._write(rows)
                return removed
        raise KeyError(proposal_id)


class ObservationStore:
    """一条 Observation 一行的追加式 JSONL 存储。"""

    filename = "observations.jsonl"

    def __init__(self, root_or_path: str | Path) -> None:
        value = Path(root_or_path)
        self.path = value if value.suffix == ".jsonl" else value / self.filename

    def append(self, observation: Observation | Mapping[str, Any]) -> Observation:
        observation = observation if isinstance(observation, Observation) else Observation.from_dict(observation)
        if not observation.observation_id or not observation.cell_id:
            raise StoreError("observation_id 和 cell_id 必填")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return observation

    def extend(self, observations: Iterable[Observation | Mapping[str, Any]]) -> int:
        count = 0
        for observation in observations:
            self.append(observation)
            count += 1
        return count

    def iter_observations(self) -> Iterator[Observation]:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise StoreError(f"观察 JSONL 第 {line_number} 行损坏") from exc
                    if not isinstance(data, dict):
                        raise StoreError(f"观察 JSONL 第 {line_number} 行不是对象")
                    yield Observation.from_dict(data)
        except OSError as exc:
            raise StoreError(f"无法读取观察存储：{self.path}") from exc

    def all(self) -> tuple[Observation, ...]:
        return tuple(self.iter_observations())

    def get(self, observation_id: str) -> Observation:
        for observation in self.iter_observations():
            if observation.observation_id == observation_id:
                return observation
        raise KeyError(observation_id)

    def query(self, *, cell_id: str | None = None, status: str | None = None,
              case_id: str | None = None, predicate: Callable[[Observation], bool] | None = None,
              **metric_equals: Any) -> tuple[Observation, ...]:
        result: list[Observation] = []
        for observation in self.iter_observations():
            if cell_id is not None and observation.cell_id != cell_id:
                continue
            if status is not None and observation.execution.get("status") != status:
                continue
            if case_id is not None and observation.inputs.get("case_id") != case_id:
                continue
            if any(observation.metrics.get(key) != value for key, value in metric_equals.items()):
                continue
            if predicate is not None and not predicate(observation):
                continue
            result.append(observation)
        return tuple(result)


ObservationJSONLStore = ObservationStore
