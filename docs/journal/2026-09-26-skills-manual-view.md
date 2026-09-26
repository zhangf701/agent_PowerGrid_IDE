---
date: 2026-09-26
type: journal
keywords: [技能手册, /skills, 主区标签页, escalation触发表, 如实健康度, mvp]
git_branch: master
previous: 2026-09-25-serverpool-t6m5.md
note: 补记 2f58dd2 + 642c718：技能手册从折叠面板升级为主区标签页。张老师反馈侧栏难读。m18 e2e 通过。
---

# 技能手册视图（折叠面板 → 主区标签页）

## 一、动因

- 原 `/skills` 只有原始 JSON，张老师反馈**侧栏排版难读**。

## 二、设计与改动（均在 `frontend/mvp.html`）

| 提交 | 内容 |
|---|---|
| `2f58dd2` | 技能手册视图：折叠面板（aside）+ 筛选框（匹配 名称/描述/触发条件/手册名）；每技能 kind 徽标 + 描述（>160 字符截断，悬停看全文）+ escalation「观测 → 手册」逐行；健康度如实展示 `unknown` 与可计算信号（ltspice 缺 escalation 表等）——「没报异常」≠「都可靠」 |
| `642c718` | 升级为**主区标签页**（对话 / 技能手册）；卡片宽幅网格（`auto-fill ≥430px`），描述用 bodySm 完整展示（不再 160 字符截断）；escalation 改两列表格（触发条件 \| 缓解手册）；kind 中文化（工作流 / 工程 / meta）；筛选框与计数移入视图头部 |

## 三、验证

- `m18-mvp-e2e.sh` 全部断言通过（含真实 LLM 对话）。
- React 工程尚未起步，MVP 仍是前端唯一载体。

## 四、状态

- 已提交。接口冻结仍暂缓（见 handoff 9-25 待办）。
