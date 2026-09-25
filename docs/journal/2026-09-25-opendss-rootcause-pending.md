---
date: 2026-09-25
type: journal
keywords: [opendss, MCP SDK, ctypes LoadLibrary, 环境变量白名单, 根因定位, 待完成]
git_branch: master
previous: 2026-09-25-g1-g5-wiring.md
note: opendss 挂载失败根因**已定位**（SDK 白名单环境 → py_dss_interface 的 ctypes.LoadLibrary 无限挂死），修复未做（用户指示跳过）。证据链 m23~m31。
---

# opendss 挂载失败：根因定位（修复待完成，2026-09-25）

> 张老师指示：跳过后续排查、标记待完成，优先完成 MVP。本文记录已坐实的根因与修复方向。

## 一、结论

**根因**：网关 `inventory.fetch_server_tools` 用 mcp SDK 的 `stdio_client` 拉起子进程时，
SDK 未显式传 `env` → 回落到 `get_default_environment()` 的 **12 项白名单**。
在该受限环境下，`powermcp.cli run opendss` 子进程在

```
py_dss_interface/DSS.py:92  →  ctypes.LoadLibrary（加载 OpenDSS 引擎 DLL）
```

处**无限挂死**（faulthandler 实抓，25s 时栈停在 LoadLibrary），stdout 永远零字节 →
SDK 等不到 initialize 应答 → 网关报「90s 未完成 MCP 握手」。

**对照**：同一命令、同一 cwd，**完整环境**下 2.8~3.1s 完成完整握手，**55 个工具全部返回**。

## 二、证据链（探针在 `.superpowers/sdd/`，可复跑）

| 探针 | 证明 |
|---|---|
| m23 手工 initialize | 裸管道下 opendss 应答正常 → 推翻"协议坏了" |
| m24 完整握手（直连脚本） | 直连路径 3s 全通 55 工具 |
| m26 CLI 路径 vs 直连 | `python -m powermcp.cli run opendss` 手工管道同样 3s 全通 → **排除 CLI/脚本/协议层** |
| m27 SDK 最小复现 | SDK 层复现成立：SDK+pandapower ✅ 4.2s，SDK+opendss ❌ 挂（唯一变量 = SDK 客户端） |
| m28 环境 A/B | 白名单 env ❌ 挂；**完整 os.environ ✅ 2.81s** |
| m29 二分 | 任何「白名单+真子集」都挂 → **谓词非单调**（非单变量缺失，机械二分无效） |
| m30 受限子进程直测 | 白名单下子进程 15s 零字节（挂死在启动期，非客户端问题） |
| m31 faulthandler | **实抓挂死栈：`ctypes.LoadLibrary` ← `py_dss_interface/DSS.py:92` ← `OpenDSS/core/engine.py:6`** |

## 三、修复方向（待裁决，未实施）

1. **网关侧（最小改动）**：`fetch_server_tools` 的 `StdioServerParameters` 显式传更完整的
   `env`（如 `server_env()` 的思路扩展，或直接 `os.environ`）。⚠️ 这是一行级改动，
   但**环境策略是安全决策**（白名单是有意的收敛），需张老师裁决放多大。
2. **PowerMCP 侧（上游修复）**：`py_dss_interface` 的 DLL 加载懒化/容错（属上游仓库，冻结中）。
3. 具体缺哪个变量未知 —— m29 证明非单调（可能 LoadLibrary 依赖多个变量组合，或与
   桌面会话状态耦合）。若将来要精确定位：对 extras 做**逐项累加**（187 × 3s ≈ 10 分钟）而非二分。

## 四、影响面

- opendss 仍挂不上 → 契约 2/8 的 opendss 行、能力矩阵 OpenDSS 行维持现状；
- 其余 8 个开源 server 不受影响（pandapower/pypsa/surge/powerio 经同一路径正常）；
- **本发现本身是选题素材**（handoff_2026-09-24 所言"尚无解释的接口层失效"）——
  现在有了可复现的解释：**受限环境 × ctypes 原生库加载 = 静默挂死**。
