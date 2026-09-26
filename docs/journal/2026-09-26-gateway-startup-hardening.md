---
date: 2026-09-26
type: journal
keywords: [启动脚本, 路径围笼, DEEPSEEK_API_KEY, run_gateway, 闪退修复, ANDES根放行, 工作区脏]
git_branch: master
previous: 2026-09-25-serverpool-t6m5.md
note: 补记 8064da6 之后的启动脚本加固三连（路径围笼 / key 映射 / 闪退修复）+ 未提交的 ANDES 根放行补丁。双击即可带 LLM 起网关。
---

# 网关启动脚本加固（路径围笼 + key 映射 + 闪退修复 + ANDES 根放行）

> 本篇补记 `handoff_2026-09-25_workbench-p0-and-mvp.md` 与 `_index.md` 滞后未收录的启动脚本改动。
> 合并三个已提交提交（`ea0fb14` / `68bb475` / `48dc354`）+ 一个**尚未提交**的工作区补丁。

## 一、动因

- 此前起网关需手动在 shell 里设 `POWERIO_MCP_ALLOWED_ROOTS` 与 `DEEPSEEK_API_KEY`，双击 `run_gateway.cmd` 不可行。
- 张老师双击 `run_gateway.cmd` 后窗口**一闪而过**：cmd.exe 对 UTF-8 + LF 的批处理解析错乱（中文注释变乱码命令、变量赋值失效、`python` 路径为空）。
- ANDES 接入（`6f5d454`）后发现：ANDES 输出根在 `%USERPROFILE%\.powermcp`，被路径围笼挡在根外 → `PathNotAllowed`。

## 二、设计与改动

| 提交 | 内容 |
|---|---|
| `ea0fb14` | 新增 `run_gateway.cmd` / `run_gateway.sh`：自含 `POWERIO_MCP_ALLOWED_ROOTS=项目根`（实测可读 `examples/data` 与 `GridData/MatpowerData`，见 `m20-allowed-roots.py`：case30.m 解析 51215 字符、根外路径被拦）+ LLM 走环境变量 |
| `68bb475` | 自动映射 `DEEPSEEK_API_KEY` → `POWERMCP_LLM_API_KEY`（值不打印、不落盘），双击即带 LLM，避免 `/chat` 503 |
| `48dc354` | `run_gateway.cmd` 重写为**纯 ASCII + CRLF**，`cmd //c` 实测可启动；退出 `pause` 留存窗口（网关异常退出能看到错误码） |
| **未提交** | 路径围笼从「仅项目根」扩为「项目根 + `%USERPROFILE%\.powermcp`」——为 ANDES 输出根放行；`gateway/run_gateway.cmd` / `.sh` 已 modified 但未 `git add` |

## 三、验证

- `m20-allowed-roots.py`：case30.m 解析 51215 字符成功；根外路径被 `PathNotAllowed` 拦。
- `run_gateway.cmd` 经 `cmd //c` 实测正常拉起网关。
- `PowerMCP/` · `PowerSkills/` 0 行改动 ✓。

## 四、状态与待办

- 前三个提交已入 `master`；**ANDES 根放行补丁仍在工作区（脏）**，建议尽快提交（见 `2026-09-26-ands-access-toolface.md`）。
- ⚠️ 根目录 `examples/` 始终未纳入版本控制（`git log -- examples/` 全空）——启动脚本依赖它，建议纳入或显式 gitignore。
