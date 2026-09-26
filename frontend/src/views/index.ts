/** 视图统一出口 —— 一个视图一个文件（地基步的结构约定）。
 *
 *  ★ 为什么拆：单文件堆视图就是 MVP 的老路（~800 行、无复用、无边界）。
 *    拆开后每个视图可独立演进、独立测试，A/B 对照的差异也能归因到具体文件。
 *  ★ 迁移顺序（方案 §十 与《MVP 崩溃后技术栈评估》第 2 步）：
 *    ⑤ 技能手册（最独立、无流式）→ ② 算例库 → ③ 对话分析 + ⑥ 校验层（最复杂，最后）。
 */
export { EnvView } from "./EnvView";
export { SkillsView, filterSkills, healthParts } from "./SkillsView";
export { CasesView } from "./CasesView";
export { ChatView, applyChatFrame } from "./ChatView";
export type { Turn } from "./ChatView";
