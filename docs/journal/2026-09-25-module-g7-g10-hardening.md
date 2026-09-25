---
date: 2026-09-25
type: journal
keywords: [模块校验, G-7, G-8, G-9, G-10, 变异探针, 清单一致性, maturity, 槽位]
git_branch: master
git_head: 95c849d
previous: handoff_2026-09-25_workbench-p0-and-mvp.md
note: G-7~G-10 四条校验缺口的补强单元 —— 4 条装配规则 + 14 条测试 + 变异探针 5/5 全红 + 文档同步。
---

# 模块校验补强 G-7~G-10（提交 `95c849d`）

## 一、来源

`modules/README.md` §四 记录的 4 条**校验缺口**（由两个真实模块的验证过程暴露，
复现脚本 `.superpowers/sdd/m15-module-gaps.py` 逐条实测）：

| # | 缺口（修复前实测） |
|---|---|
| G-7 | `servers: [surge]` + `tools: [pypsa.*]` → 装配成功，无提示（清单自相矛盾） |
| G-8 | `maturity: L0` 却填了 `entities` → 装配成功（声明与实际不符） |
| G-9 | `tools: [不存在的server.某工具]` → 无任何提示 |
| G-10 | 写任意槽位名都通过（前端注入时会静默失效） |

## 二、修法（`gateway/src/powermcp_gateway/modules.py`）

**沿用既有两条校验尺度**（见 modules.py 模块 docstring）：

- **清单内部的一致性** → **装配失败**：
  - **G-7**：`tools` 的 `server.` 前缀必须被 `requires.servers` 覆盖，否则报"清单自相矛盾"。
    ⚠️ 只在 `requires.servers` **非空**时判定 —— 「只用 tools、不写 servers」不拦，
    改为在 `load_modules` 里**警告**提示补声明（避免一刀切掉合法写法）。
  - **G-8**：`maturity` 与实际内容一致性 —— `L0` 含 `entities`/`result_tables`/`slots` 即失败；
    `L2` 无 `slots` 即失败（`L1` 没填 entities 只是"声明得比实际高"，无害，不拒）。
- **外部系统的名字** → **警告**：
  - **G-9**：`tools` 前缀引用未知 server → 警告（与 `requires.servers` 的已知性警告同尺度）。
  - **G-10**：未知槽位名 → 警告。**槽位清单尚未冻结**，故不拒绝；
    已知槽位固化为 `SLOT_NAMES` 五元组（`nav.extra` / `case.detail.tabs` /
    `chat.result.after` / `experiment.result.columns` / `verification.extra`，
    与 UI 规范 §4.7.6 / 方案 v4 §3.3 一致），并有测试钉住这份一致性。

## 三、验证

| 项 | 结果 |
|---|---|
| 测试 | **447 passed, 2 deselected**（433 基线 + 14），无回归 |
| 变异探针 | **5/5 全红**（`.superpowers/sdd/m19-g710-mutation.py`：G-7 一条、G-8 两条、G-9/G-10 各一条） |
| 真实模块护栏 | `test_real_modules_pass_the_new_rules`：两个真实模块 0 失败、无未知 server/槽位告警 |
| 装配实测 | `build_report()` 复跑：2 模块 · 0 失败 · 0 告警 · 全 L1 ✓ |
| 上游 | `PowerMCP/` · `PowerSkills/` **0 行改动** ✓ |

## 四、过程记录（本单元经过两个会话才闭环）

1. **第一会话**（16:46，交接单写完之后）写了代码与 14 条测试，但**未提交、未写 journal、
   `modules/README.md` 未同步** —— 文档与代码一度不一致（缺口表仍标"拦不住"）。
2. **第二会话**（本会话）：复核 447 全绿 → 提交 `95c849d` → 补变异探针 → 同步 README
   §三/§四/§六 → 本 journal + 索引。

**变异探针自身的两个坑**（值得记住）：

- `subprocess` 调 pytest 时**必须** `[python.exe, "-m", "pytest", ...]` ——
  直接把 pytest 参数塞给 `python.exe` 会静默失败（退出码非 0 且无摘要行）。
- pytest 摘要行的计数在**词前面**且带逗号（`3 passed, 446 deselected`）——
  按 `token.endswith("passed")` 解析会一个都抓不到。
