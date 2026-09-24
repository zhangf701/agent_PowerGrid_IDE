"""server id → PowerMCP 仓库内目录名 —— **单一真源**。

本表原先在 `doc_impl.SERVER_DOC_DIRS` 与 `api_version.SOURCE_DIRS` 各有一份，
`api_version` 的注释还写着「与 doc_impl.SERVER_DOC_DIRS 同源」——
知道该同源却只写了注释，于是从"一处定义"退化成"两处手工同步 + 一句祈祷"。
新增第三个消费者（`status_mapping`）之前先抽取，否则必然断裂。

键一律是 `powermcp/registry.py` 的 `Tool.name`（小写 server id）。

⚠️ `powerio` 不在此表中：它由自己的发行版提供（`python -m powerio.mcp`），
   PowerMCP 仓库内没有它的目录。这不是遗漏。
"""

from __future__ import annotations

SERVER_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}
