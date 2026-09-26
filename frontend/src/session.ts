/** 会话 + evidence 事件流 —— **提到 App 层**的共享状态。
 *
 *  ★ 为什么不在 ChatView 里：UI 规范 §4.7.1 要求校验层的**顶部状态条「所有视图共有」**，
 *    而 MVP 的布局也是把状态条放在 `<header>`（nav 之上）。若订阅留在 ChatView，
 *    切到别的标签页就会断流、切回来又因重放而重复计数。
 *
 *  ★ **按 `seq` 去重是必须的**：服务端**不解析 `Last-Event-ID`**，断线重连一律
 *    历史全量重放 —— 事件**不丢但会重复**（`events.py` docstring 明载）。
 *
 *  ★ 工具轨迹取自 **evidence 通道**（不取 chat 帧）：它有 `seq`（可去重、可排序）、
 *    且断线重连会重放；chat 帧里的 tool_call/tool_error 是它的子集且无 seq。
 *    每条轨迹带上到达时的**回合 id**（`turnId`），由视图按回合分组。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  SessionSchema,
  parseEvidenceFrame,
  apiParsed,
  type ContractFinding,
} from "./api";
import type { ResultItem } from "./components";
import { extractResults } from "./results";

/** 与 MVP 同口径的默认 server 清单 —— 少了 ANDES 会让模型以为「没有 ANDES 工具」。 */
export const DEFAULT_SERVERS = ["surge", "powerio", "pandapower", "pypsa", "andes"];

export interface ToolRow {
  server: string;
  tool: string;
  status: "ok" | "bad";
  args?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ToolRowWithTurn extends ToolRow {
  /** 到达时正在生成的回合；无活动回合时为 `null`（如重放的历史事件） */
  turnId: number | null;
  /** 事件序号 —— 排序与去重依据 */
  seq: number;
  /** ★ 结构化结果（F-4）：由数据适配层从**结果摘要**里算出，
   *  数值走 `Quantity`（单位+判据）、标识符走 `Identifier`（编号约定） */
  results?: ResultItem[];
}

export function useSession() {
  const [sid, setSid] = useState<string | null>(null);
  const [conn, setConn] = useState({ ok: false, text: "未连接" });
  const [rows, setRows] = useState<ToolRowWithTurn[]>([]);
  const [findings, setFindings] = useState<ContractFinding[]>([]);
  /** SSE 边界校验失败（§8.4）—— 必须可见，且**不得**打断流 */
  const [boundaryIssue, setBoundaryIssue] = useState<string | null>(null);

  const seenSeq = useRef<Set<number>>(new Set());
  const activeTurn = useRef<number | null>(null);

  /** 视图用它标注「当前正在生成的回合」 */
  const setActiveTurn = useCallback((id: number | null) => {
    activeTurn.current = id;
  }, []);

  /* 建会话 —— 与 MVP 同口径的默认 server 清单。★ 有意**急切**建立：
     校验层状态条要「所有视图共有」，事件流就不能等到第一次发问才起。 */
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await apiParsed("/sessions", SessionSchema, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ servers: DEFAULT_SERVERS }),
        });
        if (alive) setSid(s.id);
      } catch (e) {
        if (alive) setConn({ ok: false, text: `建立会话失败：${(e as Error).message}` });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!sid) return;
    // jsdom 无 EventSource —— 不静默假装已连接；纯逻辑由单测直接覆盖
    if (typeof EventSource === "undefined") {
      setConn({ ok: false, text: "当前环境不支持 EventSource（测试环境）" });
      return;
    }

    const es = new EventSource(`/sessions/${sid}/events`);
    es.addEventListener("evidence", (ev) => {
      const parsed = parseEvidenceFrame((ev as MessageEvent).data as string);
      if (!parsed) return; // 包装层坏帧：跳过（不炸流）
      if (seenSeq.current.has(parsed.seq)) return; // ★ 重放去重
      seenSeq.current.add(parsed.seq);

      const turnId = activeTurn.current;
      if (parsed.kind === "tool_call") {
        // ★ 结构化结果：从结果摘要算出可展示的数值/标识符（F-4）。
        //   认不出的形状 → []（不猜）；界面只渲染认得的部分。
        const results = extractResults(parsed.server, parsed.tool, parsed.resultExcerpt);
        setRows((rs) => [
          ...rs,
          {
            server: parsed.server,
            tool: parsed.tool,
            status: "ok",
            args: parsed.args,
            turnId,
            seq: parsed.seq,
            ...(results.length ? { results } : {}),
          },
        ]);
      } else if (parsed.kind === "tool_error") {
        setRows((rs) => [
          ...rs,
          { server: parsed.server, tool: parsed.tool, status: "bad", error: parsed.error, turnId, seq: parsed.seq },
        ]);
      } else if (parsed.kind === "contract_violation" || parsed.kind === "contract_unknown") {
        setFindings((fs) => [...fs, parsed.finding]);
      } else if (parsed.kind === "malformed") {
        // ★ §8.4：不炸流、不静默 —— 降级为 incident 并可见
        setBoundaryIssue(
          `事件流中有结构不符的事件（kind=${parsed.rawKind}）：${parsed.issues.join("；")}`,
        );
      }
      // inventory_degraded / unknown / 其它 kind：S2 不消费（前者由 chat 流的 notice 覆盖）
    });
    es.onopen = () => setConn({ ok: true, text: "已连接" });
    es.onerror = () => setConn({ ok: false, text: "事件流断开（会自动重连）" });
    return () => es.close();
  }, [sid]);

  return {
    sid,
    conn,
    rows,
    findings,
    boundaryIssue,
    setActiveTurn,
    clearBoundaryIssue: useCallback(() => setBoundaryIssue(null), []),
  };
}

export type SessionStream = ReturnType<typeof useSession>;
