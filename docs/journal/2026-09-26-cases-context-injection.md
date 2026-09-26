---
date: 2026-09-26
type: journal
keywords: [算例库, 上下文注入, build_case_context, /chat, 接线缺口, 张老师实测]
git_branch: master
previous: 2026-09-25-serverpool-t6m5.md
note: 补记 8ccae26：用户在界面登记/解析的算例注入对话上下文，模型不再瞎猜内置算例名。测试 498 → 500。
---

# 算例库现状注入对话上下文（v4 §4.3 数据源接线）

## 一、动因（张老师实测发现的接线缺口）

用户在界面登记 / 解析了算例，模型**完全不知道**，只能瞎猜内置算例名（返回 `__invalid__`）。根因：算例库与 `/chat` 的 system 消息之间没有接线。

## 二、设计（`gateway/src/powermcp_gateway/api.py`）

- 新增 `build_case_context()`：登记算例 → `label / id / format / 路径 / 已解析与否 / available · drift · within_allowed_roots` 现状，并入 chat 的 system 消息（与模块提示词同一条 system）；**算例库为空则不注入**。
- 指令明确：用户说「已解析」即指库内算例，直接按路径载入 —— 不要索要路径、不要猜内置算例名。
- chat 测试的 cases 根同步隔离（真实 HOME 的算例索引不再泄漏进测试）。

## 三、验证

- 单测 `test_api_chat.py` 增 72 行；全量 **498 → 500 passed**（无回归）。
- 上游 `PowerMCP/` · `PowerSkills/` 0 行改动 ✓。

## 四、状态

- 已提交。`/cases` 的 parse / diagnostics 仍未进审计（handoff 9-25 待办 #7）。
