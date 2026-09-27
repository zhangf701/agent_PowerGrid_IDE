/** CapabilityMatrixPanel —— ⑥ 校验层 · 能力矩阵（方案 §5.3）。
 *
 *  ★ 数据来源分两栏，**来源必须在界面上写清**（不许把文档知识冒充运行时探测）：
 *    - **动态列**（契约 1 / 契约 2）：`GET /contracts/t0` 的 findings ——
 *      契约 1 = 工具实现可判定性（静态扫描），契约 2 = README ↔ 运行时工具面（真实拉起 server）；
 *    - **静态列**（潮流 / OPF / N-1 / …）：v4 §5.3 的**文档知识**（2026-09-24 实测校正版），
 *      标注来源，**不是**本次运行探测出来的。
 *
 *  ★ §5.3 设计要点：「⚠️/❌ 必须给出可执行修复路径」「单元格可下钻看依据」——
 *    下钻用 `<details>` 展开该引擎的 finding detail（网关写好的可执行文案，不转述）。
 *
 *  ★ unknown 不猜：findings 里没有某 server 的记录 → 显示「无记录」，
 *    **不**渲染成「正常」（空集 ≠ satisfied，与状态条同一哲学）。
 */
import { useEffect, useState } from "react";

import {
  SchemaDriftError,
  ServersResponseSchema,
  T0ReportSchema,
  apiParsed,
  type T0Report,
} from "../api";
import { ContractBadge, type ContractState, type UnknownReason } from "./ContractBadge";

/** v4 §5.3 的能力矩阵（2026-09-24 实测校正后的**文档知识**）。
 *  ⚠️ 这里只放**文档已写明**的格子；文档没写的引擎-能力组合是 `—`。
 *  符号语义：`✅` 有该能力 · `—` 文档未声明该能力 ·（不使用 ❌ —— 「无此能力」与
 *  「文档没写」在静态知识里无法区分，统一用 `—` 如实表达）。 */
const STATIC_CAPABILITIES: Record<string, Record<string, string>> = {
  surge: { 潮流: "✅", "OPF/优化": "✅", "N-1": "✅ 含 N-2", 机组组合: "✅ SCUC", 矩阵: "✅ PTDF·LODF·OTDF·ATC", 转换: "✅" },
  pandapower: { 潮流: "✅", "N-1": "✅", 转换: "✅" },
  pypsa: { 潮流: "✅", "OPF/优化": "✅", "N-1": "✅", 转换: "✅" },
  powerio: { 矩阵: "✅", 转换: "✅" },
  andes: { 潮流: "✅", 时域: "✅", 转换: "✅" },
  egret: { "OPF/优化": "✅ AC/DC", 机组组合: "✅ UC", 转换: "✅" },
  hope: { "OPF/优化": "✅（求解需 Julia，挂载不需要——未验证执行）" },
  genx: { "OPF/优化": "✅ 容量规划（求解需 Julia，挂载不需要——未验证执行）" },
  opendss: { 潮流: "✅（⚠️ 无法经 mcp SDK 挂载，见立项文档）" },
};
const CAPABILITY_COLUMNS = ["潮流", "OPF/优化", "N-1", "机组组合", "时域", "矩阵", "转换"] as const;

interface Row {
  server: string;
  c1?: { state: ContractState; reason?: UnknownReason; detail: string };
  c2?: { state: ContractState; reason?: UnknownReason; detail: string };
}

function collectRows(report: T0Report, servers: string[]): Row[] {
  const byServer = new Map<string, Row>(servers.map((s) => [s, { server: s }]));
  for (const f of report.findings) {
    if (f.contract !== 1 && f.contract !== 2) continue;
    // subject 为 server id；`*` 是全局条目，不属于任何一行
    if (f.subject === "*") continue;
    const row = byServer.get(f.subject) ?? { server: f.subject };
    byServer.set(f.subject, row);
    const slot = { state: f.state as ContractState, reason: (f.reason ?? undefined) as UnknownReason | undefined, detail: f.detail };
    if (f.contract === 1) row.c1 = slot;
    else row.c2 = slot;
  }
  return servers.map((s) => byServer.get(s)!).filter(Boolean);
}

export function CapabilityMatrixPanel() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<{ message: string; incident: boolean } | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [srv, t0] = await Promise.all([
          apiParsed("/servers", ServersResponseSchema),
          apiParsed("/contracts/t0", T0ReportSchema),
        ]);
        if (!alive) return;
        setRows(collectRows(t0, srv.servers));
        setError(null);
      } catch (err) {
        if (!alive) return;
        setError({
          message: (err as Error).message,
          incident: err instanceof SchemaDriftError,
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return (
      <div className="text-bodySm">
        <span className={error.incident ? "text-contract-incident-fg" : "text-contract-violated-fg"}>
          {error.incident ? "! 事故" : "✖ 失败"}
        </span>{" "}
        {error.message}
      </div>
    );
  }
  if (!rows) return <div className="text-bodySm text-text-muted">加载中…（/servers + /contracts/t0）</div>;

  return (
    <div data-testid="capability-matrix">
      <div className="mb-1 text-caption text-text-muted">
        <strong>动态列</strong>来自 <code>GET /contracts/t0</code>（本次运行评估）；
        <strong>静态能力列</strong>是文档知识（方案 v4 §5.3，2026-09-24 实测校正），<strong>不是</strong>运行时探测。
      </div>
      <div className="overflow-x-auto rounded-sm border border-border-subtle">
        <table className="w-full border-collapse text-caption">
          <thead>
            <tr className="border-b border-border-subtle bg-surface-sunken text-left text-text-muted">
              <th className="px-2 py-1 font-normal">引擎</th>
              <th className="px-2 py-1 font-normal">契约 1</th>
              <th className="px-2 py-1 font-normal">契约 2</th>
              {CAPABILITY_COLUMNS.map((c) => (
                <th key={c} className="px-2 py-1 font-normal">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.server} className="border-b border-border-subtle last:border-b-0">
                <td className="px-2 py-1 font-mono">{r.server}</td>
                {[r.c1, r.c2].map((slot, i) => (
                  <td key={i} className="px-2 py-1">
                    {slot ? (
                      <details>
                        <summary className="cursor-pointer whitespace-nowrap">
                          <ContractBadge state={slot.state} reason={slot.reason} contractType={i === 0 ? 1 : 2} />
                        </summary>
                        <div className="mt-1 max-w-sm text-caption text-text-secondary">{slot.detail}</div>
                      </details>
                    ) : (
                      <span className="text-text-muted" title="t0 findings 里没有该 server 的这条记录">无记录</span>
                    )}
                  </td>
                ))}
                {CAPABILITY_COLUMNS.map((c) => (
                  <td key={c} className="px-2 py-1 whitespace-nowrap">
                    {STATIC_CAPABILITIES[r.server]?.[c] ?? <span className="text-text-muted">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
