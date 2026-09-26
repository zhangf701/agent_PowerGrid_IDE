/** ⑤ 技能手册视图 —— 方案 v4 §4.5「方法与经验」。
 *
 *  ★ v4 相对 v3 最重要的补口：21 个技能在 v3 中**零覆盖**（`skill` 在《UI 设计规范》出现 0 次）。
 *  ★ 健康度**如实展示 unknown** —— 后端只报**可计算**信号，不转录人工审计结论；
 *    「没报异常」≠「都可靠」，这一点必须在界面上看得见。
 *  ★ 本步（地基）保持与 MVP 的 A/B 对照指标逐字符一致：
 *    技能卡数 · 触发表数 · 计数行 · 健康度 · 筛选行为 · 空态文案。
 */
import { useMemo, useState } from "react";

import { EmptyState, Input, SkillCard } from "../components";
import type { Skill, SkillsResponse } from "../api";

/** 筛选命中：名称 / 描述 / 触发表 / 手册名（与 MVP 同口径）。 */
export function filterSkills(skills: Skill[], q: string): Skill[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return skills;
  return skills.filter((sk) => {
    const hay = [
      sk.id,
      sk.name,
      sk.kind,
      sk.description ?? "",
      ...(sk.escalation ?? []).flatMap((e) => [e.observation, e.escalate_to]),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });
}

/** 健康度行的文案：只报**可计算信号**，无异常信号时也明说「≠ 都可靠」。 */
export function healthParts(data: SkillsResponse): string[] {
  const signals = data.health?.signals ?? {};
  return [
    ...(signals.escalation_missing ?? []).map((n) => `缺 escalation 表：${n}`),
    ...(signals.dangling_escalation ?? []).map((n) => `悬空引用：${n}`),
    ...(signals.orphan_playbooks ?? []).map((n) => `孤儿手册：${n}`),
  ];
}

export function SkillsView({ data }: { data: SkillsResponse }) {
  const [q, setQ] = useState("");

  const s = data.summary ?? {};
  const hits = useMemo(() => filterSkills(data.skills, q), [data.skills, q]);
  const parts = healthParts(data);

  return (
    <section aria-label="技能手册" className="min-w-0 flex-1 overflow-auto p-4">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="筛选：名称 / 描述 / 触发条件 / 手册名"
          className="max-w-[460px] flex-1"
        />
        <span className="text-bodySm text-text-muted">
          {s.total ?? data.skills.length} 个技能
          {s.by_kind
            ? Object.entries(s.by_kind)
                .map(([k, n]) => ` · ${k} ${n}`)
                .join("")
            : ""}
          {typeof s.with_escalation === "number"
            ? ` · ${s.with_escalation} 个带触发表`
            : ""}
        </span>
      </div>

      {/* ★ 健康度 unknown 是如实状态：只报可计算信号，「没报异常」≠「都可靠」 */}
      <div className="mb-3 text-bodySm">
        健康度 <strong>{data.health?.level ?? "unknown"}</strong>
        （只报可计算信号，整体未知是<strong>如实状态</strong>）：
        {parts.length ? parts.join("；") : "当前无异常信号"}
      </div>

      <div className="grid items-start gap-3 [grid-template-columns:repeat(auto-fill,minmax(430px,1fr))]">
        {hits.map((sk) => (
          <SkillCard key={sk.id} skill={sk} />
        ))}
        {!hits.length && <EmptyState>没有匹配「{q}」的技能。</EmptyState>}
      </div>
    </section>
  );
}
